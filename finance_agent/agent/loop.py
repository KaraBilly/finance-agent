"""Main agent loop — orchestrates planner → tools → synth → verify → memory.

Architecture:
  Finance Agent (this file)
       │
  Capability Layer (abstract interfaces)
       │
  Provider Layer (concrete implementations, swappable)
       │
  External APIs (finnhub, eastmoney, cninfo, Tavily, Ark, DeepSeek, etc.)

Two-model orchestration:
  planner_llm     — planning, reranking, verification, memory extraction
  synthesizer_llm — final answer synthesis (with optional 1 repair pass)

Multi-market dispatch:
  Each question triggers a market inference step (``_infer_market``); the
  corresponding provider bundle is then obtained via
  ``registry.for_market(market)``. This is the ONLY branch that knows about
  markets — provider swapping (Finnhub → paid feed, external files → API)
  happens in the registry, not here.

Multi-turn support:
  conversation_id — optional, enables multi-turn dialogue with context.
"""
from __future__ import annotations
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from ..capabilities.base import Evidence
from ..registry import DEFAULT_MARKET, MarketProviders, ProviderRegistry, create_default_registry
from ..retrieval.unified_retriever import UnifiedRetriever
from . import planner, synthesizer, verifier, memory
from .conversation_manager import ConversationContext, ConversationManager

log = logging.getLogger(__name__)

# Hard caps to keep cost and latency bounded regardless of what the planner
# emits. LLMs occasionally hallucinate huge query fan-outs; without these
# caps a single ask can burn dozens of paid API calls.
_MAX_WEB_QUERIES_PER_PLAN = 3
_MAX_EVIDENCE_TOTAL = 24
_MAX_HISTORY_TURNS = 10

# Concurrency for tool dispatch and side-tasks. Tool calls are almost
# entirely network-bound (Finnhub / Tavily / Trafilatura) so a small thread
# pool cuts wall time roughly linearly. 4 workers is enough for the
# typical planner output (≤ 5 tools per turn).
_TOOL_CONCURRENCY = 4

# Words that look like US tickers (1–5 uppercase letters) but are actually
# common finance/regulatory acronyms. Used to guard ``_infer_market`` from
# flagging pure A-share questions as US just because they mention "SEC".
_US_ACRONYM_BLOCKLIST = frozenset({
    "SEC", "IPO", "ESG", "ETF", "GDP", "CPI", "PPI", "PMI",
    "CEO", "CFO", "COO", "CTO", "CIO", "PE", "PB", "ROE", "ROA",
    "EPS", "EBIT", "EBITDA", "USD", "CNY", "RMB", "HKD",
    "SFC", "CSRC", "SSE", "SZSE", "HKEX", "NYSE", "NASDAQ",
    "AI", "ML", "IT", "OK", "USA", "UK", "EU", "GAAP",
    "A", "H", "K", "Q",  # 短通名,避免"A股"里的 A 被判美股
})

_CN_KEYWORD_HINTS = frozenset({
    "A股", "沪市", "深市", "上证", "深证", "科创板", "创业板", "北交所",
    "证监会", "巨潮", "东财", "东方财富", "公告", "年报", "半年报",
    "比亚迪", "宁德时代", "中际旭创", "贵州茅台", "中国平安",
    "招商银行", "五粮液", "美的集团", "格力电器", "海康威视",
})

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

class AgentLoop:
    """Finance Agent — depends only on Capability interfaces, not concrete providers.

    To swap providers (e.g., external files → an internal proprietary feed,
    Tavily → DuckDuckGo):
      1. Create new provider implementing the Capability interface.
      2. Change registration in ``registry.py``.
      3. Agent code remains unchanged.

    Multi-turn support:
      - Pass ``conversation_id`` to :py:meth:`ask` to continue an existing
        conversation. When ``None``, a fresh conversation is created and its
        ID is returned in :class:`AgentResult`.
    """

    def __init__(self, registry: ProviderRegistry | None = None):
        self.registry = registry or create_default_registry()

        # Initialize storage
        self.registry.storage.init()

        # Cross-market capabilities (LLMs, web, storage)
        self._planner_llm = self.registry.planner_llm
        self._synth_llm = self.registry.synthesizer_llm
        self._web = self.registry.web_search
        self._storage = self.registry.storage

        # Unified retriever + conversation manager
        self._retriever = UnifiedRetriever(self.registry)
        self._conversation_manager = ConversationManager(self._storage)

    # ---------- tool dispatch ----------
    def _run_tools(self, tool_calls: list[dict], providers: MarketProviders) -> list[Evidence]:
        """Execute planner-emitted tool calls against a market-specific bundle.

        Tool calls run in parallel via a thread pool: they're all HTTP-bound
        (Finnhub / Tavily / Trafilatura) so serial execution wasted the wall
        time of every call after the first. Order is preserved so the
        resulting evidence list is deterministic across runs.

        Providers are passed in explicitly (rather than looked up on ``self``)
        so the same helper works for either market.
        """
        market_data = providers.market_data
        financials = providers.financials
        filings = providers.filings

        def _dispatch(t: dict) -> list[Evidence]:
            # Accept either {"tool": ...} or {"name": ...} — different LLMs
            # (Doubao vs GPT-5.x) prefer different keys despite the same prompt.
            name = t.get("tool") or t.get("name") or ""
            args = t.get("args") or t.get("arguments") or {}
            local: list[Evidence] = []
            try:
                if name == "market.index":
                    symbols = args.get("symbols") or list(market_data.list_available_indices().keys())[:3]
                    years = int(args.get("years", 20))
                    for sym in symbols:
                        try:
                            ev = market_data.summarize_index(sym, lookback_years=years)
                            local.append(self._storage.register_evidence(ev))
                        except Exception as e:
                            log.warning("summarize_index(%s) failed: %s", sym, e)

                elif name == "market.stock":
                    sym = str(args.get("symbol", "")).strip()
                    if _is_safe_symbol(sym):
                        ev = market_data.summarize_stock(sym, lookback_days=int(args.get("lookback_days", 365)))
                        local.append(self._storage.register_evidence(ev))

                elif name == "financials":
                    sym = str(args.get("symbol", "")).strip()
                    kinds = args.get("kinds") or ["income", "balance", "cashflow"]
                    if _is_safe_symbol(sym):
                        for ev in financials.collect_all(sym, statement_types=kinds,
                                                        periods=int(args.get("periods", 3))):
                            local.append(self._storage.register_evidence(ev))

                elif name == "filings":
                    sym = str(args.get("symbol", "")).strip()
                    if _is_safe_symbol(sym):
                        for ev in filings.collect_filings(sym, years_back=int(args.get("years_back", 2))):
                            local.append(self._storage.register_evidence(ev))

                elif name == "web":
                    # Sanitise LLM-emitted queries before sending them to a
                    # paid search API: cap length, strip control chars/newlines,
                    # drop empties. Without this, a hallucinating planner can
                    # send a multi-paragraph blob as one "query".
                    raw_queries = list(args.get("queries") or [])[:_MAX_WEB_QUERIES_PER_PLAN]
                    queries = []
                    for q in raw_queries:
                        if not isinstance(q, str):
                            continue
                        clean = re.sub(r"[\r\n\t\x00-\x1f]+", " ", q).strip()[:200]
                        if clean:
                            queries.append(clean)
                    for q in queries:
                        for ev in self._web.search_and_extract(
                            q, max_results=6, final_top=5, reranker=self._planner_llm
                        ):
                            local.append(self._storage.register_evidence(ev))
                else:
                    log.warning("unknown tool: %s", name)
            except Exception as e:
                log.exception("tool %s failed: %s", name, e)
            return local

        if not tool_calls:
            return []
        # Preserve planner order by iterating over the input list and picking
        # up already-computed results.
        workers = min(_TOOL_CONCURRENCY, len(tool_calls))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_dispatch, tool_calls))
        evs: list[Evidence] = []
        for chunk in results:
            evs.extend(chunk)
        return evs

    # ---------- market inference ----------
    @staticmethod
    def _is_ashare_symbol(symbol: str) -> bool:
        """Check if symbol is A-share (6-digit numeric)."""
        return bool(re.match(r"^\d{6}$", symbol))

    @classmethod
    def _is_us_symbol(cls, symbol: str) -> bool:
        """Check if symbol is US stock (1–5 uppercase letters, minus acronyms)."""
        if not re.match(r"^[A-Z]{1,5}$", symbol):
            return False
        return symbol not in _US_ACRONYM_BLOCKLIST

    def _infer_market(self, tool_calls: list[dict], question: str = "") -> str:
        """Infer market from tool calls and question text.

        Returns ``"us"`` or ``"cn"``. Uses :data:`DEFAULT_MARKET` when signals
        conflict or nothing matches — the loop always dispatches to a real
        bundle so callers never see an "unknown" market.
        """
        # First try to infer from tool calls (symbol).
        for t in tool_calls:
            args = t.get("args") or t.get("arguments") or {}
            sym = str(args.get("symbol", "")).strip()
            if sym:
                if self._is_ashare_symbol(sym):
                    return "cn"
                if self._is_us_symbol(sym):
                    return "us"

        if question:
            # Explicit CN keywords take priority — a question like
            # "分析比亚迪的 ESG 表现" mustn't be mistaken for a US ticker.
            for kw in _CN_KEYWORD_HINTS:
                if kw in question:
                    return "cn"

            # 6-digit code anywhere → A-share, but only if it looks like a
            # real ticker (00xxxx / 30xxxx / 60xxxx / 68xxxx / 8xxxxx /
            # 9xxxxx) OR co-occurs with an explicit "stock/code" hint.
            # Otherwise "202506" (a date) or "123456" (an ID) would flip us
            # to CN incorrectly.
            for m in re.finditer(r"\b(\d{6})\b", question):
                code = m.group(1)
                if re.match(r"^(00|30|60|68|8|9)\d{4}$", code):
                    return "cn"
                # Fall through: not a plausible A-share code, keep scanning.

            # Real-looking US ticker (excluding common acronyms).
            for m in re.finditer(r"\b([A-Z]{1,5})\b", question):
                if self._is_us_symbol(m.group(1)):
                    return "us"

        return DEFAULT_MARKET

    def _infer_external_kinds(self, tool_calls: list[dict]) -> list[str] | None:
        """Infer which external data sources to search based on planned tools.

        Returns ``None`` to search all sources, or a list of specific kinds.
        """
        kinds: set[str] = set()
        for t in tool_calls:
            name = t.get("tool") or t.get("name") or ""
            if name in ("market.index", "market.stock"):
                kinds.add("market")
            elif name == "financials":
                kinds.add("financials")
            elif name == "filings":
                kinds.add("filings")

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

        # Conversation state — one context per ask() call.
        conv_ctx = ConversationContext(self._conversation_manager, conversation_id)
        conv_ctx.add_user_turn(question)
        history = conv_ctx.get_context_messages(max_turns=_MAX_HISTORY_TURNS)
        trace["conversation_id"] = conv_ctx.conversation_id
        trace["conversation_history_length"] = len(history)

        prefs = self._storage.load_prefs()
        trace["prefs_in"] = prefs

        # 1. Plan (with conversation history for context).
        t_stage = time.time()
        plan_obj = planner.plan(self._planner_llm, question, prefs, history=history)
        trace["plan"] = plan_obj
        trace["plan_s"] = round(time.time() - t_stage, 2)

        # 2. Market dispatch — pick the right provider bundle for this turn.
        market = self._infer_market(plan_obj.get("tools", []), question=question)
        providers = self.registry.for_market(market)
        trace["detected_market"] = market

        # 2a. For US: hit real APIs (Finnhub) for all planner-selected tools.
        #     For CN: only ``web`` is a real network call; market/financials/filings
        #     have no CN API impl and are answered via RAG over local files below.
        #     Local RAG is skipped ONLY when the planner picked web *exclusively*.
        tools = plan_obj.get("tools", [])
        tool_names = [t.get("tool") if isinstance(t, dict) else t for t in tools]
        web_only_plan = bool(tool_names) and all(n == "web" for n in tool_names)
        has_web = "web" in tool_names
        has_non_web = any(n != "web" for n in tool_names)

        t_stage = time.time()
        if market == "cn":
            # Run only the ``web`` tool through _run_tools — other CN tools have
            # no direct provider and are handled by RAG in step 2b.
            if has_web:
                web_only_tools = [
                    t for t in tools
                    if (t.get("tool") if isinstance(t, dict) else t) == "web"
                ]
                evs: list[Evidence] = self._run_tools(web_only_tools, providers)
                if has_non_web:
                    log.info(
                        "A-share detected, running web tool + local RAG for non-web tools %s",
                        [n for n in tool_names if n != "web"],
                    )
                else:
                    log.info("A-share detected, planner selected web-only → skipping local RAG")
            else:
                evs = []
                log.info("A-share detected, using external data only (no API calls)")
        else:
            evs = self._run_tools(tools, providers)

        trace["evidence_count_from_tools"] = len(evs)
        trace["tools_s"] = round(time.time() - t_stage, 2)

        # 2b. Retrieve from external data via RAG.
        #     CN → primary evidence source (local files) unless plan is web-only.
        #     US → skip (API tools already provided authoritative data).
        t_stage = time.time()
        try:
            external_kinds = self._infer_external_kinds(tools)
            if market == "cn" and not web_only_plan:
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
                trace["evidence_count_from_rag"] = 0
                if market != "cn":
                    log.info("US stock detected, skipping external data RAG (using API data)")
                else:
                    log.info("Web-only plan for A-share, skipping external data RAG")
        except Exception as e:
            log.warning("External data RAG failed: %s", e)
            trace["evidence_count_from_rag"] = 0
        trace["rag_s"] = round(time.time() - t_stage, 2)

        # 2c. Fallback: no evidence at all → web search.
        if not evs:
            log.info("no evidence from tools or RAG, falling back to web")
            t_stage = time.time()
            try:
                for ev in self._web.search_and_extract(
                    question, max_results=6, final_top=5, reranker=self._planner_llm
                ):
                    evs.append(self._storage.register_evidence(ev))
            except Exception as e:
                # Corporate networks may block Tavily; degrade gracefully so
                # the synthesizer can still emit a "no evidence" answer.
                log.warning("web fallback failed: %s", e)
            trace["web_fallback_s"] = round(time.time() - t_stage, 2)

        # Cap evidence pool for cost control (order preserved).
        if len(evs) > _MAX_EVIDENCE_TOTAL:
            evs = evs[:_MAX_EVIDENCE_TOTAL]

        trace["evidence_count_total"] = len(evs)

        raw_sections = plan_obj.get("answer_sections") or ["Summary", "Key Numbers", "Risks", "Evidence"]
        sections: list[str] = [s for s in raw_sections if isinstance(s, str)]

        # 3. Synthesize.
        t_synth = time.time()
        draft = synthesizer.synthesize(self._synth_llm, question, prefs, evs, sections, history=history)
        trace["draft_len"] = len(draft)
        trace["synth_1_s"] = round(time.time() - t_synth, 2)

        # 4. Verify + memory extraction run concurrently on the draft.
        # Rationale: verifier and memory-extractor are both independent LLM
        # calls; running them serially added ~1 memory RTT to the critical
        # path. Memory only needs the user's question intent + a snapshot
        # of the answer to identify topics, so operating on the draft (vs
        # the post-repair answer) makes no material difference for topic
        # extraction. In the common "verify passes" case we save one full
        # LLM RTT per turn.
        mem_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory")
        mem_future = mem_pool.submit(
            memory.extract_and_update,
            self._planner_llm, self._storage, question, draft, None,
        )

        try:
            t_verify = time.time()
            vres = verifier.verify(self._planner_llm, draft, evs)
            trace["verify_1"] = vres.raw
            trace["verify_1_s"] = round(time.time() - t_verify, 2)
            answer = draft
            if not vres.passed:
                log.info("verifier failed, attempting repair")
                t_repair = time.time()
                answer = synthesizer.synthesize(
                    self._synth_llm, question, prefs, evs, sections,
                    prior_answer=draft, verifier_feedback=vres.feedback,
                )
                vres2 = verifier.verify(self._planner_llm, answer, evs)
                trace["verify_2"] = vres2.raw
                trace["repair_s"] = round(time.time() - t_repair, 2)
                if not vres2.passed:
                    answer += ("\n\n> ⚠️ **Verifier notice**: 部分论断可能仍存在证据不足,"
                               "请以下方 Evidence 段落为准。\n")

            # 5. Persist answer + citations.
            used = sorted(set(int(m) for m in _extract_used_labels(answer)))
            citations = []
            for label in used:
                if 1 <= label <= len(evs):
                    cid = evs[label - 1].chunk_id
                    if cid is not None:
                        citations.append((f"S{label}", cid))
            aid = self._storage.save_answer(question, answer, trace, citations)
            trace["answer_id"] = aid

            # 6. Collect memory result (may already be done).
            try:
                prefs_updated = mem_future.result(timeout=30)
            except Exception as e:
                log.warning("memory extraction failed / timed out: %s", e)
                prefs_updated = []
        finally:
            mem_pool.shutdown(wait=False)

        trace["prefs_updated"] = prefs_updated
        trace["elapsed_s"] = round(time.time() - t0, 2)

        # 7. Record assistant turn in conversation history.
        conv_ctx.add_assistant_turn(answer, metadata={"answer_id": aid, "evidence_count": len(evs)})

        return AgentResult(
            question=question,
            answer_md=answer,
            evidences=evs,
            plan=plan_obj,
            trace=trace,
            answer_id=aid,
            prefs_updated=prefs_updated,
            conversation_id=conv_ctx.conversation_id,
        )

# --------------------------------------------------------------------- helpers

# Symbol whitelist — planner output is LLM-generated and eventually gets
# forwarded to outbound HTTP calls; guard against weird characters that could
# break URLs or trigger downstream 500s. Alphanumerics plus a couple of
# separators cover both US tickers (AAPL) and A-share codes (600519).
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._-]{1,10}$")

def _is_safe_symbol(sym: str) -> bool:
    return bool(sym) and bool(_SYMBOL_RE.match(sym))

def _extract_used_labels(text: str) -> list[int]:

    # Only count [S#] used inline in the body — the ``## Evidence`` section
    # groups labels per source and would double-count every citation, e.g.
    # producing duplicate rows in the ``citations`` table.
    body = re.split(r"^##\s+Evidence\b", text, maxsplit=1, flags=re.MULTILINE | re.IGNORECASE)[0]
    return [int(m.group(1)) for m in re.finditer(r"\[S(\d+)\]", body)]
