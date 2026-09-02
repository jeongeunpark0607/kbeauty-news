# -*- coding: utf-8 -*-
"""
summarizer.py
=============
Claude API를 이용해 수집된 기사(제목+스니펫)를 2~3문장으로 요약하고,
관련 키워드 태그(3~5개)를 추출합니다. 기사 본문에 증권사 투자의견/목표주가가
언급된 경우 이를 함께 파싱합니다.

비용/속도 절감을 위해 기사를 BATCH_SIZE개씩 묶어 한 번의 API 호출로 처리합니다.
"""
import json
import time

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

BATCH_SIZE = 8
MAX_RETRY = 2

SYSTEM_PROMPT = """\
너는 K-뷰티(한국 화장품) 산업 전문 애널리스트다. 아래에 뉴스 기사들의 제목과 스니펫이
JSON 배열로 주어진다. 각 기사에 대해 다음을 생성해서 '입력과 동일한 개수/순서의 JSON 배열'로만
답하라. 다른 설명 문장은 절대 포함하지 마라.

각 원소 형식:
{
  "summary": "핵심 내용을 2~3문장, 한국어 존댓말이 아닌 개조식 뉴스체로 간결하게 요약",
  "keywords": "쉼표로 구분된 관련 키워드 태그 3~5개 (예: 북미, 선케어, 실적, 수출, OEM/ODM 등)",
  "opinion": "기사에 증권사 투자의견(매수/BUY/Hold/Sell 등)이 명시된 경우에만 그 값, 없으면 빈 문자열",
  "target_price": "기사에 목표주가(숫자, 원단위)가 명시된 경우에만 해당 숫자만, 없으면 빈 문자열"
}
"""


def _get_client():
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError(
            "anthropic 패키지가 설치되어 있지 않습니다. `pip install anthropic` 을 실행하세요."
        ) from e

    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY 가 설정되지 않았습니다. .env 또는 GitHub Secrets를 확인하세요.")

    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _build_user_content(batch):
    payload = [
        {"idx": i, "title": r["title"], "description": r.get("raw_description", "")}
        for i, r in enumerate(batch)
    ]
    return json.dumps(payload, ensure_ascii=False)


def _extract_json_array(text):
    """모델이 코드블록(```json ... ```)으로 감싸 응답하는 경우까지 방어적으로 파싱."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("응답에서 JSON 배열을 찾을 수 없음")
    return json.loads(text[start : end + 1])


def _summarize_batch(client, batch):
    user_content = _build_user_content(batch)
    last_err = None
    for attempt in range(MAX_RETRY + 1):
        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            text = "".join(block.text for block in resp.content if block.type == "text")
            parsed = _extract_json_array(text)
            if len(parsed) != len(batch):
                raise ValueError(f"응답 개수 불일치: 입력 {len(batch)} / 출력 {len(parsed)}")
            return parsed
        except Exception as e:
            last_err = e
            print(f"[WARN] 요약 배치 실패 (시도 {attempt + 1}/{MAX_RETRY + 1}): {e}")
            time.sleep(1.5)
    # 재시도 모두 실패하면 폴백: 원문 스니펫을 그대로 요약으로 사용
    print(f"[ERROR] 배치 요약 최종 실패, 폴백 처리: {last_err}")
    return [
        {"summary": r.get("raw_description", "")[:150], "keywords": "", "opinion": "", "target_price": ""}
        for r in batch
    ]


def summarize_records(records):
    """
    records: collector.collect_all()이 반환한 dict 리스트.
    각 record에 summary/keywords/opinion/target_price 를 채워서 반환합니다.
    """
    if not records:
        return records

    client = _get_client()

    for start in range(0, len(records), BATCH_SIZE):
        batch = records[start : start + BATCH_SIZE]
        results = _summarize_batch(client, batch)
        for r, res in zip(batch, results):
            r["summary"] = res.get("summary", "") or r.get("raw_description", "")[:150]
            r["keywords"] = ", ".join(
                filter(None, [r.get("keywords", ""), res.get("keywords", "")])
            ).strip(", ")
            # 리포트성 기사인 경우 category를 '리포트'로 격상 (투자의견/목표주가가 파싱되면)
            if res.get("opinion") or res.get("target_price"):
                r["category"] = "리포트"
            r["opinion"] = res.get("opinion", "")
            r["target_price"] = res.get("target_price", "")
        print(f"[INFO] 요약 진행: {min(start + BATCH_SIZE, len(records))}/{len(records)}")

    return records


if __name__ == "__main__":
    sample = [
        {
            "title": "아모레퍼시픽, 북미 시장서 선케어 매출 급증",
            "raw_description": "아모레퍼시픽이 북미 시장에서 선케어 제품 판매 호조로 3분기 실적 개선이 기대된다는 증권사 리포트가 나왔다. 목표주가는 20만원, 투자의견은 매수.",
        }
    ]
    print(summarize_records(sample))
