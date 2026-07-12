"""Cninfo-based filings provider for A-share companies via akshare."""
from __future__ import annotations
import logging
from datetime import datetime

import pandas as pd

from ..capabilities.filings import FilingsCapability
from ..capabilities.base import Evidence

log = logging.getLogger(__name__)


class CninfoFilingsProvider(FilingsCapability):
    """Company filings via akshare's cninfo bridge."""

    def list_annual_reports(
        self,
        symbol: str,
        *,
        years_back: int = 2,
    ) -> pd.DataFrame:
        import akshare as ak

        # `stock_annual_report_cninfo` was removed from akshare; the replacement
        # is `stock_zh_a_disclosure_report_cninfo` which queries the cninfo
        # disclosure endpoint by symbol/category/date range in one call.
        now = datetime.now()
        start = now.replace(year=now.year - years_back).strftime("%Y%m%d")
        end = now.strftime("%Y%m%d")
        try:
            df = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=symbol,
                market="沪深京",
                category="年报",
                start_date=start,
                end_date=end,
            )
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
        import akshare as ak

        try:
            df = ak.stock_notice_report(symbol="全部", date=datetime.now().strftime("%Y%m%d"))
        except Exception as e:
            log.warning("stock_notice_report failed: %s", e)
            return pd.DataFrame()
        if df is None or df.empty:
            return pd.DataFrame()
        code_col = next((c for c in df.columns if "代码" in c), None)
        if code_col:
            df = df[df[code_col].astype(str) == symbol]
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
            title = r.get("公告标题") or r.get("标题") or r.get("title") or r.get("公司简称") or "公司公告"
            date = r.get("公告日期") or r.get("日期") or r.get("date") or ""
            url = r.get("公告链接") or r.get("url") or r.get("网址") or ""
            text = f"**{title}** ({date})\n\n来源: {url or 'cninfo'}"
            ev = Evidence(
                text=text,
                source_kind="filings",
                url=url or None,
                title=str(title),
                publisher="巨潮资讯网 (cninfo)",
                meta={"symbol": symbol, "date": str(date)},
            )
            out.append(ev)
        return out
