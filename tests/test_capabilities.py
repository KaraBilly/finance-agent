"""Tests for capability interfaces."""
from __future__ import annotations
import inspect
from abc import ABC

from finance_agent.capabilities.market_data import MarketDataCapability
from finance_agent.capabilities.financials import FinancialsCapability
from finance_agent.capabilities.filings import FilingsCapability
from finance_agent.capabilities.llm import LLMCapability
from finance_agent.capabilities.web_search import WebSearchCapability
from finance_agent.capabilities.storage import StorageCapability


class TestCapabilityInterfaces:
    """Tests to ensure all capability interfaces are properly defined."""

    def test_market_data_is_abstract(self):
        """MarketDataCapability should be abstract."""
        assert issubclass(MarketDataCapability, ABC)
        assert MarketDataCapability.__abstractmethods__

    def test_financials_is_abstract(self):
        """FinancialsCapability should be abstract."""
        assert issubclass(FinancialsCapability, ABC)
        assert FinancialsCapability.__abstractmethods__

    def test_filings_is_abstract(self):
        """FilingsCapability should be abstract."""
        assert issubclass(FilingsCapability, ABC)
        assert FilingsCapability.__abstractmethods__

    def test_llm_is_abstract(self):
        """LLMCapability should be abstract."""
        assert issubclass(LLMCapability, ABC)
        assert LLMCapability.__abstractmethods__

    def test_web_search_is_abstract(self):
        """WebSearchCapability should be abstract."""
        assert issubclass(WebSearchCapability, ABC)
        assert WebSearchCapability.__abstractmethods__

    def test_storage_is_abstract(self):
        """StorageCapability should be abstract."""
        assert issubclass(StorageCapability, ABC)
        assert StorageCapability.__abstractmethods__


class TestProviderImplementations:
    """Tests to verify concrete providers implement interfaces."""

    def test_cn_market_provider_implements(self):
        """CN market provider should implement MarketDataCapability."""
        from finance_agent.providers.cn import EastmoneyMarketProvider
        assert issubclass(EastmoneyMarketProvider, MarketDataCapability)

    def test_us_market_provider_implements(self):
        """US market provider should implement MarketDataCapability."""
        from finance_agent.providers.us import FinnhubMarketProvider
        assert issubclass(FinnhubMarketProvider, MarketDataCapability)

    def test_cn_financials_provider_implements(self):
        """CN financials provider should implement FinancialsCapability."""
        from finance_agent.providers.cn import EastmoneyFinancialsProvider
        assert issubclass(EastmoneyFinancialsProvider, FinancialsCapability)

    def test_us_financials_provider_implements(self):
        """US financials provider should implement FinancialsCapability."""
        from finance_agent.providers.us import FinnhubFinancialsProvider
        assert issubclass(FinnhubFinancialsProvider, FinancialsCapability)

    def test_cn_filings_provider_implements(self):
        """CN filings provider should implement FilingsCapability."""
        from finance_agent.providers.cn import CninfoApiFilingsProvider
        assert issubclass(CninfoApiFilingsProvider, FilingsCapability)

    def test_us_filings_provider_implements(self):
        """US filings provider should implement FilingsCapability."""
        from finance_agent.providers.us import FinnhubFilingsProvider
        assert issubclass(FinnhubFilingsProvider, FilingsCapability)
