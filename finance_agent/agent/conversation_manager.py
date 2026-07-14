"""Conversation manager — handles multi-turn dialogue state and persistence.

Inspired by PydanticAI's RunContext and dependency injection patterns,
but implemented without requiring Python 3.10+.
"""
from __future__ import annotations
import json
import logging
import time
import uuid
from typing import Any

from .conversation import Conversation, ConversationTurn, CONVERSATION_SCHEMA

log = logging.getLogger(__name__)

class ConversationManager:
    """Manages conversation state and persistence.
    
    Provides conversation lifecycle management including creation,
    turn tracking, and history retrieval for multi-turn dialogue support.
    """
    
    def __init__(self, storage):
        self.storage = storage
        self._init_schema()
    
    def _init_schema(self):
        """Initialize conversation tables in database."""
        with self.storage._connect() as conn:
            conn.executescript(CONVERSATION_SCHEMA)
    
    def create_conversation(self, metadata: dict[str, Any] | None = None) -> Conversation:
        """Create and persist a new conversation."""
        conv = Conversation.create(metadata=metadata)
        with self.storage._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, created_at, updated_at, metadata_json) VALUES (?, ?, ?, ?)",
                (conv.conversation_id, conv.created_at, conv.updated_at, json.dumps(conv.metadata)),
            )
        log.info("Created conversation %s", conv.conversation_id)
        return conv
    
    def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Load a conversation with all its turns from storage."""
        with self.storage._connect() as conn:
            # Load conversation metadata
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if not row:
                return None
            
            conv = Conversation(
                conversation_id=row["id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            
            # Load all turns
            turns = conn.execute(
                "SELECT * FROM conversation_turns WHERE conversation_id = ? ORDER BY timestamp",
                (conversation_id,),
            ).fetchall()
            
            for t in turns:
                turn = ConversationTurn(
                    turn_id=t["id"],
                    conversation_id=t["conversation_id"],
                    role=t["role"],
                    content=t["content"],
                    timestamp=t["timestamp"],
                    metadata=json.loads(t["metadata_json"] or "{}"),
                )
                conv.turns.append(turn)
            
        return conv
    
    def add_turn(self, conversation_id: str, role: str, content: str, 
                 metadata: dict[str, Any] | None = None) -> ConversationTurn:
        """Add a turn to an existing conversation."""
        # Previously called Conversation.create() just to steal its UUID,
        # which also mutated timestamps for no reason. Use uuid4 directly.
        turn_id = str(uuid.uuid4())
        now = time.time()
        
        with self.storage._connect() as conn:
            conn.execute(
                "INSERT INTO conversation_turns (id, conversation_id, role, content, timestamp, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (turn_id, conversation_id, role, content, now, json.dumps(metadata or {})),
            )
            # Update conversation timestamp
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        
        log.debug("Added %s turn to conversation %s", role, conversation_id)
        return ConversationTurn(
            turn_id=turn_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            timestamp=now,
            metadata=metadata or {},
        )
    
    def get_history(self, conversation_id: str, max_turns: int | None = None) -> list[dict[str, str]]:
        """Get conversation history formatted for LLM context."""
        conv = self.get_conversation(conversation_id)
        if not conv:
            return []
        return conv.get_history(max_turns=max_turns)
    
    def list_conversations(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent conversations."""
        with self.storage._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "conversation_id": r["id"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
                for r in rows
            ]
    
    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its turns."""
        with self.storage._connect() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            return True

class ConversationContext:
    """Conversation context for managing multi-turn dialogue state.
    
    Provides a clean interface for tracking conversation history,
    adding turns, and retrieving formatted context for LLM calls.
    """
    
    def __init__(self, manager: ConversationManager, conversation_id: str | None = None):
        self.manager = manager
        self.conversation_id = conversation_id
        self._conversation: Conversation | None = None
    
    @property
    def conversation(self) -> Conversation | None:
        """Lazy-load conversation from storage."""
        if self._conversation is None and self.conversation_id:
            self._conversation = self.manager.get_conversation(self.conversation_id)
        return self._conversation
    
    def ensure_conversation(self, metadata: dict[str, Any] | None = None) -> Conversation:
        """Ensure a conversation exists, creating one if necessary."""
        if self.conversation_id:
            conv = self.manager.get_conversation(self.conversation_id)
            if conv:
                self._conversation = conv
                return conv
        
        # Create new conversation
        conv = self.manager.create_conversation(metadata=metadata)
        self.conversation_id = conv.conversation_id
        self._conversation = conv
        return conv
    
    def add_user_turn(self, content: str, metadata: dict[str, Any] | None = None) -> ConversationTurn:
        """Add a user turn to the current conversation."""
        conv = self.ensure_conversation()
        turn = self.manager.add_turn(conv.conversation_id, "user", content, metadata)
        # Invalidate the cached Conversation so ``self.conversation`` re-loads
        # from storage and includes this new turn on next access.
        self._conversation = None
        return turn
    
    def add_assistant_turn(self, content: str, metadata: dict[str, Any] | None = None) -> ConversationTurn:
        """Add an assistant turn to the current conversation."""
        conv = self.ensure_conversation()
        turn = self.manager.add_turn(conv.conversation_id, "assistant", content, metadata)
        self._conversation = None
        return turn
    
    def get_history(self, max_turns: int | None = None) -> list[dict[str, str]]:
        """Get formatted conversation history."""
        if not self.conversation_id:
            return []
        return self.manager.get_history(self.conversation_id, max_turns)
    
    def get_context_messages(self, max_turns: int = 10) -> list[dict[str, str]]:
        """Get conversation history as messages for LLM context window.
        
        Returns a list of message dicts suitable for passing to LLM APIs.
        """
        history = self.get_history(max_turns=max_turns)
        # Filter to only include user and assistant messages
        return [
            {"role": msg["role"], "content": msg["content"]}
            for msg in history
            if msg["role"] in ("user", "assistant")
        ]
