"""Tavily + Trafilatura web search provider."""
from __future__ import annotations
import hashlib
import logging
import re
from pathlib import Path

import requests

from ..capabilities.web_search import WebSearchCapability
from ..capabilities.llm import LLMCapability
from ..capabilities.base import Evidence
from ..config import CONFIG
from ..retrieval.bm25 import bm25_topk
from ..retrieval.rerank import llm_rerank

log = logging.getLogger(__name__)

_SPLIT_RE = re.compile(r"\n{2,}|(?<=[。！？!?])\s+")


class TavilyWebProvider(WebSearchCapability):
    """Web search via Tavily, extraction via Trafilatura."""

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or CONFIG.cache_dir

    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()[:16]
        return self.cache_dir / f"web_{h}.txt"

    def search(self, query: str, *, max_results: int = 6) -> list[dict]:
        CONFIG.require("tavily_api_key")
        from tavily import TavilyClient
        client = TavilyClient(api_key=CONFIG.tavily_api_key)
        resp = client.search(query=query, max_results=max_results,
                             search_depth="advanced", include_answer=False)
        return resp.get("results", [])

    def extract_content(self, url: str, fallback_snippet: str = "") -> str:
        cache = self._cache_path(url)
        if cache.exists():
            return cache.read_text(encoding="utf-8", errors="ignore")
        try:
            import trafilatura
            html = trafilatura.fetch_url(url, no_ssl=True)
            if not html:
                html = requests.get(url, timeout=10,
                                    headers={"User-Agent": "Mozilla/5.0"}).text
            text = trafilatura.extract(html, include_comments=False,
                                        include_tables=True, favor_precision=True) or ""
        except Exception as e:
            log.warning("extract failed for %s: %s", url, e)
            text = ""
        if not text:
            text = fallback_snippet or ""
        if text:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(text, encoding="utf-8")
        return text

    def _chunk(self, text: str, target: int = 500) -> list[str]:
        parts = _SPLIT_RE.split(text)
        chunks: list[str] = []
        buf = ""
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if len(buf) + len(p) < target:
                buf = (buf + " " + p).strip()
            else:
                if buf:
                    chunks.append(buf)
                buf = p
        if buf:
            chunks.append(buf)
        return chunks

    def search_and_extract(
        self,
        query: str,
        *,
        max_results: int = 6,
        bm25_top: int = 20,
        final_top: int = 6,
        reranker: LLMCapability | None = None,
    ) -> list[Evidence]:
        hits = self.search(query, max_results=max_results)
        if not hits:
            return []

        # Extract + chunk
        candidates: list[tuple[str, dict]] = []
        for h in hits:
            url = h.get("url", "")
            title = h.get("title", "")
            publisher = h.get("source") or (url.split("/")[2] if "://" in url else "")
            snippet = h.get("content", "") or ""
            text = self.extract_content(url, fallback_snippet=snippet)
            if not text:
                continue
            raw_path = self._cache_path(url)
            for ch in self._chunk(text):
                candidates.append((ch, {
                    "url": url, "title": title, "publisher": publisher,
                    "raw_path": str(raw_path),
                }))
        if not candidates:
            return []
        log.info("web candidates: %d chunks from %d urls", len(candidates), len(hits))

        # BM25 pre-filter
        texts = [c[0] for c in candidates]
        top_idx = bm25_topk(query, texts, k=min(bm25_top, len(texts)))
        pre = [candidates[i] for i in top_idx]

        # LLM rerank
        if reranker is not None and pre:
            try:
                ranked_idx = llm_rerank(reranker, query, [p[0] for p in pre], k=final_top)
                pre = [pre[i] for i in ranked_idx]
            except Exception as e:
                log.warning("LLM rerank failed, falling back to BM25 order: %s", e)
                pre = pre[:final_top]
        else:
            pre = pre[:final_top]

        # Build Evidence list (without persisting - that's storage's job)
        evidences: list[Evidence] = []
        for text, meta in pre:
            evidences.append(Evidence(
                text=text,
                source_kind="web",
                url=meta["url"],
                title=meta["title"],
                publisher=meta["publisher"],
                meta={"raw_path": meta["raw_path"]},
            ))
        log.info("web final: %d chunks", len(evidences))
        return evidences
