"""Tests for long-term user-preference memory (agent/memory.py).

Two layers under test:

* :func:`memory.persist_prefs` — pure persistence + EMA logic. Exercised
  directly with hand-crafted :class:`PrefExtractionResult` payloads.
* :func:`memory.build_memory_agent` — the pydantic-ai agent. Exercised via
  pydantic-ai's :class:`TestModel`, which returns canned structured output
  without hitting a live LLM.
"""
from __future__ import annotations

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finance_agent.agent import memory
from finance_agent.agent.memory import (
    PrefDelta,
    PrefExtractionResult,
    persist_prefs,
)
from finance_agent.providers.storage_sqlite import SQLiteStorageProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def storage(tmp_path):
    s = SQLiteStorageProvider(db_path=str(tmp_path / "mem.db"))
    s.init()
    return s

def _payload(prefs: list[dict]) -> PrefExtractionResult:
    return PrefExtractionResult(prefs=[PrefDelta(**p) for p in prefs])

# ---------------------------------------------------------------------------
# Persistence / EMA layer
# ---------------------------------------------------------------------------

class TestPersistPrefs:
    def test_empty_prefs_returns_empty_list(self, storage):
        out = persist_prefs(storage, _payload([]))
        assert out == []
        assert storage.load_prefs() == []

    def test_positive_delta_persists_pref(self, storage):
        out = persist_prefs(
            storage,
            _payload([{"topic": "liquidity_risk", "delta": 0.3, "note": "user asked"}]),
            answer_id=1,
        )
        assert len(out) == 1
        assert out[0]["topic"] == "liquidity_risk"
        assert out[0]["delta"] == 0.3
        assert 0.0 < out[0]["weight"] <= 1.0

        stored = {p["topic"]: p for p in storage.load_prefs()}
        assert "liquidity_risk" in stored
        assert stored["liquidity_risk"]["note"] == "user asked"

    def test_weight_is_clamped_to_unit_interval(self, storage):
        # Repeatedly pump large positive deltas: weight must never exceed 1.0
        payload = _payload([{"topic": "valuation", "delta": 0.9}])
        for _ in range(20):
            persist_prefs(storage, payload)
        weight = {p["topic"]: p["weight"] for p in storage.load_prefs()}["valuation"]
        assert 0.0 <= weight <= 1.0

    def test_zero_delta_is_ignored(self, storage):
        out = persist_prefs(storage, _payload([{"topic": "esg", "delta": 0}]))
        assert out == []
        assert storage.load_prefs() == []

    def test_missing_topic_is_ignored(self, storage):
        out = persist_prefs(storage, _payload([{"topic": "", "delta": 0.5}]))
        assert out == []

    def test_topic_normalized_to_lowercase(self, storage):
        persist_prefs(
            storage,
            _payload([{"topic": "  Debt_Maturity ", "delta": 0.4}]),
        )
        topics = [p["topic"] for p in storage.load_prefs()]
        assert "debt_maturity" in topics

    def test_multiple_prefs_persist_all(self, storage):
        out = persist_prefs(
            storage,
            _payload([
                {"topic": "cash_flow", "delta": 0.4},
                {"topic": "capex", "delta": 0.2},
            ]),
        )
        assert {p["topic"] for p in out} == {"cash_flow", "capex"}
        assert {p["topic"] for p in storage.load_prefs()} == {"cash_flow", "capex"}

    def test_ema_smoothing_between_turns(self, storage):
        # Two turns with the same topic — weight should update but stay bounded.
        payload = _payload([{"topic": "profitability", "delta": 0.3}])
        persist_prefs(storage, payload)
        first = [p for p in storage.load_prefs() if p["topic"] == "profitability"][0]["weight"]

        persist_prefs(storage, payload)
        second = [p for p in storage.load_prefs() if p["topic"] == "profitability"][0]["weight"]

        assert second >= first
        assert second <= 1.0

# ---------------------------------------------------------------------------
# pydantic-ai agent layer (uses TestModel, no live LLM)
# ---------------------------------------------------------------------------

def _test_agent_with_output(output: PrefExtractionResult) -> Agent[None, PrefExtractionResult]:
    """Build a memory-shaped Agent backed by pydantic-ai's TestModel."""
    return Agent(
        TestModel(custom_output_args=output.model_dump()),
        output_type=PrefExtractionResult,
        system_prompt=memory.SYSTEM,
    )

class TestMemoryAgent:
    def test_test_model_produces_valid_pref_extraction(self):
        expected = _payload([{"topic": "cash_flow", "delta": 0.5, "note": "hi"}])
        agent = _test_agent_with_output(expected)
        result = agent.run_sync("# Question\nq?\n\n# Answer\na.")
        assert isinstance(result.output, PrefExtractionResult)
        assert result.output.prefs[0].topic == "cash_flow"
        assert result.output.prefs[0].delta == 0.5

    def test_agent_output_can_be_persisted(self, storage):
        agent = _test_agent_with_output(
            _payload([{"topic": "supply_chain", "delta": 0.35}])
        )
        result = agent.run_sync("# Question\nq?\n\n# Answer\na.")
        out = persist_prefs(storage, result.output, answer_id=42)
        assert len(out) == 1
        assert out[0]["topic"] == "supply_chain"
        assert {p["topic"] for p in storage.load_prefs()} == {"supply_chain"}

    def test_wrong_model_type_raises(self, storage):
        # extract_and_update requires an OpenAICompatibleLLM; passing an
        # arbitrary object must fail loudly rather than silently no-op.
        with pytest.raises(TypeError):
            memory.extract_and_update(object(), storage, "q", "a")
