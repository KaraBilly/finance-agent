"""External API-based filings provider for A-share companies.

This provider replaces the akshare-based implementation with REST API calls
to external financial data services (Tushare, cninfo API, etc.).
"""
from __future__ import annotations
import logging
import os
from datetime import datetime

import pandas as pd
import requests

from ..capabilities.filings import FilingsCapability
from ..capabilities.base import Evidence

log = logging.getLogger(__name__)


class ExternalFilingsProvider(FilingsCapability):
    """Company filings via external REST APIs."""

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

    def list_annual_reports(
        self,
        symbol: str,
        *,
        years_back: int = 2,
    ) -> pd.DataFrame:
        now = datetime.now()
        start = now.replace(year=now.year - years_back).strftime("%Y%m%d")
        end = now.strftime("%Y%m%d")
        try:
            df = self._call_api("disclosure", {
                "ts_code": symbol,
                "start_date": start,
                "end_date": end,
            })
        except Exception as e:
            log.warning("annual reports for %s failed: %s", symbol, e)
            return pd.DataFrame()
        return df if df is not None else pd.DataFrame()

    def list_announcements(
        self,
        symbol: str,
        *,
        limit: int = 20,
    ) -> pd.DataFrame:
        try:
            df = self._call_api("disclosure", {
                "ts_code": symbol,
                "limit": limit,
            })
        except Exception as e:
            log.warning("announcements for %s failed: %s", symbol, e)
            return pd.DataFrame()
        if df is None or df.empty:
            return pd.DataFrame()
        return df.head(limit)

    def collect_filings(
        self,
        symbol: str,
        *,
        years_back: int = 2,
    ) -> list[Evidence]:
        rows: list[dict] = []

        # Annual reports
        ar_df = self.list_annual_reports(symbol, years_back=years_back)
        for _, r in ar_df.iterrows():
            rows.append(r.to_dict())

        # Announcements
        try:
            ndf = self.list_announcements(symbol)
            for _, r in ndf.iterrows():
                rows.append(r.to_dict())
        except Exception as e:
            log.warning("notices failed: %s", e)

        out: list[Evidence] = []
        for r in rows[:30]:
            title = r.get("title") or r.get("公告标题") or r.get("标题") or r.get("公司简称") or "公司公告"
            date = r.get("ann_date") or r.get("公告日期") or r.get("日期") or r.get("date") or ""
            url = r.get("url") or r.get("公告链接") or r.get("网址") or ""
            text = f"**{title}** ({date})\n\n来源: {url or 'External API'}"
            ev = Evidence(
                text=text,
                source_kind="filings",
                url=url or None,
                title=str(title),
                publisher="External API / 交易所",
                meta={"symbol": symbol, "date": str(date)},
            )
            out.append(ev)
        return out
