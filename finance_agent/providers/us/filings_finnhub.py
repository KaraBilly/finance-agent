"""Finnhub filings provider — US SEC filings.

Uses Finnhub API for US company SEC filings.
Free tier: 60 calls/minute.

Uses /stock/filings endpoint (FREE).
Returns:
- SEC filings (10-K, 10-Q, 8-K, etc.)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests

from ...capabilities.base import Evidence
from ...capabilities.filings import FilingsCapability
from ...config import CONFIG

log = logging.getLogger(__name__)

_FINNHUB_BASE = "https://finnhub.io/api/v1"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
}

# Filing type mapping
_FILING_TYPES: dict[str, str] = {
    "10-K": "年度报告",
    "10-Q": "季度报告",
    "8-K": "重大事件报告",
    "DEF 14A": "代理声明",
    "S-1": "IPO注册声明",
    "424B": "招股说明书",
    "4": "内部人交易报告",
    "13F-HR": "机构持仓报告",
    "SD": "冲突矿产报告",
    "6-K": "外国公司报告",
}


class FinnhubFilingsProvider(FilingsCapability):
    """US SEC filings via Finnhub API (Free Tier)."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        request_gap_sec: float = 1.0,
        token: str | None = None,
    ):
        self._session = session or requests.Session()
        self._session.headers.update(_HEADERS)
        self._request_gap = request_gap_sec
        self._token = token or CONFIG.finnhub_api_key
        if not self._token:
            raise RuntimeError("Finnhub API key is required. Set FINNHUB_API_KEY in .env")

    def _throttle(self) -> None:
        if self._request_gap > 0:
            time.sleep(self._request_gap)

    def _fetch_filings(
        self,
        symbol: str,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch SEC filings from Finnhub (FREE endpoint)."""
        url = f"{_FINNHUB_BASE}/stock/filings"
        
        # Default date range: last 2 years
        if not from_date:
            from_date = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
        if not to_date:
            to_date = datetime.now().strftime("%Y-%m-%d")
        
        params = {
            "symbol": symbol,
            "from": from_date,
            "to": to_date,
            "token": self._token,
        }
        
        try:
            r = self._session.get(url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            log.warning("Finnhub filings failed for %s: %s", symbol, e)
            return []

    def list_annual_reports(
        self,
        symbol: str,
        *,
        years_back: int = 2,
    ) -> pd.DataFrame:
        """List annual report (10-K) filings."""
        from_date = (datetime.now() - timedelta(days=365 * years_back)).strftime("%Y-%m-%d")
        filings = self._fetch_filings(symbol, from_date=from_date)
        self._throttle()
        
        # Filter for 10-K filings
        annual_filings = [f for f in filings if f.get("form") == "10-K"]
        
        rows = []
        for f in annual_filings:
            filing_type = f.get("form", "")
            filing_name = _FILING_TYPES.get(filing_type, filing_type)
            rows.append({
                "公告标题": f"{symbol} {filing_name}",
                "公告日期": f.get("filedDate", ""),
                "公司代码": symbol,
                "公司简称": symbol,
                "公告类型": filing_type,
                "公告链接": f.get("filingUrl", ""),
            })
        
        return pd.DataFrame(rows)

    def list_announcements(
        self,
        symbol: str,
        *,
        limit: int = 20,
    ) -> pd.DataFrame:
        """List recent SEC filings (all types)."""
        from_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        filings = self._fetch_filings(symbol, from_date=from_date)
        self._throttle()
        
        rows = []
        for f in filings[:limit]:
            filing_type = f.get("form", "")
            filing_name = _FILING_TYPES.get(filing_type, filing_type)
            rows.append({
                "公告标题": f"{symbol} {filing_name}",
                "公告日期": f.get("filedDate", ""),
                "公司代码": symbol,
                "公司简称": symbol,
                "公告类型": filing_type,
                "公告链接": f.get("filingUrl", ""),
            })
        
        return pd.DataFrame(rows)

    def collect_filings(
        self,
        symbol: str,
        *,
        years_back: int = 2,
    ) -> list[Evidence]:
        """Collect filing evidences for a US company."""
        out: list[Evidence] = []
        
        # Get annual reports
        try:
            ar_df = self.list_annual_reports(symbol, years_back=years_back)
            if not ar_df.empty:
                for _, row in ar_df.iterrows():
                    out.append(Evidence(
                        text=f"**{row['公告标题']}** ({row['公告日期']})\n\n来源: {row['公告链接']}",
                        source_kind="filings",
                        url=row["公告链接"],
                        title=row["公告标题"],
                        publisher="SEC (via Finnhub)",
                        meta={
                            "symbol": symbol,
                            "date": row["公告日期"],
                            "kind": row["公告类型"],
                        },
                    ))
        except Exception as e:
            log.warning("Failed to collect annual reports for %s: %s", symbol, e)
        
        # Get recent announcements
        try:
            n_df = self.list_announcements(symbol)
            if not n_df.empty:
                for _, row in n_df.iterrows():
                    out.append(Evidence(
                        text=f"**{row['公告标题']}** ({row['公告日期']})\n\n来源: {row['公告链接']}",
                        source_kind="filings",
                        url=row["公告链接"],
                        title=row["公告标题"],
                        publisher="SEC (via Finnhub)",
                        meta={
                            "symbol": symbol,
                            "date": row["公告日期"],
                            "kind": row["公告类型"],
                        },
                    ))
        except Exception as e:
            log.warning("Failed to collect announcements for %s: %s", symbol, e)
        
        return out
