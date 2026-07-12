"""Akshare/Sina-based financials provider for A-share companies."""
from __future__ import annotations
import logging

import pandas as pd

from ..capabilities.financials import FinancialsCapability, StatementType
from ..capabilities.base import Evidence

log = logging.getLogger(__name__)

_SINA_NAME = {
    "income": "利润表",
    "balance": "资产负债表",
    "cashflow": "现金流量表",
}


def _prefix_symbol(code: str) -> str:
    code = code.strip()
    if code.startswith(("sh", "sz")):
        return code
    if code.startswith(("6", "9")):
        return "sh" + code
    return "sz" + code


class AkshareFinancialsProvider(FinancialsCapability):
    """Financial statements via akshare (Sina source)."""

    def get_statement(
        self,
        symbol: str,
        statement_type: StatementType,
        *,
        periods: int = 3,
    ) -> pd.DataFrame:
        import akshare as ak

        sym = _prefix_symbol(symbol)
        name = _SINA_NAME[statement_type]
        df = ak.stock_financial_report_sina(stock=sym, symbol=name)
        return df

    def summarize_statement(
        self,
        symbol: str,
        statement_type: StatementType,
        *,
        periods: int = 3,
    ) -> Evidence:
        df = self.get_statement(symbol, statement_type)
        if df is None or df.empty:
            raise RuntimeError(f"no {statement_type} data for {symbol}")

        date_col = next((c for c in df.columns if "日期" in c or c.lower() == "date"), df.columns[0])
        df = df.sort_values(date_col, ascending=False).head(periods)
        md = f"**{symbol} {_SINA_NAME[statement_type]} — 最近 {len(df)} 期**\n\n"
        md += df.to_markdown(index=False)

        return Evidence(
            text=md,
            source_kind="financials",
            url=f"akshare://stock_financial_report_sina?stock={_prefix_symbol(symbol)}&symbol={_SINA_NAME[statement_type]}",
            title=f"{symbol} {_SINA_NAME[statement_type]}",
            publisher="新浪财经 / akshare",
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
