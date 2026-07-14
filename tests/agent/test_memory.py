"""Tests for long-term user-preference memory (agent/memory.py)."""
from __future__ import annotations

import pytest

from finance_agent.agent import memory
from finance_agent.capabilities.llm import LLMCapability
from finance_agent.providers.storage_sqlite import SQLiteStorageProvider


class FakeLLM(LLMCapability):
    """Minimal LLM stub that returns a pre-programmed JSON payload."""

    name = "fake-llm"

    def __init__(self, payload=None, raise_exc=None):
        self.payload = payload if payload is not None else {"prefs": []}
        self.raise_exc = raise_exc
        self.calls: list[tuple] = []

    def chat(self, messages, **kwargs):
        raise NotImplementedError

    def chat_json(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.raise_exc:
            raise self.raise_exc
        return self.payload


@pytest.fixture()
def storage(tmp_path):
    s = SQLiteStorageProvider(db_path=str(tmp_path / "mem.db"))
    s.init()
    return s


class TestExtractAndUpdate:
    def test_empty_prefs_returns_empty_list(self, storage):
        llm = FakeLLM(payload={"prefs": []})
        out = memory.extract_and_update(llm, storage, "q?", "a.")
        assert out == []
        assert storage.load_prefs() == []

    def test_positive_delta_persists_pref(self, storage):
        llm = FakeLLM(payload={
            "prefs": [{"topic": "liquidity_risk", "delta": 0.3, "note": "user asked"}]
        })
        out = memory.extract_and_update(llm, storage, "any q", "any a", answer_id=1)
        assert len(out) == 1
        assert out[0]["topic"] == "liquidity_risk"
        assert out[0]["delta"] == 0.3
        assert 0.0 < out[0]["weight"] <= 1.0

        stored = {p["topic"]: p for p in storage.load_prefs()}
        assert "liquidity_risk" in stored
        assert stored["liquidity_risk"]["note"] == "user asked"

    def test_weight_is_clamped_to_unit_interval(self, storage):
        # Repeatedly pump large positive deltas: weight must never exceed 1.0
        llm = FakeLLM(payload={"prefs": [{"topic": "valuation", "delta": 0.9}]})
        for _ in range(20):
            memory.extract_and_update(llm, storage, "q", "a")
        weight = {p["topic"]: p["weight"] for p in storage.load_prefs()}["valuation"]
        assert 0.0 <= weight <= 1.0

    def test_zero_delta_is_ignored(self, storage):
        llm = FakeLLM(payload={"prefs": [{"topic": "esg", "delta": 0}]})
        out = memory.extract_and_update(llm, storage, "q", "a")
        assert out == []
        assert storage.load_prefs() == []

    def test_missing_topic_is_ignored(self, storage):
        llm = FakeLLM(payload={"prefs": [{"topic": "", "delta": 0.5}]})
        out = memory.extract_and_update(llm, storage, "q", "a")
        assert out == []

    def test_topic_normalized_to_lowercase(self, storage):
        llm = FakeLLM(payload={
            "prefs": [{"topic": "  Debt_Maturity ", "delta": 0.4}]
        })
        memory.extract_and_update(llm, storage, "q", "a")
        topics = [p["topic"] for p in storage.load_prefs()]
        assert "debt_maturity" in topics

    def test_llm_exception_returns_empty_and_does_not_raise(self, storage):
        llm = FakeLLM(raise_exc=RuntimeError("boom"))
        out = memory.extract_and_update(llm, storage, "q", "a")
        assert out == []
        assert storage.load_prefs() == []

    def test_multiple_prefs_persist_all(self, storage):
        llm = FakeLLM(payload={"prefs": [
            {"topic": "cash_flow", "delta": 0.4},
            {"topic": "capex", "delta": 0.2},
        ]})
        out = memory.extract_and_update(llm, storage, "q", "a")
        assert {p["topic"] for p in out} == {"cash_flow", "capex"}
        assert {p["topic"] for p in storage.load_prefs()} == {"cash_flow", "capex"}

    def test_ema_smoothing_between_turns(self, storage):
        # Two turns with the same topic — weight should update but stay bounded.
        llm = FakeLLM(payload={"prefs": [{"topic": "profitability", "delta": 0.3}]})
        memory.extract_and_update(llm, storage, "q1", "a1")
        first = [p for p in storage.load_prefs() if p["topic"] == "profitability"][0]["weight"]

        memory.extract_and_update(llm, storage, "q2", "a2")
        second = [p for p in storage.load_prefs() if p["topic"] == "profitability"][0]["weight"]

        assert second >= first
        assert second <= 1.0
