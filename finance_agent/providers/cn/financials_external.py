"""A-share external financials provider — uses local files only, no API calls.

This provider replaces the Eastmoney API-based provider for A-share financial data.
It reads pre-prepared financial reports from local files and serves them through
the FinancialsCapability interface.

Expected data structure:
  data/financials/
    ├── 000001_income.csv
    ├── 000001_balance.csv
    ├── 000001_cashflow.csv
    └── ...
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ...capabilities.base import Evidence
from ...capabilities.financials import FinancialsCapability, StatementType
from ...config import CONFIG

log = logging.getLogger(__name__)

_STATEMENT_ZH: dict[StatementType, str] = {
    "income": "利润表",
    "balance": "资产负债表",
    "cashflow": "现金流量表",
}

# Common column mappings for Chinese financial statements
_COL_MAP = {
    "income": {
        "报告期": "REPORT_DATE",
        "营业总收入": "TOTAL_OPERATE_INCOME",
        "营业收入": "TOTAL_OPERATE_INCOME",
        "营业利润": "OPERATE_PROFIT",
        "利润总额": "TOTAL_PROFIT",
        "净利润": "NETPROFIT",
        "归属于母公司股东的净利润": "PARENT_NETPROFIT",
        "基本每股收益": "BPS",
        "稀释每股收益": "DILUTED_EPS",
    },
    "balance": {
        "报告期": "REPORT_DATE",
        "资产总计": "TOTAL_ASSETS",
        "负债合计": "TOTAL_LIABILITIES",
        "股东权益合计": "TOTAL_EQUITY",
        "归属于母公司股东权益": "PARENT_EQUITY",
        "货币资金": "MONEY_FUNDS",
        "应收账款": "ACCOUNTS_RECEIVABLE",
        "存货": "INVENTORY",
    },
    "cashflow": {
        "报告期": "REPORT_DATE",
        "经营活动产生的现金流量净额": "NET_CASH_FLOWS_OPERATE",
        "投资活动产生的现金流量净额": "NET_CASH_FLOWS_INVEST",
        "筹资活动产生的现金流量净额": "NET_CASH_FLOWS_FINANCE",
        "现金及现金等价物净增加额": "NET_INCREASE_CASH",
    },
}


class ExternalAshareFinancialsProvider(FinancialsCapability):
    """A-share financials provider using local files only."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or CONFIG.external_financials_dir or (CONFIG.data_dir / "financials")
        self._cache: dict[str, pd.DataFrame] = {}

    # ------------------------------------------------------------------ helpers

    def _find_file(self, symbol: str, statement_type: StatementType) -> Path | None:
        """Find financial data file for a symbol and statement type."""
        if not self.data_dir.exists():
            return None

        # Map statement type to common file name patterns
        type_patterns = {
            "income": ["income", "利润表", "pl", "profit"],
            "balance": ["balance", "资产负债表", "bs", "balancesheet"],
            "cashflow": ["cashflow", "现金流量表", "cf", "cash"],
        }

        patterns = type_patterns.get(statement_type, [statement_type])

        for pattern in patterns:
            # Try exact match
            file_path = self.data_dir / f"{symbol}_{pattern}.csv"
            if file_path.exists():
                return file_path

            # Try in subdirectories
            for subdir in self.data_dir.rglob("*"):
                if subdir.is_dir():
                    file_path = subdir / f"{symbol}_{pattern}.csv"
                    if file_path.exists():
                        return file_path

            # Try with Chinese name
            for f in self.data_dir.rglob(f"{symbol}_*"):
                if pattern.lower() in f.stem.lower():
                    return f
            
            # Try in subdirectories with Chinese name
            for subdir in self.data_dir.rglob("*"):
                if subdir.is_dir():
                    for f in subdir.rglob(f"{symbol}_*"):
                        if pattern.lower() in f.stem.lower():
                            return f

        return None

    def _load_data(self, symbol: str, statement_type: StatementType) -> pd.DataFrame:
        """Load financial data from file, with caching."""
        cache_key = f"{symbol}_{statement_type}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        file_path = self._find_file(symbol, statement_type)
        if not file_path:
            log.warning("No financial data file found for %s/%s", symbol, statement_type)
            return pd.DataFrame()

        try:
            df = pd.read_csv(file_path)
        except Exception:
            try:
                df = pd.read_csv(file_path, encoding="gbk")
            except Exception as e:
                log.warning("Failed to read %s: %s", file_path, e)
                return pd.DataFrame()

        # Standardize columns
        df = self._standardize_columns(df, statement_type)
        self._cache[cache_key] = df
        return df

    def _standardize_columns(self, df: pd.DataFrame, statement_type: StatementType) -> pd.DataFrame:
        """Standardize column names."""
        if df.empty:
            return df

        col_map = _COL_MAP.get(statement_type, {})
        if col_map:
            # Try to map columns
            new_cols = {}
            for col in df.columns:
                col_clean = col.strip()
                if col_clean in col_map:
                    new_cols[col] = col_map[col_clean]

            if new_cols:
                df = df.rename(columns=new_cols)

        return df

    # ------------------------------------------------------------- capabilities

    def get_statement(
        self,
        symbol: str,
        statement_type: StatementType,
        *,
        periods: int = 3,
    ) -> pd.DataFrame:
        """Get a financial statement from local files."""
        df = self._load_data(symbol, statement_type)
        if df.empty:
            return df

        # Sort by report date if available
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
        """Produce a Markdown summary of a financial statement."""
        df = self.get_statement(symbol, statement_type, periods=periods)
        if df is None or df.empty:
            raise RuntimeError(f"No {statement_type} data for {symbol}. Please ensure data file exists in {self.data_dir}")

        zh_name = _STATEMENT_ZH[statement_type]

        # Create markdown table
        md = f"**{symbol} {zh_name} — 最近 {len(df)} 期 (外挂数据)**\n\n"
        md += df.to_markdown(index=False)

        return Evidence(
            text=md,
            source_kind="financials",
            url=None,
            title=f"{symbol} {zh_name} (外挂数据)",
            publisher="external_data",
            meta={"symbol": symbol, "kind": statement_type, "periods": int(len(df))},
        )

    def collect_all(
        self,
        symbol: str,
        *,
        statement_types: list[StatementType] | None = None,
        periods: int = 3,
    ) -> list[Evidence]:
        """Collect summaries for multiple statement types."""
        types = statement_types or ["income", "balance", "cashflow"]
        out: list[Evidence] = []
        for t in types:
            try:
                ev = self.summarize_statement(symbol, t, periods=periods)
                out.append(ev)
            except Exception as e:
                log.warning("Financial %s/%s failed: %s", symbol, t, e)
        return out
