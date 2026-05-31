import os
import json
import pandas as pd
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

from src.managers.token_manager import TokenManager
from src.managers.db_manager import create_db_engine, get_fund_price
from src.clients.kis_client import KISApiClient
from src.clients.upbit_client import UpbitApiClient
from src.config.kis import KIS
from src.transformers import (
    transform_domestic_balance,
    transform_overseas_balance,
    transform_exchange_rate,
    transform_upbit_balance,
    transform_pension_fund_balance,
    transform_cma_cash_balance,
)

load_dotenv()

_KST = timezone(timedelta(hours=9))
PENSION_FUND_CODE = "K553W5E17401"


def get_standard_date() -> str:
    return (datetime.now(_KST) - timedelta(days=1)).strftime("%Y-%m-%d")


def load_configs() -> dict:
    return {
        key: json.loads(os.environ[key])
        for key in ("KIS_STOCK", "KIS_ISA", "KIS_PENSION", "KIS_IRP", "KIS_CMA", "UPBIT", "DB_INFO")
    }


def _fetch_upbit(token: str, config: dict, standard_date: str) -> pd.DataFrame:
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
    return transform_upbit_balance(
        balance_raw,
        market_code_raw,
        price_raw,
        standard_date,
        account_code=config.get("account", "UPBIT"),
        account_name=config.get("type", "가상자산"),
    )


def _print(label: str, df: pd.DataFrame):
    print(f"\n=== {label} ===")
    if df.empty:
        print("데이터 없음")
    else:
        print(f"{len(df)}건\n{df.to_string(index=False)}")


def main():
    standard_date = get_standard_date()
    print(f"기준일: {standard_date}")

    print("\n=== 토큰 생성 ===")
    tm = TokenManager()
    tm.TokenGenerator()
    tokens = tm.GetTokens()

    configs = load_configs()
    engine = create_db_engine(configs["DB_INFO"])

    # 환율
    kis_stock_client = KISApiClient(tokens["KIS_STOCK"], configs["KIS_STOCK"])
    exchange_rate_raw = kis_stock_client.get_exchange_rate(standard_date, KIS.EXCHANGE_RATE_PRODUCT_CODES)
    exchange_rate_df = transform_exchange_rate(exchange_rate_raw, standard_date)
    _print("환율", exchange_rate_df)

    # 잔고
    domestic_df = transform_domestic_balance(
        KISApiClient(tokens["KIS_STOCK"], configs["KIS_STOCK"]).get_domestic_balance(),
        standard_date, configs["KIS_STOCK"],
    )
    _print("종합매매 (국내주식)", domestic_df)

    overseas_df = transform_overseas_balance(
        kis_stock_client.get_overseas_balance(),
        standard_date, configs["KIS_STOCK"],
    )
    _print("종합매매 (해외주식)", overseas_df)

    isa_df = transform_domestic_balance(
        KISApiClient(tokens["KIS_ISA"], configs["KIS_ISA"]).get_domestic_balance(),
        standard_date, configs["KIS_ISA"],
    )
    _print("개인형 ISA", isa_df)

    fund_price, fund_name = get_fund_price(engine, PENSION_FUND_CODE, standard_date)
    pension_df = pd.concat(
        [
            transform_pension_fund_balance(
                KISApiClient(tokens["KIS_PENSION"], configs["KIS_PENSION"]).get_account_balance(),
                standard_date=standard_date,
                config=configs["KIS_PENSION"],
                product_code=PENSION_FUND_CODE,
                fund_price=fund_price,
                product_name=fund_name,
            ),
            transform_domestic_balance(
                KISApiClient(tokens["KIS_PENSION"], configs["KIS_PENSION"]).get_domestic_balance(),
                standard_date, configs["KIS_PENSION"],
            ),
        ],
        ignore_index=True,
    )
    _print("연금저축", pension_df)

    irp_df = transform_domestic_balance(
        KISApiClient(tokens["KIS_IRP"], configs["KIS_IRP"]).get_domestic_balance(),
        standard_date, configs["KIS_IRP"],
    )
    _print("IRP", irp_df)

    cma_df = transform_cma_cash_balance(
        KISApiClient(tokens["KIS_ISA"], configs["KIS_CMA"]).get_account_balance(),
        standard_date, configs["KIS_CMA"],
    )
    _print("CMA 현금", cma_df)

    upbit_df = _fetch_upbit(tokens["UPBIT"], configs["UPBIT"], standard_date)
    _print("업비트", upbit_df)

    # 전체 합산
    all_dfs = [df for df in [domestic_df, overseas_df, isa_df, pension_df, irp_df, cma_df, upbit_df] if not df.empty]
    balance_df = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    _print(f"전체 잔고", balance_df)


if __name__ == "__main__":
    main()
