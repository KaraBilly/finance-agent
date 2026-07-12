"""Provider Layer — concrete implementations of Capabilities.

Each provider implements a Capability interface. Providers can be swapped
without changing Agent code.

Organization:
  - providers/cn/ : China A-share market providers
  - providers/us/ : US stock market providers
  - providers/    : Common providers (LLM, WebSearch, Storage)

Current providers:
  LLM:        DoubaoProvider, DeepSeekProvider
  MarketData: EastmoneyMarketProvider     (CN, direct eastmoney JSON API)
                FinnhubMarketProvider     (US, via Finnhub API)
  Financials: EastmoneyFinancialsProvider (CN, direct eastmoney JSON API)
                FinnhubFinancialsProvider (US, via Finnhub API)
  Filings:    CninfoApiFilingsProvider    (CN, direct cninfo JSON API)
                FinnhubFilingsProvider    (US, SEC filings via Finnhub)
  WebSearch:  TavilyWebProvider
  Storage:    SQLiteStorageProvider
"""
from .llm_openai import OpenAICompatibleLLM, DoubaoProvider, DeepSeekProvider
from .cn import (
    EastmoneyMarketProvider,
    EastmoneyFinancialsProvider,
    CninfoApiFilingsProvider,
)
from .us import (
    FinnhubMarketProvider,
    FinnhubFinancialsProvider,
    FinnhubFilingsProvider,
)
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
