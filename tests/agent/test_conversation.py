"""Tests for Conversation / ConversationTurn data models (short-term memory)."""
from __future__ import annotations

import time

from finance_agent.agent.conversation import (
    CONVERSATION_SCHEMA,
    Conversation,
    ConversationTurn,
)


class TestConversationCreate:
    def test_create_generates_uuid_and_timestamps(self):
        conv = Conversation.create()
        assert isinstance(conv.conversation_id, str)
        assert len(conv.conversation_id) >= 32  # UUID length
        assert conv.created_at > 0
        assert conv.updated_at == conv.created_at
        assert conv.turns == []
        assert conv.metadata == {}

    def test_create_accepts_metadata(self):
        conv = Conversation.create(metadata={"user": "alice", "topic": "cn"})
        assert conv.metadata == {"user": "alice", "topic": "cn"}

    def test_create_produces_unique_ids(self):
        ids = {Conversation.create().conversation_id for _ in range(20)}
        assert len(ids) == 20


class TestAddTurn:
    def test_add_turn_appends_and_updates_timestamp(self):
        conv = Conversation.create()
        original_updated = conv.updated_at
        # Force clock advance
        time.sleep(0.001)
        turn = conv.add_turn("user", "What is BYD?")

        assert isinstance(turn, ConversationTurn)
        assert turn.role == "user"
        assert turn.content == "What is BYD?"
        assert turn.conversation_id == conv.conversation_id
        assert turn.turn_id and turn.turn_id != conv.conversation_id
        assert conv.turns == [turn]
        assert conv.updated_at >= original_updated

    def test_add_multiple_turns_preserves_order(self):
        conv = Conversation.create()
        conv.add_turn("user", "q1")
        conv.add_turn("assistant", "a1")
        conv.add_turn("user", "q2")
        assert [t.role for t in conv.turns] == ["user", "assistant", "user"]
        assert [t.content for t in conv.turns] == ["q1", "a1", "q2"]

    def test_add_turn_stores_metadata(self):
        conv = Conversation.create()
        turn = conv.add_turn("assistant", "hi", metadata={"tokens": 42})
        assert turn.metadata == {"tokens": 42}


class TestGetHistory:
    def test_get_history_returns_role_content_dicts(self):
        conv = Conversation.create()
        conv.add_turn("user", "q1")
        conv.add_turn("assistant", "a1")

        history = conv.get_history()
        assert history == [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ]

    def test_get_history_truncates_to_max_turns(self):
        conv = Conversation.create()
        for i in range(5):
            conv.add_turn("user", f"q{i}")
            conv.add_turn("assistant", f"a{i}")

        history = conv.get_history(max_turns=3)
        assert len(history) == 3
        # Should be the last 3
        assert history[-1] == {"role": "assistant", "content": "a4"}

    def test_get_history_empty(self):
        conv = Conversation.create()
        assert conv.get_history() == []


class TestToDict:
    def test_to_dict_roundtrip_shape(self):
        conv = Conversation.create(metadata={"src": "cli"})
        conv.add_turn("user", "hello", metadata={"n": 1})

        d = conv.to_dict()
        assert d["conversation_id"] == conv.conversation_id
        assert d["metadata"] == {"src": "cli"}
        assert len(d["turns"]) == 1
        assert d["turns"][0]["role"] == "user"
        assert d["turns"][0]["content"] == "hello"
        assert d["turns"][0]["metadata"] == {"n": 1}
        assert "turn_id" in d["turns"][0]
        assert "timestamp" in d["turns"][0]


class TestSchema:
    def test_schema_contains_required_tables(self):
        assert "CREATE TABLE IF NOT EXISTS conversations" in CONVERSATION_SCHEMA
        assert "CREATE TABLE IF NOT EXISTS conversation_turns" in CONVERSATION_SCHEMA
        assert "conversation_id" in CONVERSATION_SCHEMA
        # Cascade delete keeps memory consistent
        assert "ON DELETE CASCADE" in CONVERSATION_SCHEMA
