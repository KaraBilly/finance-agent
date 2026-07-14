"""SQLite-based storage provider."""
from __future__ import annotations
import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterable

from ..capabilities.storage import StorageCapability
from ..config import CONFIG

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    url          TEXT,
    title        TEXT,
    publisher    TEXT,
    retrieved_at REAL NOT NULL,
    sha256       TEXT,
    raw_path     TEXT,
    meta_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_sources_sha ON sources(sha256);

CREATE TABLE IF NOT EXISTS chunks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    INTEGER NOT NULL REFERENCES sources(id),
    ord          INTEGER NOT NULL,
    text         TEXT NOT NULL,
    offset_start INTEGER,
    offset_end   INTEGER,
    meta_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);

CREATE TABLE IF NOT EXISTS answers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question     TEXT NOT NULL,
    answer_md    TEXT NOT NULL,
    trace_json   TEXT NOT NULL,
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS citations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_id    INTEGER NOT NULL REFERENCES answers(id),
    label        TEXT NOT NULL,
    chunk_id     INTEGER NOT NULL REFERENCES chunks(id)
);
CREATE INDEX IF NOT EXISTS idx_citations_answer ON citations(answer_id);

CREATE TABLE IF NOT EXISTS user_prefs (
    topic        TEXT PRIMARY KEY,
    weight       REAL NOT NULL,
    note         TEXT,
    last_seen    REAL NOT NULL,
    evidence_answer_id INTEGER
);
"""

class SQLiteStorageProvider(StorageCapability):
    """SQLite-based persistence for evidence, answers, and user preferences."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(CONFIG.db_path)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # SQLite disables foreign-key enforcement by default. We rely on
        # ON DELETE CASCADE for conversation_turns, so it must be turned on
        # per-connection.
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self._connect() as c:
            c.executescript(SCHEMA)

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
        with self._connect() as c:
            cur = c.execute(
                "INSERT INTO sources(kind,url,title,publisher,retrieved_at,sha256,raw_path,meta_json)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (kind, url, title, publisher, time.time(), sha256,
                 str(raw_path) if raw_path else None,
                 json.dumps(meta or {}, ensure_ascii=False)),
            )
            return cur.lastrowid

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
        with self._connect() as c:
            cur = c.execute(
                "INSERT INTO chunks(source_id,ord,text,offset_start,offset_end,meta_json)"
                " VALUES(?,?,?,?,?,?)",
                (source_id, ord_, text, offset_start, offset_end,
                 json.dumps(meta or {}, ensure_ascii=False)),
            )
            return cur.lastrowid

    def get_chunk(self, chunk_id: int) -> dict[str, Any] | None:
        with self._connect() as c:
            row = c.execute(
                "SELECT c.*, s.url as src_url, s.title as src_title, s.publisher as src_publisher,"
                " s.kind as src_kind, s.retrieved_at as src_retrieved_at"
                " FROM chunks c JOIN sources s ON s.id=c.source_id WHERE c.id=?",
                (chunk_id,),
            ).fetchone()
            return dict(row) if row else None

    def save_answer(
        self,
        question: str,
        answer_md: str,
        trace: dict,
        citations: Iterable[tuple[str, int]],
    ) -> int:
        with self._connect() as c:
            cur = c.execute(
                "INSERT INTO answers(question,answer_md,trace_json,created_at) VALUES(?,?,?,?)",
                (question, answer_md, json.dumps(trace, ensure_ascii=False), time.time()),
            )
            aid = cur.lastrowid
            c.executemany(
                "INSERT INTO citations(answer_id,label,chunk_id) VALUES(?,?,?)",
                [(aid, label, cid) for label, cid in citations],
            )
            return aid

    def load_prefs(self, limit: int = 20) -> list[dict]:
        with self._connect() as c:
            rows = c.execute(
                "SELECT topic,weight,note,last_seen FROM user_prefs"
                " ORDER BY weight DESC, last_seen DESC LIMIT ?", (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_pref(
        self,
        topic: str,
        weight: float,
        note: str = "",
        evidence_answer_id: int | None = None,
    ) -> None:
        with self._connect() as c:
            c.execute(
                "INSERT INTO user_prefs(topic,weight,note,last_seen,evidence_answer_id)"
                " VALUES(?,?,?,?,?)"
                " ON CONFLICT(topic) DO UPDATE SET"
                "   weight=excluded.weight, note=excluded.note,"
                "   last_seen=excluded.last_seen, evidence_answer_id=excluded.evidence_answer_id",
                (topic, weight, note, time.time(), evidence_answer_id),
            )

    def clear_prefs(self) -> None:
        """Delete every row in ``user_prefs``.

        Called by the CLI ``clear-prefs`` command. Exposed via the capability
        interface so callers don't have to open their own ``sqlite3`` handle
        against ``CONFIG.db_path`` (which was the previous approach and
        bypassed the FK-enforcement PRAGMA plus the swappable storage layer).
        """
        with self._connect() as c:
            c.execute("DELETE FROM user_prefs")
