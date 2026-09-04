# -*- coding: utf-8 -*-
"""
config.py
=========
K-뷰티 뉴스클리핑 시스템 공통 설정 파일.

모든 민감한 값(API 키, Webhook URL 등)은 환경변수에서 읽어옵니다.
로컬 개발 시에는 이 폴더에 `.env` 파일을 만들고 `.env.example`을 참고해 값을 채운 뒤
`python-dotenv`가 자동으로 로드합니다. GitHub Actions에서는 리포지토리의
Settings > Secrets and variables > Actions 에 동일한 이름으로 Secret을 등록하면 됩니다.
"""
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 서버가 어느 시간대에서 돌든(GitHub Actions는 UTC) 이 시스템의 모든 날짜/시각
# 기록은 한국시간(KST, UTC+9) 기준으로 통일합니다. datetime.now()를 직접 쓰면
# GitHub Actions(UTC)에서는 실제 한국시간보다 9시간 이른 날짜로 저장되어
# "분명 오늘 아침에 실행됐는데 어제 날짜로 찍힌다" 같은 혼란이 생깁니다.
KST = timezone(timedelta(hours=9))


def now_kst():
    """서버 시간대와 무관하게 항상 한국시간(KST) 기준 현재 시각을 반환합니다."""
    return datetime.now(timezone.utc).astimezone(KST)

# .env 파일이 있으면 로드 (로컬 개발용). GitHub Actions 등 실제 서버 환경에서는
# 이미 환경변수가 주입되어 있으므로 이 호출은 아무 영향을 주지 않습니다.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _env(name, default=""):
    """환경변수/Secret 값을 읽어오면서 앞뒤 공백·줄바꿈을 제거합니다.

    GitHub Secrets나 .env에 값을 복사해 붙여넣을 때 끝에 눈에 안 보이는
    개행문자(\\n)가 같이 들어가는 경우가 흔한데, 이 개행문자가 그대로
    HTTP 헤더 값으로 쓰이면 requests 라이브러리가
    "Invalid leading whitespace, reserved character(s), or return
    character(s) in header value" 에러를 내며 실패합니다. 그래서 API 키류는
    전부 이 헬퍼를 통해 읽어 strip() 처리합니다.
    """
    return os.environ.get(name, default).strip()

# --------------------------------------------------------------------------
# 경로 설정
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = str(DATA_DIR / "kbeauty_news.db")

# --------------------------------------------------------------------------
# 대상 기업 21개사
# 검색 정확도를 높이기 위해 기업마다 '검색용 키워드'를 리스트로 관리합니다.
# (예: 정식 명칭과 통상 약칭이 다른 경우 여러 개를 등록)
# --------------------------------------------------------------------------
TARGET_COMPANIES = {
    "클리오": ["클리오"],
    "아이패밀리에스씨": ["아이패밀리에스씨", "아이패밀리SC"],
    "VT(브이티)": ["브이티", "VT코스메틱", "VT주식회사"],
    "에이블씨엔씨": ["에이블씨엔씨", "미샤"],
    "토니모리": ["토니모리"],
    "서린컴퍼니": ["서린컴퍼니"],
    "삐아": ["삐아"],
    "티르티르": ["티르티르"],
    "에프앤코": ["에프앤코"],
    "투쿨포스쿨": ["투쿨포스쿨"],
    "정샘물뷰티": ["정샘물뷰티", "정샘물"],
    "더샘인터내셔날": ["더샘인터내셔날", "더샘"],
    "아모레퍼시픽": ["아모레퍼시픽"],
    "에이피알": ["에이피알", "APR", "메디큐브"],
    "달바글로벌": ["달바글로벌", "달바", "d'Alba"],
    "마녀공장": ["마녀공장"],
    "네이처리퍼블릭": ["네이처리퍼블릭"],
    "아로마티카": ["아로마티카"],
    "한국콜마": ["한국콜마"],
    "코스맥스": ["코스맥스"],
    "코스메카코리아": ["코스메카코리아"],
}

# 기업명과 별개로 산업 전반의 동향을 잡기 위한 공통 키워드
INDUSTRY_KEYWORDS = ["K뷰티", "K-뷰티", "화장품 수출", "인디뷰티", "올리브영"]

# 수집에 실제 사용할 전체 검색어 목록 (기업 키워드 + 산업 키워드)
ALL_SEARCH_KEYWORDS = sorted(
    {kw for kws in TARGET_COMPANIES.values() for kw in kws} | set(INDUSTRY_KEYWORDS)
)

# --------------------------------------------------------------------------
# 네이버 뉴스 검색 API
#
# 2026년 기준, 네이버 뉴스 검색 API는 기존 개발자센터(developers.naver.com)에서
# "NAVER API HUB"(네이버클라우드플랫폼)로 이전되었습니다. 신규로 키를 발급받는
# 사용자는 전부 이 새 방식을 사용하게 됩니다 (README 3-1절 참고).
#   - 신규(NAVER API HUB) 키: NAVER_API_MODE=hub (기본값)
#   - 2027-06-30 이전에 발급받은 구(舊) 개발자센터 키가 아직 있다면: NAVER_API_MODE=legacy
# --------------------------------------------------------------------------
NAVER_CLIENT_ID = _env("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = _env("NAVER_CLIENT_SECRET")
NAVER_API_MODE = _env("NAVER_API_MODE", "hub")  # "hub" 또는 "legacy"

# 검색 시 최근 N시간 이내 기사만 채택 (기본 24시간)
COLLECT_WINDOW_HOURS = int(os.environ.get("COLLECT_WINDOW_HOURS", "24"))

# 키워드 1개당 최대 몇 건까지 API에서 가져올지 (네이버 뉴스 검색 API 1회 호출 결과 수, 최대 100)
NAVER_DISPLAY_COUNT = int(os.environ.get("NAVER_DISPLAY_COUNT", "30"))

# --------------------------------------------------------------------------
# Anthropic Claude API (요약 / 태그 추출)
# --------------------------------------------------------------------------
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
CLAUDE_MODEL = _env("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")

# --------------------------------------------------------------------------
# Slack 발송
# --------------------------------------------------------------------------
SLACK_WEBHOOK_URL = _env("SLACK_WEBHOOK_URL")

# 리포트에 표시할 헤드라인/산업동향 개수
REPORT_TOP_HEADLINE_COUNT = 5
REPORT_INDUSTRY_TREND_COUNT = 5
