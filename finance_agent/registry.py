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
  - "us" : US stocks     — Finnhub API-based providers
  - "cn" : China A-share — local external-data providers
The Agent picks providers per-question via ``ProviderRegistry.for_market``.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal, Optional

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
Market = Literal["us", "cn"]

# Which market the agent falls back to when it cannot infer one from the
# question. README positions this project as US-focused, so US wins ties.
DEFAULT_MARKET: Market = "us"

@dataclass
class MarketProviders:
    """Bundle of the three market-specific capabilities.

    Grouping them like this keeps the ``ProviderRegistry`` flat while still
    letting the agent pick a full set atomically via
    :py:meth:`ProviderRegistry.for_market`.
    """

    market_data: "MarketDataCapability"
    financials: "FinancialsCapability"
    filings: "FilingsCapability"

@dataclass
class ProviderRegistry:
    """Container for all capability providers used by the agent.

    Market-scoped provider bundles (``us`` / ``cn``) are constructed lazily
    via factory callables. This lets a user with only ``FINNHUB_API_KEY``
    unset still ask CN questions without a startup error (and vice versa).
    """

    # LLMs (two models for different roles)
    planner_llm: "LLMCapability"      # For planning, reranking, verification
    synthesizer_llm: "LLMCapability"  # For final answer generation

    # Shared capabilities
    web_search: "WebSearchCapability"
    storage: "StorageCapability"

    # Market-scoped provider factories. Materialized on first access.
    _us_factory: Callable[[], MarketProviders] = field(default=lambda: _build_us_providers())
    _cn_factory: Callable[[], MarketProviders] = field(default=lambda: _build_cn_providers())
    _us_cached: Optional[MarketProviders] = field(default=None, repr=False)
    _cn_cached: Optional[MarketProviders] = field(default=None, repr=False)

    @property
    def us(self) -> MarketProviders:
        if self._us_cached is None:
            self._us_cached = self._us_factory()
        return self._us_cached

    @property
    def cn(self) -> MarketProviders:
        if self._cn_cached is None:
            self._cn_cached = self._cn_factory()
        return self._cn_cached

    def for_market(self, market: str | None) -> MarketProviders:
        """Return the provider bundle for a given market symbol.

        Falls back to :data:`DEFAULT_MARKET` for unknown / None inputs so
        that callers never have to branch on ``market == "unknown"``.
        """
        if market == "us":
            return self.us
        if market == "cn":
            return self.cn
        return self.us if DEFAULT_MARKET == "us" else self.cn

    # ------------------------------------------------------------------
    # Backwards-compat flat accessors. Older tests and demos read
    # ``registry.market_data`` / ``.financials`` / ``.filings`` directly;
    # keep those working by delegating to the CN bundle (which is what the
    # original single-market registry exposed).
    # ------------------------------------------------------------------
    @property
    def market_data(self) -> "MarketDataCapability":
        return self.cn.market_data

    @property
    def financials(self) -> "FinancialsCapability":
        return self.cn.financials

    @property
    def filings(self) -> "FilingsCapability":
        return self.cn.filings

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

def _build_us_providers() -> MarketProviders:
    """Build US market providers (Finnhub-based)."""
    from .providers.us import (
        FinnhubMarketProvider,
        FinnhubFinancialsProvider,
        FinnhubFilingsProvider,
    )
    return MarketProviders(
        market_data=FinnhubMarketProvider(),
        financials=FinnhubFinancialsProvider(),
        filings=FinnhubFilingsProvider(),
    )

def _build_cn_providers() -> MarketProviders:
    """Build CN A-share providers (external local files)."""
    from .providers.cn import (
        ExternalAshareMarketProvider,
        ExternalAshareFinancialsProvider,
        ExternalAshareFilingsProvider,
    )
    return MarketProviders(
        market_data=ExternalAshareMarketProvider(),
        financials=ExternalAshareFinancialsProvider(),
        filings=ExternalAshareFilingsProvider(),
    )

def create_default_registry() -> ProviderRegistry:
    """Create the default registry: Doubao (planner) + DeepSeek (synthesizer)."""
    from .providers import (
        DoubaoProvider,
        DeepSeekProvider,
        TavilyWebProvider,
        SQLiteStorageProvider,
    )
    return ProviderRegistry(
        planner_llm=DoubaoProvider(),
        synthesizer_llm=DeepSeekProvider(),
        web_search=TavilyWebProvider(),
        storage=SQLiteStorageProvider(),
    )

