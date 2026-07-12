"""Financials Capability — abstract interface for financial statements."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

import pandas as pd

if TYPE_CHECKING:
    from .base import Evidence

StatementType = Literal["income", "balance", "cashflow"]


class FinancialsCapability(ABC):
    """Abstract interface for company financial statements."""

    @abstractmethod
    def get_statement(
        self,
        symbol: str,
        statement_type: StatementType,
        *,
        periods: int = 3,
    ) -> pd.DataFrame:
        """Get a financial statement (income/balance/cashflow)."""
        ...

    @abstractmethod
    def summarize_statement(
        self,
        symbol: str,
        statement_type: StatementType,
        *,
        periods: int = 3,
    ) -> "Evidence":
        """Produce a Markdown summary of a financial statement."""
        ...

    @abstractmethod
    def collect_all(
        self,
        symbol: str,
        *,
        statement_types: list[StatementType] | None = None,
        periods: int = 3,
    ) -> list["Evidence"]:
        """Collect summaries for multiple statement types."""
        ...
