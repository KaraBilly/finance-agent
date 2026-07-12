"""PydanticAI-based multi-turn conversation agent.

This module provides a PydanticAI-native implementation of the finance agent
with full multi-turn dialogue support using RunContext and dependency injection.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage

from ..capabilities.base import Evidence
from ..capabilities.llm import ChatMessage
from ..registry import ProviderRegistry, create_default_registry
from . import planner, synthesizer, verifier, memory
from .conversation_manager import ConversationManager, ConversationContext

log = logging.getLogger(__name__)


@dataclass
class FinanceAgentDeps:
    """Dependencies for the finance agent.
    
    Passed via PydanticAI's RunContext for dependency injection.
    """
    registry: ProviderRegistry
    conversation_manager: ConversationManager
    conversation_id: str | None = None
    max_history_turns: int = 10


@dataclass
class FinanceAgentResult:
    """Result from a finance agent run."""
    question: str
    answer_md: str
    evidences: list[Evidence]
    plan: dict
    trace: dict
    answer_id: int
    prefs_updated: list[dict] = field(default_factory=list)
    conversation_id: str | None = None


class FinancePydanticAgent:
    """Finance Agent using PydanticAI for multi-turn dialogue.
    
    Features:
    - Native PydanticAI integration with RunContext
    - Conversation history via dependency injection
    - Tool calling for market data, financials, filings, web search
    """
    
    def __init__(self, registry: ProviderRegistry | None = None):
        from ..config import CONFIG
        self.registry = registry or create_default_registry(market=CONFIG.market)
        self.registry.storage.init()
        
        # Initialize conversation manager
        self._conversation_manager = ConversationManager(self.registry.storage)
        
        # Create PydanticAI agent
        self._agent = Agent(
            model=self.registry.planner_llm.name,
            deps_type=FinanceAgentDeps,
            instructions="""You are a financial analysis assistant specializing in A-share and US stocks.
            
Use the available tools to gather evidence and provide accurate, well-sourced answers.
Always cite your sources using [S1], [S2], etc.

When answering:
1. Plan which tools to use based on the question
2. Gather evidence using the tools
3. Synthesize a comprehensive answer
4. Verify the answer against the evidence
5. Extract user preferences for future interactions
""",
        )
        
        # Register tools
        self._register_tools()
    
    def _register_tools(self):
        """Register financial analysis tools with the agent."""
        
        @self._agent.tool
        async def search_web(ctx: RunContext[FinanceAgentDeps], query: str) -> str:
            """Search the web for financial information."""
            web = ctx.deps.registry.web_search
            results = []
            for ev in web.search_and_extract(query, max_results=5, final_top=3):
                results.append(f"[{ev.source}]: {ev.text[:500]}")
            return "\n\n".join(results) if results else "No web results found."
        
        @self._agent.tool
        async def get_stock_data(ctx: RunContext[FinanceAgentDeps], symbol: str, market: str = "cn") -> str:
            """Get stock market data for a symbol."""
            market_data = ctx.deps.registry.market_data
            try:
                if market == "cn":
                    ev = market_data.summarize_stock(symbol, lookback_days=365)
                else:
                    ev = market_data.summarize_stock(symbol, lookback_days=365)
                return f"Stock data for {symbol}:\n{ev.text[:2000]}"
            except Exception as e:
                return f"Error fetching stock data: {e}"
        
        @self._agent.tool
        async def get_financials(ctx: RunContext[FinanceAgentDeps], symbol: str, 
                                  statement_types: list[str] | None = None) -> str:
            """Get financial statements for a company."""
            financials = ctx.deps.registry.financials
            kinds = statement_types or ["income", "balance", "cashflow"]
            results = []
            for ev in financials.collect_all(symbol, statement_types=kinds, periods=3):
                results.append(f"[{ev.source}]: {ev.text[:1000]}")
            return "\n\n".join(results) if results else "No financial data found."
        
        @self._agent.tool
        async def get_filings(ctx: RunContext[FinanceAgentDeps], symbol: str, years_back: int = 2) -> str:
            """Get regulatory filings for a company."""
            filings = ctx.deps.registry.filings
            results = []
            for ev in filings.collect_filings(symbol, years_back=years_back):
                results.append(f"[{ev.source}]: {ev.text[:1000]}")
            return "\n\n".join(results) if results else "No filings found."
    
    def ask(self, question: str, conversation_id: str | None = None) -> FinanceAgentResult:
        """Ask a question with optional conversation context.
        
        Args:
            question: The user's question
            conversation_id: Optional ID to continue an existing conversation
            
        Returns:
            FinanceAgentResult with answer and metadata
        """
        import time
        t0 = time.time()
        
        # Create dependencies
        deps = FinanceAgentDeps(
            registry=self.registry,
            conversation_manager=self._conversation_manager,
            conversation_id=conversation_id,
        )
        
        # Get conversation context
        conv_ctx = ConversationContext(self._conversation_manager, conversation_id)
        conv = conv_ctx.ensure_conversation()
        
        # Add user turn
        conv_ctx.add_user_turn(question)
        
        # Get conversation history for context
        history = conv_ctx.get_context_messages(max_turns=deps.max_history_turns)
        
        trace: dict[str, Any] = {
            "model_planner": self.registry.planner_llm.name,
            "model_synthesizer": self.registry.synthesizer_llm.name,
            "conversation_history_length": len(history),
            "conversation_id": conv.conversation_id,
        }
        
        # Run the agent
        try:
            result = self._agent.run_sync(question, deps=deps)
            answer = result.output
            
            # Store answer
            aid = self.registry.storage.save_answer(
                question=question,
                answer_md=answer,
                trace=trace,
                citations=[],  # TODO: extract citations from result
            )
            
            # Add assistant turn
            conv_ctx.add_assistant_turn(answer, metadata={"answer_id": aid})
            
            # Extract preferences
            prefs_updated = memory.extract_and_update(
                self.registry.planner_llm,
                self.registry.storage,
                question,
                answer,
                answer_id=aid,
            )
            
            trace["answer_id"] = aid
            trace["elapsed_s"] = round(time.time() - t0, 2)
            trace["prefs_updated"] = prefs_updated
            
            return FinanceAgentResult(
                question=question,
                answer_md=answer,
                evidences=[],  # TODO: collect from tool results
                plan={},
                trace=trace,
                answer_id=aid,
                prefs_updated=prefs_updated,
                conversation_id=conv.conversation_id,
            )
            
        except Exception as e:
            log.exception("Agent run failed: %s", e)
            error_msg = f"Error processing request: {str(e)}"
            
            return FinanceAgentResult(
                question=question,
                answer_md=error_msg,
                evidences=[],
                plan={},
                trace={"error": str(e), "conversation_id": conv.conversation_id},
                answer_id=-1,
                conversation_id=conv.conversation_id,
            )
    
    def get_conversation_history(self, conversation_id: str) -> list[dict[str, str]]:
        """Get conversation history for a given conversation ID."""
        return self._conversation_manager.get_history(conversation_id)
    
    def list_conversations(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent conversations."""
        return self._conversation_manager.list_conversations(limit)
