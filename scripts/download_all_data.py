#!/usr/bin/env python3
"""Download all A-share data (market, financials, filings) from external sources.

This script downloads all data and saves it to local files.

Usage:
    python download_all_data.py --source akshare
"""
from __future__ import annotations
import argparse
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def run_script(script_name: str, args: list[str]) -> None:
    """Run a download script."""
    script_path = Path(__file__).parent / script_name
    if not script_path.exists():
        log.error("Script not found: %s", script_path)
        return
    
    cmd = [sys.executable, str(script_path)] + args
    log.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("Script failed: %s", result.stderr)
    else:
        log.info("Script output:\n%s", result.stdout)


def main():
    parser = argparse.ArgumentParser(description="Download all A-share data")
    parser.add_argument("--source", choices=["akshare", "yahoo"], default="akshare",
                       help="Data source to use")
    parser.add_argument("--start", default="20050101", help="Start date (YYYYMMDD)")
    parser.add_argument("--end", default="20241231", help="End date (YYYYMMDD)")
    
    args = parser.parse_args()
    
    # Download market data
    log.info("=" * 60)
    log.info("Downloading market data...")
    log.info("=" * 60)
    run_script("download_market_data.py", [
        "--source", args.source,
        "--start", args.start,
        "--end", args.end,
        "--indices",
        "--stocks",
    ])
    
    # Download financials data
    log.info("=" * 60)
    log.info("Downloading financials data...")
    log.info("=" * 60)
    run_script("download_financials_data.py", [
        "--source", args.source,
    ])
    
    # Download filings data
    log.info("=" * 60)
    log.info("Downloading filings data...")
    log.info("=" * 60)
    run_script("download_filings_data.py", [
        "--source", args.source,
    ])
    
    log.info("=" * 60)
    log.info("All data downloaded successfully!")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
