"""A-share external filings provider — uses local files only, no API calls.

This provider replaces the cninfo API-based provider for A-share filings.
It reads pre-prepared filings from local files and serves them through
the FilingsCapability interface.

Expected data structure:
  data/filings/
    ├── 000001_2023年报.md
    ├── 000001_2023年报.txt
    ├── 000001_2024半年报.md
    └── ...
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from ...capabilities.base import Evidence
from ...capabilities.filings import FilingsCapability
from ...config import CONFIG

log = logging.getLogger(__name__)


class ExternalAshareFilingsProvider(FilingsCapability):
    """A-share filings provider using local files only."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or CONFIG.external_filings_dir or (CONFIG.data_dir / "filings")

    # ------------------------------------------------------------------ helpers

    def _find_files(self, symbol: str, years_back: int = 2) -> list[Path]:
        """Find filing files for a symbol."""
        if not self.data_dir.exists():
            return []

        files = []
        current_year = 2024  # Could be dynamic

        # Search in data_dir and all subdirectories
        search_dirs = [self.data_dir] + [d for d in self.data_dir.rglob("*") if d.is_dir()]
        
        for search_dir in search_dirs:
            for f in search_dir.glob("*"):
                if f.suffix.lower() not in {".md", ".txt", ".pdf"}:
                    continue

                # Check if filename contains symbol
                if symbol in f.name:
                    files.append(f)

        # Sort by modification time (newest first)
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files

    def _extract_year_from_filename(self, filename: str) -> int | None:
        """Try to extract year from filename."""
        match = re.search(r"20\d{2}", filename)
        if match:
            return int(match.group())
        return None

    def _extract_title_from_filename(self, filename: str) -> str:
        """Extract title from filename."""
        # Remove extension and symbol prefix
        name = Path(filename).stem
        # Remove symbol prefix like "000001_"
        name = re.sub(r"^\d{6}_", "", name)
        return name

    # ------------------------------------------------------------- capabilities

    def list_annual_reports(
        self,
        symbol: str,
        *,
        years_back: int = 2,
    ) -> pd.DataFrame:
        """List annual report filings for a company."""
        files = self._find_files(symbol, years_back)
        
        rows = []
        for f in files:
            year = self._extract_year_from_filename(f.name)
            title = self._extract_title_from_filename(f.name)
            rows.append({
                "year": year,
                "title": title,
                "file": str(f),
            })
        
        return pd.DataFrame(rows)

    def list_announcements(
        self,
        symbol: str,
        *,
        limit: int = 20,
    ) -> pd.DataFrame:
        """List recent company announcements."""
        # For external data, treat all files as announcements
        files = self._find_files(symbol)
        
        rows = []
        for f in files[:limit]:
            year = self._extract_year_from_filename(f.name)
            title = self._extract_title_from_filename(f.name)
            rows.append({
                "year": year,
                "title": title,
                "file": str(f),
            })
        
        return pd.DataFrame(rows)

    def collect_filings(
        self,
        symbol: str,
        *,
        years_back: int = 2,
    ) -> list[Evidence]:
        """Collect filings from local files."""
        files = self._find_files(symbol, years_back)

        if not files:
            log.warning("No filings found for %s in %s", symbol, self.data_dir)
            return []

        evidences = []
        for file_path in files[:years_back * 2]:  # Limit to reasonable number
            try:
                if file_path.suffix.lower() == ".pdf":
                    # Skip PDFs for now (would need PDF parsing)
                    continue

                with open(file_path, "r", encoding="utf-8") as f:
                    text = f.read()
            except Exception:
                try:
                    with open(file_path, "r", encoding="gbk") as f:
                        text = f.read()
                except Exception as e:
                    log.warning("Failed to read %s: %s", file_path, e)
                    continue

            title = self._extract_title_from_filename(file_path.name)
            year = self._extract_year_from_filename(file_path.name)

            # Truncate if too long
            max_length = 5000
            if len(text) > max_length:
                text = text[:max_length] + "\n\n... (内容已截断)"

            ev = Evidence(
                text=text,
                source_kind="filings",
                url=f"file://{file_path}",
                title=f"{symbol} {title} (外挂数据)",
                publisher="external_data",
                meta={
                    "symbol": symbol,
                    "file": str(file_path),
                    "year": year,
                    "title": title,
                },
            )
            evidences.append(ev)

        log.info("Found %d filings for %s", len(evidences), symbol)
        return evidences
