"""Provider Layer — concrete implementations of Capabilities.

Each provider implements a Capability interface. Providers can be swapped
without changing Agent code.

Current providers:
  LLM:        DoubaoProvider, DeepSeekProvider
  MarketData: LocalMarketProvider
  Financials: LocalFinancialsProvider
  Filings:    LocalFilingsProvider
  WebSearch:  TavilyWebProvider
  Storage:    SQLiteStorageProvider
"""
from .llm_openai import OpenAICompatibleLLM, DoubaoProvider, DeepSeekProvider
from .market_local import LocalMarketProvider
from .financials_local import LocalFinancialsProvider
from .filings_local import LocalFilingsProvider
from .web_tavily import TavilyWebProvider
from .storage_sqlite import SQLiteStorageProvider

__all__ = [
    # LLM Providers
    "OpenAICompatibleLLM",
    "DoubaoProvider",
    "DeepSeekProvider",
    # Data Providers
    "LocalMarketProvider",
    "LocalFinancialsProvider",
    "LocalFilingsProvider",
    "TavilyWebProvider",
    "SQLiteStorageProvider",
]
