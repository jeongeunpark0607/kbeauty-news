#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
search_cli.py
=============
누적된 SQLite DB를 커맨드라인에서 검색하는 도구.

사용 예:
  # 아모레퍼시픽 관련 지난 1달간 뉴스/리포트 조회
  python search_cli.py --company 아모레퍼시픽 --days 30

  # '북미' 키워드가 들어간 기사 검색 (전체 기간)
  python search_cli.py --keyword 북미

  # 특정 기간 + 키워드 조합
  python search_cli.py --keyword "EU 규제" --start 2026-08-01 --end 2026-08-31

  # 리포트만 필터
  python search_cli.py --company 코스맥스 --category 리포트
"""
import argparse
from datetime import datetime, timedelta

import db


def main():
    parser = argparse.ArgumentParser(description="K-뷰티 뉴스클리핑 DB 검색 CLI")
    parser.add_argument("--company", help="기업명 (부분일치, 예: 아모레퍼시픽)")
    parser.add_argument("--keyword", help="키워드 (제목/요약/태그 부분일치, 예: 북미, 선케어)")
    parser.add_argument("--category", choices=["뉴스", "리포트"], help="구분 필터")
    parser.add_argument("--start", help="시작일 YYYY-MM-DD")
    parser.add_argument("--end", help="종료일 YYYY-MM-DD")
    parser.add_argument("--days", type=int, help="최근 N일 (start/end 대신 간편하게 사용)")
    parser.add_argument("--limit", type=int, default=100, help="최대 표시 건수 (기본 100)")
    args = parser.parse_args()

    start_date = args.start
    end_date = args.end
    if args.days:
        start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")

    results = db.search(
        company=args.company,
        keyword=args.keyword,
        category=args.category,
        start_date=start_date,
        end_date=end_date,
        limit=args.limit,
    )

    if not results:
        print("검색 결과가 없습니다.")
        return

    print(f"총 {len(results)}건 검색됨\n" + "=" * 80)
    for r in results:
        print(f"[{r['collected_at']}] ({r['category']}) {r['company']} | {r['title']}")
        if r.get("summary"):
            print(f"   요약: {r['summary']}")
        if r.get("keywords"):
            print(f"   태그: {r['keywords']}")
        if r.get("opinion") or r.get("target_price"):
            print(f"   투자의견: {r.get('opinion','-')} / 목표주가: {r.get('target_price','-')}")
        print(f"   출처: {r.get('source','-')} | 링크: {r['link']}")
        print("-" * 80)


if __name__ == "__main__":
    main()
