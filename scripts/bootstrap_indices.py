"""Pre-download 20 years of daily data for major A-share indices.

Usage:
    python -m scripts.bootstrap_indices                 # all default indices, 20y
    python -m scripts.bootstrap_indices 000300 000905   # subset
"""
from __future__ import annotations
import logging
import sys
from datetime import datetime

from finance_agent.providers import AkshareMarketProvider
from finance_agent.providers.market_akshare import INDEX_CATALOG

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bootstrap")


def main(argv: list[str]) -> int:
    market = AkshareMarketProvider()
    symbols = argv[1:] or list(INDEX_CATALOG.keys())
    end = datetime.now().strftime("%Y%m%d")
    start = str(int(end[:4]) - 20) + end[4:]  # ~20 years ago
    log.info("Bootstrapping %d indices %s → %s", len(symbols), start, end)
    for s in symbols:
        try:
            df = market.get_index_daily(s, start=start, end=end)
            log.info("  %s (%s): %d rows, %s .. %s",
                     s, INDEX_CATALOG.get(s, "?"), len(df),
                     df["date"].min().date(), df["date"].max().date())
        except Exception as e:
            log.error("  %s FAILED: %s", s, e)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
