import os
import json
import pandas as pd
from datetime import datetime, timedelta
from pytz import timezone
from dotenv import load_dotenv

from src.managers.token_manager import TokenManager
from src.clients.kis_client import KISApiClient
from src.clients.upbit_client import UpbitApiClient
from src.config.schemas import KIS_RENAME, UPBIT_RENAME, BALANCE_COLUMNS, EXCHANGE_RATE_COLUMNS

load_dotenv()

EXCHANGE_RATE_PRODUCT_CODES = ["FX@KRWKFTC", "FX@KRWJS", "FX@GBP", "FX@EUR"]
CURRENCY_CODE_MAP = {"원/달러": "USD", "원/엔": "JPY", "원/파운드": "GBP", "원/유로": "EUR"}


# ── 공통 유틸 ──────────────────────────────────────────────────────────────

def get_standard_date() -> str:
    kst = timezone("Asia/Seoul")
    return (datetime.now(kst) - timedelta(days=1)).strftime("%Y%m%d")


def load_configs() -> dict:
    return {
        key: json.loads(os.environ[key])
        for key in ("KIS_STOCK", "KIS_ISA", "KIS_PENSION", "KIS_IRP", "UPBIT")
    }


def normalize_numeric(df: pd.DataFrame) -> pd.DataFrame:
    target_cols = [
        "holding_quantity", "purchase_average_cost", "current_price",
        "total_purchase_amount", "market_value",
        "valuation_profit_amount", "valuation_profit_rate",
    ]
    result = df.copy()
    for col in target_cols:
        if col in result.columns:
            result[col] = (
                pd.to_numeric(result[col].astype(str).str.replace(",", ""), errors="coerce")
                .fillna(0)
                .astype(float)
            )
    return result


# ── KIS 변환 함수 ──────────────────────────────────────────────────────────

def transform_overseas_balance(raw: dict, standard_date: str, account_type: str) -> pd.DataFrame:
    df = pd.json_normalize(raw["output1"])
    if df.empty:
        return pd.DataFrame()
    return normalize_numeric(
        df.rename(columns=KIS_RENAME["overseas_balance"])
        .assign(standard_date=standard_date, account_division_name=account_type)
        [BALANCE_COLUMNS]
    )


def transform_domestic_balance(raw: dict, standard_date: str, account_type: str) -> pd.DataFrame:
    df = pd.json_normalize(raw["output1"])
    if df.empty:
        return pd.DataFrame()
    return normalize_numeric(
        df.rename(columns=KIS_RENAME["domestic_balance"])
        .assign(
            standard_date=standard_date,
            currency_code="KRW",
            exchange_code="KRX",
            account_division_name=account_type,
        )
        [BALANCE_COLUMNS]
    )


def transform_exchange_rate(raw_list: list, standard_date: str) -> pd.DataFrame:
    df = pd.concat(
        [pd.json_normalize(r["output1"]) for r in raw_list],
        ignore_index=True,
    )
    df.rename(columns=KIS_RENAME["exchange_rate"], inplace=True)
    df.insert(0, "standard_date", standard_date)

    price_cols = [
        "previous_day_closing_price", "current_price",
        "opening_price", "highest_price", "lowest_price",
    ]
    df[price_cols] = df[price_cols].astype(float)

    # 달러/파운드, 달러/유로 → 원/파운드, 원/유로 (원/달러 기준 환산)
    usd_krw = df.loc[df["currency_pair_name"] == "원/달러", price_cols].values[0]
    cross_mask = df["currency_pair_name"].isin(["달러/파운드", "달러/유로"])

    cross = df[cross_mask].copy()
    cross[price_cols] = cross[price_cols].multiply(usd_krw, axis=1)
    cross["currency_pair_name"] = cross["currency_pair_name"].str.replace("달러/", "원/")

    result = pd.concat([df[~cross_mask], cross], ignore_index=True)
    result["currency_code"] = result["currency_pair_name"].map(CURRENCY_CODE_MAP)

    return result[EXCHANGE_RATE_COLUMNS]


# ── UPBIT 변환 함수 ────────────────────────────────────────────────────────

def transform_upbit_balance(
    balance_raw: list,
    market_code_raw: list,
    price_raw: list,
    standard_date: str,
) -> pd.DataFrame:
    balance_df = pd.json_normalize(balance_raw)
    if balance_df.empty:
        return pd.DataFrame()

    holding = (
        balance_df.query('currency != "KRW"')
        .assign(market=lambda df: "KRW-" + df["currency"])
        .reset_index(drop=True)
    )
    if holding.empty:
        return pd.DataFrame()

    market_df = pd.json_normalize(market_code_raw)
    krw_markets = market_df[market_df["market"].str.startswith("KRW-")]

    price_df = pd.json_normalize(price_raw)

    merged = (
        holding
        .merge(krw_markets[["market", "korean_name"]], on="market", how="left")
        .merge(price_df[["market", "trade_price"]], on="market", how="left")
        .rename(columns=UPBIT_RENAME)
    )

    for col in ["holding_quantity", "purchase_average_cost", "current_price"]:
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)

    result = merged.assign(
        standard_date=standard_date,
        currency_code="KRW",
        exchange_code="UPBIT",
        account_division_name="가상자산",
        total_purchase_amount=lambda df: df["holding_quantity"] * df["purchase_average_cost"],
        market_value=lambda df: df["holding_quantity"] * df["current_price"],
        valuation_profit_amount=lambda df: df["market_value"] - df["total_purchase_amount"],
        valuation_profit_rate=lambda df: df["valuation_profit_amount"] / df["total_purchase_amount"] * 100,
    )[BALANCE_COLUMNS]

    return normalize_numeric(result)


# ── 메인 ──────────────────────────────────────────────────────────────────

def main():
    standard_date = get_standard_date()
    print(f"기준일: {standard_date}")

    # 1. 토큰 생성
    print("\n=== 토큰 생성 ===")
    tm = TokenManager()
    tm.TokenGenerator()
    tokens = tm.GetTokens()

    # 2. 계좌 정보 로드
    configs = load_configs()

    # 3. 환율 조회
    print("\n=== 환율 조회 ===")
    kis_stock_client = KISApiClient(tokens["KIS_STOCK"], configs["KIS_STOCK"])
    exchange_rate_raw = kis_stock_client.get_exchange_rate(standard_date, EXCHANGE_RATE_PRODUCT_CODES)
    exchange_rate_df = transform_exchange_rate(exchange_rate_raw, standard_date)
    print(f"건수: {len(exchange_rate_df)}")
    print(exchange_rate_df.to_string(index=False))

    # 4. 자산 수집
    print("\n=== 자산 수집 ===")
    dfs = []

    collectors = [
        (
            "해외주식",
            lambda: transform_overseas_balance(
                kis_stock_client.get_overseas_balance(),
                standard_date,
                configs["KIS_STOCK"]["type"],
            ),
        ),
        (
            "국내주식",
            lambda: transform_domestic_balance(
                KISApiClient(tokens["KIS_STOCK"], configs["KIS_STOCK"]).get_domestic_balance(),
                standard_date,
                configs["KIS_STOCK"]["type"],
            ),
        ),
        (
            "ISA",
            lambda: transform_domestic_balance(
                KISApiClient(tokens["KIS_ISA"], configs["KIS_ISA"]).get_domestic_balance(),
                standard_date,
                configs["KIS_ISA"]["type"],
            ),
        ),
        (
            "연금저축",
            lambda: transform_domestic_balance(
                KISApiClient(tokens["KIS_PENSION"], configs["KIS_PENSION"]).get_domestic_balance(),
                standard_date,
                configs["KIS_PENSION"]["type"],
            ),
        ),
        (
            "IRP",
            lambda: transform_domestic_balance(
                KISApiClient(tokens["KIS_IRP"], configs["KIS_IRP"]).get_domestic_balance(),
                standard_date,
                configs["KIS_IRP"]["type"],
            ),
        ),
        (
            "가상자산",
            lambda: _fetch_upbit(tokens["UPBIT"], standard_date),
        ),
    ]

    for name, fn in collectors:
        df = fn()
        print(f"  {name}: {len(df)}건")
        if not df.empty:
            dfs.append(df)

    # 5. 최종 DataFrame
    if not dfs:
        print("\n수집된 자산 데이터 없음")
        return exchange_rate_df, pd.DataFrame()

    final_df = pd.concat(dfs, ignore_index=True)
    print(f"\n=== 최종 자산 DataFrame ({len(final_df)}건) ===")
    print(final_df.to_string(index=False))

    return exchange_rate_df, final_df


def _fetch_upbit(token: str, standard_date: str) -> pd.DataFrame:
    client = UpbitApiClient(token)
    balance_raw = client.get_balance()
    market_code_raw = client.get_market_codes()

    holding_markets = [
        f"KRW-{item['currency']}"
        for item in balance_raw
        if item.get("currency") != "KRW"
    ]
    if not holding_markets:
        return pd.DataFrame()

    price_raw = client.get_current_prices(holding_markets)
    return transform_upbit_balance(balance_raw, market_code_raw, price_raw, standard_date)


if __name__ == "__main__":
    main()
