#!/usr/bin/env python3
"""Milvus Vector Store — 替代本地 FAISS 的向量数据库客户端.

提供对 Milvus 的封装，支持：
- Collection 管理（创建/删除/检查）
- 向量插入和批量导入
- 向量搜索（支持过滤条件）
- 索引管理

Usage:
    from finance_agent.retrieval.milvus_store import MilvusStore
    
    store = MilvusStore()
    store.create_collection("finance_docs", dim=1024)
    store.insert("finance_docs", vectors, texts, metas)
    results = store.search("finance_docs", query_vector, top_k=10)
"""
from __future__ import annotations

import json
import logging
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
        MilvusException,
    )
    PYMILVUS_AVAILABLE = True
except ImportError:
    PYMILVUS_AVAILABLE = False
    log.warning("pymilvus not installed. Milvus store will not be available.")


class MilvusStore:
    """Milvus vector store client."""

    DEFAULT_HOST = "localhost"
    DEFAULT_PORT = "19530"
    DEFAULT_COLLECTION = "finance_docs"

    def __init__(
        self,
        host: str | None = None,
        port: str | None = None,
        collection_name: str | None = None,
    ):
        """Initialize Milvus store.

        Args:
            host: Milvus server host
            port: Milvus server port
            collection_name: Default collection name
        """
        if not PYMILVUS_AVAILABLE:
            raise RuntimeError("pymilvus is required. Install with: pip install pymilvus>=2.4.0")

        self.host = host or self.DEFAULT_HOST
        self.port = port or self.DEFAULT_PORT
        self.collection_name = collection_name or self.DEFAULT_COLLECTION
        self._connected = False

    def _connect(self) -> None:
        """Connect to Milvus server."""
        if self._connected:
            return
        try:
            connections.connect(
                alias="default",
                host=self.host,
                port=self.port,
            )
            self._connected = True
            log.info("Connected to Milvus at %s:%s", self.host, self.port)
        except Exception as e:
            log.error("Failed to connect to Milvus: %s", e)
            raise

    def _ensure_connected(self) -> None:
        """Ensure connection is established."""
        if not self._connected:
            self._connect()

    def create_collection(
        self,
        collection_name: str | None = None,
        dim: int = 1024,
        metric_type: str = "COSINE",
        index_type: str = "IVF_FLAT",
        nlist: int = 128,
    ) -> Collection:
        """Create a Milvus collection for vector storage.

        Args:
            collection_name: Collection name
            dim: Vector dimension
            metric_type: Distance metric (COSINE, L2, IP)
            index_type: Index type (IVF_FLAT, IVF_SQ8, HNSW, etc.)
            nlist: Number of clusters for IVF index

        Returns:
            Milvus Collection object
        """
        self._ensure_connected()
        name = collection_name or self.collection_name

        if utility.has_collection(name):
            log.info("Collection '%s' already exists", name)
            return Collection(name)

        # Define fields
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="meta", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="source_kind", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="symbol", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]

        schema = CollectionSchema(fields, description="Finance Agent RAG Documents")
        collection = Collection(name, schema)

        # Create index
        index_params = {
            "index_type": index_type,
            "metric_type": metric_type,
            "params": {"nlist": nlist},
        }
        collection.create_index(field_name="embedding", index_params=index_params)
        log.info("Created collection '%s' with dim=%d, metric=%s", name, dim, metric_type)

        return collection

    def get_collection(self, collection_name: str | None = None) -> Collection:
        """Get existing collection.

        Args:
            collection_name: Collection name

        Returns:
            Milvus Collection object
        """
        self._ensure_connected()
        name = collection_name or self.collection_name

        if not utility.has_collection(name):
            raise ValueError(f"Collection '{name}' does not exist. Create it first.")

        collection = Collection(name)
        return collection

    def collection_exists(self, collection_name: str | None = None) -> bool:
        """Check if collection exists.

        Args:
            collection_name: Collection name

        Returns:
            True if collection exists
        """
        self._ensure_connected()
        name = collection_name or self.collection_name
        return utility.has_collection(name)

    def delete_collection(self, collection_name: str | None = None) -> None:
        """Delete a collection.

        Args:
            collection_name: Collection name
        """
        self._ensure_connected()
        name = collection_name or self.collection_name

        if utility.has_collection(name):
            utility.drop_collection(name)
            log.info("Dropped collection '%s'", name)

    def insert(
        self,
        texts: list[str],
        embeddings: np.ndarray | list[list[float]],
        metas: list[dict] | None = None,
        source_kinds: list[str] | None = None,
        symbols: list[str] | None = None,
        collection_name: str | None = None,
    ) -> None:
        """Insert documents into Milvus.

        Args:
            texts: List of text documents
            embeddings: Array of embeddings (n_docs x dim)
            metas: List of metadata dicts
            source_kinds: List of source kinds for each document
            symbols: List of stock symbols
            collection_name: Target collection name
        """
        self._ensure_connected()
        collection = self.get_collection(collection_name)

        n = len(texts)
        if n == 0:
            log.warning("No documents to insert")
            return

        # Prepare data
        metas = metas or [{} for _ in range(n)]
        source_kinds = source_kinds or ["unknown"] * n
        symbols = symbols or [""] * n

        # Convert embeddings to list of lists if numpy array
        if isinstance(embeddings, np.ndarray):
            embeddings = embeddings.tolist()

        # Prepare entities
        entities = [
            texts,
            [json.dumps(m, ensure_ascii=False) for m in metas],
            source_kinds,
            symbols,
            embeddings,
        ]

        collection.insert(entities)
        collection.flush()
        log.info("Inserted %d documents into '%s'", n, collection.name)

    def search(
        self,
        query_embedding: np.ndarray | list[float],
        top_k: int = 10,
        source_kinds: list[str] | None = None,
        symbols: list[str] | None = None,
        collection_name: str | None = None,
    ) -> list[tuple[str, float, dict]]:
        """Search for similar documents.

        Args:
            query_embedding: Query vector
            top_k: Number of results
            source_kinds: Filter by source kinds
            symbols: Filter by stock symbols
            collection_name: Collection name

        Returns:
            List of (text, score, meta) tuples
        """
        self._ensure_connected()
        collection = self.get_collection(collection_name)

        # Build filter expression
        expr = self._build_filter(source_kinds, symbols)

        # Search parameters
        search_params = {
            "metric_type": "COSINE",
            "params": {"nprobe": 128},
        }

        # Ensure query is list
        if isinstance(query_embedding, np.ndarray):
            query_embedding = query_embedding.tolist()

        # Load collection before search
        collection.load()

        results = collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["text", "meta", "source_kind", "symbol"],
        )

        # Parse results
        output = []
        for hits in results:
            for hit in hits:
                meta = json.loads(hit.entity.get("meta", "{}"))
                output.append((
                    hit.entity.get("text", ""),
                    float(hit.distance),
                    meta,
                ))

        return output

    def _build_filter(
        self,
        source_kinds: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> str | None:
        """Build Milvus filter expression."""
        conditions = []

        if source_kinds:
            kind_expr = " || ".join([f'source_kind == "{k}"' for k in source_kinds])
            conditions.append(f"({kind_expr})")

        if symbols:
            sym_expr = " || ".join([f'symbol == "{s}"' for s in symbols])
            conditions.append(f"({sym_expr})")

        if conditions:
            return " && ".join(conditions)
        return None

    def get_stats(self, collection_name: str | None = None) -> dict:
        """Get collection statistics.

        Args:
            collection_name: Collection name

        Returns:
            Dict with collection stats
        """
        self._ensure_connected()
        collection = self.get_collection(collection_name)
        return {
            "collection_name": collection.name,
            "num_entities": collection.num_entities,
        }

    def close(self) -> None:
        """Close connection to Milvus."""
        if self._connected:
            connections.disconnect("default")
            self._connected = False
            log.info("Disconnected from Milvus")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
