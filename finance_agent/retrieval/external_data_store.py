"""External Data Store — indexes and retrieves market/financials/filings data.

Loads pre-prepared market data and financial reports from local directories,
converts them into searchable chunks, and provides BM25 + Embedding + LLM rerank retrieval.

Expected directory structure:
  data/market/        — Market data files (CSV/JSON)
  data/financials/    — Financial reports (CSV/JSON/Markdown)
  data/filings/       — SEC filings / 公告 (text/Markdown)
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from ..capabilities.base import Evidence
from ..retrieval.bm25 import bm25_topk
from ..retrieval.rerank import llm_rerank
from ..capabilities.llm import LLMCapability

log = logging.getLogger(__name__)

# File extensions we support
_SUPPORTED_EXTS = {".csv", ".json", ".jsonl", ".md", ".txt", ".pdf"}

# Chunking config
_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 100

# Embedding configuration
_USE_EMBEDDING = True  # Enable embedding-based search
_EMBEDDING_MODEL = "BAAI/bge-large-zh-v1.5"  # Chinese-optimized model

class ExternalDataStore:
    """Store for external market/financials/filings data with RAG retrieval."""

    def __init__(
        self,
        market_dir: Path | None = None,
        financials_dir: Path | None = None,
        filings_dir: Path | None = None,
        use_embedding: bool = _USE_EMBEDDING,
        use_milvus: bool | None = None,
    ):
        from ..config import CONFIG

        self.market_dir = market_dir or CONFIG.external_market_dir or (CONFIG.data_dir / "market")
        self.financials_dir = financials_dir or CONFIG.external_financials_dir or (CONFIG.data_dir / "financials")
        self.filings_dir = filings_dir or CONFIG.external_filings_dir or (CONFIG.data_dir / "filings")

        self.enabled = CONFIG.use_external_data
        self.use_embedding = use_embedding
        # Read the Milvus toggle from CONFIG so users can turn it off via
        # ``FA_USE_MILVUS=false`` without editing code. Explicit constructor
        # arg still wins for tests / callers that need to force a value.
        self.use_milvus = CONFIG.use_milvus if use_milvus is None else use_milvus

        # All documents: list of (text, metadata, source_kind)
        self._docs: list[tuple[str, dict[str, Any], str]] = []
        self._loaded = False
        
        # Embedding search — lazy init on first use to avoid heavy model
        # download when the store is instantiated but never queried.
        self._embedding_search = None
        self._embedding_search_ready = False

    # ------------------------------------------------------------------ loading

    def load_all(self) -> None:
        """Load all external data into memory."""
        if self._loaded:
            return
        
        if not self.enabled:
            log.info("External data is disabled via FA_USE_EXTERNAL_DATA")
            self._loaded = True
            return

        log.info("Loading external data...")
        count = 0

        for source_kind, directory in [
            ("market", self.market_dir),
            ("financials", self.financials_dir),
            ("filings", self.filings_dir),
        ]:
            if not directory.exists():
                log.warning("Directory not found: %s", directory)
                continue

            for file_path in directory.rglob("*"):
                if file_path.suffix.lower() not in _SUPPORTED_EXTS:
                    continue
                try:
                    docs = self._load_file(file_path, source_kind)
                    self._docs.extend(docs)
                    count += len(docs)
                except Exception as e:
                    log.warning("Failed to load %s: %s", file_path, e)

        self._loaded = True
        log.info("Loaded %d chunks from external data", count)
        
        # Build embedding index (lazy-init embedder if needed)
        if self.use_embedding:
            try:
                self._build_embedding_index()
            except Exception as e:
                log.warning("Failed to build embedding index: %s", e)

    def _ensure_embedding_search(self):
        """Lazy-init embedding search on first use."""
        if not self.use_embedding:
            return
        if self._embedding_search is not None:
            return
        if self._embedding_search_ready:
            return
        
        try:
            from ..config import CONFIG
            from ..retrieval.embedding_search import EmbeddingSearch
            self._embedding_search = EmbeddingSearch(
                model_name=_EMBEDDING_MODEL,
                use_milvus=self.use_milvus,
                milvus_host=getattr(CONFIG, 'milvus_host', None),
                milvus_port=getattr(CONFIG, 'milvus_port', None),
                milvus_collection=getattr(CONFIG, 'milvus_collection', None),
            )
            if not getattr(self._embedding_search, "is_ready", True):
                log.warning(
                    "Embedding search disabled: embedder not ready. "
                    "Install with: pip install 'sentence-transformers>=2.2.0'"
                )
                self.use_embedding = False
                self._embedding_search = None
            else:
                log.info("Embedding search initialized with model: %s (Milvus: %s)",
                        _EMBEDDING_MODEL, self.use_milvus)
                self._embedding_search_ready = True
        except Exception as e:
            log.warning("Failed to initialize embedding search: %s", e)
            self.use_embedding = False
            self._embedding_search = None

    def _build_embedding_index(self):
        """Build embedding index for semantic search."""
        if not self._docs:
            return
        
        self._ensure_embedding_search()
        if self._embedding_search is None:
            return
        
        log.info("Building embedding index...")
        texts = [d[0] for d in self._docs]
        metas = [d[1] for d in self._docs]
        
        self._embedding_search.index_documents(texts, metas)
        log.info("Embedding index built successfully")

    def _load_file(
        self, file_path: Path, source_kind: str
    ) -> list[tuple[str, dict[str, Any], str]]:
        """Load a single file and return list of (text, meta, source_kind)."""
        ext = file_path.suffix.lower()

        if ext == ".csv":
            return self._load_csv(file_path, source_kind)
        elif ext in (".json", ".jsonl"):
            return self._load_json(file_path, source_kind)
        elif ext in (".md", ".txt"):
            return self._load_text(file_path, source_kind)
        elif ext == ".pdf":
            return self._load_pdf(file_path, source_kind)
        else:
            return []

    def _load_csv(
        self, file_path: Path, source_kind: str
    ) -> list[tuple[str, dict[str, Any], str]]:
        """Load CSV file — convert each row to a text chunk."""
        try:
            df = pd.read_csv(file_path)
        except Exception:
            # Try different encodings
            df = pd.read_csv(file_path, encoding="gbk")

        docs = []
        # Get symbol from filename if possible
        symbol = self._extract_symbol_from_filename(file_path.name)

        # Use SemanticChunker for better chunking
        try:
            from ..retrieval.semantic_chunker import SemanticChunker
            chunks = SemanticChunker.chunk_csv(df, symbol=symbol, context=source_kind)
            for text, meta in chunks:
                meta["file"] = str(file_path)
                meta["source_kind"] = source_kind
                docs.append((text, meta, source_kind))
        except Exception as e:
            log.warning("Semantic chunking failed for %s: %s", file_path, e)
            # Fallback to simple chunking
            rows_per_chunk = max(1, len(df) // 10)
            for i in range(0, len(df), rows_per_chunk):
                chunk_df = df.iloc[i : i + rows_per_chunk]
                md = chunk_df.to_markdown(index=False)
                header = f"**{source_kind.upper()} Data: {symbol or file_path.stem}**\n\n"
                text = header + md
                meta = {
                    "file": str(file_path),
                    "symbol": symbol,
                    "rows": len(chunk_df),
                    "sourceKind": source_kind,
                }
                docs.append((text, meta, source_kind))

        return docs

    def _load_json(
        self, file_path: Path, source_kind: str
    ) -> list[tuple[str, dict[str, Any], str]]:
        """Load JSON/JSONL file with semantic chunking."""
        docs = []
        symbol = self._extract_symbol_from_filename(file_path.name)

        if file_path.suffix.lower() == ".jsonl":
            with open(file_path, "r", encoding="utf-8") as f:
                items = [json.loads(line) for line in f if line.strip()]
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                items = data if isinstance(data, list) else [data]

        # Use SemanticChunker for better chunking
        try:
            from ..retrieval.semantic_chunker import SemanticChunker
            chunks = SemanticChunker.chunk_json(items, symbol=symbol, context=source_kind)
            for text, meta in chunks:
                meta["file"] = str(file_path)
                meta["sourceKind"] = source_kind
                docs.append((text, meta, source_kind))
        except Exception as e:
            log.warning("Semantic chunking failed for %s: %s", file_path, e)
            # Fallback to simple chunking
            items_per_chunk = max(1, len(items) // 10)
            for i in range(0, len(items), items_per_chunk):
                chunk_items = items[i : i + items_per_chunk]
                text = f"**{source_kind.upper()} Data: {symbol or file_path.stem}**\n\n"
                text += json.dumps(chunk_items, ensure_ascii=False, indent=2)
                meta = {
                    "file": str(file_path),
                    "symbol": symbol,
                    "items": len(chunk_items),
                    "sourceKind": source_kind,
                }
                docs.append((text, meta, source_kind))

        return docs

    def _load_text(
        self, file_path: Path, source_kind: str
    ) -> list[tuple[str, dict[str, Any], str]]:
        """Load Markdown/text file with semantic chunking."""
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

        symbol = self._extract_symbol_from_filename(file_path.name)
        
        # Use SemanticChunker for better chunking
        try:
            from ..retrieval.semantic_chunker import SemanticChunker
            chunks = SemanticChunker.chunk_text(text, source_kind=source_kind, symbol=symbol)
            docs = []
            for chunk_text, meta in chunks:
                meta["file"] = str(file_path)
                meta["sourceKind"] = source_kind
                docs.append((chunk_text, meta, source_kind))
            return docs
        except Exception as e:
            log.warning("Semantic chunking failed for %s: %s", file_path, e)
            # Fallback to simple chunking
            chunks = self._chunk_text(text)
            docs = []
            for i, chunk in enumerate(chunks):
                meta = {
                    "file": str(file_path),
                    "symbol": symbol,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "sourceKind": source_kind,
                }
                docs.append((chunk, meta, source_kind))
            return docs

    def _chunk_text(self, text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
        """Split text into overlapping chunks."""
        # Split by paragraphs first
        paragraphs = re.split(r"\n{2,}", text)

        chunks = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) < size:
                current_chunk += "\n\n" + para if current_chunk else para
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                # Keep overlap
                if len(para) > size:
                    # Paragraph too long, split by sentences
                    sentences = re.split(r"(?<=[。！？!?])\s+", para)
                    current_chunk = ""
                    for sent in sentences:
                        if len(current_chunk) + len(sent) < size:
                            current_chunk += sent
                        else:
                            if current_chunk:
                                chunks.append(current_chunk.strip())
                            current_chunk = sent
                else:
                    current_chunk = para

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    def _load_pdf(
        self, file_path: Path, source_kind: str
    ) -> list[tuple[str, dict[str, Any], str]]:
        """Load PDF file and extract text for chunking."""
        try:
            import fitz  # PyMuPDF
            
            docs = []
            symbol = self._extract_symbol_from_filename(file_path.name)
            
            # Open PDF
            doc = fitz.open(file_path)
            
            # Extract text from all pages
            full_text = ""
            for page_num in range(len(doc)):
                page = doc[page_num]
                full_text += page.get_text()
            
            doc.close()
            
            if not full_text.strip():
                log.warning("No text extracted from PDF: %s", file_path)
                return []
            
            # Use SemanticChunker for better chunking
            try:
                from ..retrieval.semantic_chunker import SemanticChunker
                chunks = SemanticChunker.chunk_text(full_text, source_kind=source_kind, symbol=symbol)
                for text, meta in chunks:
                    meta["file"] = str(file_path)
                    meta["sourceKind"] = source_kind
                    docs.append((text, meta, source_kind))
            except Exception as e:
                log.warning("Semantic chunking failed for PDF %s: %s", file_path, e)
                # Fallback to simple chunking
                chunks = self._chunk_text(full_text)
                for i, chunk in enumerate(chunks):
                    meta = {
                        "file": str(file_path),
                        "symbol": symbol,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "sourceKind": source_kind,
                    }
                    docs.append((chunk, meta, source_kind))
            
            return docs
            
        except ImportError:
            log.warning("PyMuPDF not installed. Cannot process PDF: %s", file_path)
            return []
        except Exception as e:
            log.warning("Failed to load PDF %s: %s", file_path, e)
            return []

    def _extract_symbol_from_filename(self, filename: str) -> str | None:
        """Extract stock symbol or company name from filename.
        
        Supports:
        - US symbols: AAPL_2024.csv, MSFT-report.pdf
        - A-share codes: 000001_financials.json, 002594_daily.csv
        - Chinese names: 比亚迪2025年报.pdf, 宁德时代_财报.pdf
        """
        # Pattern 1: US symbols (AAPL, MSFT)
        patterns = [
            r"^([A-Z]{1,5})[_\-]",  # AAPL_, MSFT-
            r"^([A-Z]{1,5})\d",  # AAPL2024
            r"[_\-]([A-Z]{1,5})\.",  # _AAPL.csv
        ]
        for pattern in patterns:
            match = re.search(pattern, filename)
            if match:
                return match.group(1)
        
        # Pattern 2: A-share codes (6-digit)
        code_patterns = [
            r"^(\d{6})[_\-]",  # 000001_, 002594_
            r"[_\-](\d{6})\.",  # _000001.csv
            r"^(\d{6})\D",  # 002594daily
        ]
        for pattern in code_patterns:
            match = re.search(pattern, filename)
            if match:
                return match.group(1)
        
        # Pattern 3: Chinese company names
        # Common A-share company names
        cn_companies = {
            '比亚迪': '002594',
            '宁德时代': '300750',
            '中际旭创': '300308',
            '贵州茅台': '600519',
            '中国平安': '601318',
            '招商银行': '600036',
        }
        
        for cn_name, code in cn_companies.items():
            if cn_name in filename:
                return code  # Return stock code instead of name
        
        return None

    # ------------------------------------------------------------------ retrieval

    def search(
        self,
        query: str,
        *,
        source_kinds: list[str] | None = None,
        symbols: list[str] | None = None,
        bm25_top: int = 20,
        final_top: int = 6,
        reranker: LLMCapability | None = None,
    ) -> list[Evidence]:
        """Search external data using BM25 + optional LLM rerank.

        Args:
            query: Search query
            source_kinds: Filter by source kind ("market", "financials", "filings")
            symbols: Filter by stock symbols (e.g., ["002594", "300750"])
            bm25_top: Number of candidates after BM25
            final_top: Number of results after reranking
            reranker: LLM for reranking (optional)

        Returns:
            List of Evidence objects
        """
        if not self._loaded:
            self.load_all()

        # Filter by source kind
        candidates = self._docs
        if source_kinds:
            candidates = [d for d in candidates if d[2] in source_kinds]
        
        # Filter by symbols (if specified)
        if symbols:
            candidates = [d for d in candidates if d[1].get('symbol') in symbols]
            log.info("Filtered by symbols %s: %d candidates", symbols, len(candidates))

        if not candidates:
            log.info("No external data candidates for kinds: %s", source_kinds)
            return []

        # BM25 pre-filter
        texts = [d[0] for d in candidates]
        top_idx = bm25_topk(query, texts, k=min(bm25_top, len(texts)))
        pre = [candidates[i] for i in top_idx]
        
        # Embedding-based semantic search (if enabled)
        if self.use_embedding:
            self._ensure_embedding_search()
        if self._embedding_search is not None:
            try:
                embedding_results = self._embedding_search.search(
                    query,
                    top_k=bm25_top,
                    source_kinds=source_kinds,
                    symbols=symbols,
                )
                # Merge with BM25 results. Previously we only kept a Milvus
                # hit if its exact text was also in the in-memory candidate
                # list — which silently dropped everything from a persisted
                # Milvus collection when in-memory _docs was empty (e.g., a
                # fresh process that hasn't reloaded local files). Now we
                # keep every hit, using the Milvus payload directly when
                # the text isn't in memory.
                seen_texts = {p[0] for p in pre}
                added_from_milvus = 0
                for doc_text, _score, meta in embedding_results:
                    if not doc_text or doc_text in seen_texts:
                        continue
                    matched: tuple[str, dict, str] | None = None
                    for candidate in candidates:
                        if candidate[0] == doc_text:
                            matched = candidate
                            break
                    if matched is not None:
                        pre.append(matched)
                    else:
                        # Fall back to Milvus payload. MilvusStore.search
                        # guarantees ``source_kind`` and ``symbol`` are set
                        # in ``meta``.
                        sk = meta.get("source_kind") or meta.get("sourceKind") or "unknown"
                        pre.append((doc_text, dict(meta), sk))
                    seen_texts.add(doc_text)
                    added_from_milvus += 1
                log.info("Embedding search added %d unique results", added_from_milvus)
            except Exception as e:
                # This branch covers Milvus network errors AND embedder
                # failures — log both possibilities so users know what to
                # check.
                log.warning(
                    "Embedding/Milvus search failed: %s "
                    "(check Milvus connectivity and sentence-transformers install)",
                    e,
                )

        # LLM rerank
        if reranker is not None and pre:
            try:
                ranked_idx = llm_rerank(
                    reranker, query, [p[0] for p in pre], k=final_top
                )
                pre = [pre[i] for i in ranked_idx]
            except Exception as e:
                log.warning("LLM rerank failed for external data: %s", e)
                pre = pre[:final_top]
        else:
            pre = pre[:final_top]

        # Build Evidence
        evidences = []
        for text, meta, source_kind in pre:
            ev = Evidence(
                text=text,
                source_kind=source_kind,
                url=f"file://{meta.get('file', '')}",
                title=f"{source_kind.upper()}: {meta.get('symbol', 'unknown')}",
                publisher="external_data",
                meta=meta,
            )
            evidences.append(ev)

        log.info(
            "External data retrieval: %d results for query '%s'",
            len(evidences),
            query[:50],
        )
        return evidences

    def get_stats(self) -> dict[str, int]:
        """Return statistics about loaded data."""
        if not self._loaded:
            self.load_all()

        stats = {"market": 0, "financials": 0, "filings": 0, "total": len(self._docs)}
        for _, _, kind in self._docs:
            if kind in stats:
                stats[kind] += 1
        
        # Add embedding stats if available
        if self.use_embedding and self._embedding_search is not None:
            try:
                emb_stats = self._embedding_search.get_stats()
                stats["embedding"] = emb_stats
            except Exception:
                pass
        elif self.use_embedding and not self._embedding_search_ready:
            stats["embedding"] = "not_initialized"
        
        return stats

# ---------------------------------------------------------- shared instance

# Module-level singleton so callers that need the RAG store (unified
# retriever, RAG-backed financials provider, etc.) reuse the SAME loaded
# corpus + Milvus collection instead of each spinning up their own — which
# would re-parse every file and double-insert into Milvus.
_SHARED_STORE: "ExternalDataStore | None" = None

def get_shared_external_store() -> "ExternalDataStore":
    """Return a process-wide :class:`ExternalDataStore` singleton.

    First call builds the store with default (CONFIG-derived) settings.
    Subsequent calls return the same instance. Tests can reset it via
    :func:`reset_shared_external_store`.
    """
    global _SHARED_STORE
    if _SHARED_STORE is None:
        _SHARED_STORE = ExternalDataStore()
    return _SHARED_STORE

def reset_shared_external_store() -> None:
    """Clear the shared store (test helper)."""
    global _SHARED_STORE
    _SHARED_STORE = None
