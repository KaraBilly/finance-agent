"""Local file-based financials provider for A-share companies.

Reads from local parquet/CSV files instead of external APIs.
Expected file structure:
  data/financials/
    600000.parquet  # 利润表
    600000_balance.parquet  # 资产负债表
    600000_cashflow.parquet  # 现金流量表
"""
from __future__ import annotations
import logging
from pathlib import Path

import pandas as pd

from ..capabilities.financials import FinancialsCapability, StatementType
from ..capabilities.base import Evidence
from ..config import CONFIG

log = logging.getLogger(__name__)

_STATEMENT_NAME = {
    "income": "利润表",
    "balance": "资产负债表",
    "cashflow": "现金流量表",
}

_STATEMENT_SUFFIX = {
    "income": "",
    "balance": "_balance",
    "cashflow": "_cashflow",
}


class LocalFinancialsProvider(FinancialsCapability):
    """Financial statements from local parquet/CSV files."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or (CONFIG.data_dir / "financials")
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _get_parquet_path(self, symbol: str, statement_type: StatementType) -> Path:
        suffix = _STATEMENT_SUFFIX[statement_type]
        return self.data_dir / f"{symbol}{suffix}.parquet"

    def get_statement(
        self,
        symbol: str,
        statement_type: StatementType,
        *,
        periods: int = 3,
    ) -> pd.DataFrame:
        path = self._get_parquet_path(symbol, statement_type)
        if not path.exists():
            raise FileNotFoundError(
                f"Financial data not found for {symbol} ({statement_type}). "
                f"Please run the data download script first."
            )
        
        df = pd.read_parquet(path)
        log.info("financial %s/%s loaded from local file: %d rows", symbol, statement_type, len(df))
        
        # Sort by date and take most recent periods
        date_col = next((c for c in df.columns if "日期" in c or c.lower() == "date" or "end_date" in c), df.columns[0])
        df = df.sort_values(date_col, ascending=False).head(periods)
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
            url=f"local://financials?symbol={symbol}&type={statement_type}",
            title=f"{symbol} {name}",
            publisher="Local Data Files",
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
