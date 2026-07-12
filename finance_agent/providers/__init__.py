"""Provider Layer — concrete implementations of Capabilities.

Each provider implements a Capability interface. Providers can be swapped
without changing Agent code.

Current providers:
  LLM:        DoubaoProvider, DeepSeekProvider
  MarketData: EastmoneyMarketProvider     (direct eastmoney JSON API, token-free)
                FinnhubMarketProvider     (US stocks via Finnhub API)
  Financials: EastmoneyFinancialsProvider (direct eastmoney JSON API, token-free)
                FinnhubFinancialsProvider (US financials via Finnhub API)
  Filings:    CninfoApiFilingsProvider    (direct cninfo JSON API, token-free)
                FinnhubFilingsProvider    (US SEC filings via Finnhub API)
  WebSearch:  TavilyWebProvider
  Storage:    SQLiteStorageProvider
"""
from .llm_openai import OpenAICompatibleLLM, DoubaoProvider, DeepSeekProvider
from .market_eastmoney import EastmoneyMarketProvider
from .market_finnhub import FinnhubMarketProvider
from .financials_eastmoney import EastmoneyFinancialsProvider
from .financials_finnhub import FinnhubFinancialsProvider
from .filings_cninfo_api import CninfoApiFilingsProvider
from .filings_finnhub import FinnhubFilingsProvider
from .web_tavily import TavilyWebProvider
from .storage_sqlite import SQLiteStorageProvider

__all__ = [
    # LLM Providers
    "OpenAICompatibleLLM",
    "DoubaoProvider",
    "DeepSeekProvider",
    # Data Providers - CN
    "EastmoneyMarketProvider",
    "EastmoneyFinancialsProvider",
    "CninfoApiFilingsProvider",
    # Data Providers - US
    "FinnhubMarketProvider",
    "FinnhubFinancialsProvider",
    "FinnhubFilingsProvider",
    # Common
    "TavilyWebProvider",
    "SQLiteStorageProvider",
]
