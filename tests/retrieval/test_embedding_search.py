"""Tests for :mod:`finance_agent.retrieval.embedding_search`.

Focus on Milvus-related routing (init failure fallback, filter forwarding,
in-memory fallback path) rather than the embedding model itself, which
requires downloading multi-GB weights.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from finance_agent.retrieval import embedding_search as es_mod
from finance_agent.retrieval.embedding_search import EmbeddingSearch

# ---------------------------------------------------------------- helpers

def _make_search(
    *,
    use_milvus: bool = True,
    milvus_store: MagicMock | None = None,
    embedding_dim: int = 4,
) -> EmbeddingSearch:
    """Construct an ``EmbeddingSearch`` with the sentence-transformers model
    stubbed out. Optionally injects a mock ``MilvusStore``."""
    with patch.object(es_mod, "SENTENCE_TRANSFORMERS_AVAILABLE", False):
        with patch.object(es_mod, "MILVUS_AVAILABLE", True):
            with patch.object(es_mod, "MilvusStore", return_value=milvus_store or MagicMock()) as _:
                search = EmbeddingSearch(use_milvus=use_milvus, auto_download=False)
    # Pretend a model is loaded and knows its output dimension.
    search._embedding_dim = embedding_dim
    search._model = MagicMock()
    search._model.encode.side_effect = lambda texts, show_progress_bar=False: np.ones(
        (len(texts), embedding_dim), dtype=np.float32
    )
    return search

# ---------------------------------------------------------------- init

class TestInit:
    def test_use_milvus_false_disables_store(self):
        search = _make_search(use_milvus=False)
        assert search._use_milvus is False
        assert search._milvus_store is None

    def test_milvus_unavailable_forces_disable(self):
        with patch.object(es_mod, "MILVUS_AVAILABLE", False):
            search = EmbeddingSearch(use_milvus=True, auto_download=False)
        assert search._use_milvus is False

    def test_milvus_store_init_failure_falls_back(self):
        with patch.object(es_mod, "MILVUS_AVAILABLE", True):
            with patch.object(es_mod, "MilvusStore", side_effect=RuntimeError("boom")):
                search = EmbeddingSearch(use_milvus=True, auto_download=False)
        # A failed Milvus init must not crash construction — we must fall
        # back to the in-memory path so retrieval still returns *something*.
        assert search._use_milvus is False

# ---------------------------------------------------------------- indexing

class TestIndexDocuments:
    def test_indexes_via_milvus_when_available(self):
        store = MagicMock()
        store.collection_exists.return_value = False
        search = _make_search(use_milvus=True, milvus_store=store)
        # Ensure the mock is what got assigned during __init__.
        search._milvus_store = store
        search._use_milvus = True

        docs = ["a", "b", "c"]
        metas = [
            {"source_kind": "market", "symbol": "AAPL"},
            {"source_kind": "filings", "symbol": "MSFT"},
            {"source_kind": "web"},
        ]
        search.index_documents(docs, metas)

        store.create_collection.assert_called_once()
        store.insert.assert_called_once()
        kwargs = store.insert.call_args.kwargs
        assert kwargs["texts"] == docs
        assert kwargs["source_kinds"] == ["market", "filings", "web"]
        assert kwargs["symbols"] == ["AAPL", "MSFT", ""]

    def test_indexes_in_memory_when_milvus_disabled(self):
        search = _make_search(use_milvus=False)
        search.index_documents(["hello", "world"], [{"a": 1}, {"b": 2}])
        assert search._documents == ["hello", "world"]
        assert search._embeddings is not None
        assert search._embeddings.shape == (2, 4)

    def test_milvus_insert_failure_falls_back_to_memory(self):
        store = MagicMock()
        store.collection_exists.return_value = True
        store.insert.side_effect = RuntimeError("network")
        search = _make_search(use_milvus=True, milvus_store=store)
        search._milvus_store = store
        search._use_milvus = True

        search.index_documents(["x"], [{"source_kind": "market"}])
        # Failure must degrade gracefully — no more Milvus, but data is
        # still queryable in memory.
        assert search._use_milvus is False
        assert search._documents == ["x"]

# ---------------------------------------------------------------- search

class TestSearch:
    def test_search_delegates_to_milvus_with_filters(self):
        store = MagicMock()
        store.search.return_value = [("doc-1", 0.9, {"symbol": "AAPL"})]
        search = _make_search(use_milvus=True, milvus_store=store)
        search._milvus_store = store
        search._use_milvus = True

        results = search.search(
            "quarterly revenue",
            top_k=5,
            source_kinds=["filings"],
            symbols=["AAPL"],
        )

        store.search.assert_called_once()
        kwargs = store.search.call_args.kwargs
        assert kwargs["top_k"] == 5
        assert kwargs["source_kinds"] == ["filings"]
        assert kwargs["symbols"] == ["AAPL"]
        assert results == [("doc-1", 0.9, {"symbol": "AAPL"})]

    def test_search_falls_back_to_memory_on_milvus_error(self):
        store = MagicMock()
        store.search.side_effect = RuntimeError("timeout")
        search = _make_search(use_milvus=True, milvus_store=store)
        search._milvus_store = store
        search._use_milvus = True
        # Seed in-memory state so the fallback has something to return.
        search._documents = ["hello"]
        search._metas = [{"source_kind": "market"}]
        search._embeddings = np.ones((1, 4), dtype=np.float32)

        results = search.search("hello", top_k=3)
        assert len(results) == 1
        assert results[0][0] == "hello"

    def test_in_memory_search_ranks_by_cosine(self):
        search = _make_search(use_milvus=False)
        # Two docs, distinct embeddings.
        search._documents = ["match", "other"]
        search._metas = [{"i": 0}, {"i": 1}]
        search._embeddings = np.array(
            [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], dtype=np.float32
        )
        # Query embedding aligned with the first doc.
        search._model.encode.side_effect = lambda texts, show_progress_bar=False: np.array(
            [[1.0, 0.0, 0.0, 0.0]], dtype=np.float32
        )
        results = search.search("q", top_k=2)
        assert results[0][0] == "match"
        assert results[0][1] > results[1][1]

    def test_in_memory_search_with_no_docs(self):
        search = _make_search(use_milvus=False)
        # Nothing indexed → search must return [] rather than raising.
        assert search.search("x", top_k=3) == []

    def test_filter_fn_applied_to_milvus_results(self):
        store = MagicMock()
        store.search.return_value = [
            ("doc-a", 0.9, {"symbol": "AAPL"}),
            ("doc-b", 0.8, {"symbol": "MSFT"}),
        ]
        search = _make_search(use_milvus=True, milvus_store=store)
        search._milvus_store = store
        search._use_milvus = True

        results = search.search(
            "q",
            top_k=5,
            filter_fn=lambda _text, meta: meta.get("symbol") == "MSFT",
        )
        assert len(results) == 1
        assert results[0][2]["symbol"] == "MSFT"


# ---------------------------------------------------------------- readiness

class TestIsReady:
    """Regression guards for the ``No embedding model available`` failure.

    When sentence-transformers isn't installed AND ``use_api=False``, the
    old code left ``_use_milvus=True`` and blew up inside ``_get_embeddings``
    on the first ``search()`` call. Now the constructor should detect the
    missing embedder, disable Milvus, and ``search``/``index_documents``
    should early-return without raising.
    """

    def test_is_ready_false_when_no_model_and_no_api(self):
        # Simulate: sentence-transformers missing, pymilvus available.
        with patch.object(es_mod, "SENTENCE_TRANSFORMERS_AVAILABLE", False):
            with patch.object(es_mod, "MILVUS_AVAILABLE", True):
                with patch.object(es_mod, "MilvusStore", return_value=MagicMock()):
                    search = EmbeddingSearch(use_milvus=True, auto_download=False)
        assert search.is_ready is False
        # Milvus path must be turned off — otherwise every search would
        # hit the raise inside _get_embeddings.
        assert search._use_milvus is False
        assert search._milvus_store is None

    def test_is_ready_true_with_api(self):
        search = EmbeddingSearch(use_api=True, use_milvus=False, auto_download=False)
        assert search.is_ready is True

    def test_is_ready_true_with_local_model(self):
        search = _make_search(use_milvus=False)
        # helper installs a mock model.
        assert search.is_ready is True

    def test_search_returns_empty_when_not_ready(self):
        with patch.object(es_mod, "SENTENCE_TRANSFORMERS_AVAILABLE", False):
            with patch.object(es_mod, "MILVUS_AVAILABLE", False):
                search = EmbeddingSearch(use_milvus=False, auto_download=False)
        # search must NOT raise "No embedding model available" — return [].
        assert search.search("anything", top_k=5) == []

    def test_index_documents_noop_when_not_ready(self):
        with patch.object(es_mod, "SENTENCE_TRANSFORMERS_AVAILABLE", False):
            with patch.object(es_mod, "MILVUS_AVAILABLE", False):
                search = EmbeddingSearch(use_milvus=False, auto_download=False)
        # Must not raise, must not populate the in-memory arrays.
        search.index_documents(["doc"], [{"x": 1}])
        assert search._documents == []
        assert search._embeddings is None

    def test_model_load_failure_leaves_search_not_ready(self):
        # Simulate sentence-transformers installed but the download failed.
        fake_st = MagicMock(side_effect=RuntimeError("hf network"))
        with patch.object(es_mod, "SENTENCE_TRANSFORMERS_AVAILABLE", True):
            # ``SentenceTransformer`` symbol may not exist on the module
            # when the real import failed (this venv doesn't have it), so
            # inject it with ``create=True``.
            with patch.object(es_mod, "SentenceTransformer", fake_st, create=True):
                with patch.object(es_mod, "MILVUS_AVAILABLE", True):
                    with patch.object(es_mod, "MilvusStore", return_value=MagicMock()):
                        search = EmbeddingSearch(use_milvus=True, auto_download=True)
        assert search.is_ready is False
        assert search._use_milvus is False
