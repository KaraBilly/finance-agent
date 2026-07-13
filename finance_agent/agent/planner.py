"""Planner — turns a natural-language question + user prefs into a ToolPlan.

Uses doubao in JSON mode. Output schema:
{
  "intent":  "company_deep_dive" | "index_overview" | "general_web",
  "entities": {"symbol": "AAPL", "name": "苹果"} | {},
  "tools": [
     {"tool": "market_us.index", "args": {"symbols": ["QQQ","SPY"], "years": 20}},
     {"tool": "market_us.stock", "args": {"symbol": "AAPL", "lookback_days": 365}},
     {"tool": "financials_us",   "args": {"symbol": "AAPL", "kinds": ["income","balance","cashflow"]}},
     {"tool": "filings_us",      "args": {"symbol": "AAPL", "years_back": 2}},
     {"tool": "web",             "args": {"queries": ["Apple 竞争 风险"]}}
  ],
  "answer_sections": ["Summary","Key Numbers","Risks","Evidence"]
}
"""
from __future__ import annotations
import logging
from typing import Any

from ..capabilities.llm import LLMCapability, ChatMessage

log = logging.getLogger(__name__)

# Unified system prompt - market determined by semantic analysis of user question
SYSTEM = """You are the planning module of a personal finance agent that supports both US and Chinese A-share markets.
Given the user question and their stored preferences, output a JSON ToolPlan that
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
- User preferences (topics with weights) should influence tool selection AND `answer_sections`.
- Return STRICT JSON only, no prose. Keys: intent, entities, tools, answer_sections.
"""


def plan(model: LLMCapability, question: str, prefs: list[dict], 
         history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    # Use unified system prompt - market determined by semantic analysis
    prefs_str = "\n".join(f"- {p['topic']} (weight={p['weight']:.2f})" for p in prefs) or "(none)"
    
    # Build messages with optional conversation history
    messages = [ChatMessage("system", SYSTEM)]
    
    # Add conversation history if available
    if history:
        for msg in history:
            messages.append(ChatMessage(msg["role"], msg["content"]))
    
    user = f"User question:\n{question}\n\nUser preferences:\n{prefs_str}\n\nReturn ToolPlan JSON."
    messages.append(ChatMessage("user", user))
    
    obj = model.chat_json(messages, temperature=0.1)
    # minimal shape check
    obj.setdefault("tools", [])
    obj.setdefault("entities", {})
    obj.setdefault("answer_sections", ["Summary", "Evidence"])
    # Normalise tool entries — GPT-5.x tends to emit {"name": ...} while
    # Doubao follows the prompt and emits {"tool": ...}. Downstream code
    # expects "tool"/"args".
    for t in obj["tools"]:
        if "tool" not in t and "name" in t:
            t["tool"] = t.pop("name")
        if "tool" not in t and "tool_name" in t:
            t["tool"] = t.pop("tool_name")
        if "args" not in t and "arguments" in t:
            t["args"] = t.pop("arguments")
    log.info("plan: intent=%s tools=%s", obj.get("intent"), [t.get("tool") for t in obj["tools"]])
    return obj
