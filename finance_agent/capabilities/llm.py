"""LLM Capability — abstract interface for language models."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass
class ChatMessage:
    role: Role
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


class LLMCapability(ABC):
    """Abstract LLM interface. Agent depends on this, not concrete providers."""
    
    name: str = "llm"

    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage] | list[dict],
        *,
        temperature: float | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        """Send messages and get a text response."""
        ...

    @abstractmethod
    def chat_json(
        self,
        messages: list[ChatMessage] | list[dict],
        **kwargs,
    ) -> dict:
        """Chat and parse JSON response."""
        ...
