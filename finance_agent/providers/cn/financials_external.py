"""A-share external financials provider — RAG-backed, no direct file I/O.

This provider satisfies :class:`FinancialsCapability` by querying the shared
:class:`ExternalDataStore` (BM25 + Milvus embedding retrieval) instead of
scanning the ``data/financials/`` directory itself. The RAG store already
loads and indexes those same files, so serving through it removes duplicated
I/O + parsing and lets financials benefit from semantic ranking.

Note:
    ``get_statement`` returns a text-only DataFrame because RAG chunks are
    unstructured text. The main consumer (``agent/loop.py``) only uses
    ``collect_all`` / ``summarize_statement``, which return ``Evidence``
    objects and are unaffected.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from ...capabilities.base import Evidence
from ...capabilities.financials import FinancialsCapability, StatementType

if TYPE_CHECKING:
    from ...retrieval.external_data_store import ExternalDataStore

log = logging.getLogger(__name__)

_STATEMENT_ZH: dict[StatementType, str] = {
    "income": "利润表",
    "balance": "资产负债表",
    "cashflow": "现金流量表",
}

# Query hints per statement type — mixed CN + EN so BM25 and embedding
# retrievers can both latch onto them regardless of the underlying chunk
# language.
_STATEMENT_QUERY_KEYWORDS: dict[StatementType, str] = {
    "income": "利润表 营业收入 净利润 income statement revenue net profit",
    "balance": "资产负债表 总资产 总负债 股东权益 balance sheet total assets liabilities equity",
    "cashflow": "现金流量表 经营活动 投资活动 筹资活动 cash flow operating investing financing",
}

class ExternalAshareFinancialsProvider(FinancialsCapability):
    """A-share financials provider backed by the RAG :class:`ExternalDataStore`.

    Args:
        store: Optional pre-built store to share with other components (e.g.
            the :class:`UnifiedRetriever`). If ``None`` a private store is
            lazily created on first use.
    """

    def __init__(self, store: "ExternalDataStore | None" = None):
        self._store = store

    # ---------------------------------------------------------- store access

    def _get_store(self) -> "ExternalDataStore":
        """Lazily construct the RAG store when first needed."""
        if self._store is None:
            # Deferred import — the retrieval layer pulls in pymilvus /
            # sentence-transformers which we don't want on import of this
            # module (registry construction path).
            from ...retrieval.external_data_store import get_shared_external_store

            # Reuse the process-wide singleton so the unified retriever and
            # this provider share one loaded corpus + Milvus collection.
            self._store = get_shared_external_store()
        return self._store

    def _query_rag(
        self,
        symbol: str,
        statement_type: StatementType,
        *,
        periods: int,
    ) -> list[Evidence]:
        """Run one targeted RAG query for a given (symbol, statement_type)."""
        keywords = _STATEMENT_QUERY_KEYWORDS.get(statement_type, statement_type)
        zh = _STATEMENT_ZH.get(statement_type, statement_type)
        query = f"{symbol} {zh} {keywords} 最近{periods}期"

        # ``final_top`` is a rough upper bound on how many chunks a single
        # statement request may return; we don't know a-priori how many
        # chunks the store produced per period.
        top_n = max(periods, 3)

        try:
            return self._get_store().search(
                query,
                source_kinds=["financials"],
                symbols=[symbol],
                bm25_top=max(top_n * 3, 12),
                final_top=top_n,
            )
        except Exception as e:
            log.warning(
                "RAG query failed for %s/%s: %s", symbol, statement_type, e
            )
            return []

    # ------------------------------------------------------------ capabilities

    def get_statement(
        self,
        symbol: str,
        statement_type: StatementType,
        *,
        periods: int = 3,
    ) -> pd.DataFrame:
        """Return a text-only DataFrame of matching RAG chunks.

        The abstract :class:`FinancialsCapability` interface promises a
        DataFrame, but the RAG store persists unstructured chunks — there is
        no structured schema to project. We return one row per chunk with a
        few informative columns so callers that iterate can still consume
        something. In practice the agent loop uses ``collect_all`` /
        ``summarize_statement`` and never touches this method.
        """
        results = self._query_rag(symbol, statement_type, periods=periods)
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "text": [ev.text for ev in results],
                "title": [ev.title for ev in results],
                "publisher": [ev.publisher for ev in results],
            }
        )

    def summarize_statement(
        self,
        symbol: str,
        statement_type: StatementType,
        *,
        periods: int = 3,
    ) -> Evidence:
        """Return the top matching RAG chunk as a single Evidence."""
        results = self._query_rag(symbol, statement_type, periods=periods)
        if not results:
            raise RuntimeError(
                f"No {statement_type} data for {symbol} in RAG store. "
                f"Ensure the financials directory is loaded and indexed."
            )

        top = results[0]
        zh = _STATEMENT_ZH.get(statement_type, statement_type)

        # Wrap the RAG evidence with a statement-typed title/meta so the
        # synthesizer knows which statement each chunk belongs to.
        meta = dict(top.meta or {})
        meta.setdefault("symbol", symbol)
        meta["kind"] = statement_type
        meta["periods"] = int(periods)

        return Evidence(
            text=top.text,
            source_kind="financials",
            url=top.url,
            title=f"{symbol} {zh} (RAG)",
            publisher=top.publisher or "external_data",
            meta=meta,
        )

    def collect_all(
        self,
        symbol: str,
        *,
        statement_types: list[StatementType] | None = None,
        periods: int = 3,
    ) -> list[Evidence]:
        """Collect RAG chunks for multiple statement types.

        For each requested statement type we run one RAG query and keep the
        top hit — this mirrors the semantic granularity the caller expects
        (one Evidence per statement type).
        """
        types = statement_types or ["income", "balance", "cashflow"]
        out: list[Evidence] = []
        for t in types:
            try:
                ev = self.summarize_statement(symbol, t, periods=periods)
                out.append(ev)
            except Exception as e:
                # A missing statement type shouldn't sink the whole call —
                # the planner may still get useful data from the other two.
                log.warning("Financial %s/%s failed: %s", symbol, t, e)
        return out
