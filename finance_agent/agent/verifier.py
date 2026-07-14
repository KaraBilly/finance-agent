"""Verifier — doubao checks that every claim in the draft is supported.

Two-stage check:
  1) Programmatic: every non-trivial paragraph should contain at least one [S#].
  2) LLM: for a sample of numeric/strong claims, ask doubao (via a pydantic-ai
     :class:`Agent` with a :class:`VerifyVerdict` output schema) whether the
     cited evidence actually supports the claim.

If either stage fails, we return ``passed=False`` with a ``feedback`` string
that gets fed back to the synthesizer for exactly ONE repair attempt.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ..capabilities.base import Evidence
from ..capabilities.llm import LLMCapability
from ..providers.llm_openai import OpenAICompatibleLLM
from .pydantic_runtime import build_agent

log = logging.getLogger(__name__)

_CITE_RE = re.compile(r"\[S(\d+)\]")

# ---------------------------------------------------------------------------
# Output schemas (validated by pydantic-ai)
# ---------------------------------------------------------------------------

class VerifyIssue(BaseModel):
    """A single unsupported / overstated / numerically wrong claim."""

    claim: str = Field(..., description="Short quote from the draft")
    why: str = Field(..., description="Short reason it's problematic")
    suggest: str = Field("", description="What to change")

class VerifyVerdict(BaseModel):
    """Verdict returned by the fact-checker agent."""

    passed: bool = True
    issues: list[VerifyIssue] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# Result dataclass (public API — unchanged from pre-pydantic-ai version)
# ---------------------------------------------------------------------------

@dataclass
class VerifyResult:
    passed: bool
    feedback: str
    raw: dict

SYSTEM = """You are a rigorous fact-checker for a financial analyst.
Given a draft answer with [S#] citations and the underlying evidence passages,
identify claims that are:
  - Unsupported: no matching [S#] or the cited passage doesn't back the claim.
  - Overstated: draft is stronger than what the evidence says.
  - Numerically wrong: numbers in the draft don't match the evidence.

Return a VerifyVerdict. If there are no material issues, set passed=true and
leave issues empty.
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_verifier_agent(llm: OpenAICompatibleLLM) -> Agent[None, VerifyVerdict]:
    """Build the pydantic-ai agent used by :func:`verify`.

    Exposed so tests can inject a ``TestModel`` via ``agent.override(...)``.
    """
    return build_agent(llm, output_type=VerifyVerdict, system_prompt=SYSTEM)

def _paragraph_citation_check(draft: str) -> list[str]:
    """Return a list of missing-citation warnings (paragraph-level)."""
    warnings: list[str] = []
    for para in draft.split("\n\n"):
        p = para.strip()
        if not p or p.startswith("#") or p.startswith("|") or p.startswith("- **["):
            continue
        # skip Evidence section listings
        if p.lower().startswith("## evidence") or p.startswith("[S"):
            continue
        # skip pure prose disclaimers explicitly marked
        if "证据不足" in p:
            continue
        if len(p) > 30 and not _CITE_RE.search(p):
            warnings.append(p[:120] + ("…" if len(p) > 120 else ""))
    return warnings

def _cited_labels(draft: str) -> set[int]:
    return {int(m.group(1)) for m in _CITE_RE.finditer(draft)}

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def verify(model: LLMCapability, draft: str, evidences: list[Evidence]) -> VerifyResult:
    if not isinstance(model, OpenAICompatibleLLM):
        raise TypeError(
            "verifier.verify requires an OpenAICompatibleLLM (Doubao / DeepSeek); "
            f"got {type(model).__name__}"
        )

    # ---- programmatic ----
    missing = _paragraph_citation_check(draft)
    used = _cited_labels(draft)
    unknown = [i for i in used if i < 1 or i > len(evidences)]

    prog_issues: list[str] = []
    if unknown:
        prog_issues.append(f"引用了不存在的证据编号: {unknown}")
    if missing:
        prog_issues.append("以下段落缺少 [S#] 引用:\n- " + "\n- ".join(missing[:5]))

    # ---- LLM factual check ----
    ev_str = "\n\n".join(
        f"[S{i}] {(e.title or '')}: {e.text[:800]}" for i, e in enumerate(evidences, 1)
    )
    user = f"# Evidence\n{ev_str}\n\n# Draft\n{draft}\n\nReturn a VerifyVerdict."

    try:
        agent = build_verifier_agent(model)
        result = agent.run_sync(user)
        verdict = result.output
    except Exception as e:
        # Fail-closed: if the verifier LLM is unreachable OR pydantic-ai
        # exhausts its retries on schema-validation failure, treat the draft
        # as unverified rather than silently declaring victory. This
        # surfaces the outage to the caller (via feedback) and triggers the
        # single repair pass so at least we get a second synthesis attempt.
        log.warning("verifier LLM failed: %s", e)
        verdict = VerifyVerdict(
            passed=False,
            issues=[VerifyIssue(
                claim="verifier unavailable",
                why=f"LLM verification skipped due to error: {e}",
                suggest="manual review recommended",
            )],
        )

    passed = verdict.passed and not prog_issues

    feedback_parts: list[str] = []
    if prog_issues:
        feedback_parts.append("Structural issues:\n" + "\n".join(f"- {x}" for x in prog_issues))
    if verdict.issues:
        formatted = [
            f"- 「{i.claim}」→ {i.why} (建议: {i.suggest})"
            for i in verdict.issues[:8]
        ]
        feedback_parts.append("Factual issues:\n" + "\n".join(formatted))

    raw: dict[str, Any] = {
        "prog_issues": prog_issues,
        "llm": verdict.model_dump(),
    }
    return VerifyResult(
        passed=passed,
        feedback="\n\n".join(feedback_parts),
        raw=raw,
    )
