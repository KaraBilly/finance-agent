"""Web Search Capability — abstract interface for web search + extraction."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Evidence
    from .llm import LLMCapability


class WebSearchCapability(ABC):
    """Abstract interface for web search, extraction, and reranking."""

    @abstractmethod
    def search(self, query: str, *, max_results: int = 6) -> list[dict]:
        """Search the web, return list of {url, title, content/snippet}."""
        ...

    @abstractmethod
    def extract_content(self, url: str, fallback_snippet: str = "") -> str:
        """Extract main text content from a URL."""
        ...

    @abstractmethod
    def search_and_extract(
        self,
        query: str,
        *,
        max_results: int = 6,
        bm25_top: int = 20,
        final_top: int = 6,
        reranker: "LLMCapability | None" = None,
    ) -> list["Evidence"]:
        """Full pipeline: search → extract → chunk → filter → rerank → Evidence list."""
        ...
