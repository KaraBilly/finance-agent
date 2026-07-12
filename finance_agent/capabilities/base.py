"""Shared types for capability layer."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Evidence:
    """A retrievable unit that can be cited by the synthesizer.
    
    This is the universal data contract between tools and agent.
    """
    text: str
    source_kind: str          # 'web' | 'market' | 'financials' | 'filings'
    url: str | None = None
    title: str | None = None
    publisher: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    # Filled after persistence:
    chunk_id: int | None = None
    source_id: int | None = None
