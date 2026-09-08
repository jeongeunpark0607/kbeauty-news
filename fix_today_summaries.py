#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_today_summaries.py
=======================
아래 두 가지 이유로 지저분하게 저장된 오늘자 레코드를 다시 찾아 재요약하고
DB를 갱신하는 1회성 유지보수 스크립트입니다.

  1) 레이트리밋 등으로 요약 API 호출이 완전히 실패해 원문 스니펫을 그대로
     저장한 경우 (keywords가 항상 빈 문자열)
  2) 요약 API는 성공했지만 모델이 기사 인용문을 그대로 옮기거나 문장을
     너무 길게 써서(예전 프롬프트 기준) 지저분해 보이는 경우
     (summary 첫 줄이 너무 길거나, 말줄임표/따옴표로 된 인용을 포함)

사용법:
    python fix_today_summaries.py                    # 오늘자만 재요약
    python fix_today_summaries.py --date 2026-09-04   # 특정 날짜만 재요약
    python fix_today_summaries.py --send              # 재요약 후 새 리포트를 슬랙으로 재발송
"""
import argparse

import db
import summarizer
import report_generator
import notifier

# summarizer.MAX_BULLET_CHARS보다 살짝 여유를 둬서, 예전 프롬프트로 생성된
# 기준 초과 요약들을 재요약 대상으로 잡는다.
MESSY_LENGTH_THRESHOLD = summarizer.MAX_BULLET_CHARS + 10


def _looks_messy(r):
    """keywords가 비어있거나(완전 실패), summary 첫 줄이 너무 길거나 인용/말줄임표 흔적이 있으면 True."""
    if not (r.get("keywords") or "").strip():
        return True
    summary = r.get("summary") or ""
    first_line = summary.split("\n")[0].lstrip("- ").strip()
    if not first_line:
        return True
    if len(first_line) > MESSY_LENGTH_THRESHOLD:
        return True
    if "..." in first_line or "…" in first_line or '"' in first_line:
        return True
    return False


def run(date=None, send=False):
    db.init_db()
    records = db.fetch_today(collected_date=date)
    if not records:
        print("[INFO] 대상 레코드가 없습니다.")
        return

    targets = [r for r in records if _looks_messy(r)]
    print(f"[INFO] 전체 {len(records)}건 중 재요약 대상(폴백/지저분함 추정) {len(targets)}건")

    if not targets:
        print("[INFO] 재요약할 레코드가 없습니다. 이미 모두 정상 요약된 상태입니다.")
        return

    print("[INFO] 재요약 시작 (기사 수에 따라 몇 분 걸릴 수 있습니다)...")
    summarizer.summarize_records(targets)

    updated = 0
    for r in targets:
        db.update_summary(
            link=r["link"],
            category=r.get("category"),
            summary=r.get("summary"),
            keywords=r.get("keywords"),
            opinion=r.get("opinion"),
            target_price=r.get("target_price"),
        )
        updated += 1
    print(f"[DONE] {updated}건 재요약 및 DB 갱신 완료")

    if send:
        print("[INFO] 갱신된 내용으로 데일리 리포트 재생성 및 슬랙 발송 중...")
        fresh_records = db.fetch_today(collected_date=date)
        overview = ""
        try:
            overview = summarizer.generate_daily_overview(fresh_records)
        except Exception as e:
            print(f"[WARN] 총평 생성 실패, 총평 없이 진행: {e}")
        report_text = report_generator.build_report_text(fresh_records, overview=overview)
        notifier.send_slack_report(report_text)
        print("[DONE] 슬랙 재발송 완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="폴백 요약된(키워드가 비어있는) 오늘자 레코드 재요약")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD 형식 (생략 시 오늘)")
    parser.add_argument("--send", action="store_true", help="재요약 후 갱신된 리포트를 슬랙으로 재발송")
    args = parser.parse_args()
    run(date=args.date, send=args.send)
