# asset-flow

한국투자증권(KIS) · 업비트(UPBIT) · 펀드가이드 API를 통해 다중 계좌의 자산 잔고를 수집하고 표준화된 스키마로 DB에 적재하는 포트폴리오 데이터 파이프라인입니다.

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
    [Layer 2] transformers/     컬럼 리네이밍 · 숫자 정규화 · 환율 교차 환산
          │
          ▼
    [Layer 3] managers/         토큰 발급 · 캐시 · DB 연결 · fund_price 조회
          │
          ▼
    [Airflow DAGs]              오케스트레이션 · DB 적재
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
| 런타임 | Python 3.12, `uv` |

---

## 프로젝트 구조

```
asset-flow/
├── src/
│   ├── config/                     # API 설정 · 출력 스키마
│   │   ├── kis.py                  # KIS: BASE_URL, PATHS, TR_IDS, PARAMS, EXCHANGE_RATE_PRODUCT_CODES
│   │   ├── upbit.py                # UPBIT: BASE_URL, PATHS
│   │   └── schemas.py              # 컬럼 리네임 매핑, TypedDict 출력 스키마, 컬럼 리스트
│   │
│   ├── clients/                    # Layer 1 — HTTP 클라이언트
│   │   ├── base_client.py          # BaseApiClient (safe_request, _build_url, _build_headers)
│   │   ├── kis_client.py           # KISApiClient (잔고·환율·펀드잔고 조회)
│   │   └── upbit_client.py         # UpbitApiClient (잔고·시세·마켓코드 조회)
│   │
│   ├── transformers/               # Layer 2 — 데이터 변환
│   │   ├── base_transformer.py     # normalize_numeric (콤마 제거 · float 변환 · NaN 처리)
│   │   ├── kis_transformer.py      # 국내/해외/연금펀드/CMA 잔고 변환, 환율 변환
│   │   └── upbit_transformer.py    # 업비트 잔고 변환
│   │
│   ├── managers/                   # Layer 3 — 인프라 관리
│   │   ├── token_manager.py        # 토큰 발급 · 일별 파일 캐시
│   │   └── db_manager.py           # DB 엔진 생성 · fund_price_daily 조회
│   │
│   └── crawler/
│       └── fund_crawler.py         # fundguide.net 펀드 기준가 크롤러 (Playwright)
│
├── main.py                         # 통합 실행 스크립트 (개발용)
├── pyproject.toml
└── .env                            # 환경 변수 (git 제외)
```

---

## 설치

```bash
git clone https://github.com/hayden-hyun/asset-flow.git
cd asset-flow

uv sync

# 펀드 크롤러 사용 시 최초 1회
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
KIS_CMA={"appkey":"...","secret":"...","account":"XXXXXXXXXX","product_code":"01","type":"CMA"}

# 업비트 설정
UPBIT={"appkey":"...","secret":"..."}

# DB 연결 설정
DB_INFO={"host":"...","port":5432,"database":"...","user":"...","password":"..."}

# 토큰 캐시 경로 (기본값: data/tokens)
TOKEN_DIR=data/tokens
```

---

## 지원 계좌

| 환경 변수 | 계좌 유형 | 잔고 변환 함수 |
|----------|----------|--------------|
| `KIS_STOCK` | 종합매매 (국내 · 해외주식) | `transform_domestic_balance` / `transform_overseas_balance` |
| `KIS_ISA` | 개인형 ISA (중개형) | `transform_domestic_balance` |
| `KIS_PENSION` | 연금저축 | `transform_pension_fund_balance` / `transform_domestic_balance` |
| `KIS_IRP` | IRP | `transform_domestic_balance` |
| `KIS_CMA` | CMA | `transform_cma_cash_balance` |
| `UPBIT` | 가상자산 | `transform_upbit_balance` |

---

## 출력 스키마

### 잔고 (`BalanceRecord`)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `standard_date` | str | 기준일 (YYYY-MM-DD) |
| `account_code` | str | 계좌번호-상품코드 (예: `XXXXXXXXXX-01`) |
| `account_name` | str | 계좌 유형명 (예: 종합매매, 연금저축) |
| `product_code` | str | 종목코드 |
| `product_name` | str | 종목명 |
| `asset_type` | str | 자산 유형 (`STOCK` / `FUND` / `CRYPTO` / `CASH`) |
| `currency_code` | str | 통화코드 (`KRW` / `USD` 등) |
| `exchange_code` | str | 거래소코드 (`KRX` / `NASD` / `UPBIT` 등) |
| `multiplier` | float | 수량 환산 계수 (펀드: 0.001, 그 외: 1.0) |
| `holding_quantity` | float | 보유수량 |
| `unit_purchase_price` | float | 매입단가 |
| `unit_market_price` | float | 현재가 |
| `total_purchase_amount` | float | 매입금액 |
| `total_evaluation_amount` | float | 평가금액 |
| `total_profit_amount` | float | 평가손익 |
| `valuation_profit_rate` | float | 평가손익률 (%) |

### 환율 (`ExchangeRateRecord`)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `standard_date` | str | 기준일 (YYYY-MM-DD) |
| `symbol` | str | 심볼 (`FX@KRWKFTC` 등) |
| `currency_code` | str | 통화코드 (`USD` / `JPY` / `GBP` / `EUR`) |
| `currency_pair_name` | str | 통화쌍명 (원/달러 · 원/엔 등) |
| `base_rate` | float | 매매기준율 |
| `previous_day_closing_price` | float | 전일 종가 |
| `opening_price` | float | 시가 |
| `highest_price` | float | 고가 |
| `lowest_price` | float | 저가 |

> **환율 교차 환산**: KIS API가 달러/파운드·달러/유로를 반환하는 경우, 원/달러를 기준으로 원/파운드·원/유로로 자동 변환합니다.

---

## 실행

```bash
uv run python main.py

# 펀드 기준가 단독 크롤링
uv run python -m src.crawler.fund_crawler
```

---

## 토큰 관리

- **KIS**: OAuth 2.0 액세스 토큰을 일 1회 발급 → `data/tokens/YYYYMMDD_token.json` 캐시. 다음 날 실행 시 전날 파일 자동 삭제 후 재발급.
- **UPBIT**: JWT를 매 요청 시 재생성 (만료 없음).
- KST 기준 날짜 사용 (새벽 UTC 불일치 방지).

---