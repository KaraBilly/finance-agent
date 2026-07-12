#!/usr/bin/env python3
"""Download A-share market data (indices and stocks) from external sources.

This script downloads historical market data and saves it to local parquet files.
It can use multiple data sources (akshare, yfinance, etc.) as a one-time download.

Usage:
    python download_market_data.py --source akshare --start 20050101 --end 20241231
    python download_market_data.py --source yahoo --symbols 000001.SS 399001.SZ
"""
from __future__ import annotations
import argparse
import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Default indices
DEFAULT_INDICES = {
    "000001": "上证指数",
    "399001": "深证成指",
    "000300": "沪深300",
    "000905": "中证500",
    "399006": "创业板指",
    "000016": "上证50",
    "000852": "中证1000",
}

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


def download_via_akshare(symbols: dict[str, str], start: str, end: str, output_dir: Path) -> None:
    """Download data using akshare."""
    try:
        import akshare as ak
    except ImportError:
        log.error("akshare not installed. Install with: pip install akshare")
        return
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for symbol, name in symbols.items():
        try:
            log.info("Downloading %s (%s)...", symbol, name)
            
            # For indices
            if symbol in DEFAULT_INDICES:
                df = ak.index_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end)
            else:
                # For stocks
                df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end, adjust="qfq")
            
            if df.empty:
                log.warning("No data for %s", symbol)
                continue
            
            # Standardize column names
            rename = {
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "涨跌幅": "pct_change",
            }
            df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
            df["date"] = pd.to_datetime(df["date"])
            
            # Save to parquet
            output_path = output_dir / f"{symbol}.parquet"
            df.to_parquet(output_path, index=False)
            log.info("Saved %s: %d rows", output_path, len(df))
            
        except Exception as e:
            log.error("Failed to download %s: %s", symbol, e)


def download_via_yahoo(symbols: dict[str, str], start: str, end: str, output_dir: Path) -> None:
    """Download data using yfinance (Yahoo Finance)."""
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed. Install with: pip install yfinance")
        return
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for symbol, name in symbols.items():
        try:
            log.info("Downloading %s (%s)...", symbol, name)
            
            # Yahoo Finance uses different symbol formats
            if symbol.startswith("6"):
                yahoo_symbol = f"{symbol}.SS"
            else:
                yahoo_symbol = f"{symbol}.SZ"
            
            ticker = yf.Ticker(yahoo_symbol)
            df = ticker.history(start=start, end=end)
            
            if df.empty:
                log.warning("No data for %s", symbol)
                continue
            
            # Reset index to make date a column
            df = df.reset_index()
            df.columns = [c.lower().replace(" ", "_") for c in df.columns]
            
            # Standardize column names
            rename = {
                "date": "date",
                "open": "open",
                "close": "close",
                "high": "high",
                "low": "low",
                "volume": "volume",
            }
            df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
            df["date"] = pd.to_datetime(df["date"])
            
            # Save to parquet
            output_path = output_dir / f"{symbol}.parquet"
            df.to_parquet(output_path, index=False)
            log.info("Saved %s: %d rows", output_path, len(df))
            
        except Exception as e:
            log.error("Failed to download %s: %s", symbol, e)


def main():
    parser = argparse.ArgumentParser(description="Download A-share market data")
    parser.add_argument("--source", choices=["akshare", "yahoo"], default="akshare",
                       help="Data source to use")
    parser.add_argument("--start", default="20050101", help="Start date (YYYYMMDD)")
    parser.add_argument("--end", default=datetime.now().strftime("%Y%m%d"), help="End date (YYYYMMDD)")
    parser.add_argument("--output", default="data/market", help="Output directory")
    parser.add_argument("--indices", action="store_true", help="Download indices")
    parser.add_argument("--stocks", action="store_true", help="Download sample stocks")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output)
    
    if args.indices:
        log.info("Downloading indices...")
        indices_dir = output_dir / "indices"
        if args.source == "akshare":
            download_via_akshare(DEFAULT_INDICES, args.start, args.end, indices_dir)
        elif args.source == "yahoo":
            download_via_yahoo(DEFAULT_INDICES, args.start, args.end, indices_dir)
    
    if args.stocks:
        log.info("Downloading sample stocks...")
        stocks_dir = output_dir / "stocks"
        if args.source == "akshare":
            download_via_akshare(SAMPLE_STOCKS, args.start, args.end, stocks_dir)
        elif args.source == "yahoo":
            download_via_yahoo(SAMPLE_STOCKS, args.start, args.end, stocks_dir)
    
    if not args.indices and not args.stocks:
        log.info("Please specify --indices and/or --stocks")


if __name__ == "__main__":
    main()
