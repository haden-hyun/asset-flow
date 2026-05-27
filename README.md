# asset-flow

한국투자증권(KIS) · 업비트(UPBIT) · 펀드가이드 API를 통해 다중 계좌의 자산 잔고를 수집하고 표준화된 스키마로 통합 관리하는 포트폴리오 데이터 파이프라인입니다.

---

## 아키텍처

```
외부 API
  KIS API ──────────────────────┐
  UPBIT API ─────────────────── ┤
  fundguide.net (Playwright) ── ┘
          │
          ▼
    [Layer 1] clients/          HTTP 요청 · 원시 JSON 반환
          │
          ▼
    [Layer 2] transformers/     컬럼 리네이밍 · 숫자 정규화 · 환율 교차 환산  (구현 중)
          │
          ▼
    [Layer 3] managers/         토큰 발급 · 캐시 · DB 연결
          │
          ▼
    [Layer 4] services/         비즈니스 로직 · 전체 조율                      (구현 중)
```

`src/config/` 가 모든 레이어에서 공유되는 API 설정 및 출력 스키마를 담당합니다.

---

## 기술 스택

| 분류 | 라이브러리 |
|------|-----------|
| HTTP 클라이언트 | `requests` |
| 데이터 처리 | `pandas`, `numpy` |
| 크롤링 | `playwright` |
| 인증 | `pyjwt`, `python-dotenv` |
| DB | `psycopg2-binary`, `sqlalchemy` |
| 유효성 검사 | `pydantic` |
| 시간대 | `pytz` |
| 런타임 | Python 3.12, `uv` |

---

## 프로젝트 구조

```
asset-flow/
├── src/
│   ├── config/                     # API 설정 · 출력 스키마
│   │   ├── kis.py                  # KIS: BASE_URL, PATHS, TR_IDS, PARAMS
│   │   ├── upbit.py                # UPBIT: BASE_URL, PATHS
│   │   └── schemas.py              # 컬럼 리네임 매핑, TypedDict 출력 스키마
│   │
│   ├── clients/                    # Layer 1 — HTTP 클라이언트
│   │   ├── base_client.py          # BaseApiClient (safe_request, _build_url)
│   │   ├── kis_client.py           # KISApiClient
│   │   └── upbit_client.py         # UpbitApiClient
│   │
│   ├── transformers/               # Layer 2 — 데이터 변환 (구현 중)
│   │
│   ├── managers/                   # Layer 3 — 인프라 관리
│   │   ├── token_manager.py        # 토큰 발급 · 일별 파일 캐시
│   │   └── db_manager.py           # DB 연결 (구현 중)
│   │
│   ├── services/                   # Layer 4 — 비즈니스 로직 (구현 중)
│   │
│   └── crawler/
│       └── fund_crawler.py         # fundguide.net 펀드 기준가 크롤러
│
├── test.py                         # 통합 실행 스크립트 (개발용)
├── main.py                         # 엔트리포인트
├── pyproject.toml
└── .env                            # 환경 변수 (git 제외)
```

---

## 설치

```bash
# 저장소 클론
git clone https://github.com/hayden-hyun/asset-flow.git
cd asset-flow

# 의존성 설치 (uv)
uv sync

# Playwright 브라우저 설치 (펀드 크롤러 사용 시)
uv run playwright install chromium
```

---

## 환경 변수 설정

`.env` 파일을 프로젝트 루트에 생성합니다.

```dotenv
# KIS 계좌별 설정 (JSON 문자열)
KIS_STOCK={"appkey":"...","secret":"...","account":"XXXXXXXXXX","product_code":"01","type":"종합매매"}
KIS_ISA={"appkey":"...","secret":"...","account":"XXXXXXXXXX","product_code":"01","type":"개인형ISA"}
KIS_PENSION={"appkey":"...","secret":"...","account":"XXXXXXXXXX","product_code":"01","type":"연금저축"}
KIS_IRP={"appkey":"...","secret":"...","account":"XXXXXXXXXX","product_code":"01","type":"IRP"}

# 업비트 설정
UPBIT={"appkey":"...","secret":"..."}

# 토큰 캐시 경로 (기본값: data/tokens)
TOKEN_DIR=data/tokens
```

---

## 지원 계좌

| 환경 변수 | 계좌 유형 |
|----------|----------|
| `KIS_STOCK` | 종합매매 (국내 · 해외주식) |
| `KIS_ISA` | 개인형 ISA (중개형) |
| `KIS_PENSION` | 연금저축 |
| `KIS_IRP` | IRP |
| `UPBIT` | 가상자산 |

---

## 실행

```bash
# 통합 자산 수집 (개발용)
uv run python test.py

# 펀드 기준가 크롤링
uv run python src/crawler/fund_crawler.py
```

---

## 출력 스키마

### 잔고 (`BalanceRecord`)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `standard_date` | str | 기준일 (YYYYMMDD) |
| `account_division_name` | str | 계좌 구분명 |
| `product_code` | str | 종목코드 |
| `product_name` | str | 종목명 |
| `currency_code` | str | 통화코드 (KRW / USD 등) |
| `exchange_code` | str | 거래소코드 (KRX / NASD / UPBIT 등) |
| `holding_quantity` | float | 보유수량 |
| `purchase_average_cost` | float | 매입단가 |
| `current_price` | float | 현재가 |
| `total_purchase_amount` | float | 매입금액 |
| `market_value` | float | 평가금액 |
| `valuation_profit_amount` | float | 평가손익 |
| `valuation_profit_rate` | float | 평가손익률 (%) |

### 환율 (`ExchangeRateRecord`)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `standard_date` | str | 기준일 |
| `product_code` | str | 상품코드 (`FX@KRWKFTC` 등) |
| `currency_pair_name` | str | 통화쌍명 (원/달러 · 원/엔 등) |
| `currency_code` | str | 통화코드 |
| `previous_day_closing_price` | float | 전일 종가 |
| `current_price` | float | 현재가 |
| `opening_price` | float | 시가 |
| `highest_price` | float | 고가 |
| `lowest_price` | float | 저가 |

> **환율 교차 환산**: 달러/파운드, 달러/유로는 원/달러를 기준으로 원/파운드, 원/유로로 자동 변환됩니다.

---

## 토큰 관리

- KIS: OAuth 2.0 액세스 토큰 (일 1회 발급 → `data/tokens/YYYYMMDD_token.json` 캐시)
- UPBIT: JWT (매 요청 시 재생성)
- 자정 이후 실행 시 전날 토큰 파일 자동 삭제 후 재발급
- KST 기준 날짜 사용 (새벽 UTC 불일치 방지)

---

## 구현 현황

| 레이어 | 상태 |
|--------|------|
| `config/` | ✅ 완료 |
| `clients/` | ✅ 완료 |
| `managers/token_manager.py` | ✅ 완료 |
| `crawler/fund_crawler.py` | ✅ 완료 |
| `transformers/` | 🚧 구현 중 |
| `managers/db_manager.py` | 🚧 구현 중 |
| `services/` | 🚧 구현 중 |
