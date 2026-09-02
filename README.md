# K-뷰티 데일리 뉴스클리핑 자동화 시스템

21개 K-뷰티 상장/비상장사 + 산업 전반 뉴스를 매일 자동 수집 → AI 요약 → SQLite 누적 저장 →
Slack 데일리 리포트 발송 → 과거 이력 검색까지 지원하는 무료(서버비 0원) 자동화 시스템입니다.

## 1. 전체 구조

```
kbeauty_news/
├── config.py              # 공통 설정 (기업 리스트, 키워드, 환경변수)
├── db.py                  # SQLite 스키마 및 CRUD/검색 함수
├── collector.py           # 네이버 뉴스 검색 API 수집기
├── summarizer.py          # Claude API 요약 + 태그 추출
├── report_generator.py    # 데일리 리포트 텍스트 생성
├── notifier.py            # Slack(+이메일 옵션) 발송
├── main_daily.py          # 전체 파이프라인 오케스트레이션 (매일 실행 대상)
├── search_cli.py          # 커맨드라인 검색 도구
├── search_app.py          # Streamlit 검색 웹 UI
├── requirements.txt
├── .env.example           # 로컬 개발용 환경변수 템플릿
├── .github/workflows/
│   └── daily_news.yml     # GitHub Actions 매일 자동 실행 스케줄
└── data/
    └── kbeauty_news.db    # SQLite DB (최초 실행 시 자동 생성, 이후 계속 누적)
```

### 데이터 흐름

```
[네이버 뉴스 검색 API]
        │  (21개사 키워드 + K뷰티 산업 키워드, 최근 24시간)
        ▼
   collector.py  ──── 중복(link) 제거
        ▼
   summarizer.py ──── Claude API로 요약 2~3문장 + 태그 추출
        │              (투자의견/목표주가 언급 시 파싱 → category='리포트')
        ▼
      db.py    ──── SQLite에 누적 저장 (link UNIQUE로 영구 중복방지)
        ▼
report_generator.py ── 헤드라인Top5 + 산업동향5선 + 기업별 이슈 텍스트 생성
        ▼
   notifier.py  ──── Slack Webhook 발송
```

## 2. DB 테이블 구조 (`news_report`)

| 컬럼 | 설명 |
|---|---|
| collected_at | 수집(적재) 일시 |
| published_at | 원문 발행 일시 |
| category | `뉴스` \| `리포트` |
| company | 관련 기업명 (21개사 중 하나 또는 `산업전반`) |
| title | 제목 |
| summary | AI 요약 (2~3문장) |
| source | 매체명 |
| link | 원문 링크 (**UNIQUE**, 중복 수집 방지 키) |
| opinion | 투자의견 (증권사 리포트 언급 시) |
| target_price | 목표주가 (증권사 리포트 언급 시) |
| keywords | 관련 키워드 태그 (쉼표 구분) |
| raw_description | 원문 스니펫 (요약 실패시 폴백) |

`db.py`의 `search(company, keyword, start_date, end_date, category)` 함수 하나로
기업명/키워드/기간 조합 검색이 모두 가능합니다.

## 3. 처음 설치하기 (로컬에서 먼저 테스트)

### 3-1. 필요한 API 키 발급

1. **네이버 뉴스 검색 API** (무료 쿼터 제공, 초과 시 종량제)
   - ⚠️ 2026년 기준 뉴스 검색 API는 기존 개발자센터(developers.naver.com)에서
     **NAVER API HUB**(네이버클라우드플랫폼)로 이전되었습니다. 옛 개발자센터의
     "사용 API" 드롭다운에는 더 이상 "검색"이 뜨지 않으니 아래 새 경로로 발급받으세요.
   - https://apihub.naver.com 접속 → 네이버클라우드플랫폼(NCP) 계정으로 로그인/가입
     (일반 네이버 계정과 별개로 NCP 회원가입이 필요할 수 있습니다)
   - NCP 콘솔에서 **All Services → Application Services → NAVER API HUB → 신청하기**
     이동 → Subscription 메뉴에서 **[서비스 이용 신청]**
   - Application을 새로 등록하면서 사용할 API로 **뉴스 검색**을 선택
   - 등록 후 **Application 관리** 화면에서 **Client ID(API Key ID)** / **Client Secret(API Key)**
     확인
   - 이미 2027-06-30 이전 발급된 구 개발자센터 키를 갖고 있다면 그대로 써도 되며, 이 경우
     `.env`에 `NAVER_API_MODE=legacy`로 설정하세요 (기본값은 신규 방식인 `hub`).
2. **Anthropic Claude API 키**
   - https://console.anthropic.com/settings/keys 에서 발급 (유료, 사용량 과금)
3. **Slack Incoming Webhook URL**
   - https://api.slack.com/apps 에서 앱 생성 → "Incoming Webhooks" 활성화 →
     보고서를 받을 채널 선택 후 Webhook URL 발급

### 3-2. 로컬 환경 설정

```bash
git clone <이 저장소 주소>
cd kbeauty_news

python -m venv venv
source venv/bin/activate   # Windows는 venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# .env 파일을 열어 위에서 발급받은 키들을 채워넣으세요
```

### 3-3. 수동 실행 테스트

```bash
# 1) DB만 초기화
python db.py

# 2) 전체 파이프라인 실행 (수집→요약→저장→Slack발송)
python main_daily.py

# Slack 발송 없이 DB 저장까지만 테스트
python main_daily.py --no-send

# 아무것도 저장/발송하지 않고 콘솔에만 출력 (가장 안전한 첫 테스트)
python main_daily.py --dry-run
```

정상적으로 동작하면 콘솔에 수집 건수, 요약 진행 상황, 생성된 리포트 텍스트가 출력되고,
Slack 채널에 데일리 리포트 메시지가 도착합니다.

## 4. 과거 데이터 검색하기

### 4-1. CLI로 검색

```bash
# 아모레퍼시픽 관련 지난 1달간 뉴스/리포트
python search_cli.py --company 아모레퍼시픽 --days 30

# '북미' 키워드가 들어간 기사 전체 검색
python search_cli.py --keyword 북미

# 'EU 규제' + 특정 기간
python search_cli.py --keyword "EU 규제" --start 2026-08-01 --end 2026-08-31

# 리포트만 필터
python search_cli.py --company 코스맥스 --category 리포트
```

### 4-2. Streamlit 웹 UI로 검색

```bash
streamlit run search_app.py
```

브라우저가 자동으로 열리고 (`http://localhost:8501`), 사이드바에서 기업명 드롭다운,
키워드 텍스트박스, 기간(슬라이더 또는 직접 지정)을 조합해 검색할 수 있습니다.
표 형태 또는 카드 형태로 결과를 보고, CSV로 다운로드할 수도 있습니다.

## 5. 매일 자동 실행하기 (GitHub Actions, 서버 비용 0원)

이 저장소는 `.github/workflows/daily_news.yml` 워크플로우가 이미 포함되어 있어,
GitHub에 푸시만 하면 별도 서버 없이 GitHub이 제공하는 무료 실행 환경(월 2,000분)에서
매일 자동으로 파이프라인이 실행됩니다.

### 5-1. GitHub 저장소 준비

```bash
# 최초 1회
git init
git add .
git commit -m "init: K-뷰티 데일리 뉴스클리핑 시스템"
git branch -M main
git remote add origin <내 GitHub 저장소 주소>
git push -u origin main
```

> ⚠️ `.env` 파일은 `.gitignore`에 의해 절대 커밋되지 않습니다. API 키는 아래처럼
> GitHub Secrets로 별도 등록해야 합니다.

### 5-2. GitHub Secrets 등록

저장소 페이지 → **Settings** → **Secrets and variables** → **Actions** →
**New repository secret** 에서 아래 4개를 각각 등록합니다.

| Secret 이름 | 값 |
|---|---|
| `NAVER_CLIENT_ID` | NAVER API HUB에서 발급받은 Client ID (API Key ID) |
| `NAVER_CLIENT_SECRET` | NAVER API HUB에서 발급받은 Client Secret (API Key) |
| `ANTHROPIC_API_KEY` | Anthropic Console에서 발급받은 API 키 |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL |

### 5-3. 실행 스케줄 확인/변경

`.github/workflows/daily_news.yml` 상단의 cron 설정:

```yaml
on:
  schedule:
    - cron: "0 23 * * *"   # UTC 기준 → 한국시간(KST) 매일 오전 8시
```

GitHub Actions의 cron은 **UTC 기준**입니다. 한국시간 오전 N시에 실행하려면
`(N - 9)`시(UTC)로 설정하세요 (음수면 +24, 전날 날짜로 계산). 예: 한국시간 오전 7시 → `0 22 * * *`.

### 5-4. 동작 확인

- 저장소의 **Actions** 탭에서 워크플로우 실행 로그를 볼 수 있습니다.
- 스케줄을 기다리지 않고 바로 테스트하려면 Actions 탭 → `K-뷰티 데일리 뉴스클리핑` →
  **Run workflow** 버튼으로 수동 실행이 가능합니다 (`workflow_dispatch` 등록되어 있음).
- 매일 실행 후, 누적된 `data/kbeauty_news.db` 파일이 자동으로 다시 저장소에 커밋되어
  다음 실행에서도 이어서 누적됩니다 (워크플로우 마지막 "누적 DB 변경사항 커밋" 스텝).

### 5-5. 검색 UI를 상시 서비스로 쓰고 싶다면

GitHub Actions는 배치 실행용이라 Streamlit 앱을 상시 구동하기엔 적합하지 않습니다.
비용 없이 Streamlit 검색 UI를 웹에 상시 배포하려면 **Streamlit Community Cloud**
(https://streamlit.io/cloud, 무료 티어 제공)에 이 저장소를 연결해 `search_app.py`를
배포하는 방법을 추천합니다. GitHub Actions가 커밋하는 `data/kbeauty_news.db`를
그대로 읽어오도록 저장소만 동일하게 연결하면 됩니다.

## 6. 증권사 리포트(PDF) 수집 확장 안내

네이버 뉴스 검색 API는 뉴스 기사만 포함하고, 증권사 애널리스트 리포트(PDF)는 포함하지
않습니다. DB 스키마(`category`, `opinion`, `target_price` 컬럼)는 이미 리포트를 위한
자리가 마련되어 있으므로, 필요 시 아래와 같이 확장할 수 있습니다.

1. 한경컨센서스(https://consensus.hankyung.com) 또는 네이버금융 리서치 페이지를
   `requests` + `BeautifulSoup`으로 크롤링하는 `report_collector.py`를 추가로 작성
2. 종목명이 21개사 중 하나와 일치하는 리포트만 필터링
3. PDF는 `pdfplumber` 등으로 텍스트 추출 후 `summarizer.py`의 요약 로직 재사용
4. 결과 dict를 `category='리포트'`로 만들어 `collector.collect_all()`의 결과 리스트에 합친 뒤
   동일하게 `db.insert_records()`에 전달

크롤링 대상 사이트의 저작권/이용약관을 반드시 확인한 후 진행하세요.

## 7. 비용 및 제약사항 요약

- 네이버 뉴스 검색 API (NAVER API HUB): 무료 쿼터 제공 + 초과분 종량제 (정확한 무료 한도는
  apihub.naver.com 콘솔에서 확인하세요). 이 시스템은 21개사×평균 1.x키워드 + 산업키워드 5개 =
  하루 약 30회 내외 호출만 하므로 대부분의 경우 무료 쿼터 내에서 충분합니다.
- Claude API: 사용량 기반 과금 (배치 처리로 호출 횟수를 최소화하도록 설계됨, `BATCH_SIZE`는
  `summarizer.py` 상단에서 조정 가능)
- Slack Webhook: 무료
- GitHub Actions: 무료 티어 월 2,000분 (이 파이프라인은 1회 실행에 수 분 내외 소요)
- SQLite: 별도 비용 없음, 단 GitHub 저장소 용량 한도(무료 플랜 기준 넉넉함) 내에서 계속 누적됨
