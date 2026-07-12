"""External API-based market data provider for A-share indices and stocks.

This provider replaces the akshare-based implementation with REST API calls
to external financial data services (Tushare, Alpha Vantage, etc.).
"""
from __future__ import annotations
import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

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


class ExternalMarketProvider(MarketDataCapability):
    """Market data via external REST APIs with local parquet cache."""

    def __init__(self, indices_dir: Path | None = None, api_key: str | None = None):
        self.indices_dir = indices_dir or CONFIG.indices_dir
        self.api_key = api_key or os.getenv("TUSHARE_API_KEY", "")
        self.base_url = "https://api.tushare.pro"  # Default to Tushare

    def _index_parquet(self, symbol: str) -> Path:
        return self.indices_dir / f"{symbol}.parquet"

    def list_available_indices(self) -> dict[str, str]:
        return INDEX_CATALOG.copy()

    def _fetch_from_api(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """Fetch index data from external API."""
        if not self.api_key:
            raise RuntimeError("No API key configured. Set TUSHARE_API_KEY env var.")
        
        # Tushare API call for index daily data
        api_name = "index_daily"
        params = {
            "ts_code": symbol,
            "start_date": start,
            "end_date": end,
        }
        
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
        
        # Standardize column names
        rename = {
            "trade_date": "date",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "vol": "volume",
            "amount": "amount",
            "pct_change": "pct_change",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        df["date"] = pd.to_datetime(df["date"])
        return df

    def get_index_daily(
        self,
        symbol: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        cache = self._index_parquet(symbol)
        if cache.exists():
            df = pd.read_parquet(cache)
            log.info("index %s loaded from cache: %d rows", symbol, len(df))
            return df

        start = start or "20050101"
        end = end or datetime.now().strftime("%Y%m%d")
        log.info("index %s fetching from API %s..%s", symbol, start, end)
        
        df = self._fetch_from_api(symbol, start, end)
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
        if not self.api_key:
            raise RuntimeError("No API key configured. Set TUSHARE_API_KEY env var.")
        
        start = start or (datetime.now() - pd.Timedelta(days=400)).strftime("%Y%m%d")
        end = end or datetime.now().strftime("%Y%m%d")
        
        # Tushare API for stock daily data
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "daily",
                "token": self.api_key,
                "params": {
                    "ts_code": symbol,
                    "start_date": start,
                    "end_date": end,
                },
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        
        if data.get("code") != 0:
            raise RuntimeError(f"API error: {data.get('msg', 'Unknown error')}")
        
        df = pd.DataFrame(data.get("data", {}).get("items", []),
                         columns=data.get("data", {}).get("fields", []))
        
        rename = {
            "trade_date": "date",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "vol": "volume",
            "amount": "amount",
            "pct_chg": "pct_change",
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
            url=f"api://index_daily?symbol={symbol}",
            title=f"{name} 日线 (External API)",
            publisher="Tushare / External API",
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
            url=f"api://daily?symbol={symbol}",
            title=f"{symbol} 日线 (External API)",
            publisher="Tushare / External API",
            meta={"symbol": symbol, "lookback_days": lookback_days},
        )
