"""Main agent loop — orchestrates planner → tools → synth → verify → memory.

Architecture:
  Finance Agent (this file)
       │
  Capability Layer (abstract interfaces)
       │
  Provider Layer (concrete implementations, swappable)
       │
  External APIs (eastmoney, cninfo, Tavily, Ark, DeepSeek, etc.)

Two-model orchestration:
  planner_llm     — planning, reranking, verification, memory extraction
  synthesizer_llm — final answer synthesis (with optional 1 repair pass)
"""
from __future__ import annotations
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..capabilities.base import Evidence
from ..registry import ProviderRegistry, create_default_registry
from . import planner, synthesizer, verifier, memory

log = logging.getLogger(__name__)

@dataclass
class AgentResult:
    question: str
    answer_md: str
    evidences: list[Evidence]
    plan: dict
    trace: dict
    answer_id: int
    prefs_updated: list[dict] = field(default_factory=list)

class AgentLoop:
    """Finance Agent — depends only on Capability interfaces, not concrete providers.
    
    To swap providers (e.g., eastmoney → an internal proprietary feed, Tavily → DuckDuckGo):
      1. Create new provider implementing the Capability interface
      2. Pass custom ProviderRegistry to __init__
      3. Agent code remains unchanged
    """
    
    def __init__(self, registry: ProviderRegistry | None = None):
        self.registry = registry or create_default_registry()
        
        # Initialize storage
        self.registry.storage.init()
        
        # Aliases for cleaner code
        self._planner_llm = self.registry.planner_llm
        self._synth_llm = self.registry.synthesizer_llm
        self._market = self.registry.market_data
        self._financials = self.registry.financials
        self._filings = self.registry.filings
        self._web = self.registry.web_search
        self._storage = self.registry.storage

    # ---------- tool dispatch ----------
    def _run_tools(self, tool_calls: list[dict]) -> list[Evidence]:
        """Execute tool calls and collect evidence. Uses Capability interfaces."""
        evs: list[Evidence] = []
        for t in tool_calls:
            # Accept either {"tool": ...} or {"name": ...} — different LLMs
            # (Doubao vs GPT-5.x) prefer different keys despite the same prompt.
            name = t.get("tool") or t.get("name") or ""
            args = t.get("args") or t.get("arguments") or {}
            try:
                if name == "market_cn.index":
                    symbols = args.get("symbols") or list(self._market.list_available_indices().keys())[:3]
                    years = int(args.get("years", 20))
                    for sym in symbols:
                        try:
                            ev = self._market.summarize_index(sym, lookback_years=years)
                            evs.append(self._storage.register_evidence(ev))
                        except Exception as e:
                            log.warning("summarize_index(%s) failed: %s", sym, e)
                            
                elif name == "market_cn.stock":
                    sym = str(args.get("symbol", "")).strip()
                    if sym:
                        ev = self._market.summarize_stock(sym, lookback_days=int(args.get("lookback_days", 365)))
                        evs.append(self._storage.register_evidence(ev))
                        
                elif name == "financials":
                    sym = str(args.get("symbol", "")).strip()
                    kinds = args.get("kinds") or ["income", "balance", "cashflow"]
                    if sym:
                        for ev in self._financials.collect_all(sym, statement_types=kinds,
                                                               periods=int(args.get("periods", 3))):
                            evs.append(self._storage.register_evidence(ev))
                            
                elif name == "filings":
                    sym = str(args.get("symbol", "")).strip()
                    if sym:
                        for ev in self._filings.collect_filings(sym, years_back=int(args.get("years_back", 2))):
                            evs.append(self._storage.register_evidence(ev))
                            
                elif name == "web":
                    queries = args.get("queries") or []
                    for q in queries:
                        for ev in self._web.search_and_extract(
                            q, max_results=6, final_top=5, reranker=self._planner_llm
                        ):
                            evs.append(self._storage.register_evidence(ev))
                else:
                    log.warning("unknown tool: %s", name)
            except Exception as e:
                log.exception("tool %s failed: %s", name, e)
        return evs

    # ---------- one turn ----------
    def ask(self, question: str) -> AgentResult:
        t0 = time.time()
        trace: dict[str, Any] = {
            "model_planner": self._planner_llm.name,
            "model_synthesizer": self._synth_llm.name,
        }

        prefs = self._storage.load_prefs()
        trace["prefs_in"] = prefs

        # 1. Plan (via Capability)
        plan_obj = planner.plan(self._planner_llm, question, prefs)
        trace["plan"] = plan_obj

        # 2. Tools (via Capabilities)
        evs = self._run_tools(plan_obj.get("tools", []))
        trace["evidence_count"] = len(evs)
        if not evs:
            log.info("no evidence from planned tools, falling back to web")
            try:
                for ev in self._web.search_and_extract(
                    question, max_results=6, final_top=5, reranker=self._planner_llm
                ):
                    evs.append(self._storage.register_evidence(ev))
            except Exception as e:
                # Corporate networks may block Tavily; degrade gracefully so
                # the synthesizer can still emit a "no evidence" answer.
                log.warning("web fallback failed: %s", e)

        # Cap evidence pool for cost control
        MAX_EV = 24
        if len(evs) > MAX_EV:
            evs = evs[:MAX_EV]

        sections = plan_obj.get("answer_sections") or ["Summary", "Key Numbers", "Risks", "Evidence"]

        # 3. Synthesize (via Capability)
        draft = synthesizer.synthesize(self._synth_llm, question, prefs, evs, sections)
        trace["draft_len"] = len(draft)

        # 4. Verify (via Capability) + up to 1 repair
        vres = verifier.verify(self._planner_llm, draft, evs)
        trace["verify_1"] = vres.raw
        answer = draft
        if not vres.passed:
            log.info("verifier failed, attempting repair")
            answer = synthesizer.synthesize(
                self._synth_llm, question, prefs, evs, sections,
                prior_answer=draft, verifier_feedback=vres.feedback,
            )
            vres2 = verifier.verify(self._planner_llm, answer, evs)
            trace["verify_2"] = vres2.raw
            if not vres2.passed:
                answer += ("\n\n> ⚠️ **Verifier notice**: 部分论断可能仍存在证据不足,"
                           "请以下方 Evidence 段落为准。\n")

        # 5. Persist answer + citations (via Capability)
        used = sorted(set(int(m) for m in _extract_used_labels(answer)))
        citations = []
        for label in used:
            if 1 <= label <= len(evs):
                cid = evs[label - 1].chunk_id
                if cid is not None:
                    citations.append((f"S{label}", cid))
        aid = self._storage.save_answer(question, answer, trace, citations)
        trace["answer_id"] = aid
        trace["elapsed_s"] = round(time.time() - t0, 2)

        # 6. Memory (via Capability)
        prefs_updated = memory.extract_and_update(self._planner_llm, self._storage, question, answer, answer_id=aid)
        trace["prefs_updated"] = prefs_updated

        return AgentResult(
            question=question,
            answer_md=answer,
            evidences=evs,
            plan=plan_obj,
            trace=trace,
            answer_id=aid,
            prefs_updated=prefs_updated,
        )

def _extract_used_labels(text: str) -> list[int]:
    return [int(m.group(1)) for m in re.finditer(r"\[S(\d+)\]", text)]
