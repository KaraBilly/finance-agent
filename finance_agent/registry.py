"""Provider Registry — wires Capabilities to concrete Providers.

This is the ONLY place where Provider implementations are instantiated.
Agent code imports Capabilities, not Providers.

To swap a provider (e.g., eastmoney → an internal proprietary feed):
  1. Create new provider implementing the Capability interface
  2. Change the registration here
  3. Agent code remains unchanged

Supported LLM backends:
  - "doubao"   : Volcengine Ark (doubao-seed-evolving)
  - "deepseek" : DeepSeek API

Supported markets:
  - "cn" : China A-share (default)
  - "us" : US stocks
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .capabilities import (
        LLMCapability,
        MarketDataCapability,
        FinancialsCapability,
        FilingsCapability,
        WebSearchCapability,
        StorageCapability,
    )

LLMBackend = Literal["doubao", "deepseek"]

@dataclass
class ProviderRegistry:
    """Container for all capability providers used by the agent."""
    
    # LLMs (two models for different roles)
    planner_llm: "LLMCapability"      # For planning, reranking, verification
    synthesizer_llm: "LLMCapability"  # For final answer generation
    
    # Data capabilities
    market_data: "MarketDataCapability"
    financials: "FinancialsCapability"
    filings: "FilingsCapability"
    web_search: "WebSearchCapability"
    
    # Storage
    storage: "StorageCapability"

def create_llm_provider(
    backend: LLMBackend,
    model: str | None = None,
    **kwargs,
) -> "LLMCapability":
    """Factory function to create LLM provider by backend name.
    
    Args:
        backend: One of "doubao", "deepseek"
        model: Model name/ID (uses default from config if not specified)
        **kwargs: Additional provider-specific arguments
    
    Examples:
        llm = create_llm_provider("doubao")
        llm = create_llm_provider("deepseek", model="deepseek-chat")
    """
    if backend == "doubao":
        from .providers import DoubaoProvider
        return DoubaoProvider(model=model)
    
    elif backend == "deepseek":
        from .providers import DeepSeekProvider
        return DeepSeekProvider(model=model)
    
    else:
        raise ValueError(f"Unknown LLM backend: {backend}")

def _build_data_providers():
    """Build data providers for both US and A-share markets.
    
    A-share uses external data (local files) only.
    US uses Finnhub API.
    """
    from .providers.cn import (
        ExternalAshareMarketProvider,
        ExternalAshareFinancialsProvider,
        ExternalAshareFilingsProvider,
    )
    from .providers.us import (
        FinnhubMarketProvider,
        FinnhubFinancialsProvider,
        FinnhubFilingsProvider,
    )
    from .providers import (
        TavilyWebProvider,
        SQLiteStorageProvider,
    )
    
    # A-share uses external data (local files) only
    # US uses Finnhub API
    return {
        "market_data": ExternalAshareMarketProvider(),
        "financials": ExternalAshareFinancialsProvider(),
        "filings": ExternalAshareFilingsProvider(),
        "web_search": TavilyWebProvider(),
        "storage": SQLiteStorageProvider(),
    }

def create_default_registry() -> ProviderRegistry:
    """Create the default registry: Doubao (planner) + DeepSeek (synthesizer)."""
    from .providers import DoubaoProvider, DeepSeekProvider
    return ProviderRegistry(
        planner_llm=DoubaoProvider(),
        synthesizer_llm=DeepSeekProvider(),
        **_build_data_providers(),
    )

