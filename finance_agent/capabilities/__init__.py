"""Capability Layer — abstract interfaces that Agent depends on.

Agent code only imports from this layer, never from providers directly.
This enables swapping providers (e.g., akshare → tushare, Tavily → DuckDuckGo)
without touching agent logic.
"""
from .llm import LLMCapability, ChatMessage
from .market_data import MarketDataCapability
from .financials import FinancialsCapability
from .filings import FilingsCapability
from .web_search import WebSearchCapability
from .storage import StorageCapability

__all__ = [
    "LLMCapability",
    "ChatMessage",
    "MarketDataCapability",
    "FinancialsCapability",
    "FilingsCapability",
    "WebSearchCapability",
    "StorageCapability",
]
