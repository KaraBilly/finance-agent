"""Tests for provider package structure and imports."""
from __future__ import annotations


class TestProviderPackageStructure:
    """Tests to verify the CN/US provider package structure."""

    def test_cn_package_imports(self):
        """Should be able to import all CN providers."""
        from finance_agent.providers.cn import (
            EastmoneyMarketProvider,
            EastmoneyFinancialsProvider,
            CninfoApiFilingsProvider,
        )
        assert EastmoneyMarketProvider is not None
        assert EastmoneyFinancialsProvider is not None
        assert CninfoApiFilingsProvider is not None

    def test_us_package_imports(self):
        """Should be able to import all US providers."""
        from finance_agent.providers.us import (
            FinnhubMarketProvider,
            FinnhubFinancialsProvider,
            FinnhubFilingsProvider,
        )
        assert FinnhubMarketProvider is not None
        assert FinnhubFinancialsProvider is not None
        assert FinnhubFilingsProvider is not None

    def test_unified_imports(self):
        """Should be able to import from unified providers package."""
        from finance_agent.providers import (
            EastmoneyMarketProvider,
            FinnhubMarketProvider,
            EastmoneyFinancialsProvider,
            FinnhubFinancialsProvider,
            CninfoApiFilingsProvider,
            FinnhubFilingsProvider,
            TavilyWebProvider,
            SQLiteStorageProvider,
        )
        assert all([
            EastmoneyMarketProvider,
            FinnhubMarketProvider,
            EastmoneyFinancialsProvider,
            FinnhubFinancialsProvider,
            CninfoApiFilingsProvider,
            FinnhubFilingsProvider,
            TavilyWebProvider,
            SQLiteStorageProvider,
        ])

    def test_cn_providers_are_distinct_from_us(self):
        """CN and US providers should be different classes."""
        from finance_agent.providers.cn import EastmoneyMarketProvider
        from finance_agent.providers.us import FinnhubMarketProvider
        assert EastmoneyMarketProvider != FinnhubMarketProvider

    def test_provider_modules_exist(self):
        """All provider modules should be importable."""
        import finance_agent.providers.cn.market_eastmoney
        import finance_agent.providers.cn.financials_eastmoney
        import finance_agent.providers.cn.filings_cninfo_api
        import finance_agent.providers.us.market_finnhub
        import finance_agent.providers.us.financials_finnhub
        import finance_agent.providers.us.filings_finnhub

        assert finance_agent.providers.cn.market_eastmoney is not None
        assert finance_agent.providers.cn.financials_eastmoney is not None
        assert finance_agent.providers.cn.filings_cninfo_api is not None
        assert finance_agent.providers.us.market_finnhub is not None
        assert finance_agent.providers.us.financials_finnhub is not None
        assert finance_agent.providers.us.filings_finnhub is not None
