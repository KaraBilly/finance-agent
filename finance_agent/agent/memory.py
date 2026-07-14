"""User-preference memory — long-term interests.

Each turn, doubao (via a pydantic-ai :class:`Agent` with a
:class:`PrefExtractionResult` output schema) extracts a small structured delta
from the (question, answer) pair, which we merge into the ``user_prefs`` table
with an EMA on the weight. Topics use snake_case; keep them stable across turns.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ..capabilities.llm import LLMCapability
from ..capabilities.storage import StorageCapability
from ..providers.llm_openai import OpenAICompatibleLLM
from .pydantic_runtime import build_agent

log = logging.getLogger(__name__)

_TOPIC_HINTS = [
    "liquidity_risk", "debt_maturity", "cash_flow", "profitability",
    "competition", "regulatory_risk", "esg", "valuation",
    "dividend_policy", "supply_chain", "management_quality", "capex",
]

_EMA_ALPHA = 0.4

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class PrefDelta(BaseModel):
    """A single preference update emitted by the memory extractor."""

    topic: str = Field(..., description="snake_case topic slug")
    delta: float = Field(..., ge=-1.0, le=1.0,
                         description="Positive when user cares more; negative when user cares less")
    note: str = Field("", max_length=200, description="Short reason")

class PrefExtractionResult(BaseModel):
    """Result envelope — always a list, may be empty."""

    prefs: list[PrefDelta] = Field(default_factory=list)

SYSTEM = f"""You extract long-term user preferences from a single financial Q&A turn.
Choose from these stable topic slugs (add new snake_case slugs only if none fit):
{_TOPIC_HINTS}

Use positive delta (0.1-0.5) when the user asks about the topic; higher when explicit
("我更关心 liquidity risk"). Negative delta only if the user explicitly says
they don't care. If nothing to record, return prefs=[].
"""

# ---------------------------------------------------------------------------
# Agent factory + public entry point
# ---------------------------------------------------------------------------

def build_memory_agent(llm: OpenAICompatibleLLM) -> Agent[None, PrefExtractionResult]:
    """Build the pydantic-ai agent used by :func:`extract_and_update`.

    Exposed so tests can inject a ``TestModel`` via ``agent.override(...)``.
    """
    return build_agent(llm, output_type=PrefExtractionResult, system_prompt=SYSTEM)

def extract_and_update(model: LLMCapability, storage: StorageCapability,
                       question: str, answer: str,
                       answer_id: int | None = None) -> list[dict]:
    """Extract user preferences from Q&A and persist via StorageCapability."""
    if not isinstance(model, OpenAICompatibleLLM):
        raise TypeError(
            "memory.extract_and_update requires an OpenAICompatibleLLM "
            f"(Doubao / DeepSeek); got {type(model).__name__}"
        )

    user = f"# Question\n{question}\n\n# Answer\n{answer[:2000]}"
    try:
        agent = build_memory_agent(model)
        result = agent.run_sync(user)
        payload = result.output
    except Exception as e:
        log.warning("memory extract failed: %s", e)
        return []

    return persist_prefs(storage, payload, answer_id=answer_id)


def persist_prefs(storage: StorageCapability, payload: PrefExtractionResult,
                  *, answer_id: int | None = None) -> list[dict]:
    """Apply a :class:`PrefExtractionResult` to storage with EMA smoothing.

    Split out from :func:`extract_and_update` so tests can exercise the
    persistence / EMA logic without spinning up a pydantic-ai agent.
    """
    updated: list[dict] = []
    for p in payload.prefs:
        topic = p.topic.strip().lower()
        delta = float(p.delta)
        if not topic or delta == 0:
            continue
        # Merge with existing weight via EMA against a clipped target.
        # Original code was ``new = (1-α)·current + α·(current+delta)`` which
        # algebraically simplifies to ``current + α·delta`` — a plain
        # linear step, not an EMA. Correct EMA is toward a target value; we
        # clip the target into [0, 1] first so a single large delta cannot
        # drag ``new_weight`` outside the valid range once smoothed.
        current = _current_weight(storage, topic)
        target = max(0.0, min(1.0, current + delta))
        new_weight = (1 - _EMA_ALPHA) * current + _EMA_ALPHA * target
        storage.upsert_pref(topic, new_weight, note=p.note[:200],
                            evidence_answer_id=answer_id)
        updated.append({"topic": topic, "weight": new_weight, "delta": delta})
    return updated

def _current_weight(storage: StorageCapability, topic: str) -> float:
    for p in storage.load_prefs(limit=1000):
        if p["topic"] == topic:
            return float(p["weight"])
    return 0.0
