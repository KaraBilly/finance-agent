"""Tests for CN market data providers."""
from __future__ import annotations
from unittest.mock import Mock, patch
import pandas as pd
import pytest

from finance_agent.providers.cn import (
    EastmoneyMarketProvider,
    EastmoneyFinancialsProvider,
    CninfoApiFilingsProvider,
)
from finance_agent.capabilities.market_data import MarketDataCapability
from finance_agent.capabilities.financials import FinancialsCapability
from finance_agent.capabilities.filings import FilingsCapability


class TestEastmoneyMarketProvider:
    """Tests for Eastmoney market data provider."""

    def test_implements_interface(self):
        """Provider should implement MarketDataCapability."""
        provider = EastmoneyMarketProvider()
        assert isinstance(provider, MarketDataCapability)

    def test_list_available_indices(self):
        """Should return dict of available indices."""
        provider = EastmoneyMarketProvider()
        indices = provider.list_available_indices()
        assert isinstance(indices, dict)
        assert len(indices) > 0
        assert "000001" in indices  # 上证指数

    @patch("finance_agent.providers.cn.market_eastmoney._fetch_kline")
    def test_get_index_daily(self, mock_fetch, tmp_path):
        """Should fetch index daily data."""
        mock_df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "open": [100.0, 101.0],
            "close": [101.0, 102.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "volume": [1000000, 2000000],
        })
        mock_fetch.return_value = mock_df

        provider = EastmoneyMarketProvider(indices_dir=tmp_path)
        df = provider.get_index_daily("000001", start="20240101", end="20240102")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert "close" in df.columns

    @patch("finance_agent.providers.cn.market_eastmoney._fetch_kline")
    def test_get_stock_daily(self, mock_fetch):
        """Should fetch stock daily data."""
        mock_df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]),
            "open": [10.0],
            "close": [10.5],
            "high": [10.8],
            "low": [9.8],
            "volume": [500000],
        })
        mock_fetch.return_value = mock_df

        provider = EastmoneyMarketProvider()
        df = provider.get_stock_daily("600519", start="20240101", end="20240101")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1

    @patch("finance_agent.providers.cn.market_eastmoney._fetch_kline")
    def test_summarize_index(self, mock_fetch):
        """Should produce Evidence summary for index."""
        dates = pd.date_range("2020-01-01", "2024-01-01", freq="D")
        mock_df = pd.DataFrame({
            "date": dates,
            "open": [3000.0] * len(dates),
            "close": list(range(3000, 3000 + len(dates))),
            "high": [3100.0] * len(dates),
            "low": [2900.0] * len(dates),
            "volume": [1000000] * len(dates),
        })
        mock_fetch.return_value = mock_df

        provider = EastmoneyMarketProvider()
        evidence = provider.summarize_index("000001", lookback_years=1)

        assert evidence is not None
        assert evidence.source_kind == "market"
        assert "000001" in evidence.text


class TestEastmoneyFinancialsProvider:
    """Tests for Eastmoney financials provider."""

    def test_implements_interface(self):
        """Provider should implement FinancialsCapability."""
        provider = EastmoneyFinancialsProvider()
        assert isinstance(provider, FinancialsCapability)

    @patch("finance_agent.providers.cn.financials_eastmoney.EastmoneyFinancialsProvider._query")
    def test_get_statement(self, mock_query):
        """Should fetch financial statement."""
        mock_df = pd.DataFrame({
            "REPORT_DATE": ["2024-03-31", "2023-12-31"],
            "TOTAL_OPERATE_INCOME": [1000000, 4000000],
            "PARENT_NETPROFIT": [100000, 500000],
        })
        mock_query.return_value = mock_df

        provider = EastmoneyFinancialsProvider()
        df = provider.get_statement("600519", "income", periods=2)

        assert isinstance(df, pd.DataFrame)
        assert len(df) <= 2

    @patch("finance_agent.providers.cn.financials_eastmoney.EastmoneyFinancialsProvider._query")
    def test_summarize_statement(self, mock_query):
        """Should produce Evidence summary."""
        mock_df = pd.DataFrame({
            "REPORT_DATE": ["2024-03-31", "2023-12-31"],
            "TOTAL_OPERATE_INCOME": [1000000, 4000000],
            "PARENT_NETPROFIT": [100000, 500000],
        })
        mock_query.return_value = mock_df

        provider = EastmoneyFinancialsProvider()
        evidence = provider.summarize_statement("600519", "income", periods=2)

        assert evidence is not None
        assert evidence.source_kind == "financials"
        assert "600519" in evidence.text


class TestCninfoApiFilingsProvider:
    """Tests for Cninfo filings provider."""

    def test_implements_interface(self):
        """Provider should implement FilingsCapability."""
        provider = CninfoApiFilingsProvider()
        assert isinstance(provider, FilingsCapability)

    @patch("finance_agent.providers.cn.filings_cninfo_api.CninfoApiFilingsProvider._query")
    def test_list_annual_reports(self, mock_query):
        """Should list annual reports."""
        mock_query.return_value = [
            {
                "announcementTitle": "2023年度报告",
                "announcementTime": "1704067200000",
                "secCode": "600519",
                "secName": "贵州茅台",
                "adjunctUrl": "/finalpage/2024-04-01/123456789.pdf",
            }
        ]

        provider = CninfoApiFilingsProvider()
        df = provider.list_annual_reports("600519", years_back=1)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert "2023年度报告" in str(df.iloc[0]["公告标题"])

    @patch("finance_agent.providers.cn.filings_cninfo_api.CninfoApiFilingsProvider._query")
    def test_collect_filings(self, mock_query):
        """Should collect filing evidences."""
        mock_query.return_value = [
            {
                "announcementTitle": "2023年度报告",
                "announcementTime": "1704067200000",
                "secCode": "600519",
                "secName": "贵州茅台",
                "adjunctUrl": "/finalpage/2024-04-01/123456789.pdf",
            }
        ]

        provider = CninfoApiFilingsProvider()
        evidences = provider.collect_filings("600519", years_back=1)

        assert isinstance(evidences, list)
        assert len(evidences) > 0
        assert evidences[0].source_kind == "filings"
