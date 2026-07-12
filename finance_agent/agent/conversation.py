"""Conversation data models and database schema for multi-turn dialogue."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
import uuid


@dataclass
class ConversationTurn:
    """Single turn in a conversation."""
    turn_id: str
    conversation_id: str
    role: str  # "user" or "assistant"
    content: str
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Conversation:
    """A multi-turn conversation session."""
    conversation_id: str
    created_at: float
    updated_at: float
    turns: list[ConversationTurn] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def create(cls, metadata: dict[str, Any] | None = None) -> "Conversation":
        """Create a new conversation with auto-generated ID."""
        now = datetime.now().timestamp()
        return cls(
            conversation_id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
    
    def add_turn(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> ConversationTurn:
        """Add a new turn to the conversation."""
        turn = ConversationTurn(
            turn_id=str(uuid.uuid4()),
            conversation_id=self.conversation_id,
            role=role,
            content=content,
            timestamp=datetime.now().timestamp(),
            metadata=metadata or {},
        )
        self.turns.append(turn)
        self.updated_at = turn.timestamp
        return turn
    
    def get_history(self, max_turns: int | None = None) -> list[dict[str, str]]:
        """Get conversation history as list of message dicts for LLM context."""
        turns = self.turns if max_turns is None else self.turns[-max_turns:]
        return [
            {"role": t.role, "content": t.content}
            for t in turns
        ]
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize conversation to dict."""
        return {
            "conversation_id": self.conversation_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "turns": [
                {
                    "turn_id": t.turn_id,
                    "role": t.role,
                    "content": t.content,
                    "timestamp": t.timestamp,
                    "metadata": t.metadata,
                }
                for t in self.turns
            ],
        }


# SQL Schema for conversation tables
CONVERSATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id              TEXT PRIMARY KEY,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    metadata_json   TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS conversation_turns (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    metadata_json   TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_turns_conversation 
    ON conversation_turns(conversation_id, timestamp);
"""
