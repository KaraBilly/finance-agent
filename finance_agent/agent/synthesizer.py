"""Synthesizer — deepseek produces the final Markdown answer, cite-only.

Contract: every non-trivial factual claim MUST end with one or more citations
of the form [S<int>], where <int> refers to the evidence label passed in.
"""
from __future__ import annotations
import logging
from ..capabilities.llm import LLMCapability, ChatMessage
from ..capabilities.base import Evidence

log = logging.getLogger(__name__)

SYSTEM = """You are a financial analyst assistant for A-share investing.
You will be given:
  1) The user question.
  2) The user's persistent preferences (topics they care about).
  3) A numbered list of EVIDENCE passages, each labeled [S1], [S2], ...
  4) The desired output sections.

Rules — absolutely mandatory:
- Write in the language of the user question (default Chinese).
- Use Markdown. Prefer tables for numeric comparisons.
- EVERY factual statement, number, or quoted phrase MUST be followed by one or more
  citations like [S3] or [S1][S4]. Multiple citations are fine.
- Do NOT use knowledge outside the evidence. If evidence is insufficient for a section,
  write "证据不足" for that section and explain what's missing.
- Include a final `## Evidence` section that lists each cited [S#] with title and URL.
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
               verifier_feedback: str | None = None) -> str:
    prefs_str = ", ".join(f"{p['topic']}({p['weight']:.2f})" for p in prefs) or "(none)"
    ev_str = _format_evidence(evidences)
    sec_str = ", ".join(sections)

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
    return model.chat(
        [ChatMessage("system", SYSTEM), ChatMessage("user", user)],
        temperature=0.2,
    )
