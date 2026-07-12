"""Tests for US market data providers."""
from __future__ import annotations
from unittest.mock import Mock, patch
import pandas as pd
import pytest

from finance_agent.providers.us import (
    FinnhubMarketProvider,
    FinnhubFinancialsProvider,
    FinnhubFilingsProvider,
)
from finance_agent.capabilities.market_data import MarketDataCapability
from finance_agent.capabilities.financials import FinancialsCapability
from finance_agent.capabilities.filings import FilingsCapability


class TestFinnhubMarketProvider:
    """Tests for Finnhub market data provider."""

    @patch("finance_agent.providers.us.market_finnhub.CONFIG")
    def test_implements_interface(self, mock_config):
        """Provider should implement MarketDataCapability."""
        mock_config.finnhub_api_key = "test_key"
        provider = FinnhubMarketProvider()
        assert isinstance(provider, MarketDataCapability)

    @patch("finance_agent.providers.us.market_finnhub.CONFIG")
    def test_list_available_indices(self, mock_config):
        """Should return dict of available US indices."""
        mock_config.finnhub_api_key = "test_key"
        provider = FinnhubMarketProvider()
        indices = provider.list_available_indices()
        assert isinstance(indices, dict)
        assert len(indices) > 0
        assert "QQQ" in indices

    @patch("finance_agent.providers.us.market_finnhub._fetch_quote")
    @patch("finance_agent.providers.us.market_finnhub.CONFIG")
    def test_get_index_daily(self, mock_config, mock_fetch):
        """Should fetch index daily data."""
        mock_config.finnhub_api_key = "test_key"
        mock_fetch.return_value = {
            "o": 380.0, "h": 385.0, "l": 378.0, "c": 384.0, "d": 4.0, "dp": 1.05
        }

        provider = FinnhubMarketProvider()
        df = provider.get_index_daily("QQQ")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert "close" in df.columns
        assert df.iloc[0]["close"] == 384.0

    @patch("finance_agent.providers.us.market_finnhub._fetch_quote")
    @patch("finance_agent.providers.us.market_finnhub.CONFIG")
    def test_get_stock_daily(self, mock_config, mock_fetch):
        """Should fetch stock daily data."""
        mock_config.finnhub_api_key = "test_key"
        mock_fetch.return_value = {
            "o": 150.0, "h": 155.0, "l": 148.0, "c": 154.0, "d": 4.0, "dp": 2.67
        }

        provider = FinnhubMarketProvider()
        df = provider.get_stock_daily("AAPL")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert df.iloc[0]["close"] == 154.0

    @patch("finance_agent.providers.us.market_finnhub._fetch_metric")
    @patch("finance_agent.providers.us.market_finnhub._fetch_quote")
    @patch("finance_agent.providers.us.market_finnhub.CONFIG")
    def test_summarize_index(self, mock_config, mock_quote, mock_metric):
        """Should produce Evidence summary for US index."""
        mock_config.finnhub_api_key = "test_key"
        mock_quote.return_value = {
            "c": 384.0, "d": 4.0, "dp": 1.05
        }
        mock_metric.return_value = {
            "metric": {"52WeekHigh": 420.0, "52WeekLow": 320.0}
        }

        provider = FinnhubMarketProvider()
        evidence = provider.summarize_index("QQQ")

        assert evidence is not None
        assert evidence.source_kind == "market"
        assert "QQQ" in evidence.text


class TestFinnhubFinancialsProvider:
    """Tests for Finnhub financials provider."""

    @patch("finance_agent.providers.us.financials_finnhub.CONFIG")
    def test_implements_interface(self, mock_config):
        """Provider should implement FinancialsCapability."""
        mock_config.finnhub_api_key = "test_key"
        provider = FinnhubFinancialsProvider()
        assert isinstance(provider, FinancialsCapability)

    @patch("finance_agent.providers.us.financials_finnhub.FinnhubFinancialsProvider._fetch_financials_reported")
    @patch("finance_agent.providers.us.financials_finnhub.CONFIG")
    def test_get_statement(self, mock_config, mock_fetch):
        """Should fetch financial statement."""
        mock_config.finnhub_api_key = "test_key"
        mock_fetch.return_value = [
            {
                "endDate": "2024-03-31",
                "form": "10-Q",
                "year": "2024",
                "quarter": "Q1",
                "report": {
                    "ic": [
                        {"label": "Revenue", "value": 100000000},
                        {"label": "Net Income", "value": 20000000},
                    ]
                }
            }
        ]

        provider = FinnhubFinancialsProvider()
        df = provider.get_statement("AAPL", "income", periods=1)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1

    @patch("finance_agent.providers.us.financials_finnhub.FinnhubFinancialsProvider._fetch_financials_reported")
    @patch("finance_agent.providers.us.financials_finnhub.CONFIG")
    def test_summarize_statement(self, mock_config, mock_fetch):
        """Should produce Evidence summary."""
        mock_config.finnhub_api_key = "test_key"
        mock_fetch.return_value = [
            {
                "endDate": "2024-03-31",
                "form": "10-Q",
                "year": "2024",
                "quarter": "Q1",
                "report": {
                    "ic": [
                        {"label": "Revenue", "value": 100000000},
                        {"label": "Net Income", "value": 20000000},
                    ]
                }
            }
        ]

        provider = FinnhubFinancialsProvider()
        evidence = provider.summarize_statement("AAPL", "income", periods=1)

        assert evidence is not None
        assert evidence.source_kind == "financials"
        assert "AAPL" in evidence.text


class TestFinnhubFilingsProvider:
    """Tests for Finnhub filings provider."""

    @patch("finance_agent.providers.us.filings_finnhub.CONFIG")
    def test_implements_interface(self, mock_config):
        """Provider should implement FilingsCapability."""
        mock_config.finnhub_api_key = "test_key"
        provider = FinnhubFilingsProvider()
        assert isinstance(provider, FilingsCapability)

    @patch("finance_agent.providers.us.filings_finnhub.FinnhubFilingsProvider._fetch_filings")
    @patch("finance_agent.providers.us.filings_finnhub.CONFIG")
    def test_list_annual_reports(self, mock_config, mock_fetch):
        """Should list annual reports (10-K filings)."""
        mock_config.finnhub_api_key = "test_key"
        mock_fetch.return_value = [
            {
                "form": "10-K",
                "filedDate": "2024-02-15",
                "filingUrl": "https://sec.gov/10k.pdf",
            }
        ]

        provider = FinnhubFilingsProvider()
        df = provider.list_annual_reports("AAPL", years_back=1)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert "10-K" in str(df.iloc[0]["公告类型"])

    @patch("finance_agent.providers.us.filings_finnhub.FinnhubFilingsProvider._fetch_filings")
    @patch("finance_agent.providers.us.filings_finnhub.CONFIG")
    def test_collect_filings(self, mock_config, mock_fetch):
        """Should collect filing evidences."""
        mock_config.finnhub_api_key = "test_key"
        mock_fetch.return_value = [
            {
                "form": "10-K",
                "filedDate": "2024-02-15",
                "filingUrl": "https://sec.gov/10k.pdf",
            }
        ]

        provider = FinnhubFilingsProvider()
        evidences = provider.collect_filings("AAPL", years_back=1)

        assert isinstance(evidences, list)
        assert len(evidences) > 0
        assert evidences[0].source_kind == "filings"
