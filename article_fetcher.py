# -*- coding: utf-8 -*-
"""
article_fetcher.py
===================
기사 링크에서 실제 본문 텍스트를 가져옵니다.

네이버 뉴스 검색 API가 주는 'description'은 1~2문장짜리 짧은 스니펫이라
이것만으로는 인사이트 있는 요약을 만들기 어렵습니다. 그래서 원문 링크에
직접 접속해 기사 본문 전체를 추출한 뒤, 이 본문을 summarizer.py에 넘겨
Claude가 실제 내용을 바탕으로 5줄 핵심 요약을 만들도록 합니다.

`trafilatura` 라이브러리로 각 언론사 사이트마다 제각각인 HTML 구조에서
광고/메뉴/댓글 등을 자동으로 걸러내고 본문만 뽑아냅니다. 일부 사이트는
접근을 차단하거나 구조가 특이해서 추출에 실패할 수 있는데, 이 경우
빈 문자열을 반환하고 summarizer.py가 자동으로 네이버 스니펫으로 폴백합니다.
"""
import requests

REQUEST_TIMEOUT = 8
MAX_CHARS = 4000  # 본문이 너무 길면 Claude 호출 비용/토큰이 커지므로 앞부분만 사용
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def fetch_article_text(url, max_chars=MAX_CHARS, timeout=REQUEST_TIMEOUT):
    """기사 URL에서 본문 텍스트를 추출합니다. 실패하면 빈 문자열을 반환합니다."""
    if not url:
        return ""

    try:
        import trafilatura
    except ImportError:
        # trafilatura가 없으면 본문 추출 없이 폴백 (요약 품질은 떨어지지만 시스템은 계속 동작)
        return ""

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        if resp.status_code != 200 or not resp.text:
            return ""

        text = trafilatura.extract(
            resp.text,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
        if not text:
            return ""

        text = text.strip()
        return text[:max_chars]
    except Exception as e:
        print(f"[WARN] 본문 추출 실패 ({url}): {e}")
        return ""


if __name__ == "__main__":
    import sys

    test_url = sys.argv[1] if len(sys.argv) > 1 else ""
    print(fetch_article_text(test_url)[:500])
