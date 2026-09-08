# -*- coding: utf-8 -*-
"""
summarizer.py
=============
기사 원문 본문(article_fetcher.py로 추출)을 바탕으로 Claude API가 핵심을
5줄 내외 불릿 포인트로 요약하고, 관련 키워드 태그(3~5개)를 추출합니다.
기사 본문에 증권사 투자의견/목표주가가 언급된 경우 이를 함께 파싱합니다.

요약(summary)은 "- 문장\\n- 문장\\n..." 형태의 여러 줄 문자열로 저장되어,
Slack 메시지나 검색 화면에서 줄바꿈된 불릿 목록으로 바로 표시됩니다.

비용/속도 절감을 위해 기사를 BATCH_SIZE개씩 묶어 한 번의 API 호출로 처리합니다.
본문 전체를 프롬프트에 포함하므로, 스니펫만 쓰던 이전 버전보다 배치 크기를
줄여 토큰 사용량을 조절합니다.
"""
import json
import time

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from article_fetcher import fetch_article_text

BATCH_SIZE = 5
MAX_RETRY = 4
SUMMARY_BULLET_COUNT = 5
MAX_BULLET_CHARS = 55  # 한 줄(불릿)의 최대 길이. 넘으면 강제로 잘라서라도 짧게 유지 (Slack 1줄 표시용)
BATCH_PACING_SEC = 1.2  # 배치 사이 기본 대기 시간 (레이트리밋 예방)
RATE_LIMIT_WAIT_SEC = 25  # 레이트리밋(429) 감지 시 대기 시간

SYSTEM_PROMPT = f"""\
너는 K-뷰티(한국 화장품) 산업 전문 애널리스트다. 아래에 뉴스 기사들이 JSON 배열로
주어진다. 각 기사는 "title"(제목)과 "content"(본문 전체 또는 일부, 본문을 못 가져온
경우 짧은 스니펫)를 가지고 있다. 반드시 주어진 content의 실제 내용에 근거해서
(제목만 보고 추측하지 말고) 각 기사에 대해 아래를 생성하고, '입력과 동일한
개수/순서의 JSON 배열'로만 답하라. 다른 설명 문장은 절대 포함하지 마라.

각 원소 형식:
{{
  "summary_bullets": [
    "핵심 포인트 1 (숫자·고유명사 등 구체적 사실 위주, 개조식 뉴스체, 반드시 {MAX_BULLET_CHARS}자 이내)",
    "핵심 포인트 2",
    "... 최대 {SUMMARY_BULLET_COUNT}개까지, 기사에 실제 담긴 내용이 적으면 2~3개만 생성해도 됨"
  ],
  "keywords": "쉼표로 구분된 관련 키워드 태그 3~5개 (예: 북미, 선케어, 실적, 수출, OEM/ODM 등)",
  "opinion": "기사에 증권사 투자의견(매수/BUY/Hold/Sell 등)이 명시된 경우에만 그 값, 없으면 빈 문자열",
  "target_price": "기사에 목표주가(숫자, 원단위)가 명시된 경우에만 해당 숫자만, 없으면 빈 문자열"
}}

summary_bullets 작성 시 반드시 지킬 것:
- 뭉뚱그린 얘기("호조를 보였다", "관심이 높아지고 있다" 등)가 아니라 기사에 나온 구체적
  수치·이름·비교·원인 등 인사이트 있는 사실 위주로, 반드시 너 자신의 말로 압축해서 쓴다.
- 기사 속 문장이나 인터뷰 인용문("...")을 그대로 옮기거나 이어 붙이지 않는다. 아무리
  중요한 문장이라도 반드시 핵심만 재구성한 새 문장으로 요약한다.
- 각 문장은 {MAX_BULLET_CHARS}자를 절대 넘기지 않는다. 넘을 것 같으면 부수적인 내용을
  빼고 가장 중요한 사실 하나만 남긴다.
- 말줄임표("...", "…")로 문장을 흐리게 끝내지 않는다. 항상 완결된 짧은 문장으로 끝낸다.
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


def _content_for(r):
    """요약 프롬프트에 넣을 본문. 본문 추출 성공 시 그걸, 실패하면 네이버 스니펫."""
    return r.get("full_text") or r.get("raw_description", "")


def _build_user_content(batch):
    payload = [
        {"idx": i, "title": r["title"], "content": _content_for(r)}
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


def _clean_bullet(b):
    """
    모델이 프롬프트 지시(길이 제한/인용 금지)를 지키지 않았을 때를 대비한 방어 로직.
    - 기사 인용문 등에서 흔한 말줄임표를 제거
    - 지정된 최대 길이를 넘으면 문장 끝(마침표/쉼표 등)을 최대한 살려서 자르고, 없으면 강제로 잘라 '…' 부착
    """
    b = b.strip().strip('"').strip("'").strip()
    for ell in ("...", "…"):
        if b.endswith(ell):
            b = b[: -len(ell)].rstrip()

    if len(b) <= MAX_BULLET_CHARS:
        return b

    truncated = b[:MAX_BULLET_CHARS]
    # 문장 중간에 단어가 잘리지 않도록 마지막 공백 기준으로 한 번 더 다듬기 (너무 짧아지면 포기)
    last_space = truncated.rfind(" ")
    if last_space > MAX_BULLET_CHARS * 0.6:
        truncated = truncated[:last_space]
    return truncated.rstrip(",.;: ") + "…"


def _bullets_to_summary(bullets):
    """['a', 'b'] -> '- a\\n- b' 형태의 여러 줄 문자열로 변환 (Slack/Streamlit에서 줄바꿈되어 보임)."""
    bullets = [_clean_bullet(b) for b in (bullets or []) if b and b.strip()]
    bullets = [b for b in bullets if b]
    bullets = bullets[:SUMMARY_BULLET_COUNT]
    return "\n".join(f"- {b}" for b in bullets)


def _is_rate_limit_error(e):
    """anthropic 패키지의 RateLimitError(429)인지 문자열 기반으로 방어적으로 판별."""
    name = e.__class__.__name__.lower()
    msg = str(e).lower()
    return "ratelimit" in name or "429" in msg or "rate_limit" in msg or "overloaded" in msg


def _summarize_batch(client, batch):
    user_content = _build_user_content(batch)
    last_err = None
    for attempt in range(MAX_RETRY + 1):
        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=3000,
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
            if attempt >= MAX_RETRY:
                break
            # 레이트리밋(429)인 경우 충분히 오래 대기해야 회복됨. 그 외 오류는 짧게 재시도.
            if _is_rate_limit_error(e):
                wait = RATE_LIMIT_WAIT_SEC
                reason = "레이트리밋"
            else:
                wait = 1.5 * (attempt + 1)
                reason = "일반 오류"
            print(f"[WARN] 요약 배치 실패 ({reason}, 시도 {attempt + 1}/{MAX_RETRY + 1}): {e} → {wait}초 대기 후 재시도")
            time.sleep(wait)
    # 재시도 모두 실패하면 폴백: 원문 스니펫을 그대로 요약으로 사용
    print(f"[ERROR] 배치 요약 최종 실패, 폴백 처리: {last_err}")
    return [
        {"summary_bullets": [r.get("raw_description", "")[:150]], "keywords": "", "opinion": "", "target_price": ""}
        for r in batch
    ]


OVERVIEW_SYSTEM_PROMPT = """\
너는 K-뷰티(한국 화장품) 산업 전문 애널리스트다. 아래에 오늘 하루 수집된 기사/리포트
목록이 "[기업명] 제목: 핵심요약" 형태로 여러 줄 주어진다. 이 목록 전체를 훑어서,
개별 기사를 나열하지 말고 오늘 하루 K-뷰티 산업 전체를 관통하는 흐름·공통 이슈·
주목할 만한 시그널을 종합한 "오늘의 총평"을 3~5줄로 작성하라.

규칙:
- 각 줄은 "- "로 시작하는 개조식 문장 (예: "- 북미향 선케어 수출 호조가 다수 기업에서 공통 확인됨")
- 여러 기사에 걸쳐 반복되는 주제(예: 특정 지역 수출, 특정 카테고리 실적, 정책/규제 이슈)가 있다면 우선적으로 짚을 것
- 개별 기업 실적 나열이 아니라 "산업 차원에서 오늘 무엇이 의미 있었는지"에 초점
- 다른 설명 문장, 제목, 인사말 없이 불릿 줄들만 출력
"""


def generate_daily_overview(records, max_digest_chars=6000):
    """
    오늘 수집된 전체 records를 훑어서 산업 전체 관점의 '오늘의 총평' 3~5줄을 생성합니다.
    개별 기사 요약(summarize_records)과는 별개로, 하루 전체를 한 번 더 종합하는 호출입니다.
    실패하면 빈 문자열을 반환하여 리포트 생성 자체는 계속 진행되도록 합니다.
    """
    if not records:
        return ""

    try:
        client = _get_client()
    except RuntimeError as e:
        print(f"[WARN] 총평 생성 건너뜀: {e}")
        return ""

    digest_lines = []
    for r in records:
        first_line = ""
        if r.get("summary"):
            first_line = r["summary"].split("\n")[0].lstrip("- ").strip()
        first_line = first_line or r.get("raw_description", "")[:80]
        digest_lines.append(f"- [{r.get('company', '산업전반')}] {r.get('title', '')}: {first_line}")
    digest_text = "\n".join(digest_lines)[:max_digest_chars]

    last_err = None
    for attempt in range(MAX_RETRY + 1):
        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=600,
                system=OVERVIEW_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": digest_text}],
            )
            text = "".join(block.text for block in resp.content if block.type == "text")
            return text.strip()
        except Exception as e:
            last_err = e
            if attempt >= MAX_RETRY:
                break
            wait = RATE_LIMIT_WAIT_SEC if _is_rate_limit_error(e) else 1.5 * (attempt + 1)
            print(f"[WARN] 총평 생성 실패 (시도 {attempt + 1}/{MAX_RETRY + 1}): {e} → {wait}초 대기 후 재시도")
            time.sleep(wait)
    print(f"[WARN] 총평 생성 최종 실패, 총평 없이 진행: {last_err}")
    return ""


def summarize_records(records):
    """
    records: collector.collect_all()이 반환한 dict 리스트.
    각 record에 summary(여러 줄 불릿)/keywords/opinion/target_price 를 채워서 반환합니다.
    """
    if not records:
        return records

    client = _get_client()

    # 1) 기사 본문 미리 가져오기 (요약 API 호출 전에 채워둬야 실제 본문 기반 요약이 가능)
    print("[INFO] 기사 본문 수집 중...")
    for i, r in enumerate(records):
        r["full_text"] = fetch_article_text(r.get("link", ""))
        if (i + 1) % 10 == 0 or (i + 1) == len(records):
            print(f"[INFO] 본문 수집 진행: {i + 1}/{len(records)}")

    # 2) 배치 단위로 Claude 요약 호출
    # 배치 사이에 짧게 쉬어가며 호출해 레이트리밋(요청량 과다) 오류를 예방합니다.
    for batch_idx, start in enumerate(range(0, len(records), BATCH_SIZE)):
        if batch_idx > 0:
            time.sleep(BATCH_PACING_SEC)
        batch = records[start : start + BATCH_SIZE]
        results = _summarize_batch(client, batch)
        for r, res in zip(batch, results):
            bullets = res.get("summary_bullets")
            summary = _bullets_to_summary(bullets)
            r["summary"] = summary or r.get("raw_description", "")[:150]
            r["keywords"] = ", ".join(
                filter(None, [r.get("keywords", ""), res.get("keywords", "")])
            ).strip(", ")
            # 리포트성 기사인 경우 category를 '리포트'로 격상 (투자의견/목표주가가 파싱되면)
            if res.get("opinion") or res.get("target_price"):
                r["category"] = "리포트"
            r["opinion"] = res.get("opinion", "")
            r["target_price"] = res.get("target_price", "")
            r.pop("full_text", None)  # DB에 저장할 필요 없는 임시 필드 정리
        print(f"[INFO] 요약 진행: {min(start + BATCH_SIZE, len(records))}/{len(records)}")

    return records


if __name__ == "__main__":
    sample = [
        {
            "title": "아모레퍼시픽, 북미 시장서 선케어 매출 급증",
            "link": "",
            "raw_description": "아모레퍼시픽이 북미 시장에서 선케어 제품 판매 호조로 3분기 실적 개선이 기대된다는 증권사 리포트가 나왔다. 목표주가는 20만원, 투자의견은 매수.",
        }
    ]
    result = summarize_records(sample)
    print(result[0]["summary"])
