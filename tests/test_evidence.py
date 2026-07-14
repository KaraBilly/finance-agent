"""Tests for the Evidence dataclass — universal data contract for tools."""
from __future__ import annotations

from finance_agent.capabilities.base import Evidence


class TestEvidenceDefaults:
    def test_minimal_construction(self):
        ev = Evidence(text="hi", source_kind="web")
        assert ev.text == "hi"
        assert ev.source_kind == "web"
        assert ev.url is None
        assert ev.title is None
        assert ev.publisher is None
        assert ev.meta == {}
        assert ev.chunk_id is None
        assert ev.source_id is None

    def test_meta_default_is_isolated_per_instance(self):
        """Regression: default_factory=dict must not share state."""
        a = Evidence(text="a", source_kind="web")
        b = Evidence(text="b", source_kind="web")
        a.meta["x"] = 1
        assert "x" not in b.meta

    def test_full_construction(self):
        ev = Evidence(
            text="body",
            source_kind="filings",
            url="https://sec.gov",
            title="10-K",
            publisher="SEC",
            meta={"symbol": "AAPL"},
            chunk_id=42,
            source_id=7,
        )
        assert ev.url == "https://sec.gov"
        assert ev.title == "10-K"
        assert ev.publisher == "SEC"
        assert ev.meta == {"symbol": "AAPL"}
        assert ev.chunk_id == 42
        assert ev.source_id == 7
