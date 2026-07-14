"""Synthesizer — deepseek produces the final Markdown answer, cite-only.

Contract: every non-trivial factual claim MUST end with one or more citations
of the form [S<int>], where <int> refers to the evidence label passed in.
"""
from __future__ import annotations
import logging
from ..capabilities.llm import LLMCapability, ChatMessage
from ..capabilities.base import Evidence

log = logging.getLogger(__name__)

SYSTEM = """You are a financial analyst assistant covering both US-listed equities
and China A-share equities. Adapt terminology and reporting norms to the market
implied by the question (e.g., 10-K/10-Q vs. 年报/半年报, USD vs. CNY).
You will be given:
  1) The user question.
  2) The user's persistent preferences (topics they care about).
  3) A numbered list of EVIDENCE passages, each labeled [S1], [S2], ...
  4) The desired output sections.

Rules — absolutely mandatory:
- Write in the language of the user question (Chinese if the question is Chinese,
  English if the question is English).
- Use Markdown. Prefer tables for numeric comparisons.
- EVERY factual statement, number, or quoted phrase MUST be followed by one or more
  citations like [S3] or [S1][S4]. Multiple citations are fine.
- Do NOT use knowledge outside the evidence. If evidence is insufficient for a section,
  write "证据不足" (or "Insufficient evidence") for that section and explain what's missing.
- Include a final `## Evidence` section that lists SOURCES (not chunks). Group multiple
  [S#] labels that share the same document/URL onto one bullet. Format each bullet as:
      - [S1][S3][S4] <document title> — <URL or publisher>
  Do NOT emit one bullet per [S#] when several point at the same source; that produces
  visually duplicated entries. When only one [S#] cites a source, a single-label bullet
  is fine.
- Keep it structured, terse, and skimmable.
"""

def _format_evidence(evs: list[Evidence]) -> str:
    lines = []
    for i, e in enumerate(evs, 1):
        head = f"[S{i}] ({e.source_kind})"
        if e.title:
            head += f" {e.title}"
        if e.url:
            head += f"  <{e.url}>"
        lines.append(head + "\n" + e.text.strip())
    return "\n\n---\n\n".join(lines)

def synthesize(model: LLMCapability, question: str, prefs: list[dict],
               evidences: list[Evidence], sections: list[str],
               *, prior_answer: str | None = None,
               verifier_feedback: str | None = None,
               history: list[dict[str, str]] | None = None) -> str:
    prefs_str = ", ".join(f"{p['topic']}({p['weight']:.2f})" for p in prefs) or "(none)"
    ev_str = _format_evidence(evidences)
    sec_str = ", ".join(sections)

    # Build messages with optional conversation history
    messages = [ChatMessage("system", SYSTEM)]
    
    # Add conversation history if available
    if history:
        for msg in history:
            messages.append(ChatMessage(msg["role"], msg["content"]))

    user_parts = [
        f"# Question\n{question}",
        f"# User preferences\n{prefs_str}",
        f"# Desired sections\n{sec_str}",
        f"# Evidence\n{ev_str}",
    ]
    if prior_answer and verifier_feedback:
        user_parts.append(
            f"# Previous draft (needs repair)\n{prior_answer}\n\n"
            f"# Verifier feedback — fix these issues\n{verifier_feedback}"
        )
    user = "\n\n".join(user_parts)
    messages.append(ChatMessage("user", user))
    
    return model.chat(messages, temperature=0.2)
