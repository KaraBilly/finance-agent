"""Provider Layer — concrete implementations of Capabilities.

Each provider implements a Capability interface. Providers can be swapped
without changing Agent code.

Current providers:
  LLM:        DoubaoProvider, DeepSeekProvider
  MarketData: AkshareMarketProvider
  Financials: AkshareFinancialsProvider
  Filings:    CninfoFilingsProvider
  WebSearch:  TavilyWebProvider
  Storage:    SQLiteStorageProvider
"""
from .llm_openai import OpenAICompatibleLLM, DoubaoProvider, DeepSeekProvider
from .market_akshare import AkshareMarketProvider
from .financials_akshare import AkshareFinancialsProvider
from .filings_cninfo import CninfoFilingsProvider
from .web_tavily import TavilyWebProvider
from .storage_sqlite import SQLiteStorageProvider

__all__ = [
    # LLM Providers
    "OpenAICompatibleLLM",
    "DoubaoProvider",
    "DeepSeekProvider",
    # Data Providers
    "AkshareMarketProvider",
    "AkshareFinancialsProvider",
    "CninfoFilingsProvider",
    "TavilyWebProvider",
    "SQLiteStorageProvider",
]
