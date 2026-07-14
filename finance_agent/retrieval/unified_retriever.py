"""Unified Retriever — combines web search + external data for RAG.

This is the main entry point for evidence retrieval. It orchestrates:
1. External data retrieval (market/financials/filings from local files)
2. Web search (Tavily)
3. BM25 + LLM rerank across all sources
4. Deduplication and ranking

Usage:
    retriever = UnifiedRetriever(registry)
    evidences = retriever.retrieve(question, plan)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..capabilities.base import Evidence
from ..retrieval.external_data_store import ExternalDataStore, get_shared_external_store
from ..retrieval.bm25 import bm25_topk
from ..retrieval.rerank import llm_rerank

if TYPE_CHECKING:
    from ..registry import ProviderRegistry

log = logging.getLogger(__name__)

# Maximum evidence from each source
_MAX_EXTERNAL = 8
_MAX_WEB = 6
_MAX_TOTAL = 24
# Cap chunks returned from the same underlying document. Without this, a
# single PDF (e.g. an annual report) can dominate the evidence pool with
# 4+ near-identical entries, making the synthesizer emit a "## Evidence"
# section where S1/S3/S4/S5 all cite the same filing.
_MAX_CHUNKS_PER_SOURCE = 2

class UnifiedRetriever:
    """Unified retriever that combines external data + web search."""

    def __init__(self, registry: "ProviderRegistry"):
        self.registry = registry
        self._external_store: ExternalDataStore | None = None

    @property
    def external_store(self) -> ExternalDataStore:
        """Lazy initialization of external data store.

        Uses the process-wide singleton so the RAG-backed financials
        provider (and any other consumer) shares the same loaded corpus and
        Milvus collection.
        """
        if self._external_store is None:
            self._external_store = get_shared_external_store()
            self._external_store.load_all()
        return self._external_store

    def retrieve(
        self,
        query: str,
        plan: dict | None = None,
        *,
        use_external: bool = True,
        use_web: bool = True,
        external_kinds: list[str] | None = None,
        final_top: int = 12,
    ) -> list[Evidence]:
        """Retrieve evidence from all configured sources.

        Args:
            query: The user query
            plan: Planner output (optional, for tool-based hints)
            use_external: Whether to search external data
            use_web: Whether to search web
            external_kinds: Specific source kinds to search ("market", "financials", "filings")
            final_top: Maximum number of evidence to return

        Returns:
            List of Evidence objects, ranked by relevance
        """
        all_evidences: list[Evidence] = []

        # 1. Retrieve from external data
        if use_external:
            try:
                external_evs = self.external_store.search(
                    query,
                    source_kinds=external_kinds,
                    bm25_top=_MAX_EXTERNAL * 2,
                    final_top=_MAX_EXTERNAL,
                    reranker=self.registry.planner_llm,
                )
                all_evidences.extend(external_evs)
                log.info("External data: %d evidence", len(external_evs))
            except Exception as e:
                log.warning("External data retrieval failed: %s", e)

        # 2. Retrieve from web
        if use_web:
            try:
                web_evs = self.registry.web_search.search_and_extract(
                    query,
                    max_results=6,
                    final_top=_MAX_WEB,
                    reranker=self.registry.planner_llm,
                )
                all_evidences.extend(web_evs)
                log.info("Web search: %d evidence", len(web_evs))
            except Exception as e:
                log.warning("Web search failed: %s", e)

        if not all_evidences:
            log.warning("No evidence retrieved from any source")
            return []

        # 3. Cross-source reranking (BM25 + LLM)
        if len(all_evidences) > final_top:
            try:
                all_evidences = self._rerank_all(query, all_evidences, final_top)
            except Exception as e:
                log.warning("Cross-source rerank failed: %s", e)
                all_evidences = all_evidences[:final_top]

        # 4. Deduplicate by content similarity
        all_evidences = self._deduplicate(all_evidences)

        log.info("Unified retrieval: %d final evidence", len(all_evidences))
        return all_evidences[:final_top]

    def _rerank_all(
        self, query: str, evidences: list[Evidence], top_k: int
    ) -> list[Evidence]:
        """Rerank evidence from multiple sources."""
        texts = [ev.text for ev in evidences]

        # BM25 pre-filter
        bm25_idx = bm25_topk(query, texts, k=min(20, len(texts)))
        pre = [evidences[i] for i in bm25_idx]

        # LLM rerank
        try:
            ranked_idx = llm_rerank(
                self.registry.planner_llm, query, [p.text for p in pre], k=top_k
            )
            return [pre[i] for i in ranked_idx]
        except Exception as e:
            log.warning("LLM rerank in unified retrieval failed: %s", e)
            return pre[:top_k]

    def _deduplicate(self, evidences: list[Evidence], threshold: float = 0.85) -> list[Evidence]:
        """Remove near-duplicate evidence and cap chunks per source document.

        Two-stage filter:
        1. Drop near-identical text (Jaccard > ``threshold``).
        2. Cap survivors to ``_MAX_CHUNKS_PER_SOURCE`` chunks per source file.
           Different chunks of the same PDF are distinct passages but all
           cite the same document, so returning more than a few produces a
           bloated ``## Evidence`` section with visually duplicated entries.
        """
        if len(evidences) <= 1:
            return evidences

        unique: list[Evidence] = []
        for ev in evidences:
            is_duplicate = False
            for existing in unique:
                similarity = self._text_similarity(ev.text, existing.text)
                if similarity > threshold:
                    is_duplicate = True
                    break
            if not is_duplicate:
                unique.append(ev)

        # Per-source-file cap. Key by URL (which is ``file://...`` for
        # external RAG chunks) with a fallback to (title, publisher) so web
        # results without a shared URL aren't over-collapsed. Order preserved.
        capped: list[Evidence] = []
        seen_per_key: dict[str, int] = {}
        for ev in unique:
            key = ev.url or f"{ev.title or ''}|{ev.publisher or ''}"
            count = seen_per_key.get(key, 0)
            if count >= _MAX_CHUNKS_PER_SOURCE:
                continue
            seen_per_key[key] = count + 1
            capped.append(ev)
        return capped

    def _text_similarity(self, a: str, b: str) -> float:
        """Calculate simple text similarity (Jaccard on word sets)."""
        import re

        def tokenize(text: str) -> set[str]:
            return set(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text.lower()))

        set_a = tokenize(a)
        set_b = tokenize(b)
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def get_stats(self) -> dict:
        """Get statistics about the retriever."""
        stats = {"external_data": self.external_store.get_stats()}
        return stats
