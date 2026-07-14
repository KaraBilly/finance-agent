"""pydantic-ai runtime adapter.

Wraps our :class:`OpenAICompatibleLLM` providers (Doubao via Ark, DeepSeek)
into a pydantic-ai :class:`Agent`, so planner / verifier / memory can declare
their expected output as a :class:`pydantic.BaseModel` and get schema-validated
responses back — without having to hand-parse JSON.

Why a thin adapter rather than a direct dependency:
  * Ark's Chat Completions endpoint doesn't honour ``response_format=json_object``,
    so pydantic-ai's normal structured-output path (which prefers JSON mode)
    would silently fall back to plain text. We nudge the model via an extra
    system instruction — matching the workaround already used in
    :mod:`finance_agent.providers.llm_openai`.
  * Keeping the pydantic-ai construction in one place makes it trivial to swap
    LLM backends later (Anthropic, Google, local) without touching planner /
    verifier / memory.
"""
from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from ..providers.llm_openai import OpenAICompatibleLLM

TOut = TypeVar("TOut", bound=BaseModel)

# Some upstreams (火山方舟 Ark) reject ``response_format=json_object`` even when
# the pydantic-ai OpenAI backend tries to enable it. Detect them by base_url so
# we can add a belt-and-braces prompt instruction instead of a hard
# ``response_format`` constraint.
_ARK_HOST_MARKERS = ("ark.cn-beijing.volces.com",)

def _is_ark(base_url: str) -> bool:
    return any(marker in base_url for marker in _ARK_HOST_MARKERS)

def build_agent(
    llm: OpenAICompatibleLLM,
    *,
    output_type: type[TOut],
    system_prompt: str,
) -> Agent[None, TOut]:
    """Construct a pydantic-ai :class:`Agent` backed by ``llm``.

    Parameters
    ----------
    llm:
        One of our OpenAI-compatible providers (Doubao / DeepSeek). Its
        ``api_key`` / ``base_url`` / ``model`` are re-used verbatim so we don't
        double up on env-var reads.
    output_type:
        A :class:`pydantic.BaseModel` subclass. The agent will validate the
        model response against this schema; a validation failure triggers
        pydantic-ai's built-in single retry.
    system_prompt:
        The system prompt for the underlying model.
    """
    base_url = str(llm.client.base_url)
    provider = OpenAIProvider(api_key=llm.client.api_key, base_url=base_url)
    model = OpenAIChatModel(model_name=llm.model, provider=provider)

    prompt = system_prompt
    if _is_ark(base_url):
        # Ark needs an explicit reminder; without it the model happily wraps
        # the JSON in ```json fences and pydantic-ai's parser rejects the
        # payload.
        prompt = (
            prompt
            + "\n\nIMPORTANT: Reply with pure JSON matching the requested schema. "
            "Do not wrap it in markdown code fences."
        )

    return Agent(
        model,
        output_type=output_type,
        system_prompt=prompt,
        # One automatic retry on schema-validation failure. Matches the
        # ``tenacity`` retry count used in :class:`OpenAICompatibleLLM.chat`.
        retries=1,
    )
