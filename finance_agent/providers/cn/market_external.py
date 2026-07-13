"""A-share external data provider — uses local files only, no API calls.

This provider replaces the Eastmoney API-based provider for A-share market data.
It reads pre-prepared data from local files and serves it through the
MarketDataCapability interface.

Expected data structure:
  data/market/
    ├── 000001_上证指数_daily.csv
    ├── 000001_上证指数_weekly.csv
    └── ...
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from ...capabilities.base import Evidence
from ...capabilities.market_data import MarketDataCapability
from ...config import CONFIG

log = logging.getLogger(__name__)

# A-share index catalog
CN_INDEX_CATALOG: dict[str, str] = {
    "000001": "上证指数",
    "399001": "深证成指",
    "000300": "沪深300",
    "000905": "中证500",
    "399006": "创业板指",
    "000016": "上证50",
    "000852": "中证1000",
}


class ExternalAshareMarketProvider(MarketDataCapability):
    """A-share market data provider using local files only."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or CONFIG.external_market_dir or (CONFIG.data_dir / "market")
        self._cache: dict[str, pd.DataFrame] = {}

    # ------------------------------------------------------------------ helpers

    def _find_file(self, symbol: str, freq: str = "daily") -> Path | None:
        """Find data file for a symbol."""
        if not self.data_dir.exists():
            return None

        # Try exact match first
        patterns = [
            f"{symbol}_*{freq}.csv",
            f"{symbol}_*.csv",
            f"*{symbol}*_{freq}.csv",
            f"*{symbol}*.csv",
        ]

        for pattern in patterns:
            matches = list(self.data_dir.rglob(pattern))
            if matches:
                # Prefer files with the frequency in name
                freq_matches = [m for m in matches if freq in m.name.lower()]
                if freq_matches:
                    return freq_matches[0]
                return matches[0]

        return None

    def _load_data(self, symbol: str, freq: str = "daily") -> pd.DataFrame:
        """Load data from file, with caching."""
        cache_key = f"{symbol}_{freq}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        file_path = self._find_file(symbol, freq)
        if not file_path:
            log.warning("No data file found for symbol: %s", symbol)
            return pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume"])

        try:
            df = pd.read_csv(file_path)
        except Exception:
            try:
                df = pd.read_csv(file_path, encoding="gbk")
            except Exception as e:
                log.warning("Failed to read %s: %s", file_path, e)
                return pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume"])

        # Standardize column names
        df = self._standardize_columns(df)
        self._cache[cache_key] = df
        return df

    def _standardize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize column names to match OHLCV format."""
        if df.empty:
            return df

        # Common column name mappings
        col_map = {
            # Date
            "日期": "date",
            "交易日期": "date",
            "time": "date",
            "trade_date": "date",
            # Open
            "开盘": "open",
            "开盘价": "open",
            "open_price": "open",
            # Close
            "收盘": "close",
            "收盘价": "close",
            "close_price": "close",
            # High
            "最高": "high",
            "最高价": "high",
            "high_price": "high",
            # Low
            "最低": "low",
            "最低价": "low",
            "low_price": "low",
            # Volume
            "成交量": "volume",
            "vol": "volume",
            "volume": "volume",
            # Amount (optional)
            "成交额": "amount",
            "amount": "amount",
            "amt": "amount",
        }

        # Rename columns
        new_cols = {}
        for col in df.columns:
            col_lower = col.strip().lower()
            if col_lower in col_map:
                new_cols[col] = col_map[col_lower]
            elif col in col_map:
                new_cols[col] = col_map[col]

        if new_cols:
            df = df.rename(columns=new_cols)

        # Ensure required columns exist
        required = ["date", "open", "close", "high", "low", "volume"]
        for col in required:
            if col not in df.columns:
                df[col] = 0.0 if col != "date" else ""

        return df

    def _is_ashare_symbol(self, symbol: str) -> bool:
        """Check if symbol is A-share."""
        return bool(re.match(r"^\d{6}$", symbol))

    # ------------------------------------------------------------- capabilities

    def list_available_indices(self) -> dict[str, str]:
        return CN_INDEX_CATALOG.copy()

    def get_index_daily(
        self,
        symbol: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Get daily OHLCV for an A-share index."""
        df = self._load_data(symbol, freq="daily")
        if df.empty:
            return df

        # Filter by date if specified
        if start:
            df = df[df["date"] >= start]
        if end:
            df = df[df["date"] <= end]

        return df.reset_index(drop=True)

    def get_stock_daily(
        self,
        symbol: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Get daily OHLCV for an A-share stock."""
        df = self._load_data(symbol, freq="daily")
        if df.empty:
            return df

        # Filter by date if specified
        if start:
            df = df[df["date"] >= start]
        if end:
            df = df[df["date"] <= end]

        return df.reset_index(drop=True)

    def summarize_index(self, symbol: str, *, lookback_years: int = 20) -> Evidence:
        """Produce a Markdown summary of an A-share index."""
        name = CN_INDEX_CATALOG.get(symbol, symbol)
        df = self._load_data(symbol, freq="daily")

        if df.empty or len(df) < 2:
            # Try weekly data
            df = self._load_data(symbol, freq="weekly")

        if df.empty:
            raise RuntimeError(f"No data found for index {symbol}. Please ensure data file exists in {self.data_dir}")

        # Get recent data
        recent = df.tail(30)
        latest = df.iloc[-1] if len(df) > 0 else None

        if latest is None:
            raise RuntimeError(f"No data available for index {symbol}")

        # Calculate stats
        current_price = float(latest.get("close", 0))
        prev_price = float(df.iloc[-2]["close"]) if len(df) > 1 else current_price
        day_change = current_price - prev_price
        day_change_pct = (day_change / prev_price * 100) if prev_price else 0

        high_52w = float(df["high"].tail(252).max()) if len(df) >= 252 else float(df["high"].max())
        low_52w = float(df["low"].tail(252).min()) if len(df) >= 252 else float(df["low"].min())

        md = (
            f"**{name} ({symbol}) — 概览**\n\n"
            f"| 指标 | 数值 |\n|---|---|\n"
            f"| 当前点位 | {current_price:.2f} |\n"
            f"| 当日涨跌 | {day_change:+.2f} ({day_change_pct:+.2f}%) |\n"
            f"| 52周最高 | {high_52w:.2f} |\n"
            f"| 52周最低 | {low_52w:.2f} |\n"
            f"| 数据点数 | {len(df)} 天 |\n"
        )

        return Evidence(
            text=md,
            source_kind="market",
            url=None,
            title=f"{name} 概览 (外挂数据)",
            publisher="external_data",
            meta={"symbol": symbol, "price": current_price, "data_points": len(df)},
        )

    def summarize_stock(self, symbol: str, *, lookback_days: int = 365) -> Evidence:
        """Produce a Markdown summary of an A-share stock."""
        df = self._load_data(symbol, freq="daily")

        if df.empty or len(df) < 2:
            # Try weekly
            df = self._load_data(symbol, freq="weekly")

        if df.empty:
            raise RuntimeError(f"No data found for stock {symbol}. Please ensure data file exists in {self.data_dir}")

        latest = df.iloc[-1] if len(df) > 0 else None
        if latest is None:
            raise RuntimeError(f"No data available for stock {symbol}")

        current_price = float(latest.get("close", 0))
        prev_price = float(df.iloc[-2]["close"]) if len(df) > 1 else current_price
        day_change = current_price - prev_price
        day_change_pct = (day_change / prev_price * 100) if prev_price else 0

        high_52w = float(df["high"].tail(252).max()) if len(df) >= 252 else float(df["high"].max())
        low_52w = float(df["low"].tail(252).min()) if len(df) >= 252 else float(df["low"].min())

        # Calculate turnover if available
        turnover = float(latest.get("turnover", 0)) if "turnover" in latest else 0

        md = (
            f"**{symbol} — 概览**\n\n"
            f"| 指标 | 数值 |\n|---|---|\n"
            f"| 当前价格 | {current_price:.2f} CNY |\n"
            f"| 当日涨跌 | {day_change:+.2f} ({day_change_pct:+.2f}%) |\n"
            f"| 52周最高 | {high_52w:.2f} CNY |\n"
            f"| 52周最低 | {low_52w:.2f} CNY |\n"
        )

        if turnover:
            md += f"| 换手率 | {turnover:.2f}% |\n"

        md += f"| 数据天数 | {len(df)} 天 |\n"

        return Evidence(
            text=md,
            source_kind="market",
            url=None,
            title=f"{symbol} 概览 (外挂数据)",
            publisher="external_data",
            meta={"symbol": symbol, "price": current_price, "data_points": len(df)},
        )
