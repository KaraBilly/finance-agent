"""Embedding-based semantic search for RAG.

Provides embedding-based retrieval as an alternative/complement to BM25.
Uses sentence-transformers for local embeddings or API-based embeddings.

Usage:
    from finance_agent.retrieval.embedding_search import EmbeddingSearch
    
    search = EmbeddingSearch()
    search.index_documents(docs)
    results = search.search(query, top_k=10)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# Try to import sentence-transformers
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    log.warning("sentence-transformers not installed. Embedding search will use fallback.")

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    log.warning("faiss not installed. Will use numpy for similarity search.")


class EmbeddingSearch:
    """Embedding-based semantic search.
    
    Supports multiple embedding models:
    - Local: sentence-transformers (all-MiniLM-L6-v2, etc.)
    - API: OpenAI, Doubao, etc.
    """
    
    def __init__(
        self,
        model_name: str | None = None,
        use_api: bool = False,
        api_key: str | None = None,
        cache_dir: Path | None = None,
        auto_download: bool = True,
    ):
        """Initialize embedding search.
        
        Args:
            model_name: Model name for embeddings
                - Local: "all-MiniLM-L6-v2", "BAAI/bge-large-zh-v1.5", etc.
                - API: "text-embedding-3-small", etc.
            use_api: Whether to use API for embeddings
            api_key: API key for embedding service
            cache_dir: Directory to cache embeddings
            auto_download: Whether to auto-download model if not found
        """
        self.model_name = model_name or "BAAI/bge-large-zh-v1.5"
        self.use_api = use_api
        self.api_key = api_key
        self.cache_dir = cache_dir
        
        self._model = None
        self._embeddings: np.ndarray | None = None
        self._documents: list[str] = []
        self._metas: list[dict] = []
        self._faiss_index = None
        
        if not use_api and SENTENCE_TRANSFORMERS_AVAILABLE:
            if auto_download:
                self._download_and_load_model()
            else:
                self._load_local_model()
    
    def _download_and_load_model(self):
        """Download and load embedding model."""
        try:
            log.info(f"Downloading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
            log.info(f"Embedding model downloaded and loaded successfully")
        except Exception as e:
            log.error(f"Failed to download embedding model: {e}")
            self._model = None
    
    def _load_local_model(self):
        """Load local embedding model."""
        try:
            log.info(f"Loading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
            log.info(f"Embedding model loaded successfully")
        except Exception as e:
            log.error(f"Failed to load embedding model: {e}")
            self._model = None
    
    def _get_embeddings(self, texts: list[str]) -> np.ndarray:
        """Get embeddings for texts.
        
        Returns:
            numpy array of shape (len(texts), embedding_dim)
        """
        if self.use_api:
            return self._get_api_embeddings(texts)
        elif self._model is not None:
            return self._model.encode(texts, show_progress_bar=False)
        else:
            raise RuntimeError("No embedding model available")
    
    def _get_api_embeddings(self, texts: list[str]) -> np.ndarray:
        """Get embeddings via API (OpenAI, Doubao, etc.)."""
        # TODO: Implement API-based embeddings
        # For now, raise an error
        raise NotImplementedError("API embeddings not yet implemented")
    
    def index_documents(self, documents: list[str], metas: list[dict] | None = None):
        """Index documents for search.
        
        Args:
            documents: List of text documents
            metas: Optional metadata for each document
        """
        if not documents:
            log.warning("No documents to index")
            return
        
        self._documents = documents
        self._metas = metas or [{} for _ in documents]
        
        # Compute embeddings
        log.info(f"Computing embeddings for {len(documents)} documents...")
        self._embeddings = self._get_embeddings(documents)
        
        # Build FAISS index if available
        if FAISS_AVAILABLE and self._embeddings is not None:
            self._build_faiss_index()
        
        log.info(f"Indexed {len(documents)} documents")
    
    def _build_faiss_index(self):
        """Build FAISS index for fast similarity search."""
        if not FAISS_AVAILABLE or self._embeddings is None:
            return
        
        embedding_dim = self._embeddings.shape[1]
        
        # Use IndexFlatIP for cosine similarity (after normalization)
        # or IndexFlatL2 for Euclidean distance
        self._faiss_index = faiss.IndexFlatIP(embedding_dim)
        
        # Normalize embeddings for cosine similarity
        faiss.normalize_L2(self._embeddings)
        
        # Add embeddings to index
        self._faiss_index.add(self._embeddings)
        
        log.info(f"FAISS index built with {len(self._documents)} documents")
    
    def search(
        self,
        query: str,
        top_k: int = 10,
        filter_fn: callable | None = None,
    ) -> list[tuple[str, float, dict]]:
        """Search for similar documents.
        
        Args:
            query: Search query
            top_k: Number of results to return
            filter_fn: Optional filter function (doc_text, meta) -> bool
        
        Returns:
            List of (document, score, meta) tuples
        """
        if self._embeddings is None or len(self._documents) == 0:
            log.warning("No documents indexed")
            return []
        
        # Get query embedding
        query_embedding = self._get_embeddings([query])
        
        # Search
        if self._faiss_index is not None and FAISS_AVAILABLE:
            # FAISS search
            faiss.normalize_L2(query_embedding)
            scores, indices = self._faiss_index.search(query_embedding, top_k * 2)
            
            results = []
            for idx, score in zip(indices[0], scores[0]):
                if idx < 0 or idx >= len(self._documents):
                    continue
                
                doc = self._documents[idx]
                meta = self._metas[idx]
                
                # Apply filter
                if filter_fn is not None and not filter_fn(doc, meta):
                    continue
                
                results.append((doc, float(score), meta))
                
                if len(results) >= top_k:
                    break
            
            return results
        else:
            # Fallback to numpy cosine similarity
            return self._numpy_search(query_embedding[0], top_k, filter_fn)
    
    def _numpy_search(
        self,
        query_embedding: np.ndarray,
        top_k: int,
        filter_fn: callable | None = None,
    ) -> list[tuple[str, float, dict]]:
        """Fallback search using numpy."""
        # Normalize query
        query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-8)
        
        # Compute cosine similarities
        similarities = np.dot(self._embeddings, query_norm)
        
        # Get top-k indices
        top_indices = np.argsort(similarities)[::-1]
        
        results = []
        for idx in top_indices:
            doc = self._documents[idx]
            meta = self._metas[idx]
            
            # Apply filter
            if filter_fn is not None and not filter_fn(doc, meta):
                continue
            
            results.append((doc, float(similarities[idx]), meta))
            
            if len(results) >= top_k:
                break
        
        return results
    
    def hybrid_search(
        self,
        query: str,
        bm25_results: list[tuple[int, float]],
        top_k: int = 10,
        bm25_weight: float = 0.3,
        embedding_weight: float = 0.7,
    ) -> list[tuple[str, float, dict]]:
        """Hybrid search combining BM25 and embedding scores.
        
        Args:
            query: Search query
            bm25_results: BM25 results as list of (doc_index, bm25_score)
            top_k: Number of results to return
            bm25_weight: Weight for BM25 scores
            embedding_weight: Weight for embedding scores
        
        Returns:
            List of (document, combined_score, meta) tuples
        """
        if self._embeddings is None:
            # Fallback to BM25 only
            return [
                (self._documents[idx], score, self._metas[idx])
                for idx, score in bm25_results[:top_k]
                if 0 <= idx < len(self._documents)
            ]
        
        # Get query embedding
        query_embedding = self._get_embeddings([query])
        query_norm = query_embedding[0] / (np.linalg.norm(query_embedding[0]) + 1e-8)
        
        # Compute embedding scores for all documents
        embedding_scores = np.dot(self._embeddings, query_norm)
        
        # Normalize scores
        bm25_dict = {idx: score for idx, score in bm25_results}
        
        # Combine scores
        combined_scores = {}
        for idx in range(len(self._documents)):
            bm25_score = bm25_dict.get(idx, 0)
            emb_score = embedding_scores[idx]
            
            # Normalize to [0, 1]
            bm25_norm = min(1.0, bm25_score / 10.0)  # BM25 scores can be large
            emb_norm = (emb_score + 1) / 2  # Cosine similarity is [-1, 1]
            
            combined = bm25_weight * bm25_norm + embedding_weight * emb_norm
            combined_scores[idx] = combined
        
        # Get top-k
        top_indices = sorted(combined_scores.keys(), key=lambda x: -combined_scores[x])
        
        results = []
        for idx in top_indices[:top_k]:
            results.append((
                self._documents[idx],
                combined_scores[idx],
                self._metas[idx]
            ))
        
        return results
    
    def save_index(self, path: Path):
        """Save index to disk."""
        if self._embeddings is None:
            log.warning("No index to save")
            return
        
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save embeddings
        np.save(path.with_suffix(".npy"), self._embeddings)
        
        # Save documents and metadata
        import json
        with open(path.with_suffix(".json"), "w", encoding="utf-8") as f:
            json.dump({
                "documents": self._documents,
                "metas": self._metas,
            }, f, ensure_ascii=False)
        
        log.info(f"Index saved to {path}")
    
    def load_index(self, path: Path):
        """Load index from disk."""
        path = Path(path)
        
        # Load embeddings
        self._embeddings = np.load(path.with_suffix(".npy"))
        
        # Load documents and metadata
        import json
        with open(path.with_suffix(".json"), "r", encoding="utf-8") as f:
            data = json.load(f)
            self._documents = data["documents"]
            self._metas = data["metas"]
        
        # Rebuild FAISS index
        if FAISS_AVAILABLE:
            self._build_faiss_index()
        
        log.info(f"Index loaded from {path}")


def test_embedding_search():
    """Test embedding search functionality."""
    print("Testing Embedding Search...")
    
    # Sample documents
    docs = [
        "比亚迪2024年第三季度营收增长15%，净利润达到100亿元",
        "特斯拉Q3财报：电动车销量创新高，毛利率下降",
        "宁德时代发布2024年报：电池出货量全球第一",
        "比亚迪股价今日上涨5%，创年内新高",
        "新能源汽车行业2024年发展报告",
    ]
    
    metas = [
        {"symbol": "002594", "type": "financials"},
        {"symbol": "TSLA", "type": "financials"},
        {"symbol": "300750", "type": "financials"},
        {"symbol": "002594", "type": "market"},
        {"symbol": "行业", "type": "report"},
    ]
    
    # Initialize search
    search = EmbeddingSearch(model_name="all-MiniLM-L6-v2")
    search.index_documents(docs, metas)
    
    # Test queries
    queries = [
        "比亚迪财报",
        "特斯拉业绩",
        "电池销量",
    ]
    
    for query in queries:
        print(f"\nQuery: {query}")
        results = search.search(query, top_k=3)
        for doc, score, meta in results:
            print(f"  Score: {score:.4f} | {doc[:50]}... | {meta}")
    
    print("\n✅ Embedding search test completed!")


if __name__ == "__main__":
    test_embedding_search()
