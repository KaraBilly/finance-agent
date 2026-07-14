"""Storage Capability — abstract interface for persistence."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from .base import Evidence

class StorageCapability(ABC):
    """Abstract interface for evidence and answer persistence."""

    @abstractmethod
    def init(self) -> None:
        """Initialize storage (create tables, etc.)."""
        ...

    @abstractmethod
    def add_source(
        self,
        kind: str,
        *,
        url: str | None = None,
        title: str | None = None,
        publisher: str | None = None,
        sha256: str | None = None,
        raw_path: str | None = None,
        meta: dict | None = None,
    ) -> int:
        """Add a source record, return source_id."""
        ...

    @abstractmethod
    def add_chunk(
        self,
        source_id: int,
        ord_: int,
        text: str,
        *,
        offset_start: int | None = None,
        offset_end: int | None = None,
        meta: dict | None = None,
    ) -> int:
        """Add a chunk record, return chunk_id."""
        ...

    @abstractmethod
    def get_chunk(self, chunk_id: int) -> dict[str, Any] | None:
        """Get chunk with source info."""
        ...

    @abstractmethod
    def save_answer(
        self,
        question: str,
        answer_md: str,
        trace: dict,
        citations: Iterable[tuple[str, int]],
    ) -> int:
        """Save an answer with citations, return answer_id."""
        ...

    @abstractmethod
    def load_prefs(self, limit: int = 20) -> list[dict]:
        """Load user preferences."""
        ...

    @abstractmethod
    def upsert_pref(
        self,
        topic: str,
        weight: float,
        note: str = "",
        evidence_answer_id: int | None = None,
    ) -> None:
        """Insert or update a user preference."""
        ...

    @abstractmethod
    def clear_prefs(self) -> None:
        """Delete all stored user preferences.

        Used by the CLI ``clear-prefs`` command. Kept on the capability
        interface (rather than reaching into the SQLite connection directly)
        so alternative backends stay swappable.
        """
        ...

    def register_evidence(self, ev: "Evidence", raw_path: str | None = None) -> "Evidence":
        """Persist evidence and fill chunk_id/source_id. Default impl uses add_source/add_chunk."""
        import hashlib
        sha = hashlib.sha256(ev.text.encode("utf-8", errors="ignore")).hexdigest()
        sid = self.add_source(
            kind=ev.source_kind,
            url=ev.url,
            title=ev.title,
            publisher=ev.publisher,
            sha256=sha,
            raw_path=raw_path,
            meta=ev.meta,
        )
        cid = self.add_chunk(sid, ord_=0, text=ev.text, meta=ev.meta)
        ev.source_id, ev.chunk_id = sid, cid
        return ev
