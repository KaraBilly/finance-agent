#!/usr/bin/env python3
"""Download A-share financial data from external sources.

This script downloads financial statements and saves them to local parquet files.

Usage:
    python download_financials_data.py --source akshare --symbols 600000 000001
"""
from __future__ import annotations
import argparse
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Sample stocks from each exchange/board
SAMPLE_STOCKS = {
    # SSE (上交所)
    "600000": "浦发银行",
    "600519": "贵州茅台",
    "601318": "中国平安",
    "600036": "招商银行",
    "600276": "恒瑞医药",
    # SZSE (深交所主板)
    "000001": "平安银行",
    "000002": "万科A",
    "000333": "美的集团",
    "000568": "泸州老窖",
    "000725": "京东方A",
    # GEM (创业板)
    "300001": "特锐德",
    "300002": "神州泰岳",
    "300003": "乐普医疗",
    "300004": "南风股份",
    "300005": "探路者",
    # STAR (科创板)
    "688001": "华兴源创",
    "688002": "睿创微纳",
    "688003": "天准科技",
    "688004": "博汇科技",
    "688005": "容百科技",
}


def download_via_akshare(symbols: dict[str, str], output_dir: Path) -> None:
    """Download financial data using akshare."""
    try:
        import akshare as ak
    except ImportError:
        log.error("akshare not installed. Install with: pip install akshare")
        return
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for symbol, name in symbols.items():
        try:
            log.info("Downloading financials for %s (%s)...", symbol, name)
            
            # Download income statement
            try:
                df_income = ak.stock_financial_report_sina(stock=f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}", symbol="利润表")
                if not df_income.empty:
                    output_path = output_dir / f"{symbol}.parquet"
                    df_income.to_parquet(output_path, index=False)
                    log.info("Saved income statement: %s", output_path)
            except Exception as e:
                log.warning("Failed to download income statement for %s: %s", symbol, e)
            
            # Download balance sheet
            try:
                df_balance = ak.stock_financial_report_sina(stock=f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}", symbol="资产负债表")
                if not df_balance.empty:
                    output_path = output_dir / f"{symbol}_balance.parquet"
                    df_balance.to_parquet(output_path, index=False)
                    log.info("Saved balance sheet: %s", output_path)
            except Exception as e:
                log.warning("Failed to download balance sheet for %s: %s", symbol, e)
            
            # Download cash flow statement
            try:
                df_cashflow = ak.stock_financial_report_sina(stock=f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}", symbol="现金流量表")
                if not df_cashflow.empty:
                    output_path = output_dir / f"{symbol}_cashflow.parquet"
                    df_cashflow.to_parquet(output_path, index=False)
                    log.info("Saved cash flow statement: %s", output_path)
            except Exception as e:
                log.warning("Failed to download cash flow for %s: %s", symbol, e)
            
        except Exception as e:
            log.error("Failed to download financials for %s: %s", symbol, e)


def main():
    parser = argparse.ArgumentParser(description="Download A-share financial data")
    parser.add_argument("--source", choices=["akshare"], default="akshare",
                       help="Data source to use")
    parser.add_argument("--symbols", nargs="+", default=list(SAMPLE_STOCKS.keys()),
                       help="Stock symbols to download")
    parser.add_argument("--output", default="data/financials", help="Output directory")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output)
    symbols = {s: SAMPLE_STOCKS.get(s, s) for s in args.symbols}
    
    if args.source == "akshare":
        download_via_akshare(symbols, output_dir)


if __name__ == "__main__":
    main()
