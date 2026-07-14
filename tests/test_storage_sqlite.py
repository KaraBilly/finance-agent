"""Tests for SQLiteStorageProvider — evidence, answers, and long-term prefs."""
from __future__ import annotations

import pytest

from finance_agent.capabilities.base import Evidence
from finance_agent.providers.storage_sqlite import SQLiteStorageProvider


@pytest.fixture()
def storage(tmp_path):
    s = SQLiteStorageProvider(db_path=str(tmp_path / "store.db"))
    s.init()
    return s


class TestInit:
    def test_init_creates_expected_tables(self, storage):
        with storage._connect() as c:
            names = {
                row["name"]
                for row in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        for expected in {"sources", "chunks", "answers", "citations", "user_prefs"}:
            assert expected in names

    def test_init_is_idempotent(self, storage):
        storage.init()  # second call should not raise
        storage.init()


class TestSourcesAndChunks:
    def test_add_source_returns_incrementing_ids(self, storage):
        a = storage.add_source(kind="web", url="https://a", title="A")
        b = storage.add_source(kind="web", url="https://b", title="B")
        assert isinstance(a, int) and isinstance(b, int)
        assert b > a

    def test_add_chunk_and_get_chunk_joins_source_fields(self, storage):
        sid = storage.add_source(
            kind="filings", url="https://x", title="10K", publisher="SEC"
        )
        cid = storage.add_chunk(sid, ord_=0, text="revenue grew 12%")

        row = storage.get_chunk(cid)
        assert row is not None
        assert row["text"] == "revenue grew 12%"
        assert row["source_id"] == sid
        assert row["src_kind"] == "filings"
        assert row["src_title"] == "10K"
        assert row["src_publisher"] == "SEC"
        assert row["src_url"] == "https://x"

    def test_get_missing_chunk_returns_none(self, storage):
        assert storage.get_chunk(999_999) is None


class TestRegisterEvidence:
    def test_register_evidence_fills_ids(self, storage):
        ev = Evidence(
            text="AAPL beat Q3 revenue estimates.",
            source_kind="web",
            url="https://news.example.com/aapl",
            title="AAPL beats",
            publisher="Example News",
        )
        out = storage.register_evidence(ev)
        assert out is ev
        assert out.source_id is not None
        assert out.chunk_id is not None

        chunk = storage.get_chunk(out.chunk_id)
        assert chunk["text"] == "AAPL beat Q3 revenue estimates."
        assert chunk["src_url"] == "https://news.example.com/aapl"


class TestAnswersAndCitations:
    def test_save_answer_persists_and_links_citations(self, storage):
        sid = storage.add_source(kind="web", url="https://x")
        c1 = storage.add_chunk(sid, ord_=0, text="chunk one")
        c2 = storage.add_chunk(sid, ord_=1, text="chunk two")

        aid = storage.save_answer(
            question="Q?",
            answer_md="A.",
            trace={"steps": 3},
            citations=[("S1", c1), ("S2", c2)],
        )
        assert isinstance(aid, int)

        with storage._connect() as c:
            rows = c.execute(
                "SELECT label, chunk_id FROM citations WHERE answer_id=? ORDER BY label",
                (aid,),
            ).fetchall()
            labels = [(r["label"], r["chunk_id"]) for r in rows]
        assert labels == [("S1", c1), ("S2", c2)]

    def test_save_answer_with_no_citations(self, storage):
        aid = storage.save_answer("q?", "no evidence", {}, citations=[])
        assert isinstance(aid, int)
        with storage._connect() as c:
            n = c.execute(
                "SELECT COUNT(*) AS n FROM citations WHERE answer_id=?", (aid,)
            ).fetchone()["n"]
            assert n == 0


class TestUserPrefs:
    def test_load_prefs_empty_by_default(self, storage):
        assert storage.load_prefs() == []

    def test_upsert_pref_insert_then_update(self, storage):
        storage.upsert_pref("liquidity_risk", 0.3, note="first")
        rows = storage.load_prefs()
        assert len(rows) == 1
        assert rows[0]["topic"] == "liquidity_risk"
        assert rows[0]["weight"] == pytest.approx(0.3)
        assert rows[0]["note"] == "first"

        # Upsert same topic
        storage.upsert_pref("liquidity_risk", 0.55, note="second")
        rows = storage.load_prefs()
        assert len(rows) == 1
        assert rows[0]["weight"] == pytest.approx(0.55)
        assert rows[0]["note"] == "second"

    def test_load_prefs_ordered_by_weight_desc(self, storage):
        storage.upsert_pref("a", 0.1)
        storage.upsert_pref("b", 0.9)
        storage.upsert_pref("c", 0.5)
        topics = [r["topic"] for r in storage.load_prefs()]
        assert topics == ["b", "c", "a"]

    def test_load_prefs_respects_limit(self, storage):
        for i in range(5):
            storage.upsert_pref(f"topic_{i}", weight=i / 10)
        assert len(storage.load_prefs(limit=2)) == 2
