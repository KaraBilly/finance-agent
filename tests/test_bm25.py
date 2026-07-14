"""Tests for retrieval.bm25 tokenizer and top-k ranker."""
from __future__ import annotations

from finance_agent.retrieval.bm25 import bm25_topk, tokenize


class TestTokenize:
    def test_english_lowercased(self):
        assert tokenize("Hello World") == ["hello", "world"]

    def test_alphanumeric_tokens(self):
        assert tokenize("Apple AAPL 2024") == ["apple", "aapl", "2024"]

    def test_chinese_bigrams(self):
        # Two adjacent CJK chars → one bigram token
        toks = tokenize("比亚迪")
        assert "比亚" in toks
        assert "亚迪" in toks

    def test_mixed_chinese_english(self):
        toks = tokenize("AAPL 苹果公司")
        assert "aapl" in toks
        assert "苹果" in toks or "果公" in toks or "公司" in toks

    def test_empty_string(self):
        assert tokenize("") == []

    def test_punctuation_stripped(self):
        assert "hello" in tokenize("hello, world!")


class TestBm25TopK:
    def test_empty_docs_returns_empty(self):
        assert bm25_topk("q", [], k=5) == []

    def test_returns_indices_in_score_order(self):
        docs = [
            "apple pie recipe",
            "banana bread recipe",
            "apple crumble dessert",
        ]
        top = bm25_topk("apple", docs, k=3)
        # both apple-containing docs should out-rank the banana one
        assert top[-1] == 1

    def test_k_truncates_result(self):
        docs = [f"doc {i}" for i in range(10)]
        top = bm25_topk("doc", docs, k=3)
        assert len(top) == 3

    def test_k_larger_than_docs(self):
        docs = ["a", "b"]
        top = bm25_topk("a", docs, k=10)
        assert len(top) == 2
        assert set(top) == {0, 1}

    def test_chinese_query_shortlist(self):
        docs = [
            "比亚迪发布新款电动车",
            "宁德时代动力电池出货量",
            "苹果公司发布新款手机",
        ]
        top = bm25_topk("比亚迪 电动车", docs, k=1)
        assert top == [0]
