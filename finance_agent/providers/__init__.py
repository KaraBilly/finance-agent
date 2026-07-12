"""Provider Layer — concrete implementations of Capabilities.

Each provider implements a Capability interface. Providers can be swapped
without changing Agent code.

Current providers:
  LLM:        DoubaoProvider, DeepSeekProvider
  MarketData: EastmoneyMarketProvider     (direct eastmoney JSON API, token-free)
  Financials: EastmoneyFinancialsProvider (direct eastmoney JSON API, token-free)
  Filings:    CninfoApiFilingsProvider    (direct cninfo JSON API, token-free)
  WebSearch:  TavilyWebProvider
  Storage:    SQLiteStorageProvider
"""
from .llm_openai import OpenAICompatibleLLM, DoubaoProvider, DeepSeekProvider
from .market_eastmoney import EastmoneyMarketProvider
from .financials_eastmoney import EastmoneyFinancialsProvider
from .filings_cninfo_api import CninfoApiFilingsProvider
from .web_tavily import TavilyWebProvider
from .storage_sqlite import SQLiteStorageProvider

__all__ = [
    # LLM Providers
    "OpenAICompatibleLLM",
    "DoubaoProvider",
    "DeepSeekProvider",
    # Data Providers
    "EastmoneyMarketProvider",
    "EastmoneyFinancialsProvider",
    "CninfoApiFilingsProvider",
    "TavilyWebProvider",
    "SQLiteStorageProvider",
]
