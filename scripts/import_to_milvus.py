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
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finance_agent.config import CONFIG
from finance_agent.retrieval.external_data_store import ExternalDataStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)


def import_data(
    data_dir: Path | None = None,
    collection_name: str | None = None,
    recreate: bool = False,
) -> None:
    """Import external data into Milvus.
    
    Args:
        data_dir: Data directory (default from config)
        collection_name: Milvus collection name (default from config)
        recreate: Whether to recreate collection if exists
    """
    log.info("Starting data import to Milvus...")
    
    # Initialize data store
    store = ExternalDataStore(
        market_dir=(data_dir / "market") if data_dir else None,
        financials_dir=(data_dir / "financials") if data_dir else None,
        filings_dir=(data_dir / "filings") if data_dir else None,
        use_embedding=True,
        use_milvus=True,
    )
    
    # Load all data
    log.info("Loading external data...")
    store.load_all()
    
    # Get stats
    stats = store.get_stats()
    log.info("Import complete!")
    log.info("Stats: %s", stats)
    
    return stats


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Import external data into Milvus vector database"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=CONFIG.data_dir,
        help="Data directory (default: from config)",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=CONFIG.milvus_collection,
        help="Milvus collection name (default: from config)",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate collection if exists",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=CONFIG.milvus_host,
        help="Milvus host (default: from config)",
    )
    parser.add_argument(
        "--port",
        type=str,
        default=CONFIG.milvus_port,
        help="Milvus port (default: from config)",
    )
    
    args = parser.parse_args()
    
    # Override config with CLI args
    import os
    os.environ["FA_MILVUS_HOST"] = args.host
    os.environ["FA_MILVUS_PORT"] = args.port
    os.environ["FA_MILVUS_COLLECTION"] = args.collection
    
    try:
        stats = import_data(
            data_dir=args.data_dir,
            collection_name=args.collection,
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
