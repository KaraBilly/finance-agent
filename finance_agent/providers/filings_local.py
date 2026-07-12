"""Local file-based filings provider for A-share companies.

Reads from local parquet/CSV files instead of external APIs.
Expected file structure:
  data/filings/
    600000_annual.parquet  # 年报
    600000_announcement.parquet  # 公告
"""
from __future__ import annotations
import logging
from pathlib import Path

import pandas as pd

from ..capabilities.filings import FilingsCapability
from ..capabilities.base import Evidence
from ..config import CONFIG

log = logging.getLogger(__name__)


class LocalFilingsProvider(FilingsCapability):
    """Company filings from local parquet/CSV files."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or (CONFIG.data_dir / "filings")
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _get_annual_path(self, symbol: str) -> Path:
        return self.data_dir / f"{symbol}_annual.parquet"

    def _get_announcement_path(self, symbol: str) -> Path:
        return self.data_dir / f"{symbol}_announcement.parquet"

    def list_annual_reports(
        self,
        symbol: str,
        *,
        years_back: int = 2,
    ) -> pd.DataFrame:
        path = self._get_annual_path(symbol)
        if not path.exists():
            log.warning("Annual reports not found for %s", symbol)
            return pd.DataFrame()
        
        df = pd.read_parquet(path)
        log.info("annual reports %s loaded from local file: %d rows", symbol, len(df))
        return df

    def list_announcements(
        self,
        symbol: str,
        *,
        limit: int = 20,
    ) -> pd.DataFrame:
        path = self._get_announcement_path(symbol)
        if not path.exists():
            log.warning("Announcements not found for %s", symbol)
            return pd.DataFrame()
        
        df = pd.read_parquet(path)
        log.info("announcements %s loaded from local file: %d rows", symbol, len(df))
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
            text = f"**{title}** ({date})\n\n来源: {url or 'Local Data Files'}"
            ev = Evidence(
                text=text,
                source_kind="filings",
                url=url or None,
                title=str(title),
                publisher="Local Data Files",
                meta={"symbol": symbol, "date": str(date)},
            )
            out.append(ev)
        return out
