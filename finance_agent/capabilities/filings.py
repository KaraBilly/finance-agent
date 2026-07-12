"""Filings Capability — abstract interface for company filings/announcements."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from .base import Evidence


class FilingsCapability(ABC):
    """Abstract interface for company filings (annual reports, announcements)."""

    @abstractmethod
    def list_annual_reports(
        self,
        symbol: str,
        *,
        years_back: int = 2,
    ) -> pd.DataFrame:
        """List annual report filings for a company."""
        ...

    @abstractmethod
    def list_announcements(
        self,
        symbol: str,
        *,
        limit: int = 20,
    ) -> pd.DataFrame:
        """List recent company announcements."""
        ...

    @abstractmethod
    def collect_filings(
        self,
        symbol: str,
        *,
        years_back: int = 2,
    ) -> list["Evidence"]:
        """Collect filing evidences for a company."""
        ...
