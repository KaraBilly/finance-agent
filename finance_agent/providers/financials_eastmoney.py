"""Eastmoney (东方财富) financials provider — no token required.

Talks to ``datacenter-web.eastmoney.com/api/data/v1/get`` — the JSON
endpoint that powers the eastmoney F10 finance pages. Returns three
statements (income / balance / cashflow) using standardised report
names. See ``DATA_SOURCES.md`` §2.1.2.
"""
from __future__ import annotations

import logging
import time

import pandas as pd
import requests

from ..capabilities.base import Evidence
from ..capabilities.financials import FinancialsCapability, StatementType

log = logging.getLogger(__name__)

_ENDPOINT = "https://datacenter-web.eastmoney.com/api/data/v1/get"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}

# Report names used by the eastmoney datacenter for A-share financials.
# These are the same identifiers the F10 pages request in DevTools.
_REPORT: dict[StatementType, str] = {
    "income":   "RPT_LICO_FN_CPD",         # 利润表
    "balance":  "RPT_DMSK_FN_BALANCE",     # 资产负债表
    "cashflow": "RPT_DMSK_FN_CASHFLOW",    # 现金流量表
}

_STATEMENT_ZH: dict[StatementType, str] = {
    "income":   "利润表",
    "balance":  "资产负债表",
    "cashflow": "现金流量表",
}

# A short curated column projection so that the markdown summary stays
# readable. If a column is missing we skip it — the raw DataFrame is
# always available via ``get_statement``.
_DISPLAY_COLS: dict[StatementType, list[str]] = {
    "income": [
        "REPORT_DATE", "TOTAL_OPERATE_INCOME", "OPERATE_PROFIT",
        "TOTAL_PROFIT", "PARENT_NETPROFIT", "BASIC_EPS",
    ],
    "balance": [
        "REPORT_DATE", "TOTAL_ASSETS", "TOTAL_LIABILITIES",
        "TOTAL_EQUITY", "MONETARYFUNDS", "ACCOUNTS_RECE",
    ],
    "cashflow": [
        "REPORT_DATE",
        "NETCASH_OPERATE", "NETCASH_INVEST", "NETCASH_FINANCE",
        "CCE_ADD",
    ],
}

class EastmoneyFinancialsProvider(FinancialsCapability):
    """Financial statements via public eastmoney JSON APIs (token-free)."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        request_gap_sec: float = 0.3,
    ):
        self._session = session or requests.Session()
        self._session.headers.update(_HEADERS)
        self._request_gap = request_gap_sec

    def _throttle(self) -> None:
        if self._request_gap > 0:
            time.sleep(self._request_gap)

    def _query(
        self,
        report_name: str,
        symbol: str,
        *,
        page_size: int,
    ) -> pd.DataFrame:
        params = {
            "reportName": report_name,
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{symbol}")',
            "pageNumber": 1,
            "pageSize": page_size,
            "sortColumns": "REPORT_DATE",
            "sortTypes": -1,
        }
        r = self._session.get(_ENDPOINT, params=params, timeout=15)
        r.raise_for_status()
        payload = r.json() or {}
        result = payload.get("result") or {}
        rows = result.get("data") or []
        self._throttle()
        return pd.DataFrame(rows)

    def get_statement(
        self,
        symbol: str,
        statement_type: StatementType,
        *,
        periods: int = 3,
    ) -> pd.DataFrame:
        report = _REPORT[statement_type]
        try:
            df = self._query(report, symbol, page_size=max(periods, 8))
        except Exception as e:
            log.warning("eastmoney %s/%s failed: %s", symbol, statement_type, e)
            return pd.DataFrame()
        if df.empty:
            return df
        if "REPORT_DATE" in df.columns:
            df = df.sort_values("REPORT_DATE", ascending=False)
        return df.head(periods).reset_index(drop=True)

    def summarize_statement(
        self,
        symbol: str,
        statement_type: StatementType,
        *,
        periods: int = 3,
    ) -> Evidence:
        df = self.get_statement(symbol, statement_type, periods=periods)
        if df is None or df.empty:
            raise RuntimeError(f"no {statement_type} data for {symbol}")

        # Project to a stable subset of columns for readability.
        cols = [c for c in _DISPLAY_COLS[statement_type] if c in df.columns]
        view = df[cols] if cols else df

        md = (
            f"**{symbol} {_STATEMENT_ZH[statement_type]} — 最近 {len(view)} 期 (eastmoney)**\n\n"
            + view.to_markdown(index=False)
        )
        return Evidence(
            text=md,
            source_kind="financials",
            url=(
                f"https://datacenter-web.eastmoney.com/api/data/v1/get"
                f"?reportName={_REPORT[statement_type]}"
                f"&filter=(SECURITY_CODE=%22{symbol}%22)"
            ),
            title=f"{symbol} {_STATEMENT_ZH[statement_type]}",
            publisher="东方财富 datacenter",
            meta={"symbol": symbol, "kind": statement_type, "periods": int(len(view))},
        )

    def collect_all(
        self,
        symbol: str,
        *,
        statement_types: list[StatementType] | None = None,
        periods: int = 3,
    ) -> list[Evidence]:
        types = statement_types or ["income", "balance", "cashflow"]
        out: list[Evidence] = []
        for t in types:
            try:
                ev = self.summarize_statement(symbol, t, periods=periods)
                out.append(ev)
            except Exception as e:
                log.warning("financial %s/%s failed: %s", symbol, t, e)
        return out
