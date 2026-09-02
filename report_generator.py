# -*- coding: utf-8 -*-
"""
report_generator.py
====================
당일 수집/요약된 레코드들을 받아 Slack에 발송할 '데일리 뉴스클리핑 보고서' 텍스트를 만듭니다.

구성:
  1) 헤드라인 Top N (전체 기사 중 상위 N건 - 산업전반 우선 + 최신순)
  2) K뷰티 산업동향 Top N (company == '산업전반')
  3) 기업별 이슈 (기업명별로 그룹핑, 기업 키워드에 등록된 21개사 순서 유지)

Slack mrkdwn 포맷을 사용합니다 (*bold*, <link|text> 등).
"""
from datetime import datetime
from collections import defaultdict

from config import TARGET_COMPANIES, REPORT_TOP_HEADLINE_COUNT, REPORT_INDUSTRY_TREND_COUNT


def _fmt_item(r, with_company=False):
    prefix = f"[{r['company']}] " if with_company else ""
    line = f"• {prefix}<{r['link']}|{r['title']}>"
    if r.get("source"):
        line += f"  _({r['source']})_"
    if r.get("summary"):
        line += f"\n   {r['summary']}"
    tags = r.get("keywords", "")
    if tags:
        line += f"\n   `태그: {tags}`"
    if r.get("opinion") or r.get("target_price"):
        extra = []
        if r.get("opinion"):
            extra.append(f"투자의견: {r['opinion']}")
        if r.get("target_price"):
            extra.append(f"목표주가: {r['target_price']}원")
        line += f"\n   :chart_with_upwards_trend: {' / '.join(extra)}"
    return line


def build_report_text(records, report_date=None):
    """records: db.insert_records()에 넘긴 것과 동일한 dict 리스트 (오늘자 전체)."""
    report_date = report_date or datetime.now().strftime("%Y-%m-%d (%a)")

    if not records:
        return (
            f"*:sparkles: K-뷰티 데일리 뉴스클리핑 — {report_date}*\n\n"
            "오늘은 수집된 신규 기사가 없습니다."
        )

    # 최신순 정렬 (published_at 우선)
    sorted_records = sorted(records, key=lambda r: r.get("published_at", ""), reverse=True)

    # 1) 헤드라인 Top N
    headlines = sorted_records[:REPORT_TOP_HEADLINE_COUNT]

    # 2) 산업동향 Top N
    industry = [r for r in sorted_records if r.get("company") == "산업전반"][:REPORT_INDUSTRY_TREND_COUNT]

    # 3) 기업별 이슈 그룹핑 (21개사 순서 유지, 기사 있는 기업만 표시)
    by_company = defaultdict(list)
    for r in sorted_records:
        if r.get("company") != "산업전반":
            by_company[r["company"]].append(r)

    parts = [f"*:sparkles: K-뷰티 데일리 뉴스클리핑 — {report_date}*"]
    parts.append(f"오늘 수집된 신규 기사/리포트: 총 *{len(records)}건*\n")

    parts.append("*:one: 헤드라인 Top " + str(len(headlines)) + "*")
    parts.extend(_fmt_item(r, with_company=True) for r in headlines)
    parts.append("")

    if industry:
        parts.append("*:two: K뷰티 산업동향 " + str(len(industry)) + "선*")
        parts.extend(_fmt_item(r) for r in industry)
        parts.append("")

    parts.append("*:three: 기업별 이슈*")
    for company in TARGET_COMPANIES.keys():
        items = by_company.get(company)
        if not items:
            continue
        parts.append(f"\n*▸ {company}* ({len(items)}건)")
        parts.extend(_fmt_item(r) for r in items[:5])  # 기업당 최대 5건만 노출 (과다 발송 방지)

    return "\n".join(parts)


if __name__ == "__main__":
    sample = [
        {
            "company": "아모레퍼시픽",
            "title": "아모레퍼시픽 북미 선케어 매출 급증",
            "link": "https://example.com/1",
            "source": "한국경제",
            "summary": "북미 선케어 판매 호조로 3분기 실적 개선 기대.",
            "keywords": "북미, 선케어, 실적",
            "opinion": "매수",
            "target_price": "200000",
            "published_at": "2026-09-01 08:00:00",
        }
    ]
    print(build_report_text(sample))
