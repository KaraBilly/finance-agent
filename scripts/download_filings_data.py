#!/usr/bin/env python3
"""Download A-share filings data from external sources.

This script downloads company filings and saves them to local parquet files.

Usage:
    python download_filings_data.py --source akshare --symbols 600000 000001
"""
from __future__ import annotations
import argparse
import logging
from datetime import datetime
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
    """Download filings data using akshare."""
    try:
        import akshare as ak
    except ImportError:
        log.error("akshare not installed. Install with: pip install akshare")
        return
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for symbol, name in symbols.items():
        try:
            log.info("Downloading filings for %s (%s)...", symbol, name)
            
            # Download annual reports
            try:
                now = datetime.now()
                start = now.replace(year=now.year - 5).strftime("%Y%m%d")
                end = now.strftime("%Y%m%d")
                df = ak.stock_zh_a_disclosure_report_cninfo(
                    symbol=symbol,
                    market="沪深京",
                    category="年报",
                    start_date=start,
                    end_date=end,
                )
                if not df.empty:
                    output_path = output_dir / f"{symbol}_annual.parquet"
                    df.to_parquet(output_path, index=False)
                    log.info("Saved annual reports: %s", output_path)
            except Exception as e:
                log.warning("Failed to download annual reports for %s: %s", symbol, e)
            
            # Download announcements
            try:
                df = ak.stock_notice_report(symbol="全部", date=datetime.now().strftime("%Y%m%d"))
                if not df.empty:
                    # Filter by symbol
                    code_col = next((c for c in df.columns if "代码" in c), None)
                    if code_col:
                        df = df[df[code_col].astype(str) == symbol]
                    
                    if not df.empty:
                        output_path = output_dir / f"{symbol}_announcement.parquet"
                        df.to_parquet(output_path, index=False)
                        log.info("Saved announcements: %s", output_path)
            except Exception as e:
                log.warning("Failed to download announcements for %s: %s", symbol, e)
            
        except Exception as e:
            log.error("Failed to download filings for %s: %s", symbol, e)


def main():
    parser = argparse.ArgumentParser(description="Download A-share filings data")
    parser.add_argument("--source", choices=["akshare"], default="akshare",
                       help="Data source to use")
    parser.add_argument("--symbols", nargs="+", default=list(SAMPLE_STOCKS.keys()),
                       help="Stock symbols to download")
    parser.add_argument("--output", default="data/filings", help="Output directory")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output)
    symbols = {s: SAMPLE_STOCKS.get(s, s) for s in args.symbols}
    
    if args.source == "akshare":
        download_via_akshare(symbols, output_dir)


if __name__ == "__main__":
    main()
