"""User-preference memory — long-term interests.

Each turn, doubao extracts a small JSON delta from the (question, answer) pair,
which we merge into the user_prefs table with an EMA on the weight.
Topics use snake_case; keep them stable across turns.
"""
from __future__ import annotations
import logging
from ..capabilities.llm import LLMCapability, ChatMessage
from ..capabilities.storage import StorageCapability

log = logging.getLogger(__name__)

_TOPIC_HINTS = [
    "liquidity_risk", "debt_maturity", "cash_flow", "profitability",
    "competition", "regulatory_risk", "esg", "valuation",
    "dividend_policy", "supply_chain", "management_quality", "capex",
]

SYSTEM = f"""You extract long-term user preferences from a single financial Q&A turn.
Choose from these stable topic slugs (add new snake_case slugs only if none fit):
{_TOPIC_HINTS}

Return STRICT JSON:
{{
  "prefs": [
    {{"topic": "<slug>", "delta": <float in [-1, 1]>, "note": "<short reason>"}}
  ]
}}
Use positive delta (0.1-0.5) when the user asks about the topic; higher when explicit
("我更关心 liquidity risk"). Negative delta only if the user explicitly says
they don't care. If nothing to record, return prefs=[].
"""

_EMA_ALPHA = 0.4


def extract_and_update(model: LLMCapability, storage: StorageCapability,
                       question: str, answer: str,
                       answer_id: int | None = None) -> list[dict]:
    """Extract user preferences from Q&A and persist via StorageCapability."""
    user = f"# Question\n{question}\n\n# Answer\n{answer[:2000]}\n\nReturn JSON."
    try:
        obj = model.chat_json(
            [ChatMessage("system", SYSTEM), ChatMessage("user", user)],
            temperature=0.0,
        )
    except Exception as e:
        log.warning("memory extract failed: %s", e)
        return []
    updated: list[dict] = []
    for p in obj.get("prefs", []):
        topic = str(p.get("topic", "")).strip().lower()
        delta = float(p.get("delta", 0))
        if not topic or delta == 0:
            continue
        # merge with existing weight via EMA
        current = _current_weight(storage, topic)
        new_weight = max(0.0, min(1.0, (1 - _EMA_ALPHA) * current + _EMA_ALPHA * (current + delta)))
        storage.upsert_pref(topic, new_weight, note=str(p.get("note", ""))[:200],
                            evidence_answer_id=answer_id)
        updated.append({"topic": topic, "weight": new_weight, "delta": delta})
    return updated


def _current_weight(storage: StorageCapability, topic: str) -> float:
    for p in storage.load_prefs(limit=1000):
        if p["topic"] == topic:
            return float(p["weight"])
    return 0.0
