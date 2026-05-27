"""
fundguide.net 펀드 기준가 크롤러
- 로컬/Airflow 공통 실행 가능 (Playwright 사용)
- 입력: 표준코드 리스트 -> 출력: [{fund_cd, fund_nm, nav, change, crawled_at}, ...]

사용 예 (로컬):
    uv run playwright install chromium  # 최초 1회
    uv run python fund_crawler.py

Airflow 주의사항은 파일 하단 docstring 참고.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

BASE_URL = "https://www.fundguide.net/Fund/SimpleSearch?search_key={code}"
NAV_SELECTOR = 'td.taC[data-tab="tab0"]'
# "검색결과" 탭/링크 — 클릭해야 결과 그리드가 렌더됨
RESULT_TAB = 'a:has-text("검색결과"), button:has-text("검색결과")'


@dataclass
class FundQuote:
    fund_cd: str
    fund_nm: str | None
    nav: float | None
    change: float | None
    crawled_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_number(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", text)
    return float(m.group(0).replace(",", "")) if m else None


def fetch_fund_quote(page, code: str, timeout_ms: int = 30_000) -> FundQuote:
    # networkidle 까지 대기해 초기 AJAX(SearchCnd/GetFundCnt 등) 완료 보장
    page.goto(BASE_URL.format(code=code), wait_until="networkidle", timeout=timeout_ms)

    # "검색결과" 탭 클릭 → 그리드 렌더 트리거. 없거나 이미 활성화면 무시.
    tab = page.locator(RESULT_TAB).first
    try:
        if tab.count() and tab.is_visible():
            tab.click()
    except Exception:
        pass

    # 결과 그리드가 렌더될 때까지 대기 (탭 클릭 후 GetFundList 응답 반영 시간)
    page.wait_for_selector(NAV_SELECTOR, timeout=timeout_ms, state="visible")

    row = page.locator(NAV_SELECTOR).first
    # 기준가 텍스트 = 자식 텍스트노드의 첫 토큰
    nav_text = row.evaluate("el => el.childNodes[0]?.textContent || ''").strip()
    change_text = (
        row.locator("span.tcr").inner_text() if row.locator("span.tcr").count() else ""
    )

    fund_nm = None
    chk = page.locator(f'input[data-fund-cd="{code}"]').first
    if chk.count():
        fund_nm = chk.get_attribute("data-fund-nm")

    return FundQuote(
        fund_cd=code,
        fund_nm=fund_nm,
        nav=_parse_number(nav_text),
        change=_parse_number(change_text),
        crawled_at=datetime.now(timezone.utc).isoformat(),
    )


def crawl_fund(code: str, headless: bool = True) -> dict:
    """단일 펀드 코드의 기준가를 크롤링."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            locale="ko-KR",
        )
        page = context.new_page()
        try:
            quote = fetch_fund_quote(page, code)
            logger.info("OK %s nav=%s", code, quote.nav)
            return quote.to_dict()
        except PWTimeout:
            logger.warning("TIMEOUT %s", code)
            return FundQuote(
                code, None, None, None, datetime.now(timezone.utc).isoformat()
            ).to_dict()
        finally:
            browser.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    CODES = ["K553W5E17401", "K55105D43299"]
    out = [crawl_fund(code) for code in CODES]
    print(json.dumps(out, ensure_ascii=False, indent=2))
