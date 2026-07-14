"""OpenAI-compatible LLM providers (Doubao via Ark, DeepSeek)."""
from __future__ import annotations
import json
import logging
from typing import Any

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..capabilities.llm import LLMCapability, ChatMessage
from ..config import CONFIG

log = logging.getLogger(__name__)


class OpenAICompatibleLLM(LLMCapability):
    """Base provider for any OpenAI-compatible API."""

    default_temperature: float = 0.3

    def __init__(self, *, api_key: str, base_url: str, model: str, name: str = "llm"):
        if not api_key:
            raise RuntimeError(f"{name}: api_key is empty; check .env")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.name = name

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    def chat(
        self,
        messages: list[ChatMessage] | list[dict],
        *,
        temperature: float | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        payload: list[dict] = [
            m.to_dict() if isinstance(m, ChatMessage) else m for m in messages
        ]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": payload,
            "temperature": temperature if temperature is not None else self.default_temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            # 火山方舟等部分模型不支持 json_object，改用 prompt 方式
            base_url = str(self.client.base_url)
            if "ark.cn-beijing.volces.com" in base_url:
                # 在 system 或 user message 中追加 JSON 格式要求
                if payload and payload[0].get("role") == "system":
                    payload[0]["content"] += "\n\n请直接输出 JSON 格式，不要包含 markdown 代码块标记。"
                else:
                    payload.insert(0, {
                        "role": "system",
                        "content": "请直接输出 JSON 格式，不要包含 markdown 代码块标记。"
                    })
            else:
                kwargs["response_format"] = {"type": "json_object"}
        log.debug("[%s] chat model=%s json=%s msgs=%d", self.name, self.model, json_mode, len(payload))
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def chat_json(self, messages: list[ChatMessage] | list[dict], **kw) -> dict:
        raw = self.chat(messages, json_mode=True, **kw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start : end + 1])
            raise


class DoubaoProvider(OpenAICompatibleLLM):
    """doubao-seed-evolving via 火山方舟 Ark."""

    def __init__(self, model: str | None = None):
        CONFIG.require("ark_api_key")
        super().__init__(
            api_key=CONFIG.ark_api_key,
            base_url=CONFIG.ark_base_url,
            model=model or CONFIG.doubao_model,
            name="doubao",
        )


class DeepSeekProvider(OpenAICompatibleLLM):
    """DeepSeek via OpenAI-compatible endpoint."""

    default_temperature = 0.2

    def __init__(self, model: str | None = None):
        CONFIG.require("deepseek_api_key")
        super().__init__(
            api_key=CONFIG.deepseek_api_key,
            base_url=CONFIG.deepseek_base_url,
            model=model or CONFIG.deepseek_model,
            name="deepseek",
        )
