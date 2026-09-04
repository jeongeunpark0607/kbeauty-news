#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main_daily.py
=============
매일 1회 실행하는 메인 파이프라인.

  1. 네이버 뉴스 수집 (collector.collect_all)
  2. 이미 DB에 있는 기사는 사전 제외 (요약 API 비용 절감)
  3. Claude API로 요약 + 태그 추출 (summarizer.summarize_records)
  4. SQLite DB에 누적 저장 (db.insert_records) — link UNIQUE로 중복 자동 방지
  5. 오늘자 데일리 리포트 텍스트 생성 (report_generator.build_report_text)
  6. Slack Webhook으로 발송 (notifier.send_slack_report)

GitHub Actions에서 매일 아침 자동 실행되도록 .github/workflows/daily_news.yml 에
스케줄이 등록되어 있습니다. 로컬에서 수동 실행하려면:

    python main_daily.py

옵션:
    python main_daily.py --no-send      # DB 저장까지만 하고 Slack 발송은 생략
    python main_daily.py --dry-run      # 아무것도 저장/발송하지 않고 콘솔 출력만
"""
import argparse
import sys

import db
import collector
import summarizer
import report_generator
import notifier


def _safe_generate_overview(records):
    """'오늘의 총평' 생성 실패가 전체 파이프라인을 막지 않도록 감싸는 헬퍼."""
    try:
        return summarizer.generate_daily_overview(records)
    except Exception as e:
        print(f"[WARN] 총평 생성 중 오류 발생, 총평 없이 진행합니다: {e}")
        return ""


def run(send=True, dry_run=False):
    print("=" * 60)
    print("[STEP 0] DB 초기화")
    db.init_db()

    print("[STEP 1] 네이버 뉴스 수집 중...")
    try:
        raw_records = collector.collect_all()
    except RuntimeError as e:
        print(f"[FATAL] {e}")
        sys.exit(1)

    if not raw_records:
        print("[INFO] 신규 수집 기사가 없습니다. 종료합니다.")
        return

    # 이미 DB에 있는 링크는 미리 걸러내어 요약 API 호출을 아낍니다.
    existing_links = db.get_existing_links()
    new_records = [r for r in raw_records if r["link"] not in existing_links]
    print(f"[INFO] 수집 {len(raw_records)}건 중 신규 {len(new_records)}건 (기존 {len(raw_records) - len(new_records)}건 제외)")

    if not new_records:
        print("[INFO] 모두 기존 수집 기사와 중복입니다. 종료합니다.")
        return

    print("[STEP 2] Claude API 요약/태그 추출 중...")
    try:
        summarized = summarizer.summarize_records(new_records)
    except RuntimeError as e:
        print(f"[FATAL] {e}")
        sys.exit(1)

    if dry_run:
        print("[DRY-RUN] DB 저장/발송 없이 종료합니다.")
        overview = _safe_generate_overview(summarized)
        report_text = report_generator.build_report_text(summarized, overview=overview)
        print(report_text)
        return

    print("[STEP 3] DB 저장 중...")
    inserted = db.insert_records(summarized)
    print(f"[INFO] DB 신규 저장: {inserted}건")

    print("[STEP 4] 데일리 리포트 생성 중...")
    today_records = db.fetch_today()
    overview = _safe_generate_overview(today_records)
    report_text = report_generator.build_report_text(today_records, overview=overview)
    print(report_text)

    if send:
        print("[STEP 5] Slack 발송 중...")
        notifier.send_slack_report(report_text)
    else:
        print("[INFO] --no-send 옵션으로 Slack 발송을 생략합니다.")

    print("[DONE] 파이프라인 완료")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="K-뷰티 데일리 뉴스클리핑 파이프라인")
    parser.add_argument("--no-send", action="store_true", help="Slack 발송을 생략하고 DB 저장까지만 수행")
    parser.add_argument("--dry-run", action="store_true", help="DB 저장/발송 없이 콘솔에만 결과 출력")
    args = parser.parse_args()

    run(send=not args.no_send, dry_run=args.dry_run)
