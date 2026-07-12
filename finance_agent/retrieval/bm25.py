"""BM25 pre-filter — cheap lexical shortlisting before LLM rerank.

Tokenization is intentionally simple (regex on unicode word chars). Chinese
text is handled at the character n-gram level (bi-grams) which turns out to
be surprisingly competitive as a first-stage filter without pulling in jieba.
"""
from __future__ import annotations
import re
from rank_bm25 import BM25Okapi

_WORD = re.compile(r"[A-Za-z0-9]+", re.UNICODE)
_CJK = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    toks = [t.lower() for t in _WORD.findall(text)]
    cjk = _CJK.findall(text)
    # character bigrams for Chinese
    toks += [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    return toks


def bm25_topk(query: str, docs: list[str], k: int = 20) -> list[int]:
    if not docs:
        return []
    corpus = [tokenize(d) for d in docs]
    bm = BM25Okapi(corpus)
    scores = bm.get_scores(tokenize(query))
    order = sorted(range(len(docs)), key=lambda i: -scores[i])
    return order[:k]
