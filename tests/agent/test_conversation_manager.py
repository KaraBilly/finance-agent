"""Tests for ConversationManager + ConversationContext (short-term memory)."""
from __future__ import annotations

import pytest

from finance_agent.agent.conversation_manager import (
    ConversationContext,
    ConversationManager,
)
from finance_agent.providers.storage_sqlite import SQLiteStorageProvider


@pytest.fixture()
def storage(tmp_path):
    """Isolated SQLite storage under tmp_path."""
    db_path = tmp_path / "test.db"
    s = SQLiteStorageProvider(db_path=str(db_path))
    s.init()
    return s


@pytest.fixture()
def manager(storage):
    return ConversationManager(storage)


class TestConversationManagerCRUD:
    def test_create_conversation_persists(self, manager):
        conv = manager.create_conversation(metadata={"src": "unit-test"})
        loaded = manager.get_conversation(conv.conversation_id)

        assert loaded is not None
        assert loaded.conversation_id == conv.conversation_id
        assert loaded.metadata == {"src": "unit-test"}
        assert loaded.turns == []

    def test_get_missing_conversation_returns_none(self, manager):
        assert manager.get_conversation("does-not-exist") is None

    def test_add_turn_persists_and_orders(self, manager):
        conv = manager.create_conversation()
        manager.add_turn(conv.conversation_id, "user", "q1")
        manager.add_turn(conv.conversation_id, "assistant", "a1")
        manager.add_turn(conv.conversation_id, "user", "q2")

        loaded = manager.get_conversation(conv.conversation_id)
        assert [t.role for t in loaded.turns] == ["user", "assistant", "user"]
        assert [t.content for t in loaded.turns] == ["q1", "a1", "q2"]

    def test_add_turn_updates_conversation_updated_at(self, manager):
        conv = manager.create_conversation()
        original = manager.get_conversation(conv.conversation_id).updated_at
        manager.add_turn(conv.conversation_id, "user", "q1")
        after = manager.get_conversation(conv.conversation_id).updated_at
        assert after >= original

    def test_get_history_returns_formatted_messages(self, manager):
        conv = manager.create_conversation()
        manager.add_turn(conv.conversation_id, "user", "q1")
        manager.add_turn(conv.conversation_id, "assistant", "a1")

        history = manager.get_history(conv.conversation_id)
        assert history == [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ]

    def test_get_history_max_turns(self, manager):
        conv = manager.create_conversation()
        for i in range(4):
            manager.add_turn(conv.conversation_id, "user", f"q{i}")

        history = manager.get_history(conv.conversation_id, max_turns=2)
        assert len(history) == 2
        assert history[-1]["content"] == "q3"

    def test_get_history_for_missing_conversation_is_empty(self, manager):
        assert manager.get_history("nope") == []

    def test_list_conversations_orders_by_updated_at_desc(self, manager):
        c1 = manager.create_conversation()
        c2 = manager.create_conversation()
        # Touch c1 so it becomes the most recent
        manager.add_turn(c1.conversation_id, "user", "later")

        listed = manager.list_conversations(limit=10)
        ids = [row["conversation_id"] for row in listed]
        assert c1.conversation_id in ids
        assert c2.conversation_id in ids
        assert ids.index(c1.conversation_id) < ids.index(c2.conversation_id)

    def test_delete_conversation_cascades_turns(self, manager, storage):
        conv = manager.create_conversation()
        manager.add_turn(conv.conversation_id, "user", "q1")
        manager.add_turn(conv.conversation_id, "assistant", "a1")
        manager.delete_conversation(conv.conversation_id)

        # Conversation row is gone.
        assert manager.get_conversation(conv.conversation_id) is None
        with storage._connect() as c:
            n_conv = c.execute(
                "SELECT COUNT(*) AS n FROM conversations WHERE id = ?",
                (conv.conversation_id,),
            ).fetchone()["n"]
            n_turns = c.execute(
                "SELECT COUNT(*) AS n FROM conversation_turns WHERE conversation_id = ?",
                (conv.conversation_id,),
            ).fetchone()["n"]
        assert n_conv == 0
        # ON DELETE CASCADE removes turns because SQLiteStorageProvider now
        # enables `PRAGMA foreign_keys = ON` per connection.
        assert n_turns == 0


class TestConversationContext:
    def test_ensure_creates_when_no_id(self, manager):
        ctx = ConversationContext(manager, conversation_id=None)
        conv = ctx.ensure_conversation(metadata={"foo": "bar"})
        assert ctx.conversation_id == conv.conversation_id
        assert manager.get_conversation(conv.conversation_id) is not None

    def test_ensure_reuses_existing_conversation(self, manager):
        existing = manager.create_conversation()
        ctx = ConversationContext(manager, conversation_id=existing.conversation_id)
        conv = ctx.ensure_conversation()
        assert conv.conversation_id == existing.conversation_id

    def test_ensure_creates_new_when_id_not_found(self, manager):
        ctx = ConversationContext(manager, conversation_id="bogus-id")
        conv = ctx.ensure_conversation()
        assert ctx.conversation_id == conv.conversation_id
        assert ctx.conversation_id != "bogus-id"

    def test_add_user_and_assistant_turns_roundtrip(self, manager):
        ctx = ConversationContext(manager)
        ctx.add_user_turn("hello")
        ctx.add_assistant_turn("hi there")

        history = ctx.get_history()
        assert history == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

    def test_get_context_messages_filters_roles(self, manager):
        conv = manager.create_conversation()
        # Inject a non user/assistant turn directly
        manager.add_turn(conv.conversation_id, "user", "q1")
        manager.add_turn(conv.conversation_id, "system", "should-be-filtered")
        manager.add_turn(conv.conversation_id, "assistant", "a1")

        ctx = ConversationContext(manager, conversation_id=conv.conversation_id)
        msgs = ctx.get_context_messages()
        roles = [m["role"] for m in msgs]
        assert "system" not in roles
        assert roles == ["user", "assistant"]

    def test_get_history_without_conversation_is_empty(self, manager):
        ctx = ConversationContext(manager, conversation_id=None)
        assert ctx.get_history() == []
