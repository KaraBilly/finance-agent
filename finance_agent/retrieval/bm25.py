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

class BM25Index:
    """Pre-built BM25 index for a static corpus.

    Building the index tokenizes every doc once (expensive for thousands of
    chunks). Callers with a static corpus (e.g., ``ExternalDataStore``) should
    build one of these at load time and reuse it, instead of paying tokenize +
    ``BM25Okapi(...)`` on every query.
    """

    __slots__ = ("_bm25", "_size")

    def __init__(self, docs: list[str]):
        corpus = [tokenize(d) for d in docs]
        self._bm25 = BM25Okapi(corpus) if corpus else None
        self._size = len(docs)

    def topk(self, query: str, k: int = 20) -> list[int]:
        if self._bm25 is None or self._size == 0:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(self._size), key=lambda i: -scores[i])
        return order[:k]
