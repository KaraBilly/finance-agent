"""Milvus Vector Store — 替代本地 FAISS 的向量数据库客户端.

提供对 Milvus 的封装,支持:
- Collection 管理(创建/删除/检查)
- 向量插入和批量导入
- 向量搜索(支持过滤条件)
- 索引管理

Usage:
    from finance_agent.retrieval.milvus_store import MilvusStore

    store = MilvusStore()
    store.create_collection("finance_docs", dim=1024)
    store.insert(texts, embeddings, metas)
    results = store.search(query_vector, top_k=10)
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

try:
    from pymilvus import (
        Collection,
        CollectionSchema,
        DataType,
        FieldSchema,
        connections,
        utility,
    )
    PYMILVUS_AVAILABLE = True
except ImportError:
    PYMILVUS_AVAILABLE = False
    log.warning("pymilvus not installed. Milvus store will not be available.")

# Milvus VARCHAR fields are limited to 65535 bytes (not chars). Use bytes to
# be conservative — Chinese chars take 3 bytes in UTF-8.
_VARCHAR_MAX_BYTES = 65535
# Reserve a bit so we never hit the exact boundary.
_VARCHAR_SAFE_BYTES = 60000

# Milvus insert has practical per-request limits (~10 MB / 10k rows). Chunk
# large inserts so a single call doesn't OOM the server or time out.
_INSERT_BATCH = 500

def _truncate_bytes(s: str, limit: int = _VARCHAR_SAFE_BYTES) -> str:
    """Truncate a string so its UTF-8 encoding fits within ``limit`` bytes.

    Decoding with ``errors="ignore"`` drops any partial multi-byte codepoint
    at the boundary, guaranteeing valid UTF-8 output.
    """
    if not s:
        return s
    encoded = s.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return s
    return encoded[:limit].decode("utf-8", errors="ignore")

class MilvusStore:
    """Milvus vector store client.

    Each instance owns its own pymilvus connection alias so multiple stores
    (pointing at different hosts, or created by different subsystems) do not
    stomp on each other's global ``"default"`` connection.
    """

    DEFAULT_HOST = "localhost"
    DEFAULT_PORT = "19530"
    DEFAULT_COLLECTION = "finance_docs"

    def __init__(
        self,
        host: str | None = None,
        port: str | None = None,
        collection_name: str | None = None,
        *,
        alias: str | None = None,
    ):
        """Initialize Milvus store.

        Args:
            host: Milvus server host.
            port: Milvus server port.
            collection_name: Default collection name.
            alias: pymilvus connection alias. If ``None``, generate a unique
                one so this instance's connection cannot be closed by another
                caller that happens to own ``"default"``.
        """
        if not PYMILVUS_AVAILABLE:
            raise RuntimeError("pymilvus is required. Install with: pip install pymilvus>=2.4.0")

        self.host = host or self.DEFAULT_HOST
        self.port = port or self.DEFAULT_PORT
        self.collection_name = collection_name or self.DEFAULT_COLLECTION
        # Unique alias per instance keeps connection state isolated.
        self.alias = alias or f"fa_{uuid.uuid4().hex[:8]}"
        self._connected = False
        # Cache metric type per collection so ``search`` doesn't have to
        # guess — using the wrong metric silently returns junk results.
        self._metric_by_collection: dict[str, str] = {}

    # ---------------------------------------------------------- connection

    def _connect(self) -> None:
        if self._connected:
            return
        try:
            connections.connect(
                alias=self.alias,
                host=self.host,
                port=self.port,
            )
            self._connected = True
            log.info("Connected to Milvus at %s:%s (alias=%s)", self.host, self.port, self.alias)
        except Exception as e:
            log.error("Failed to connect to Milvus: %s", e)
            raise

    def _ensure_connected(self) -> None:
        if not self._connected:
            self._connect()

    # ---------------------------------------------------------- collection

    def create_collection(
        self,
        collection_name: str | None = None,
        dim: int = 1024,
        metric_type: str = "COSINE",
        index_type: str = "IVF_FLAT",
        nlist: int = 128,
    ) -> "Collection":
        """Create a Milvus collection for vector storage."""
        self._ensure_connected()
        name = collection_name or self.collection_name

        if utility.has_collection(name, using=self.alias):
            log.info("Collection '%s' already exists", name)
            existing = Collection(name, using=self.alias)
            # Read metric type from an existing vector index if present so
            # subsequent searches use the correct metric.
            self._metric_by_collection[name] = self._read_metric(existing) or metric_type
            return existing

        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=_VARCHAR_MAX_BYTES),
            FieldSchema(name="meta", dtype=DataType.VARCHAR, max_length=_VARCHAR_MAX_BYTES),
            FieldSchema(name="source_kind", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="symbol", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields, description="Finance Agent RAG Documents")
        collection = Collection(name, schema, using=self.alias)

        index_params = {
            "index_type": index_type,
            "metric_type": metric_type,
            "params": {"nlist": nlist},
        }
        collection.create_index(field_name="embedding", index_params=index_params)
        self._metric_by_collection[name] = metric_type
        log.info("Created collection '%s' with dim=%d, metric=%s", name, dim, metric_type)
        return collection

    @staticmethod
    def _read_metric(collection: "Collection") -> str | None:
        """Best-effort read of the vector index's metric_type."""
        try:
            for idx in getattr(collection, "indexes", []) or []:
                params = getattr(idx, "params", None) or {}
                metric = params.get("metric_type")
                if metric:
                    return metric
        except Exception as e:
            log.debug("Failed to read metric from collection index: %s", e)
        return None

    def get_collection(self, collection_name: str | None = None) -> "Collection":
        self._ensure_connected()
        name = collection_name or self.collection_name
        if not utility.has_collection(name, using=self.alias):
            raise ValueError(f"Collection '{name}' does not exist. Create it first.")
        return Collection(name, using=self.alias)

    def collection_exists(self, collection_name: str | None = None) -> bool:
        self._ensure_connected()
        name = collection_name or self.collection_name
        return utility.has_collection(name, using=self.alias)

    def delete_collection(self, collection_name: str | None = None) -> None:
        self._ensure_connected()
        name = collection_name or self.collection_name
        if utility.has_collection(name, using=self.alias):
            utility.drop_collection(name, using=self.alias)
            self._metric_by_collection.pop(name, None)
            log.info("Dropped collection '%s'", name)

    # ---------------------------------------------------------- write path

    def insert(
        self,
        texts: list[str],
        embeddings: np.ndarray | list[list[float]],
        metas: list[dict] | None = None,
        source_kinds: list[str] | None = None,
        symbols: list[str] | None = None,
        collection_name: str | None = None,
        batch_size: int = _INSERT_BATCH,
    ) -> None:
        """Insert documents into Milvus in batches.

        Raises ``ValueError`` on length mismatch between parallel arrays
        rather than letting the server reject the batch with an opaque
        error.
        """
        self._ensure_connected()
        collection = self.get_collection(collection_name)

        n = len(texts)
        if n == 0:
            log.warning("No documents to insert")
            return

        # Materialize once so we can validate + slice.
        if isinstance(embeddings, np.ndarray):
            embeddings_list = embeddings.tolist()
        else:
            embeddings_list = list(embeddings)

        if len(embeddings_list) != n:
            raise ValueError(
                f"insert: len(texts)={n} != len(embeddings)={len(embeddings_list)}"
            )

        metas = metas or [{} for _ in range(n)]
        source_kinds = source_kinds or ["unknown"] * n
        symbols = symbols or [""] * n

        if len(metas) != n or len(source_kinds) != n or len(symbols) != n:
            raise ValueError(
                f"insert: metadata length mismatch (texts={n}, "
                f"metas={len(metas)}, source_kinds={len(source_kinds)}, "
                f"symbols={len(symbols)})"
            )

        # Guard against silent server-side rejection by clipping the
        # VARCHAR-bound fields ourselves.
        safe_texts = [_truncate_bytes(t or "") for t in texts]
        safe_metas_json = [
            _truncate_bytes(json.dumps(m or {}, ensure_ascii=False)) for m in metas
        ]
        safe_kinds = [_truncate_bytes(k or "unknown", limit=127) for k in source_kinds]
        safe_symbols = [_truncate_bytes(s or "", limit=31) for s in symbols]

        # Chunked insert — one huge insert can hit Milvus per-request
        # limits (~10 MB) or trigger long GC pauses.
        for start in range(0, n, batch_size):
            end = min(start + batch_size, n)
            entities = [
                safe_texts[start:end],
                safe_metas_json[start:end],
                safe_kinds[start:end],
                safe_symbols[start:end],
                embeddings_list[start:end],
            ]
            collection.insert(entities)

        collection.flush()
        log.info("Inserted %d documents into '%s' (batch=%d)", n, collection.name, batch_size)

    # ---------------------------------------------------------- read path

    def search(
        self,
        query_embedding: np.ndarray | list[float],
        top_k: int = 10,
        source_kinds: list[str] | None = None,
        symbols: list[str] | None = None,
        collection_name: str | None = None,
    ) -> list[tuple[str, float, dict]]:
        """Search for similar documents.

        Returns:
            List of ``(text, score, meta)`` tuples. ``meta`` always contains
            the persisted ``sourceKind``/``source_kind`` and ``symbol``
            fields so callers can reconstruct evidence downstream.
        """
        self._ensure_connected()
        collection = self.get_collection(collection_name)

        expr = self._build_filter(source_kinds, symbols)

        # Use the collection's actual metric — hardcoding "COSINE" against
        # an L2 index silently returns garbage.
        metric = (
            self._metric_by_collection.get(collection.name)
            or self._read_metric(collection)
            or "COSINE"
        )
        self._metric_by_collection[collection.name] = metric

        search_params = {
            "metric_type": metric,
            "params": {"nprobe": 128},
        }

        if isinstance(query_embedding, np.ndarray):
            query_embedding = query_embedding.tolist()

        collection.load()

        results = collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["text", "meta", "source_kind", "symbol"],
        )

        output: list[tuple[str, float, dict]] = []
        for hits in results:
            for hit in hits:
                entity = hit.entity
                raw_meta = _entity_get(entity, "meta", "{}") or "{}"
                try:
                    meta = json.loads(raw_meta) if raw_meta else {}
                except (json.JSONDecodeError, TypeError):
                    meta = {}
                sk = _entity_get(entity, "source_kind", "")
                sym = _entity_get(entity, "symbol", "")
                # Preserve source classification for downstream Evidence.
                meta.setdefault("sourceKind", sk)
                meta.setdefault("source_kind", sk)
                meta.setdefault("symbol", sym)
                text = _entity_get(entity, "text", "")
                output.append((text, float(hit.distance), meta))

        return output

    @staticmethod
    def _escape_value(value: str) -> str:
        """Escape a string literal for a Milvus boolean expression.

        Milvus expressions use double-quoted string literals; a stray ``"``
        in the value would either break parsing or (worse) allow expression
        injection. Escape backslashes first, then quotes.
        """
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _build_filter(
        self,
        source_kinds: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> str | None:
        """Build Milvus filter expression."""
        conditions: list[str] = []

        if source_kinds:
            kind_expr = " || ".join(
                f'source_kind == "{self._escape_value(k)}"' for k in source_kinds
            )
            conditions.append(f"({kind_expr})")

        if symbols:
            sym_expr = " || ".join(
                f'symbol == "{self._escape_value(s)}"' for s in symbols
            )
            conditions.append(f"({sym_expr})")

        if conditions:
            return " && ".join(conditions)
        return None

    def get_stats(self, collection_name: str | None = None) -> dict:
        self._ensure_connected()
        collection = self.get_collection(collection_name)
        return {
            "collection_name": collection.name,
            "num_entities": collection.num_entities,
        }

    def close(self) -> None:
        """Close this instance's connection.

        Uses the per-instance alias so we never disconnect other MilvusStore
        instances that happen to share the process.
        """
        if self._connected:
            try:
                connections.disconnect(self.alias)
            except Exception as e:
                log.debug("Milvus disconnect(%s) failed: %s", self.alias, e)
            self._connected = False
            log.info("Disconnected from Milvus (alias=%s)", self.alias)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

def _entity_get(entity: Any, key: str, default: Any = None) -> Any:
    """Read a field off a Milvus hit's entity.

    pymilvus versions vary between exposing ``entity`` as a dict-like object
    (with ``.get``) and as an attribute proxy. Handle both.
    """
    if entity is None:
        return default
    if hasattr(entity, "get"):
        try:
            return entity.get(key, default)
        except TypeError:
            pass
    return getattr(entity, key, default)
