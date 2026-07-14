"""Planner — turns a natural-language question + user prefs into a ToolPlan.

Runs on doubao via a pydantic-ai :class:`Agent` with a strict
:class:`ToolPlan` output schema, so the caller receives a validated object
rather than a hand-parsed JSON blob.

Exposed publicly:
  * :class:`ToolPlan`, :class:`ToolCall`, :class:`ToolPlanIntent` — schemas
  * :func:`plan` — the loop entry point (returns ``dict`` for back-compat)
  * :func:`build_planner_agent` — factory used by tests / advanced callers to
    inject their own model (``TestModel`` / ``FunctionModel``)
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ..capabilities.llm import LLMCapability
from ..providers.llm_openai import OpenAICompatibleLLM
from .pydantic_runtime import build_agent

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output schema — validated by pydantic-ai on every call
# ---------------------------------------------------------------------------

ToolPlanIntent = Literal[
    "company_deep_dive",
    "index_overview",
    "general_web",
]

ToolName = Literal[
    "market.index",
    "market.stock",
    "financials",
    "filings",
    "web",
]

class ToolCall(BaseModel):
    """A single tool invocation emitted by the planner."""

    tool: ToolName
    args: dict[str, Any] = Field(default_factory=dict)

class ToolPlan(BaseModel):
    """Full plan for a single user question."""

    intent: ToolPlanIntent = "general_web"
    entities: dict[str, Any] = Field(default_factory=dict)
    tools: list[ToolCall] = Field(default_factory=list)
    answer_sections: list[str] = Field(default_factory=lambda: ["Summary", "Evidence"])

# ---------------------------------------------------------------------------
# System prompt (identical intent to the pre-pydantic-ai version)
# ---------------------------------------------------------------------------

SYSTEM = """You are the planning module of a personal finance agent that supports both US and Chinese A-share markets.
Given the user question and their stored preferences, produce a ToolPlan that
selects which tools to call and with what arguments. Available tools:

  market.index        args: {symbols:[str], years:int}    # index summaries (supports both US and A-share indices)
  market.stock        args: {symbol:str, lookback_days:int}  # single-stock price behaviour
  financials          args: {symbol:str, kinds:[income|balance|cashflow], periods:int}
  filings             args: {symbol:str, years_back:int}   # SEC filings for US, cninfo for A-share
  web                 args: {queries:[str]}                # Tavily + Trafilatura for news/opinion

Rules:
- Determine the market (US or A-share) from the user question semantics, not from any configuration.
- For US stocks: use US stock symbols (e.g., AAPL, TSLA, SPY, QQQ).
- For A-share stocks: use A-share stock symbols (e.g., 000001, 600000, 上证指数).
- Prefer structured tools (financials/filings/market) over web when the question is factual.
- If the question mentions liquidity/debt/cash flow, always include financials with the relevant statement.
- If the question asks about competition/risk factors qualitatively, include web + filings.
- If entities are unclear, still return a plan; put a web query to disambiguate.
- User preferences (topics with weights) should influence tool selection AND answer_sections.
"""

# ---------------------------------------------------------------------------
# Agent factory + public entry point
# ---------------------------------------------------------------------------

def build_planner_agent(llm: OpenAICompatibleLLM) -> Agent[None, ToolPlan]:
    """Build the pydantic-ai agent used by :func:`plan`.

    Split out so tests can swap in a ``TestModel`` via ``agent.override(...)``.
    """
    return build_agent(llm, output_type=ToolPlan, system_prompt=SYSTEM)

def _format_user_prompt(question: str, prefs: list[dict],
                        history: list[dict[str, str]] | None) -> str:
    prefs_str = (
        "\n".join(f"- {p['topic']} (weight={p['weight']:.2f})" for p in prefs)
        or "(none)"
    )
    parts: list[str] = []
    if history:
        # Fold history into the user message so we don't have to smuggle
        # multi-turn state through pydantic-ai's ``message_history`` — which
        # would require converting our ChatMessage dicts into
        # ``ModelMessage`` objects for every call.
        hist_lines = [f"{m['role'].upper()}: {m['content']}" for m in history]
        parts.append("Prior turns:\n" + "\n".join(hist_lines))
    parts.append(f"User question:\n{question}")
    parts.append(f"User preferences:\n{prefs_str}")
    parts.append("Return a ToolPlan.")
    return "\n\n".join(parts)

def plan(model: LLMCapability, question: str, prefs: list[dict],
         history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Produce a ToolPlan dict for the given question.

    Returned as a plain ``dict`` (not the :class:`ToolPlan` instance itself) so
    the surrounding :mod:`finance_agent.agent.loop` code — which treats the
    plan as loose JSON — keeps working unchanged.
    """
    if not isinstance(model, OpenAICompatibleLLM):
        raise TypeError(
            "planner.plan requires an OpenAICompatibleLLM (Doubao / DeepSeek); "
            f"got {type(model).__name__}"
        )

    agent = build_planner_agent(model)
    prompt = _format_user_prompt(question, prefs, history)
    result = agent.run_sync(prompt)
    tp: ToolPlan = result.output
    log.info(
        "plan: intent=%s tools=%s",
        tp.intent,
        [t.tool for t in tp.tools],
    )
    return tp.model_dump()
