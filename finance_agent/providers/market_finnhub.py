"""Finnhub market data provider — US stocks and indices.

Uses Finnhub API (https://finnhub.io) for US market data.
Free tier: 60 calls/minute.

Supports:
- US stocks (AAPL, MSFT, etc.)
- US indices (QQQ, SPY, DIA, etc.)

Note: Historical candle data (stock/candle) is a paid feature.
This provider uses quote + metric endpoints for free tier.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from ..capabilities.base import Evidence
from ..capabilities.market_data import MarketDataCapability
from ..config import CONFIG

log = logging.getLogger(__name__)

# US Index catalog
US_INDEX_CATALOG: dict[str, str] = {
    "QQQ": "纳斯达克100指数ETF",
    "SPY": "标普500指数ETF",
    "DIA": "道琼斯工业指数ETF",
    "IWM": "罗素2000指数ETF",
    "VTI": "全美股票市场ETF",
}

_FINNHUB_BASE = "https://finnhub.io/api/v1"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
}


def _fetch_quote(symbol: str, token: str, session: requests.Session | None = None) -> dict:
    """Fetch real-time quote from Finnhub (FREE)."""
    url = f"{_FINNHUB_BASE}/quote"
    params = {
        "symbol": symbol,
        "token": token,
    }
    client = session or requests
    r = client.get(url, params=params, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def _fetch_metric(symbol: str, token: str, session: requests.Session | None = None) -> dict:
    """Fetch metric data from Finnhub (FREE)."""
    url = f"{_FINNHUB_BASE}/stock/metric"
    params = {
        "symbol": symbol,
        "metric": "all",
        "token": token,
    }
    client = session or requests
    r = client.get(url, params=params, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def _fetch_profile(symbol: str, token: str, session: requests.Session | None = None) -> dict:
    """Fetch company profile from Finnhub (FREE)."""
    url = f"{_FINNHUB_BASE}/stock/profile2"
    params = {
        "symbol": symbol,
        "token": token,
    }
    client = session or requests
    r = client.get(url, params=params, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


class FinnhubMarketProvider(MarketDataCapability):
    """US Market Data via Finnhub API (Free Tier)."""

    def __init__(
        self,
        indices_dir: Path | None = None,
        *,
        session: requests.Session | None = None,
        request_gap_sec: float = 1.0,  # Finnhub free tier: 60 calls/min
        token: str | None = None,
    ):
        self.indices_dir = indices_dir or CONFIG.indices_dir
        self._session = session or requests.Session()
        self._session.headers.update(_HEADERS)
        self._request_gap = request_gap_sec
        self._token = token or CONFIG.finnhub_api_key
        if not self._token:
            raise RuntimeError("Finnhub API key is required. Set FINNHUB_API_KEY in .env")

    # ------------------------------------------------------------------ helpers
    def _throttle(self) -> None:
        if self._request_gap > 0:
            time.sleep(self._request_gap)

    # ------------------------------------------------------------- capabilities
    def list_available_indices(self) -> dict[str, str]:
        return US_INDEX_CATALOG.copy()

    def get_index_daily(
        self,
        symbol: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Get daily OHLCV for a US index (via its ETF).
        
        Note: Historical candle data is a paid feature in Finnhub.
        For free tier, we return a DataFrame with current quote data only.
        """
        log.warning("Historical candle data is a paid feature. Returning current quote only.")
        
        try:
            quote = _fetch_quote(symbol, self._token, self._session)
            self._throttle()
            
            # Create a single-row DataFrame with current data
            now = datetime.now()
            df = pd.DataFrame({
                "date": [now],
                "open": [quote.get("o", 0)],
                "high": [quote.get("h", 0)],
                "low": [quote.get("l", 0)],
                "close": [quote.get("c", 0)],
                "volume": [0],  # Volume not available in free quote
            })
            return df
        except Exception as e:
            log.warning("Failed to fetch quote for %s: %s", symbol, e)
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    def get_stock_daily(
        self,
        symbol: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Get daily OHLCV for a US stock.
        
        Note: Historical candle data is a paid feature in Finnhub.
        For free tier, we return a DataFrame with current quote data only.
        """
        log.warning("Historical candle data is a paid feature. Returning current quote only.")
        
        try:
            quote = _fetch_quote(symbol, self._token, self._session)
            self._throttle()
            
            # Create a single-row DataFrame with current data
            now = datetime.now()
            df = pd.DataFrame({
                "date": [now],
                "open": [quote.get("o", 0)],
                "high": [quote.get("h", 0)],
                "low": [quote.get("l", 0)],
                "close": [quote.get("c", 0)],
                "volume": [0],  # Volume not available in free quote
            })
            return df
        except Exception as e:
            log.warning("Failed to fetch quote for %s: %s", symbol, e)
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    def summarize_index(self, symbol: str, *, lookback_years: int = 20) -> Evidence:
        """Produce a Markdown summary of a US index (in Chinese)."""
        name = US_INDEX_CATALOG.get(symbol, symbol)
        
        try:
            # Fetch current quote
            quote = _fetch_quote(symbol, self._token, self._session)
            self._throttle()
            
            # Fetch metric data for 52-week high/low
            metric_data = _fetch_metric(symbol, self._token, self._session)
            self._throttle()
            
            metrics = metric_data.get("metric", {})
            
            current_price = quote.get("c", 0)
            day_change = quote.get("d", 0)
            day_change_pct = quote.get("dp", 0)
            week_high = metrics.get("52WeekHigh", 0)
            week_low = metrics.get("52WeekLow", 0)
            
            md = (
                f"**{name} ({symbol}) — 概览**\n\n"
                f"| 指标 | 数值 |\n|---|---|\n"
                f"| 当前价格 | {current_price:.2f} USD |\n"
                f"| 当日涨跌 | {day_change:+.2f} ({day_change_pct:+.2f}%) |\n"
                f"| 52周最高 | {week_high:.2f} USD |\n"
                f"| 52周最低 | {week_low:.2f} USD |\n"
            )
            
            return Evidence(
                text=md,
                source_kind="market",
                url=f"https://finnhub.io/api/v1/quote?symbol={symbol}",
                title=f"{name} 概览 (Finnhub)",
                publisher="Finnhub",
                meta={"symbol": symbol, "price": current_price},
            )
        except Exception as e:
            log.warning("Failed to summarize index %s: %s", symbol, e)
            raise RuntimeError(f"Failed to summarize index {symbol}: {e}")

    def summarize_stock(self, symbol: str, *, lookback_days: int = 365) -> Evidence:
        """Produce a Markdown summary of a US stock's recent performance (in Chinese)."""
        try:
            # Fetch current quote
            quote = _fetch_quote(symbol, self._token, self._session)
            self._throttle()
            
            # Fetch metric data
            metric_data = _fetch_metric(symbol, self._token, self._session)
            self._throttle()
            
            # Fetch company profile
            profile = _fetch_profile(symbol, self._token, self._session)
            self._throttle()
            
            metrics = metric_data.get("metric", {})
            
            current_price = quote.get("c", 0)
            day_change = quote.get("d", 0)
            day_change_pct = quote.get("dp", 0)
            week_high = metrics.get("52WeekHigh", 0)
            week_low = metrics.get("52WeekLow", 0)
            market_cap = metrics.get("marketCapitalization", 0)
            pe = metrics.get("peBasicExclExtraTTM", 0)
            
            company_name = profile.get("name", symbol)
            
            md = (
                f"**{company_name} ({symbol}) — 概览**\n\n"
                f"| 指标 | 数值 |\n|---|---|\n"
                f"| 当前价格 | {current_price:.2f} USD |\n"
                f"| 当日涨跌 | {day_change:+.2f} ({day_change_pct:+.2f}%) |\n"
                f"| 52周最高 | {week_high:.2f} USD |\n"
                f"| 52周最低 | {week_low:.2f} USD |\n"
                f"| 市值 | {market_cap:,.0f}M USD |\n"
                f"| P/E (TTM) | {pe:.2f} |\n"
            )
            
            return Evidence(
                text=md,
                source_kind="market",
                url=f"https://finnhub.io/api/v1/quote?symbol={symbol}",
                title=f"{symbol} 概览 (Finnhub)",
                publisher="Finnhub",
                meta={"symbol": symbol, "price": current_price, "market_cap": market_cap},
            )
        except Exception as e:
            log.warning("Failed to summarize stock %s: %s", symbol, e)
            raise RuntimeError(f"Failed to summarize stock {symbol}: {e}")
