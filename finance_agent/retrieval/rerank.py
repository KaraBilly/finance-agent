"""LLM-based reranking using doubao.

We ask the model for a JSON list of {index, score} — cheaper and more robust
than freeform scoring text. We do NOT trust unknown indices; we clip.
"""
from __future__ import annotations
import logging
from ..capabilities.llm import LLMCapability, ChatMessage

log = logging.getLogger(__name__)

_SYS = (
    "You are a retrieval reranker for a financial-analysis agent. "
    "Given a user question and a numbered list of candidate passages, "
    "score each passage 0-10 on how directly useful it is for answering. "
    "Return STRICT JSON: {\"scores\": [{\"index\": <int>, \"score\": <float>}, ...]}"
    " covering every index. Do not add commentary."
)


def llm_rerank(model: LLMCapability, query: str, passages: list[str], k: int = 6) -> list[int]:
    if not passages:
        return []
    numbered = "\n\n".join(f"[{i}] {p[:800]}" for i, p in enumerate(passages))
    user = f"Question:\n{query}\n\nPassages:\n{numbered}\n\nReturn JSON now."
    try:
        obj = model.chat_json(
            [ChatMessage("system", _SYS), ChatMessage("user", user)],
            temperature=0.0,
        )
        scored = obj.get("scores", [])
        # sanitize
        clean = [(int(s["index"]), float(s["score"])) for s in scored
                 if isinstance(s, dict) and "index" in s and "score" in s
                 and 0 <= int(s["index"]) < len(passages)]
        clean.sort(key=lambda x: -x[1])
        return [i for i, _ in clean[:k]]
    except Exception as e:
        log.warning("rerank parse failed (%s), falling back to input order", e)
        return list(range(min(k, len(passages))))
