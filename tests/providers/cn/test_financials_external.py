"""Tests for the RAG-backed :class:`ExternalAshareFinancialsProvider`.

The provider must never hit the filesystem itself — every request should
route through the injected :class:`ExternalDataStore`. These tests verify
routing, filter passing, statement-type differentiation, and graceful
handling of empty RAG responses.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from finance_agent.capabilities.base import Evidence
from finance_agent.capabilities.financials import FinancialsCapability
from finance_agent.providers.cn.financials_external import (
    ExternalAshareFinancialsProvider,
    _STATEMENT_ZH,
)

# ---------------------------------------------------------------- helpers

def _make_store(results_by_query: dict | None = None) -> MagicMock:
    """Build a mock ``ExternalDataStore``. ``results_by_query`` maps the
    first positional arg of ``search`` (the query string) to the Evidence
    list it should return; anything else returns an empty list."""
    store = MagicMock()
    results_by_query = results_by_query or {}

    def _search(query, **kwargs):
        for pattern, evs in results_by_query.items():
            if pattern in query:
                return evs
        return []

    store.search.side_effect = _search
    return store

def _ev(text: str, symbol: str = "002594", statement_hint: str = "") -> Evidence:
    return Evidence(
        text=text,
        source_kind="financials",
        url=None,
        title=f"{symbol} {statement_hint}",
        publisher="external_data",
        meta={"symbol": symbol, "file": "/tmp/mock.csv"},
    )

# ---------------------------------------------------------------- interface

class TestInterface:
    def test_implements_capability(self):
        provider = ExternalAshareFinancialsProvider(store=MagicMock())
        assert isinstance(provider, FinancialsCapability)

# ---------------------------------------------------------------- no file I/O

class TestNoDirectFileIO:
    """Regression guard: the provider must never touch pandas.read_csv or
    Path.rglob. All data must flow through the injected RAG store."""

    def test_provider_module_does_not_import_pandas_reader(self):
        # Sanity check the module's top-level symbols — nothing that would
        # walk the filesystem should be referenced.
        import finance_agent.providers.cn.financials_external as mod

        assert not hasattr(mod, "_load_data")
        assert not hasattr(mod, "_find_file")
        assert not hasattr(mod, "_COL_MAP")
        # Public class no longer exposes a data_dir attribute.
        provider = ExternalAshareFinancialsProvider(store=MagicMock())
        assert not hasattr(provider, "data_dir")
        assert not hasattr(provider, "_cache")

# ---------------------------------------------------------------- routing

class TestRAGRouting:
    def test_summarize_statement_queries_rag_with_symbol_and_kind(self):
        expected = _ev("income statement content", statement_hint="利润表")
        store = _make_store({"利润表": [expected]})
        provider = ExternalAshareFinancialsProvider(store=store)

        ev = provider.summarize_statement("002594", "income", periods=4)

        # The provider must ONLY talk to RAG.
        store.search.assert_called_once()
        kwargs = store.search.call_args.kwargs
        assert kwargs["source_kinds"] == ["financials"]
        assert kwargs["symbols"] == ["002594"]
        # Returned Evidence carries the correct statement-type meta.
        assert ev.source_kind == "financials"
        assert ev.meta["kind"] == "income"
        assert ev.meta["symbol"] == "002594"
        assert ev.meta["periods"] == 4
        assert "利润表" in ev.title

    def test_summarize_statement_raises_when_rag_empty(self):
        store = _make_store({})  # every query returns []
        provider = ExternalAshareFinancialsProvider(store=store)
        with pytest.raises(RuntimeError, match="No income data"):
            provider.summarize_statement("999999", "income", periods=3)

    def test_get_statement_returns_dataframe_of_chunks(self):
        evs = [
            _ev("chunk 1", statement_hint="资产负债表"),
            _ev("chunk 2", statement_hint="资产负债表"),
        ]
        store = _make_store({"资产负债表": evs})
        provider = ExternalAshareFinancialsProvider(store=store)

        df = provider.get_statement("002594", "balance", periods=3)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert list(df.columns) == ["text", "title", "publisher"]
        assert df.iloc[0]["text"] == "chunk 1"

    def test_get_statement_returns_empty_dataframe_when_rag_empty(self):
        store = _make_store({})
        provider = ExternalAshareFinancialsProvider(store=store)
        df = provider.get_statement("999999", "income", periods=3)
        assert df.empty

# ---------------------------------------------------------------- collect_all

class TestCollectAll:
    def test_collect_all_default_types(self):
        # Different Evidence per statement type — the query key contains
        # the statement's Chinese name so our mock can route by substring.
        results = {
            "利润表": [_ev("income data", statement_hint="利润表")],
            "资产负债表": [_ev("balance data", statement_hint="资产负债表")],
            "现金流量表": [_ev("cashflow data", statement_hint="现金流量表")],
        }
        store = _make_store(results)
        provider = ExternalAshareFinancialsProvider(store=store)

        evs = provider.collect_all("002594")

        assert len(evs) == 3
        assert store.search.call_count == 3
        kinds = [e.meta["kind"] for e in evs]
        assert kinds == ["income", "balance", "cashflow"]

    def test_collect_all_partial_types(self):
        results = {"利润表": [_ev("income data")]}
        store = _make_store(results)
        provider = ExternalAshareFinancialsProvider(store=store)

        evs = provider.collect_all("002594", statement_types=["income"])
        assert len(evs) == 1
        assert store.search.call_count == 1
        assert evs[0].meta["kind"] == "income"

    def test_collect_all_survives_missing_statement(self):
        # Only income has data; balance & cashflow fail with RuntimeError
        # inside summarize_statement, but collect_all should keep going.
        results = {"利润表": [_ev("income data")]}
        store = _make_store(results)
        provider = ExternalAshareFinancialsProvider(store=store)

        evs = provider.collect_all("002594")
        assert len(evs) == 1
        assert evs[0].meta["kind"] == "income"

    def test_collect_all_survives_rag_exception(self):
        # A raised exception inside RAG search must not crash collect_all.
        store = MagicMock()
        store.search.side_effect = RuntimeError("Milvus timeout")
        provider = ExternalAshareFinancialsProvider(store=store)

        evs = provider.collect_all("002594")
        # All three statement queries failed, but the method returns [].
        assert evs == []

# ---------------------------------------------------------------- store sharing

class TestSharedStore:
    def test_default_store_uses_shared_singleton(self):
        # When no store is injected the provider must lazily reach for the
        # module-level shared instance — never construct its own private
        # ExternalDataStore, which would double-load data + double-insert
        # into Milvus.
        from unittest.mock import patch

        with patch(
            "finance_agent.retrieval.external_data_store.get_shared_external_store"
        ) as get_shared:
            sentinel = MagicMock()
            sentinel.search.return_value = []
            get_shared.return_value = sentinel

            provider = ExternalAshareFinancialsProvider()
            # Force a call so the lazy _get_store fires.
            provider.collect_all("002594", statement_types=["income"])

        get_shared.assert_called()
        assert sentinel.search.call_count == 1

# ---------------------------------------------------------------- keywords

class TestStatementKeywords:
    """Sanity check that every StatementType has a matching Chinese title
    and query keyword bundle."""

    @pytest.mark.parametrize("kind", ["income", "balance", "cashflow"])
    def test_all_types_have_zh_title(self, kind):
        assert kind in _STATEMENT_ZH

    def test_query_includes_symbol_and_periods_hint(self):
        received: dict = {}
        store = MagicMock()

        def _capture(q, **kw):
            received["q"] = q
            return []  # force RuntimeError below; we only care about q

        store.search.side_effect = _capture
        provider = ExternalAshareFinancialsProvider(store=store)

        with pytest.raises(RuntimeError):
            provider.summarize_statement("002594", "income", periods=5)
        assert "002594" in received["q"]
        assert "5" in received["q"]
        assert "利润表" in received["q"]
