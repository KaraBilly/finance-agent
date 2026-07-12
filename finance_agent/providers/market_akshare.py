"""Akshare-based market data provider for A-share indices and stocks."""
from __future__ import annotations
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..capabilities.market_data import MarketDataCapability
from ..capabilities.base import Evidence
from ..config import CONFIG

log = logging.getLogger(__name__)

INDEX_CATALOG: dict[str, str] = {
    "000001": "上证指数",
    "399001": "深证成指",
    "000300": "沪深300",
    "000905": "中证500",
    "399006": "创业板指",
    "000016": "上证50",
    "000852": "中证1000",
}


class AkshareMarketProvider(MarketDataCapability):
    """Market data via akshare with local parquet cache for indices."""

    def __init__(self, indices_dir: Path | None = None):
        self.indices_dir = indices_dir or CONFIG.indices_dir

    def _index_parquet(self, symbol: str) -> Path:
        return self.indices_dir / f"{symbol}.parquet"

    def list_available_indices(self) -> dict[str, str]:
        return INDEX_CATALOG.copy()

    def get_index_daily(
        self,
        symbol: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        import akshare as ak

        cache = self._index_parquet(symbol)
        if cache.exists():
            df = pd.read_parquet(cache)
            log.info("index %s loaded from cache: %d rows", symbol, len(df))
            return df

        start = start or "20050101"
        end = end or datetime.now().strftime("%Y%m%d")
        log.info("index %s fetching from akshare %s..%s", symbol, start, end)
        df = ak.index_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end)
        rename = {
            "日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
            "最低": "low", "成交量": "volume", "成交额": "amount", "涨跌幅": "pct_change",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        df["date"] = pd.to_datetime(df["date"])
        cache.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache, index=False)
        return df

    def get_stock_daily(
        self,
        symbol: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        import akshare as ak

        start = start or (datetime.now() - pd.Timedelta(days=400)).strftime("%Y%m%d")
        end = end or datetime.now().strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                start_date=start, end_date=end, adjust="qfq")
        rename = {
            "日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
            "最低": "low", "成交量": "volume", "成交额": "amount", "涨跌幅": "pct_change",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def summarize_index(self, symbol: str, *, lookback_years: int = 20) -> Evidence:
        name = INDEX_CATALOG.get(symbol, symbol)
        df = self.get_index_daily(symbol)
        if df.empty:
            raise RuntimeError(f"empty index data for {symbol}")

        end_date = df["date"].max()
        start_date = end_date - pd.DateOffset(years=lookback_years)
        d = df[df["date"] >= start_date].sort_values("date")
        first, last = d.iloc[0], d.iloc[-1]
        hi = d.loc[d["high"].idxmax()] if "high" in d.columns else d.loc[d["close"].idxmax()]
        lo = d.loc[d["low"].idxmin()] if "low" in d.columns else d.loc[d["close"].idxmin()]
        total_ret = (last["close"] / first["close"] - 1) * 100
        ann_ret = ((last["close"] / first["close"]) ** (1 / max(1, lookback_years)) - 1) * 100
        avg_vol = d["volume"].mean() if "volume" in d.columns else float("nan")

        md = (
            f"**{name} ({symbol}) — 近 {lookback_years} 年概览**\n\n"
            f"| 指标 | 数值 |\n|---|---|\n"
            f"| 起始日 | {first['date'].date()} |\n"
            f"| 起始收盘 | {first['close']:.2f} |\n"
            f"| 最新日 | {last['date'].date()} |\n"
            f"| 最新收盘 | {last['close']:.2f} |\n"
            f"| 累计涨跌 | {total_ret:+.2f}% |\n"
            f"| 年化(近似) | {ann_ret:+.2f}% |\n"
            f"| 最高点 | {hi['close']:.2f} ({hi['date'].date()}) |\n"
            f"| 最低点 | {lo['close']:.2f} ({lo['date'].date()}) |\n"
            f"| 日均成交量 | {avg_vol:,.0f} |\n"
        )
        return Evidence(
            text=md,
            source_kind="market",
            url=f"akshare://index_zh_a_hist?symbol={symbol}",
            title=f"{name} 日线 (akshare)",
            publisher="akshare / 交易所",
            meta={"symbol": symbol, "rows": int(len(d)),
                  "start": str(first["date"].date()), "end": str(last["date"].date())},
        )

    def summarize_stock(self, symbol: str, *, lookback_days: int = 365) -> Evidence:
        start = (datetime.now() - pd.Timedelta(days=lookback_days + 30)).strftime("%Y%m%d")
        df = self.get_stock_daily(symbol, start=start)
        if df.empty:
            raise RuntimeError(f"no data for stock {symbol}")
        d = df.sort_values("date").tail(lookback_days)
        first, last = d.iloc[0], d.iloc[-1]
        ret = (last["close"] / first["close"] - 1) * 100
        md = (
            f"**{symbol} 近 {lookback_days} 交易日行情**\n\n"
            f"| 指标 | 数值 |\n|---|---|\n"
            f"| 期间 | {first['date'].date()} → {last['date'].date()} |\n"
            f"| 起始收盘 | {first['close']:.2f} |\n"
            f"| 最新收盘 | {last['close']:.2f} |\n"
            f"| 区间涨跌 | {ret:+.2f}% |\n"
            f"| 区间最高 | {d['high'].max():.2f} |\n"
            f"| 区间最低 | {d['low'].min():.2f} |\n"
            f"| 日均成交量 | {d['volume'].mean():,.0f} |\n"
        )
        return Evidence(
            text=md,
            source_kind="market",
            url=f"akshare://stock_zh_a_hist?symbol={symbol}",
            title=f"{symbol} 日线 (akshare)",
            publisher="akshare / 交易所",
            meta={"symbol": symbol, "lookback_days": lookback_days},
        )
