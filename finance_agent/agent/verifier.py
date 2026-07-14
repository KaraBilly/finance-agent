"""Verifier — doubao checks that every claim in the draft is supported.

Two-stage check:
  1) Programmatic: every non-trivial paragraph should contain at least one [S#].
  2) LLM: for a sample of numeric/strong claims, ask doubao whether the cited
     evidence actually supports the claim. Returns a JSON verdict.

If either stage fails, we return `passed=False` with a `feedback` string that
gets fed back to the synthesizer for exactly ONE repair attempt.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass

from ..capabilities.llm import LLMCapability, ChatMessage
from ..capabilities.base import Evidence

log = logging.getLogger(__name__)

_CITE_RE = re.compile(r"\[S(\d+)\]")

SYSTEM = """You are a rigorous fact-checker for a financial analyst.
Given a draft answer with [S#] citations and the underlying evidence passages,
identify claims that are:
  - Unsupported: no matching [S#] or the cited passage doesn't back the claim.
  - Overstated: draft is stronger than what the evidence says.
  - Numerically wrong: numbers in the draft don't match the evidence.

Return STRICT JSON:
{
  "passed": true|false,
  "issues": [
    {"claim": "<short quote>", "why": "<short reason>", "suggest": "<what to change>"}
  ]
}
If there are no material issues, return passed=true with empty issues.
"""

@dataclass
class VerifyResult:
    passed: bool
    feedback: str
    raw: dict

def _paragraph_citation_check(draft: str) -> list[str]:
    """Return a list of missing-citation warnings (paragraph-level)."""
    warnings = []
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

def verify(model: LLMCapability, draft: str, evidences: list[Evidence]) -> VerifyResult:
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
    user = f"# Evidence\n{ev_str}\n\n# Draft\n{draft}\n\nReturn JSON verdict."
    try:
        obj = model.chat_json(
            [ChatMessage("system", SYSTEM), ChatMessage("user", user)],
            temperature=0.0,
        )
    except Exception as e:
        # Fail-closed: if the verifier LLM is unreachable, treat the draft as
        # unverified rather than silently declaring victory. This surfaces the
        # outage to the caller (via feedback + a warning banner) and triggers
        # the single repair pass so at least we get a second synthesis attempt.
        log.warning("verifier LLM failed: %s", e)
        obj = {
            "passed": False,
            "issues": [{
                "claim": "verifier unavailable",
                "why": f"LLM verification skipped due to error: {e}",
                "suggest": "manual review recommended",
            }],
        }

    llm_issues = obj.get("issues", []) if isinstance(obj, dict) else []
    passed = obj.get("passed", True) and not prog_issues

    feedback_parts: list[str] = []
    if prog_issues:
        feedback_parts.append("Structural issues:\n" + "\n".join(f"- {x}" for x in prog_issues))
    if llm_issues:
        formatted = [f"- 「{i.get('claim','')}」→ {i.get('why','')} (建议: {i.get('suggest','')})"
                     for i in llm_issues[:8]]
        feedback_parts.append("Factual issues:\n" + "\n".join(formatted))

    return VerifyResult(
        passed=passed,
        feedback="\n\n".join(feedback_parts),
        raw={"prog_issues": prog_issues, "llm": obj},
    )
