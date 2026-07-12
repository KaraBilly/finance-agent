"""Market Data Capability — abstract interface for stock/index data."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from .base import Evidence


class MarketDataCapability(ABC):
    """Abstract interface for market data (indices, stocks)."""

    @abstractmethod
    def get_index_daily(
        self,
        symbol: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Get daily OHLCV for an index. Returns DataFrame with date,open,close,high,low,volume."""
        ...

    @abstractmethod
    def get_stock_daily(
        self,
        symbol: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Get daily OHLCV for a stock."""
        ...

    @abstractmethod
    def summarize_index(self, symbol: str, *, lookback_years: int = 20) -> "Evidence":
        """Produce a Markdown summary of an index."""
        ...

    @abstractmethod
    def summarize_stock(self, symbol: str, *, lookback_days: int = 365) -> "Evidence":
        """Produce a Markdown summary of a stock's recent performance."""
        ...

    @abstractmethod
    def list_available_indices(self) -> dict[str, str]:
        """Return {symbol: name} of available indices."""
        ...
