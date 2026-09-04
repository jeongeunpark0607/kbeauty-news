# -*- coding: utf-8 -*-
"""
collector.py
============
네이버 뉴스 검색 API를 이용해 21개 대상 기업 + K뷰티 산업 키워드에 대한
최근 N시간 이내 뉴스를 수집합니다.

2026년 기준 네이버 뉴스 검색 API는 "NAVER API HUB"(네이버클라우드플랫폼,
https://apihub.naver.com)로 이전되었습니다. 이 파일은 기본적으로 새 방식(hub)을
사용하며, config.NAVER_API_MODE="legacy" 로 설정하면 2027-06-30까지 유효한
구 개발자센터 키(openapi.naver.com)도 계속 쓸 수 있습니다.

네이버 뉴스 검색 API는 '검색' API이며 실시간 크롤링이 아니므로, 최근 게시물 위주로
검색 결과가 정렬(sort=date)되어 오지만 완벽한 실시간 피드는 아닙니다. 하루 1회
(예: 오전 8시) 실행 기준으로 직전 24시간 윈도우를 커버하도록 설계했습니다.

증권사 리포트(PDF)는 네이버 뉴스 검색 API의 범위 밖이므로 이 파일은 뉴스만 수집합니다.
리포트 수집을 추가하려면 한경컨센서스/네이버금융 리서치 페이지 등을 별도로 크롤링하는
모듈을 만들어 collect_all()의 결과 리스트에 합치면 됩니다 (README 참고).
"""
import html
import re
import time
from datetime import timedelta
from email.utils import parsedate_to_datetime

import requests

from config import (
    NAVER_CLIENT_ID,
    NAVER_CLIENT_SECRET,
    NAVER_API_MODE,
    NAVER_DISPLAY_COUNT,
    COLLECT_WINDOW_HOURS,
    now_kst,
    TARGET_COMPANIES,
    INDUSTRY_KEYWORDS,
)

# NAVER API HUB (신규, 기본값)
NAVER_HUB_NEWS_API_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
# 구 개발자센터 (2027-06-30까지 유효한 키를 이미 보유한 경우)
NAVER_LEGACY_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(raw):
    """네이버 API가 <b> 하이라이트 태그와 HTML 엔티티를 섞어 반환하므로 정제합니다."""
    if not raw:
        return ""
    text = TAG_RE.sub("", raw)
    text = html.unescape(text)
    return text.strip()


def _parse_pubdate(pub_date_str):
    """네이버 API의 pubDate는 RFC 822 형식 (예: 'Tue, 01 Sep 2026 09:00:00 +0900')"""
    try:
        dt = parsedate_to_datetime(pub_date_str)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return now_kst().replace(tzinfo=None)


def _search_naver_news(query, display=NAVER_DISPLAY_COUNT):
    """단일 검색어로 네이버 뉴스 검색 API를 호출해 결과 리스트(dict)를 반환.

    NAVER_API_MODE 설정에 따라 신규 NAVER API HUB / 구 개발자센터 방식 중 하나로 호출합니다.
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise RuntimeError(
            "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 설정되지 않았습니다. "
            ".env 또는 GitHub Secrets를 확인하세요."
        )

    if NAVER_API_MODE == "legacy":
        url = NAVER_LEGACY_NEWS_API_URL
        headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        }
    else:
        url = NAVER_HUB_NEWS_API_URL
        headers = {
            "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
            "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET,
        }

    params = {
        "query": query,
        "display": display,
        "start": 1,
        "sort": "date",  # 최신순 정렬
    }

    resp = requests.get(url, headers=headers, params=params, timeout=10)
    if resp.status_code != 200:
        print(f"[WARN] 네이버 뉴스 API 오류 (query={query}, status={resp.status_code}): {resp.text[:200]}")
        return []

    items = resp.json().get("items", [])
    results = []
    for item in items:
        results.append(
            {
                "title": _clean_text(item.get("title")),
                "raw_description": _clean_text(item.get("description")),
                "link": item.get("originallink") or item.get("link"),
                "source": _guess_source(item.get("originallink") or item.get("link")),
                "published_at": _parse_pubdate(item.get("pubDate")).strftime("%Y-%m-%d %H:%M:%S"),
                "_pubdate_dt": _parse_pubdate(item.get("pubDate")),
            }
        )
    return results


def _guess_source(url):
    """링크 도메인에서 매체명을 대략 추정 (완벽하지 않으면 도메인 그대로 표기)."""
    if not url:
        return "알수없음"
    m = re.search(r"https?://(?:www\.)?([^./]+)\.", url)
    return m.group(1) if m else url


def collect_all(window_hours=COLLECT_WINDOW_HOURS, sleep_sec=0.15):
    """
    21개 기업 키워드 + 산업 키워드 전체에 대해 순차적으로 네이버 뉴스를 검색하고,
    최근 window_hours 이내 기사만 남긴 뒤, 기업명 매핑을 붙여 반환합니다.

    반환: dict 리스트 (collector 레벨에서는 category='뉴스' 고정, opinion/target_price는 비움 -
          이 두 값은 리포트 전용이며 summarizer 단계에서 본문에 명시된 경우 채워질 수 있습니다)
    """
    # 네이버 API의 pubDate는 한국시간(KST)으로 오므로, 기준 시각도 서버 시간대와
    # 무관하게 항상 KST로 계산해야 GitHub Actions(UTC 서버)에서도 정확한
    # "최근 N시간" 윈도우가 됩니다.
    cutoff = now_kst().replace(tzinfo=None) - timedelta(hours=window_hours)
    seen_links = set()
    collected = []

    # 기업 키워드 검색
    for company, keywords in TARGET_COMPANIES.items():
        for kw in keywords:
            try:
                items = _search_naver_news(kw)
            except RuntimeError:
                raise
            except Exception as e:
                print(f"[WARN] '{kw}' 검색 중 오류: {e}")
                continue

            for it in items:
                if it["_pubdate_dt"] < cutoff:
                    continue
                if it["link"] in seen_links:
                    continue
                seen_links.add(it["link"])
                collected.append(
                    {
                        "category": "뉴스",
                        "company": company,
                        "title": it["title"],
                        "raw_description": it["raw_description"],
                        "source": it["source"],
                        "link": it["link"],
                        "published_at": it["published_at"],
                        "opinion": "",
                        "target_price": "",
                        "keywords": kw,
                    }
                )
            time.sleep(sleep_sec)  # API 호출 과속 방지

    # 산업 전반 키워드 검색 (특정 기업에 속하지 않는 업계 동향 기사)
    for kw in INDUSTRY_KEYWORDS:
        try:
            items = _search_naver_news(kw)
        except RuntimeError:
            raise
        except Exception as e:
            print(f"[WARN] '{kw}' 검색 중 오류: {e}")
            continue

        for it in items:
            if it["_pubdate_dt"] < cutoff:
                continue
            if it["link"] in seen_links:
                continue
            seen_links.add(it["link"])
            collected.append(
                {
                    "category": "뉴스",
                    "company": "산업전반",
                    "title": it["title"],
                    "raw_description": it["raw_description"],
                    "source": it["source"],
                    "link": it["link"],
                    "published_at": it["published_at"],
                    "opinion": "",
                    "target_price": "",
                    "keywords": kw,
                }
            )
        time.sleep(sleep_sec)

    print(f"[INFO] 총 {len(collected)}건 수집 (최근 {window_hours}시간, 중복 제거 후)")
    return collected


if __name__ == "__main__":
    records = collect_all()
    for r in records[:5]:
        print(r["company"], "|", r["title"], "|", r["link"])
