"""External API-based financials provider for A-share companies.

This provider replaces the akshare-based implementation with REST API calls
to external financial data services (Tushare, etc.).
"""
from __future__ import annotations
import logging
import os

import pandas as pd
import requests

from ..capabilities.financials import FinancialsCapability, StatementType
from ..capabilities.base import Evidence

log = logging.getLogger(__name__)

_STATEMENT_API_MAP = {
    "income": "income",
    "balance": "balancesheet",
    "cashflow": "cashflow",
}

_STATEMENT_NAME = {
    "income": "利润表",
    "balance": "资产负债表",
    "cashflow": "现金流量表",
}


class ExternalFinancialsProvider(FinancialsCapability):
    """Financial statements via external REST APIs."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("TUSHARE_API_KEY", "")
        self.base_url = "https://api.tushare.pro"

    def _call_api(self, api_name: str, params: dict) -> pd.DataFrame:
        """Call Tushare-like API and return DataFrame."""
        if not self.api_key:
            raise RuntimeError("No API key configured. Set TUSHARE_API_KEY env var.")
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": api_name,
                "token": self.api_key,
                "params": params,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        
        if data.get("code") != 0:
            raise RuntimeError(f"API error: {data.get('msg', 'Unknown error')}")
        
        df = pd.DataFrame(data.get("data", {}).get("items", []),
                         columns=data.get("data", {}).get("fields", []))
        return df

    def get_statement(
        self,
        symbol: str,
        statement_type: StatementType,
        *,
        periods: int = 3,
    ) -> pd.DataFrame:
        api_name = _STATEMENT_API_MAP[statement_type]
        df = self._call_api(api_name, {"ts_code": symbol, "limit": periods})
        return df

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

        name = _STATEMENT_NAME[statement_type]
        date_col = next((c for c in df.columns if "日期" in c or c.lower() == "date" or "end_date" in c), df.columns[0])
        df = df.sort_values(date_col, ascending=False).head(periods)
        md = f"**{symbol} {name} — 最近 {len(df)} 期**\n\n"
        md += df.to_markdown(index=False)

        return Evidence(
            text=md,
            source_kind="financials",
            url=f"api://{_STATEMENT_API_MAP[statement_type]}?ts_code={symbol}",
            title=f"{symbol} {name}",
            publisher="Tushare / External API",
            meta={"symbol": symbol, "kind": statement_type, "periods": int(len(df))},
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
