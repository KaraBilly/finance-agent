"""Tests for :mod:`finance_agent.retrieval.milvus_store`.

The tests inject a lightweight fake ``pymilvus`` module into ``sys.modules``
before importing ``milvus_store`` so they run regardless of whether the real
pymilvus wheel is installed in the venv. Individual tests replace the
module-level ``connections`` / ``utility`` / ``Collection`` symbols on a
per-test basis via monkeypatch.
"""
from __future__ import annotations

import importlib
import json
import sys
from types import ModuleType
from unittest.mock import MagicMock

import numpy as np
import pytest

# ---------------------------------------------------------------- test setup

def _install_fake_pymilvus() -> ModuleType:
    """Ensure ``pymilvus`` resolves to a mock so ``from pymilvus import ...``
    inside ``milvus_store`` succeeds. Returns the fake module."""
    fake = sys.modules.get("pymilvus")
    if fake is None or not getattr(fake, "_fa_test_fake", False):
        fake = ModuleType("pymilvus")
        fake._fa_test_fake = True  # marker
        # Names imported by milvus_store
        fake.Collection = MagicMock(name="Collection")
        fake.CollectionSchema = MagicMock(name="CollectionSchema")
        fake.DataType = MagicMock(name="DataType")
        # DataType.INT64 / VARCHAR / FLOAT_VECTOR — used only as sentinels
        fake.DataType.INT64 = "INT64"
        fake.DataType.VARCHAR = "VARCHAR"
        fake.DataType.FLOAT_VECTOR = "FLOAT_VECTOR"
        fake.FieldSchema = MagicMock(name="FieldSchema")
        fake.connections = MagicMock(name="connections")
        fake.utility = MagicMock(name="utility")
        sys.modules["pymilvus"] = fake
    return fake

_install_fake_pymilvus()

# Import (or reload) with the fake in place so PYMILVUS_AVAILABLE=True.
from finance_agent.retrieval import milvus_store as _ms  # noqa: E402
if not _ms.PYMILVUS_AVAILABLE:
    _ms = importlib.reload(_ms)

MilvusStore = _ms.MilvusStore

# ---------------------------------------------------------- pure functions

class TestTruncateBytes:
    def test_shorter_string_passes_through(self):
        assert _ms._truncate_bytes("hello", limit=100) == "hello"

    def test_ascii_boundary(self):
        s = "a" * 500
        out = _ms._truncate_bytes(s, limit=100)
        assert len(out) == 100
        assert out == "a" * 100

    def test_multibyte_utf8_never_produces_partial_codepoint(self):
        # Every CJK char is 3 bytes; a naive byte-slice at limit 4 would
        # split the second char. _truncate_bytes must decode cleanly.
        s = "中" * 10  # 30 bytes UTF-8
        out = _ms._truncate_bytes(s, limit=4)
        assert out == "中"
        # Round-trips as valid UTF-8.
        out.encode("utf-8")

    def test_empty_string_returns_empty(self):
        assert _ms._truncate_bytes("") == ""
        assert _ms._truncate_bytes(None) is None  # graceful with None

    def test_exact_boundary(self):
        s = "abc"
        out = _ms._truncate_bytes(s, limit=3)
        assert out == "abc"

class TestEscapeValue:
    def test_plain_value(self):
        assert MilvusStore._escape_value("AAPL") == "AAPL"

    def test_escapes_double_quote(self):
        # Injection guard: a ticker "MSFT\"; drop_collection " must not
        # terminate the string literal.
        assert MilvusStore._escape_value('MSFT"') == 'MSFT\\"'

    def test_escapes_backslash_before_quote(self):
        assert MilvusStore._escape_value('a\\b"c') == 'a\\\\b\\"c'

class TestBuildFilter:
    def _mk_store(self) -> "MilvusStore":
        s = MilvusStore(host="h", port="19530", collection_name="c")
        return s

    def test_no_filters_returns_none(self):
        s = self._mk_store()
        assert s._build_filter(None, None) is None
        assert s._build_filter([], []) is None

    def test_source_kinds_only(self):
        s = self._mk_store()
        expr = s._build_filter(source_kinds=["market", "filings"])
        assert expr == '(source_kind == "market" || source_kind == "filings")'

    def test_symbols_only(self):
        s = self._mk_store()
        expr = s._build_filter(symbols=["AAPL"])
        assert expr == '(symbol == "AAPL")'

    def test_both_are_conjoined(self):
        s = self._mk_store()
        expr = s._build_filter(source_kinds=["market"], symbols=["AAPL", "MSFT"])
        assert "source_kind" in expr and "symbol" in expr
        assert " && " in expr

    def test_symbol_with_quote_is_escaped(self):
        s = self._mk_store()
        expr = s._build_filter(symbols=['ABC"'])
        # The raw double quote must be escaped so it does not close the
        # Milvus string literal.
        assert '\\"' in expr

# ---------------------------------------------------------- entity helper

class TestEntityGet:
    def test_dict_like(self):
        e = {"text": "hello", "symbol": "AAPL"}
        assert _ms._entity_get(e, "text") == "hello"
        assert _ms._entity_get(e, "missing", "d") == "d"

    def test_attribute_proxy(self):
        class E:
            text = "hi"
        assert _ms._entity_get(E(), "text") == "hi"
        assert _ms._entity_get(E(), "missing", 42) == 42

    def test_none(self):
        assert _ms._entity_get(None, "x", "fallback") == "fallback"

# ---------------------------------------------------------- init / alias

class TestInit:
    def test_defaults(self):
        s = MilvusStore()
        assert s.host == MilvusStore.DEFAULT_HOST
        assert s.port == MilvusStore.DEFAULT_PORT
        assert s.collection_name == MilvusStore.DEFAULT_COLLECTION
        assert s.alias.startswith("fa_")
        assert not s._connected

    def test_two_instances_get_different_aliases(self):
        a = MilvusStore()
        b = MilvusStore()
        # Isolation: two stores in the same process must not share aliases,
        # otherwise closing one closes the other.
        assert a.alias != b.alias

    def test_explicit_alias(self):
        s = MilvusStore(alias="explicit")
        assert s.alias == "explicit"

# ---------------------------------------------------------- connect / close

class TestConnectClose:
    def test_connect_uses_own_alias(self, monkeypatch):
        conn = MagicMock()
        monkeypatch.setattr(_ms, "connections", conn)
        s = MilvusStore(host="h1", port="19530", alias="alpha")
        s._connect()
        conn.connect.assert_called_once_with(alias="alpha", host="h1", port="19530")
        assert s._connected

    def test_connect_is_idempotent(self, monkeypatch):
        conn = MagicMock()
        monkeypatch.setattr(_ms, "connections", conn)
        s = MilvusStore(alias="a")
        s._connect()
        s._connect()
        assert conn.connect.call_count == 1

    def test_close_disconnects_own_alias_only(self, monkeypatch):
        conn = MagicMock()
        monkeypatch.setattr(_ms, "connections", conn)
        s = MilvusStore(alias="my_alias")
        s._connected = True
        s.close()
        conn.disconnect.assert_called_once_with("my_alias")
        assert not s._connected

    def test_close_swallows_disconnect_error(self, monkeypatch):
        conn = MagicMock()
        conn.disconnect.side_effect = RuntimeError("boom")
        monkeypatch.setattr(_ms, "connections", conn)
        s = MilvusStore(alias="a")
        s._connected = True
        s.close()  # must not raise
        assert not s._connected

# ---------------------------------------------------------- insert validation

class TestInsertValidation:
    def _prepare(self, monkeypatch, n_existing: int = 0):
        """Wire up module-level stubs so a call into ``insert`` reaches
        ``get_collection`` and returns a mock collection."""
        conn = MagicMock()
        util = MagicMock()
        util.has_collection.return_value = True
        monkeypatch.setattr(_ms, "connections", conn)
        monkeypatch.setattr(_ms, "utility", util)
        coll_instance = MagicMock()
        coll_instance.name = "c"
        # Collection(name, using=alias) → coll_instance
        monkeypatch.setattr(_ms, "Collection", MagicMock(return_value=coll_instance))
        return coll_instance

    def test_empty_texts_no_op(self, monkeypatch):
        coll = self._prepare(monkeypatch)
        s = MilvusStore()
        s.insert(texts=[], embeddings=np.empty((0, 4)))
        coll.insert.assert_not_called()
        coll.flush.assert_not_called()

    def test_length_mismatch_raises(self, monkeypatch):
        self._prepare(monkeypatch)
        s = MilvusStore()
        with pytest.raises(ValueError, match="len\\(texts\\)"):
            s.insert(texts=["a", "b"], embeddings=np.zeros((3, 4)))

    def test_meta_length_mismatch_raises(self, monkeypatch):
        self._prepare(monkeypatch)
        s = MilvusStore()
        with pytest.raises(ValueError, match="metadata length mismatch"):
            s.insert(
                texts=["a", "b"],
                embeddings=np.zeros((2, 4)),
                metas=[{"x": 1}],  # only 1 meta for 2 texts
            )

    def test_batches_large_insert(self, monkeypatch):
        coll = self._prepare(monkeypatch)
        s = MilvusStore()
        n = 1050
        s.insert(
            texts=[f"doc {i}" for i in range(n)],
            embeddings=np.zeros((n, 4)),
            batch_size=500,
        )
        # 1050 rows / 500 batch = 3 insert calls.
        assert coll.insert.call_count == 3
        coll.flush.assert_called_once()

    def test_meta_serialized_as_json(self, monkeypatch):
        coll = self._prepare(monkeypatch)
        s = MilvusStore()
        s.insert(
            texts=["hello"],
            embeddings=np.zeros((1, 4)),
            metas=[{"foo": "bar", "n": 1}],
            source_kinds=["market"],
            symbols=["AAPL"],
        )
        entities = coll.insert.call_args.args[0]
        # entities: [texts, metas_json, kinds, symbols, embeddings]
        assert entities[0] == ["hello"]
        meta_str = entities[1][0]
        assert json.loads(meta_str) == {"foo": "bar", "n": 1}
        assert entities[2] == ["market"]
        assert entities[3] == ["AAPL"]

    def test_text_truncated_when_exceeds_varchar(self, monkeypatch):
        coll = self._prepare(monkeypatch)
        s = MilvusStore()
        big = "a" * (_ms._VARCHAR_SAFE_BYTES + 5000)
        s.insert(
            texts=[big],
            embeddings=np.zeros((1, 4)),
        )
        stored_text = coll.insert.call_args.args[0][0][0]
        # Bytes-length capped at _VARCHAR_SAFE_BYTES.
        assert len(stored_text.encode("utf-8")) <= _ms._VARCHAR_SAFE_BYTES

# ---------------------------------------------------------- search integration

class TestSearch:
    def test_search_uses_stored_metric(self, monkeypatch):
        conn = MagicMock()
        util = MagicMock()
        util.has_collection.return_value = True
        monkeypatch.setattr(_ms, "connections", conn)
        monkeypatch.setattr(_ms, "utility", util)

        coll_instance = MagicMock()
        coll_instance.name = "c"
        coll_instance.indexes = []  # no index → falls back to cached / default
        # Build a fake search return: list-of-lists of hits.
        hit = MagicMock()
        hit.distance = 0.42

        class Entity:
            def get(self, key, default=""):
                return {
                    "text": "hello",
                    "meta": '{"foo": "bar"}',
                    "source_kind": "market",
                    "symbol": "AAPL",
                }.get(key, default)
        hit.entity = Entity()
        coll_instance.search.return_value = [[hit]]
        monkeypatch.setattr(_ms, "Collection", MagicMock(return_value=coll_instance))

        s = MilvusStore()
        s._metric_by_collection["c"] = "L2"  # simulate collection uses L2
        results = s.search(query_embedding=np.zeros(4), top_k=5)

        # Search was invoked with L2, NOT the hardcoded COSINE.
        call_kwargs = coll_instance.search.call_args.kwargs
        assert call_kwargs["param"]["metric_type"] == "L2"

        assert len(results) == 1
        text, score, meta = results[0]
        assert text == "hello"
        assert score == pytest.approx(0.42)
        # source_kind + symbol propagated into meta.
        assert meta["symbol"] == "AAPL"
        assert meta["source_kind"] == "market"
        assert meta["sourceKind"] == "market"
        assert meta["foo"] == "bar"

    def test_search_handles_malformed_meta_json(self, monkeypatch):
        util = MagicMock()
        util.has_collection.return_value = True
        monkeypatch.setattr(_ms, "connections", MagicMock())
        monkeypatch.setattr(_ms, "utility", util)

        coll_instance = MagicMock()
        coll_instance.name = "c"
        coll_instance.indexes = []
        hit = MagicMock()
        hit.distance = 1.0

        class E:
            def get(self, key, default=""):
                return {"text": "t", "meta": "not-json", "source_kind": "web", "symbol": ""}.get(key, default)
        hit.entity = E()
        coll_instance.search.return_value = [[hit]]
        monkeypatch.setattr(_ms, "Collection", MagicMock(return_value=coll_instance))

        s = MilvusStore()
        results = s.search(query_embedding=[0.0] * 4, top_k=1)
        # Falls back to empty dict + source_kind promotion.
        assert results[0][2]["source_kind"] == "web"
