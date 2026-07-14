#!/usr/bin/env python3

"""Import external data into Milvus vector database.

This script loads all external data (market, financials, filings) from the data directory,
chunks them, computes embeddings, and inserts them into Milvus.

Usage:
    # Start Milvus first
    docker-compose -f docker-compose.milvus.yml up -d

    # Then run import
    python scripts/import_to_milvus.py

    # Or with custom options
    python scripts/import_to_milvus.py --data-dir ./data --collection finance_docs

"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# NOTE: env-based CLI overrides (--host / --port / --collection) MUST be set
# before importing anything that materializes CONFIG, because CONFIG is a
# frozen dataclass loaded exactly once at import time. We defer the heavy
# imports into main() after parsing args so that pattern works.

def import_data(
    data_dir: Path | None,
    collection_name: str,
    host: str,
    port: str,
    recreate: bool = False,
) -> dict:
    """Import external data into Milvus.

    Args:
        data_dir: Data directory.
        collection_name: Milvus collection name.
        host: Milvus host.
        port: Milvus port.
        recreate: Whether to drop-and-recreate the collection before import.
    """
    # Local import so any env overrides in ``main`` take effect first.
    from finance_agent.retrieval.external_data_store import ExternalDataStore
    from finance_agent.retrieval.milvus_store import MilvusStore, PYMILVUS_AVAILABLE

    log = logging.getLogger(__name__)
    log.info("Starting data import to Milvus (host=%s:%s, collection=%s)...",
             host, port, collection_name)

    if recreate and PYMILVUS_AVAILABLE:
        # Drop the collection ahead of time so ExternalDataStore starts
        # from a clean slate; otherwise it would just append duplicates.
        drop_store = MilvusStore(host=host, port=port, collection_name=collection_name)
        try:
            drop_store.delete_collection()
        finally:
            drop_store.close()

    store = ExternalDataStore(
        market_dir=(data_dir / "market") if data_dir else None,
        financials_dir=(data_dir / "financials") if data_dir else None,
        filings_dir=(data_dir / "filings") if data_dir else None,
        use_embedding=True,
        use_milvus=True,
    )
    store.load_all()
    stats = store.get_stats()
    log.info("Import complete!")
    log.info("Stats: %s", stats)
    return stats

def main() -> None:
    """Main entry point."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    log = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(
        description="Import external data into Milvus vector database"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Data directory (default: from FA_DATA_DIR env / repo default)",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=os.getenv("FA_MILVUS_COLLECTION", "finance_docs"),
        help="Milvus collection name",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate the collection before importing",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.getenv("FA_MILVUS_HOST", "localhost"),
        help="Milvus host",
    )
    parser.add_argument(
        "--port",
        type=str,
        default=os.getenv("FA_MILVUS_PORT", "19530"),
        help="Milvus port",
    )

    args = parser.parse_args()

    # Push CLI values into the env BEFORE CONFIG is imported. CONFIG is a
    # frozen dataclass that captures env vars once at import; ExternalDataStore
    # reads ``CONFIG.milvus_host`` / ``.milvus_port`` / ``.milvus_collection``
    # to build its EmbeddingSearch, so we have to set the env vars first for
    # them to take effect.
    os.environ["FA_MILVUS_HOST"] = args.host
    os.environ["FA_MILVUS_PORT"] = args.port
    os.environ["FA_MILVUS_COLLECTION"] = args.collection

    try:
        stats = import_data(
            data_dir=args.data_dir,
            collection_name=args.collection,
            host=args.host,
            port=args.port,
            recreate=args.recreate,
        )
        print("\n" + "=" * 60)
        print("Import Summary:")
        print("=" * 60)
        for key, value in stats.items():
            print(f"  {key}: {value}")
        print("=" * 60)
    except Exception as e:
        log.error("Import failed: %s", e)
        raise

if __name__ == "__main__":
    main()
