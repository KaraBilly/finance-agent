"""Eastmoney (东方财富) market data provider — no token required.

Replaces the akshare-based provider. Talks directly to the public JSON
endpoints that power the eastmoney.com front-end
(``push2his.eastmoney.com``), which is the same upstream that akshare
wraps but without the intermediate layer.

Endpoint reference: see ``DATA_SOURCES.md`` §2.1.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

from ...capabilities.base import Evidence
from ...capabilities.market_data import MarketDataCapability
from ...config import CONFIG

log = logging.getLogger(__name__)

# Symbol → human-readable name for the indices we bootstrap by default.
INDEX_CATALOG: dict[str, str] = {
    "000001": "上证指数",
    "399001": "深证成指",
    "000300": "沪深300",
    "000905": "中证500",
    "399006": "创业板指",
    "000016": "上证50",
    "000852": "中证1000",
}

# Eastmoney secid prefix rules:
#   1.xxxxxx  — 上交所 (600/601/603/605/688/689 stock; 000/000016/000300/000852/000905 index)
#   0.xxxxxx  — 深交所 (000/001/002/003/300/301 stock; 399xxx index) 和 北交所 (43/83/87/88/92)
_SH_STOCK_PREFIXES = ("6", "9")
_SH_INDEX_PREFIXES = ("000",)  # Shanghai indices: 000001/000016/000300/000852/000905
_SZ_INDEX_PREFIXES = ("399",)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}

_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_KLINE_COLUMNS = [
    "date", "open", "close", "high", "low", "volume", "amount",
    "amplitude", "pct_change", "change", "turnover",
]
_NUMERIC_COLS = ["open", "close", "high", "low", "volume", "amount",
                 "amplitude", "pct_change", "change", "turnover"]

def _secid_for_stock(symbol: str) -> str:
    """Return ``prefix.symbol`` for a stock code."""
    prefix = "1" if symbol.startswith(_SH_STOCK_PREFIXES) else "0"
    return f"{prefix}.{symbol}"

def _secid_for_index(symbol: str) -> str:
    """Return ``prefix.symbol`` for an index code."""
    if symbol.startswith(_SH_INDEX_PREFIXES):
        prefix = "1"
    elif symbol.startswith(_SZ_INDEX_PREFIXES):
        prefix = "0"
    else:
        # Fallback: treat 6xxxxx as Shanghai, rest as Shenzhen.
        prefix = "1" if symbol.startswith(_SH_STOCK_PREFIXES) else "0"
    return f"{prefix}.{symbol}"

def _fetch_kline(
    secid: str,
    *,
    start: str,
    end: str,
    fq: int,
    session: requests.Session | None = None,
    timeout: float = 15.0,
) -> pd.DataFrame:
    """Call the eastmoney kline endpoint and return a normalized DataFrame."""
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",   # 101=daily, 102=weekly, 103=monthly
        "fqt": str(fq), # 0=raw, 1=前复权, 2=后复权
        "beg": start,
        "end": end,
    }
    client = session or requests
    r = client.get(_KLINE_URL, params=params, headers=_HEADERS, timeout=timeout)
    r.raise_for_status()
    data = r.json() or {}
    payload = data.get("data") or {}
    klines: Iterable[str] = payload.get("klines") or []
    if not klines:
        return pd.DataFrame(columns=_KLINE_COLUMNS)

    rows = [ln.split(",") for ln in klines]
    df = pd.DataFrame(rows, columns=_KLINE_COLUMNS)
    for c in _NUMERIC_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    return df

class EastmoneyMarketProvider(MarketDataCapability):
    """MarketData via public eastmoney JSON APIs (token-free)."""

    def __init__(
        self,
        indices_dir: Path | None = None,
        *,
        session: requests.Session | None = None,
        request_gap_sec: float = 0.3,
    ):
        self.indices_dir = indices_dir or CONFIG.indices_dir
        self._session = session or requests.Session()
        self._session.headers.update(_HEADERS)
        self._request_gap = request_gap_sec

    # ------------------------------------------------------------------ helpers
    def _index_parquet(self, symbol: str) -> Path:
        return self.indices_dir / f"{symbol}.parquet"

    def _throttle(self) -> None:
        if self._request_gap > 0:
            time.sleep(self._request_gap)

    # ------------------------------------------------------------- capabilities
    def list_available_indices(self) -> dict[str, str]:
        return INDEX_CATALOG.copy()

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
        log.info("index %s fetching from eastmoney %s..%s", symbol, start, end)
        df = _fetch_kline(
            _secid_for_index(symbol),
            start=start, end=end, fq=0,
            session=self._session,
        )
        self._throttle()
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
        start = start or (datetime.now() - pd.Timedelta(days=400)).strftime("%Y%m%d")
        end = end or datetime.now().strftime("%Y%m%d")
        log.info("stock %s fetching from eastmoney %s..%s", symbol, start, end)
        df = _fetch_kline(
            _secid_for_stock(symbol),
            start=start, end=end, fq=1,   # front-adjusted (前复权)
            session=self._session,
        )
        self._throttle()
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
            url=(
                f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
                f"?secid={_secid_for_index(symbol)}&klt=101&fqt=0"
            ),
            title=f"{name} 日线 (eastmoney)",
            publisher="东方财富",
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
            url=(
                f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
                f"?secid={_secid_for_stock(symbol)}&klt=101&fqt=1"
            ),
            title=f"{symbol} 日线 (eastmoney)",
            publisher="东方财富",
            meta={"symbol": symbol, "lookback_days": lookback_days},
        )
