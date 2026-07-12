"""Tests for provider registry."""
from __future__ import annotations
from unittest.mock import patch
import pytest

from finance_agent.registry import (
    ProviderRegistry,
    create_default_registry,
    create_cn_registry,
    create_us_registry,
    create_llm_provider,
)
from finance_agent.providers.cn import (
    EastmoneyMarketProvider,
    EastmoneyFinancialsProvider,
    CninfoApiFilingsProvider,
)
from finance_agent.providers.us import (
    FinnhubMarketProvider,
    FinnhubFinancialsProvider,
    FinnhubFilingsProvider,
)
from finance_agent.providers import TavilyWebProvider, SQLiteStorageProvider
from finance_agent.capabilities import (
    MarketDataCapability,
    FinancialsCapability,
    FilingsCapability,
    WebSearchCapability,
    StorageCapability,
    LLMCapability,
)


class TestProviderRegistry:
    """Tests for ProviderRegistry dataclass."""

    def test_registry_creation(self):
        """Should create registry with all required providers."""
        with patch("finance_agent.providers.llm_openai.OpenAI"):
            with patch("finance_agent.providers.cn.market_eastmoney.requests.Session"):
                with patch("finance_agent.providers.us.market_finnhub.requests.Session"):
                    registry = create_default_registry(market="cn")

        assert isinstance(registry, ProviderRegistry)
        assert isinstance(registry.market_data, MarketDataCapability)
        assert isinstance(registry.financials, FinancialsCapability)
        assert isinstance(registry.filings, FilingsCapability)
        assert isinstance(registry.web_search, WebSearchCapability)
        assert isinstance(registry.storage, StorageCapability)
        assert isinstance(registry.planner_llm, LLMCapability)
        assert isinstance(registry.synthesizer_llm, LLMCapability)


class TestCreateCnRegistry:
    """Tests for CN market registry."""

    def test_uses_cn_providers(self):
        """CN registry should use CN-specific providers."""
        with patch("finance_agent.providers.llm_openai.OpenAI"):
            with patch("finance_agent.providers.cn.market_eastmoney.requests.Session"):
                registry = create_cn_registry()

        assert isinstance(registry.market_data, EastmoneyMarketProvider)
        assert isinstance(registry.financials, EastmoneyFinancialsProvider)
        assert isinstance(registry.filings, CninfoApiFilingsProvider)
        assert isinstance(registry.web_search, TavilyWebProvider)
        assert isinstance(registry.storage, SQLiteStorageProvider)


class TestCreateUsRegistry:
    """Tests for US market registry."""

    @patch("finance_agent.providers.us.market_finnhub.CONFIG")
    def test_uses_us_providers(self, mock_config):
        """US registry should use US-specific providers."""
        mock_config.finnhub_api_key = "test_key"
        with patch("finance_agent.providers.llm_openai.OpenAI"):
            with patch("finance_agent.providers.us.market_finnhub.requests.Session"):
                registry = create_us_registry()

        assert isinstance(registry.market_data, FinnhubMarketProvider)
        assert isinstance(registry.financials, FinnhubFinancialsProvider)
        assert isinstance(registry.filings, FinnhubFilingsProvider)
        assert isinstance(registry.web_search, TavilyWebProvider)
        assert isinstance(registry.storage, SQLiteStorageProvider)


class TestCreateLlmProvider:
    """Tests for LLM provider factory."""

    def test_create_doubao_provider(self):
        """Should create Doubao provider."""
        with patch("finance_agent.providers.llm_openai.OpenAI"):
            provider = create_llm_provider("doubao")
        assert isinstance(provider, LLMCapability)

    def test_create_deepseek_provider(self):
        """Should create DeepSeek provider."""
        with patch("finance_agent.providers.llm_openai.OpenAI"):
            provider = create_llm_provider("deepseek")
        assert isinstance(provider, LLMCapability)

    def test_unknown_backend_raises(self):
        """Should raise for unknown backend."""
        with pytest.raises(ValueError, match="Unknown LLM backend"):
            create_llm_provider("unknown")


class TestRegistryMarketSwitching:
    """Tests for switching between CN and US markets."""

    @patch("finance_agent.providers.us.market_finnhub.CONFIG")
    def test_market_switching(self, mock_config):
        """Should be able to create different market registries."""
        mock_config.finnhub_api_key = "test_key"

        with patch("finance_agent.providers.llm_openai.OpenAI"):
            with patch("finance_agent.providers.cn.market_eastmoney.requests.Session"):
                with patch("finance_agent.providers.us.market_finnhub.requests.Session"):
                    cn_registry = create_default_registry(market="cn")
                    us_registry = create_default_registry(market="us")

        assert isinstance(cn_registry.market_data, EastmoneyMarketProvider)
        assert isinstance(us_registry.market_data, FinnhubMarketProvider)
        assert isinstance(cn_registry.financials, EastmoneyFinancialsProvider)
        assert isinstance(us_registry.financials, FinnhubFinancialsProvider)
        assert isinstance(cn_registry.filings, CninfoApiFilingsProvider)
        assert isinstance(us_registry.filings, FinnhubFilingsProvider)
