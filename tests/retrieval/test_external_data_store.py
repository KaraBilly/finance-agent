"""Tests for the Milvus-related plumbing in ``ExternalDataStore``.

Focus on the two regressions fixed alongside the Milvus integration:
1. Constructor now respects ``CONFIG.use_milvus`` when the caller passes
   ``use_milvus=None``.
2. The merge in ``search`` no longer silently drops Milvus hits whose
   text is not present in the in-memory candidate list.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from finance_agent.retrieval import external_data_store as eds_mod
from finance_agent.retrieval.external_data_store import ExternalDataStore

# ---------------------------------------------------------------- config

class TestUseMilvusResolution:
    def _make(self, **kwargs) -> ExternalDataStore:
        """Build a store with the heavy embedding path disabled so the
        constructor doesn't try to talk to Milvus / download a model."""
        return ExternalDataStore(use_embedding=False, **kwargs)

    def test_explicit_true_overrides_config(self):
        with patch.object(eds_mod, "__name__", eds_mod.__name__):
            with patch("finance_agent.config.CONFIG") as cfg:
                cfg.use_milvus = False
                cfg.use_external_data = False
                cfg.external_market_dir = None
                cfg.external_financials_dir = None
                cfg.external_filings_dir = None
                cfg.data_dir = MagicMock()
                store = self._make(use_milvus=True)
        assert store.use_milvus is True

    def test_explicit_false_overrides_config(self):
        with patch("finance_agent.config.CONFIG") as cfg:
            cfg.use_milvus = True
            cfg.use_external_data = False
            cfg.external_market_dir = None
            cfg.external_financials_dir = None
            cfg.external_filings_dir = None
            cfg.data_dir = MagicMock()
            store = self._make(use_milvus=False)
        assert store.use_milvus is False

    def test_none_defers_to_config_true(self):
        with patch("finance_agent.config.CONFIG") as cfg:
            cfg.use_milvus = True
            cfg.use_external_data = False
            cfg.external_market_dir = None
            cfg.external_financials_dir = None
            cfg.external_filings_dir = None
            cfg.data_dir = MagicMock()
            store = self._make(use_milvus=None)
        assert store.use_milvus is True

    def test_none_defers_to_config_false(self):
        with patch("finance_agent.config.CONFIG") as cfg:
            cfg.use_milvus = False
            cfg.use_external_data = False
            cfg.external_market_dir = None
            cfg.external_financials_dir = None
            cfg.external_filings_dir = None
            cfg.data_dir = MagicMock()
            store = self._make(use_milvus=None)
        assert store.use_milvus is False

# ---------------------------------------------------------------- merge

class TestSearchMergesMilvusHits:
    """The merge logic in ``ExternalDataStore.search`` was silently dropping
    Milvus results whose text was not also present in the local candidate
    list. Verify each Milvus hit lands in the Evidence output."""

    def _make(self, docs, embedding_hits):
        # Force the CONFIG-touching branch to a benign state, then build.
        with patch("finance_agent.config.CONFIG") as cfg:
            cfg.use_milvus = False  # skip real Milvus init
            cfg.use_external_data = True
            cfg.external_market_dir = None
            cfg.external_financials_dir = None
            cfg.external_filings_dir = None
            cfg.data_dir = MagicMock()
            store = ExternalDataStore(use_embedding=False)
        # Directly install the pre-loaded corpus and a fake embedding search.
        store._loaded = True
        store._docs = docs
        store.use_embedding = True
        emb = MagicMock()
        emb.search.return_value = embedding_hits
        store._embedding_search = emb
        return store

    def test_milvus_only_hit_survives_merge(self):
        # In-memory corpus contains only one doc, BM25 picks it up.
        docs = [("local-doc", {"symbol": "AAPL"}, "market")]
        # Milvus returns an unrelated hit that is NOT in the local corpus.
        # Pre-fix: this got silently discarded. Post-fix: it must appear.
        embedding_hits = [
            (
                "milvus-only-doc",
                0.9,
                {"symbol": "MSFT", "source_kind": "filings"},
            )
        ]
        store = self._make(docs, embedding_hits)

        evidences = store.search("query", final_top=10)

        texts = [e.text for e in evidences]
        assert "local-doc" in texts
        assert "milvus-only-doc" in texts
        # source_kind must survive the merge for downstream Evidence.
        milvus_ev = next(e for e in evidences if e.text == "milvus-only-doc")
        assert milvus_ev.source_kind == "filings"

    def test_duplicate_milvus_hit_deduped(self):
        docs = [("shared-doc", {"symbol": "AAPL"}, "market")]
        embedding_hits = [
            ("shared-doc", 0.9, {"symbol": "AAPL", "source_kind": "market"})
        ]
        store = self._make(docs, embedding_hits)
        evidences = store.search("query", final_top=10)
        # Shared text must appear exactly once.
        assert sum(1 for e in evidences if e.text == "shared-doc") == 1

    def test_milvus_hit_with_missing_source_kind_defaults_to_unknown(self):
        docs = [("local-doc", {"symbol": "AAPL"}, "market")]
        embedding_hits = [
            # No source_kind / sourceKind — pre-fix would have KeyError'd
            # inside the merge; must now default to "unknown".
            ("stray-doc", 0.5, {"symbol": "UNK"})
        ]
        store = self._make(docs, embedding_hits)
        evidences = store.search("query", final_top=10)
        stray = next((e for e in evidences if e.text == "stray-doc"), None)
        assert stray is not None
        assert stray.source_kind == "unknown"

    def test_empty_milvus_hits_leaves_bm25_only(self):
        docs = [("only", {"symbol": "AAPL"}, "market")]
        store = self._make(docs, [])
        evidences = store.search("query", final_top=10)
        assert len(evidences) == 1
        assert evidences[0].text == "only"

    def test_milvus_search_failure_does_not_crash(self):
        docs = [("local", {"symbol": "AAPL"}, "market")]
        store = self._make(docs, [])
        # Overwrite the embedding search to raise.
        store._embedding_search.search.side_effect = RuntimeError("net")
        evidences = store.search("query", final_top=10)
        # BM25 results must still come back even if Milvus search dies.
        assert len(evidences) == 1
        assert evidences[0].text == "local"


class TestEmbedderReadinessGate:
    """Regression: when the embedder isn't ready (sentence-transformers not
    installed, model download failed), ``ExternalDataStore.__init__`` must
    disable ``use_embedding`` instead of leaving a broken embedder in place
    that would raise ``No embedding model available`` on every search.
    """

    def test_unready_embedder_disables_embedding_path(self):
        with patch("finance_agent.config.CONFIG") as cfg:
            cfg.use_milvus = False
            cfg.use_external_data = False
            cfg.external_market_dir = None
            cfg.external_financials_dir = None
            cfg.external_filings_dir = None
            cfg.data_dir = MagicMock()

            # Return an EmbeddingSearch look-alike that reports is_ready=False.
            fake_emb = MagicMock()
            fake_emb.is_ready = False
            with patch(
                "finance_agent.retrieval.embedding_search.EmbeddingSearch",
                return_value=fake_emb,
            ):
                store = ExternalDataStore(use_embedding=True)

        # Broken embedder must be dropped so search() doesn't hit the
        # "No embedding model available" RuntimeError on every call.
        assert store.use_embedding is False
        assert store._embedding_search is None

    def test_ready_embedder_is_retained(self):
        with patch("finance_agent.config.CONFIG") as cfg:
            cfg.use_milvus = False
            cfg.use_external_data = False
            cfg.external_market_dir = None
            cfg.external_financials_dir = None
            cfg.external_filings_dir = None
            cfg.data_dir = MagicMock()

            fake_emb = MagicMock()
            fake_emb.is_ready = True
            with patch(
                "finance_agent.retrieval.embedding_search.EmbeddingSearch",
                return_value=fake_emb,
            ):
                store = ExternalDataStore(use_embedding=True)

        assert store.use_embedding is True
        assert store._embedding_search is fake_emb
