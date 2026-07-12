"""Cninfo (巨潮资讯) filings provider — direct JSON API, no scraping.

Uses the same endpoints that the ``cninfo.com.cn`` web front-end calls:

* ``http://www.cninfo.com.cn/new/data/szse_stock.json`` — full A-share
  ``code → orgId`` catalogue, cached to disk on first use.
* ``http://www.cninfo.com.cn/new/hisAnnouncement/query`` — announcement
  search (POST). PDF direct links are exposed via ``adjunctUrl``.

See ``DATA_SOURCES.md`` §2.2.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from ...capabilities.base import Evidence
from ...capabilities.filings import FilingsCapability
from ...config import CONFIG

log = logging.getLogger(__name__)

_STOCK_CATALOGUE_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
_PDF_PREFIX = "http://static.cninfo.com.cn/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "http://www.cninfo.com.cn",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
    "X-Requested-With": "XMLHttpRequest",
}

# category codes accepted by hisAnnouncement/query.
_CATEGORY_ANNUAL = "category_ndbg_szsh"

def _plate_for_symbol(symbol: str) -> str:
    """Map a bare 6-digit code to cninfo's ``column`` parameter."""
    if symbol.startswith(("6", "9")):
        return "sse"
    if symbol.startswith(("4", "8")):
        return "bj"
    return "szse"

class CninfoApiFilingsProvider(FilingsCapability):
    """Filings via the public cninfo hisAnnouncement JSON API."""

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        session: requests.Session | None = None,
        request_gap_sec: float = 0.3,
    ):
        self._cache_dir = cache_dir or CONFIG.cache_dir
        self._catalogue_path = self._cache_dir / "cninfo_stock_catalogue.json"
        self._session = session or requests.Session()
        self._session.headers.update(_HEADERS)
        self._request_gap = request_gap_sec
        self._catalogue: dict[str, str] | None = None  # code → orgId

    # ---------------------------------------------------------------- catalogue
    def _load_catalogue(self) -> dict[str, str]:
        if self._catalogue is not None:
            return self._catalogue

        if self._catalogue_path.exists():
            try:
                data = json.loads(self._catalogue_path.read_text(encoding="utf-8"))
                self._catalogue = {row["code"]: row["orgId"] for row in data if row.get("code")}
                return self._catalogue
            except Exception as e:
                log.warning("cached cninfo catalogue unreadable, refetching: %s", e)

        log.info("fetching cninfo stock catalogue → %s", self._catalogue_path)
        r = self._session.get(_STOCK_CATALOGUE_URL, timeout=20)
        r.raise_for_status()
        rows = r.json() or []
        self._catalogue_path.parent.mkdir(parents=True, exist_ok=True)
        self._catalogue_path.write_text(
            json.dumps(rows, ensure_ascii=False), encoding="utf-8"
        )
        self._catalogue = {row["code"]: row["orgId"] for row in rows if row.get("code")}
        return self._catalogue

    def _org_id(self, symbol: str) -> str | None:
        try:
            return self._load_catalogue().get(symbol)
        except Exception as e:
            log.warning("cninfo catalogue lookup failed for %s: %s", symbol, e)
            return None

    def _throttle(self) -> None:
        if self._request_gap > 0:
            time.sleep(self._request_gap)

    # -------------------------------------------------------------------- query
    def _query(
        self,
        symbol: str,
        *,
        category: str | None,
        page_size: int,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        org_id = self._org_id(symbol) or ""
        # ``stock`` accepts "code,orgId"; if orgId lookup failed, sending just
        # the code still returns results for that specific market.
        stock_ref = f"{symbol},{org_id}" if org_id else symbol
        form: dict[str, Any] = {
            "stock": stock_ref,
            "tabName": "fulltext",
            "pageSize": page_size,
            "pageNum": 1,
            "column": _plate_for_symbol(symbol),
            "plate": "",
            "searchkey": "",
            "secid": "",
            "seDate": f"{start_date}~{end_date}",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        if category:
            form["category"] = category + ";"

        try:
            r = self._session.post(_QUERY_URL, data=form, timeout=20)
            r.raise_for_status()
        except Exception as e:
            log.warning("cninfo query failed for %s: %s", symbol, e)
            return []
        finally:
            self._throttle()

        payload = r.json() or {}
        return payload.get("announcements") or []

    @staticmethod
    def _row_from_announcement(a: dict[str, Any]) -> dict[str, Any]:
        adj = a.get("adjunctUrl") or ""
        pdf = f"{_PDF_PREFIX}{adj}" if adj else ""
        ts = a.get("announcementTime")
        try:
            date_str = (
                datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d")
                if ts is not None else ""
            )
        except Exception:
            date_str = ""
        return {
            "公告标题": a.get("announcementTitle") or "",
            "公告日期": date_str,
            "公司代码": a.get("secCode") or "",
            "公司简称": a.get("secName") or "",
            "公告类型": a.get("adjunctType") or "",
            "公告链接": pdf,
        }

    # -------------------------------------------------------------- capabilities
    def list_annual_reports(
        self,
        symbol: str,
        *,
        years_back: int = 2,
    ) -> pd.DataFrame:
        now = datetime.now()
        start = (now - timedelta(days=365 * years_back + 60)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        anns = self._query(
            symbol,
            category=_CATEGORY_ANNUAL,
            page_size=30,
            start_date=start,
            end_date=end,
        )
        rows = [self._row_from_announcement(a) for a in anns]
        return pd.DataFrame(rows)

    def list_announcements(
        self,
        symbol: str,
        *,
        limit: int = 20,
    ) -> pd.DataFrame:
        now = datetime.now()
        # 90 days of recent filings — matches how cninfo defaults its picker.
        start = (now - timedelta(days=90)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        anns = self._query(
            symbol,
            category=None,
            page_size=max(limit, 30),
            start_date=start,
            end_date=end,
        )
        rows = [self._row_from_announcement(a) for a in anns[:limit]]
        return pd.DataFrame(rows)

    def collect_filings(
        self,
        symbol: str,
        *,
        years_back: int = 2,
    ) -> list[Evidence]:
        rows: list[dict[str, Any]] = []

        ar_df = self.list_annual_reports(symbol, years_back=years_back)
        if not ar_df.empty:
            rows.extend(ar_df.to_dict("records"))

        try:
            n_df = self.list_announcements(symbol)
            if not n_df.empty:
                rows.extend(n_df.to_dict("records"))
        except Exception as e:
            log.warning("cninfo announcements failed for %s: %s", symbol, e)

        out: list[Evidence] = []
        seen_urls: set[str] = set()
        for r in rows[:30]:
            url = r.get("公告链接") or ""
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            title = r.get("公告标题") or r.get("公司简称") or "公司公告"
            date = r.get("公告日期") or ""
            text = f"**{title}** ({date})\n\n来源: {url or 'cninfo'}"
            out.append(
                Evidence(
                    text=text,
                    source_kind="filings",
                    url=url or None,
                    title=str(title),
                    publisher="巨潮资讯网 (cninfo)",
                    meta={
                        "symbol": symbol,
                        "date": str(date),
                        "kind": r.get("公告类型") or "",
                    },
                )
            )
        return out
