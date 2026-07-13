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

Multi-turn support:
  conversation_id — optional, enables multi-turn dialogue with context
  Uses PydanticAI-inspired RunContext pattern for dependency injection
"""
from __future__ import annotations
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..capabilities.base import Evidence
from ..registry import ProviderRegistry, create_default_registry
from ..retrieval.unified_retriever import UnifiedRetriever
from . import planner, synthesizer, verifier, memory
from .conversation_manager import ConversationManager, ConversationContext

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
    conversation_id: str | None = None

@dataclass
class AgentContext:
    """Context object inspired by PydanticAI's RunContext.
    
    Provides dependency injection for agent operations including:
    - Conversation history management
    - User preferences
    - Tool registry access
    """
    registry: ProviderRegistry
    conversation_manager: ConversationManager
    conversation_id: str | None = None
    max_history_turns: int = 10
    
    @property
    def conversation_context(self) -> ConversationContext:
        """Get or create conversation context."""
        return ConversationContext(self.conversation_manager, self.conversation_id)
    
    def get_history(self) -> list[dict[str, str]]:
        """Get conversation history for LLM context."""
        conv_ctx = self.conversation_context
        return conv_ctx.get_context_messages(max_turns=self.max_history_turns)
    
    def add_user_turn(self, content: str, metadata: dict[str, Any] | None = None):
        """Record user turn in conversation."""
        return self.conversation_context.add_user_turn(content, metadata)
    
    def add_assistant_turn(self, content: str, metadata: dict[str, Any] | None = None):
        """Record assistant turn in conversation."""
        return self.conversation_context.add_assistant_turn(content, metadata)

class AgentLoop:
    """Finance Agent — depends only on Capability interfaces, not concrete providers.
    
    To swap providers (e.g., eastmoney → an internal proprietary feed, Tavily → DuckDuckGo):
      1. Create new provider implementing the Capability interface
      2. Pass custom ProviderRegistry to __init__
      3. Agent code remains unchanged
    
    Multi-turn support:
      - Pass conversation_id to ask() to continue an existing conversation
      - Agent will load previous context and include it in planning/synthesis
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
        
        # Initialize unified retriever for RAG
        self._retriever = UnifiedRetriever(self.registry)
        
        # Initialize conversation manager for multi-turn support
        self._conversation_manager = ConversationManager(self._storage)

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
                if name == "market.index":
                    symbols = args.get("symbols") or list(self._market.list_available_indices().keys())[:3]
                    years = int(args.get("years", 20))
                    for sym in symbols:
                        try:
                            ev = self._market.summarize_index(sym, lookback_years=years)
                            evs.append(self._storage.register_evidence(ev))
                        except Exception as e:
                            log.warning("summarize_index(%s) failed: %s", sym, e)
                            
                elif name == "market.stock":
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

    def _is_ashare_symbol(self, symbol: str) -> bool:
        """Check if symbol is A-share (6-digit numeric)."""
        return bool(re.match(r"^\d{6}$", symbol))

    def _is_us_symbol(self, symbol: str) -> bool:
        """Check if symbol is US stock (alphabetic)."""
        return bool(re.match(r"^[A-Z]{1,5}$", symbol)) and not self._is_ashare_symbol(symbol)

    def _infer_market(self, tool_calls: list[dict]) -> str:
        """Infer market from tool calls."""
        for t in tool_calls:
            args = t.get("args") or t.get("arguments") or {}
            sym = str(args.get("symbol", "")).strip()
            if sym:
                if self._is_ashare_symbol(sym):
                    return "cn"
                elif self._is_us_symbol(sym):
                    return "us"
        return "unknown"

    def _infer_external_kinds(self, tool_calls: list[dict]) -> list[str] | None:
        """Infer which external data sources to search based on planned tools.
        
        Returns None to search all sources, or a list of specific kinds.
        """
        kinds = set()
        for t in tool_calls:
            name = t.get("tool") or t.get("name") or ""
            if name in ("market.index", "market.stock"):
                kinds.add("market")
            elif name == "financials":
                kinds.add("financials")
            elif name == "filings":
                kinds.add("filings")
        
        # If no specific tools, search all external data
        if not kinds:
            return None
        return list(kinds)

    # ---------- one turn ----------
    def ask(self, question: str, conversation_id: str | None = None) -> AgentResult:
        t0 = time.time()
        trace: dict[str, Any] = {
            "model_planner": self._planner_llm.name,
            "model_synthesizer": self._synth_llm.name,
        }
        
        # Create AgentContext for dependency injection pattern
        agent_ctx = AgentContext(
            registry=self.registry,
            conversation_manager=self._conversation_manager,
            conversation_id=conversation_id,
            max_history_turns=10,
        )
        
        # Add user turn to conversation history
        agent_ctx.add_user_turn(question)
        
        # Get conversation history for context (PydanticAI-inspired)
        history = agent_ctx.get_history()
        trace["conversation_history_length"] = len(history)
        trace["conversation_id"] = agent_ctx.conversation_context.conversation_id

        prefs = self._storage.load_prefs()
        trace["prefs_in"] = prefs

        # 1. Plan (via Capability) - with conversation context
        plan_obj = planner.plan(self._planner_llm, question, prefs, history=history)
        trace["plan"] = plan_obj

        # 2. Tools (via Capabilities) + External Data RAG
        # Determine market from tool calls
        market = self._infer_market(plan_obj.get("tools", []))
        trace["detected_market"] = market
        
        # For A-share: skip API tools, use external data only
        # For US: use API tools as before
        if market == "cn":
            log.info("A-share detected, using external data only (no API calls)")
            evs = []
        else:
            evs = self._run_tools(plan_obj.get("tools", []))
        
        trace["evidence_count_from_tools"] = len(evs)
        
        # 2.5 Retrieve from external data via RAG
        # For A-share: always search external data
        # For US: search external data as supplement (optional, can be disabled)
        try:
            # Determine which external data sources to search based on tools used
            external_kinds = self._infer_external_kinds(plan_obj.get("tools", []))
            
            # For A-share: always use external data
            # For US: skip external data RAG (already got API data from tools)
            if market == "cn":
                rag_evs = self._retriever.retrieve(
                    question,
                    plan=plan_obj,
                    use_external=True,
                    use_web=False,
                    external_kinds=external_kinds,
                    final_top=12,
                )
                evs.extend(rag_evs)
                trace["evidence_count_from_rag"] = len(rag_evs)
                log.info("RAG retrieved %d evidence from external data", len(rag_evs))
            else:
                # US stocks: skip external data RAG to avoid duplication with API data
                trace["evidence_count_from_rag"] = 0
                log.info("US stock detected, skipping external data RAG (using API data)")
        except Exception as e:
            log.warning("External data RAG failed: %s", e)
            trace["evidence_count_from_rag"] = 0
        
        # If still no evidence, fallback to web search
        if not evs:
            log.info("no evidence from tools or RAG, falling back to web")
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

        trace["evidence_count_total"] = len(evs)

        raw_sections = plan_obj.get("answer_sections") or ["Summary", "Key Numbers", "Risks", "Evidence"]
        sections: list[str] = [s for s in raw_sections if isinstance(s, str)]

        # 3. Synthesize (via Capability) - with conversation context
        draft = synthesizer.synthesize(self._synth_llm, question, prefs, evs, sections, history=history)
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
        
        # 7. Add assistant turn to conversation history
        agent_ctx.add_assistant_turn(answer, metadata={"answer_id": aid, "evidence_count": len(evs)})

        return AgentResult(
            question=question,
            answer_md=answer,
            evidences=evs,
            plan=plan_obj,
            trace=trace,
            answer_id=aid,
            prefs_updated=prefs_updated,
            conversation_id=agent_ctx.conversation_context.conversation_id,
        )

def _extract_used_labels(text: str) -> list[int]:
    return [int(m.group(1)) for m in re.finditer(r"\[S(\d+)\]", text)]
