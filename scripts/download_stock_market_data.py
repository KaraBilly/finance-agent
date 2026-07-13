#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载比亚迪、宁德时代、中际旭创三家公司20年内的日/周线市场数据

使用方法:
    python -m scripts.download_stock_market_data          # 下载所有数据
    python -m scripts.download_stock_market_data --weekly   # 仅下载周线
    python -m scripts.download_stock_market_data --daily    # 仅下载日线
"""
from __future__ import annotations
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from finance_agent.providers import EastmoneyMarketProvider

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("stock_market")

# 股票配置: (代码, 名称, 交易所)
STOCKS = [
    ("002594", "比亚迪", "sz"),      # 深交所
    ("300750", "宁德时代", "sz"),    # 深交所
    ("300308", "中际旭创", "sz"),    # 深交所
]

def download_daily_data(provider: EastmoneyMarketProvider, symbol: str, name: str, output_dir: Path) -> None:
    """下载日线数据"""
    end = datetime.now().strftime("%Y%m%d")
    start = str(int(end[:4]) - 20) + end[4:]  # 20年前
    
    log.info("下载 %s(%s) 日线数据 %s → %s", name, symbol, start, end)
    
    try:
        df = provider.get_stock_daily(symbol, start=start, end=end)
        if df.empty:
            log.warning("  %s(%s) 日线数据为空", name, symbol)
            return
        
        output_file = output_dir / f"{symbol}_{name}_daily.csv"
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        log.info("  ✓ 日线: %d 条记录 → %s", len(df), output_file)
        
    except Exception as e:
        log.error("  下载 %s(%s) 日线失败: %s", name, symbol, e)

def download_weekly_data(provider: EastmoneyMarketProvider, symbol: str, name: str, output_dir: Path) -> None:
    """下载周线数据"""
    end = datetime.now().strftime("%Y%m%d")
    start = str(int(end[:4]) - 20) + end[4:]  # 20年前
    
    log.info("下载 %s(%s) 周线数据 %s → %s", name, symbol, start, end)
    
    try:
        # 使用内部方法获取周线数据，klt=102表示周线
        from finance_agent.providers.cn.market_eastmoney import _fetch_kline, _secid_for_stock
        
        secid = _secid_for_stock(symbol)
        
        # 手动构建参数获取周线数据
        import requests
        import pandas as pd
        
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "102",   # 102=weekly
            "fqt": "1",     # 前复权
            "beg": start,
            "end": end,
        }
        
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            ),
            "Referer": "https://quote.eastmoney.com/",
        }
        
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        r = requests.get(url, params=params, headers=headers, timeout=15.0)
        r.raise_for_status()
        data = r.json() or {}
        payload = data.get("data") or {}
        klines = payload.get("klines") or []
        
        if not klines:
            log.warning("  %s(%s) 周线数据为空", name, symbol)
            return
        
        columns = [
            "date", "open", "close", "high", "low", "volume", "amount",
            "amplitude", "pct_change", "change", "turnover",
        ]
        numeric_cols = ["open", "close", "high", "low", "volume", "amount",
                       "amplitude", "pct_change", "change", "turnover"]
        
        rows = [ln.split(",") for ln in klines]
        df = pd.DataFrame(rows, columns=columns)
        for c in numeric_cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])
        
        output_file = output_dir / f"{symbol}_{name}_weekly.csv"
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        log.info("  ✓ 周线: %d 条记录 → %s", len(df), output_file)
        
    except Exception as e:
        log.error("  下载 %s(%s) 周线失败: %s", name, symbol, e)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="下载A股股票历史市场数据")
    parser.add_argument("--daily", action="store_true", help="仅下载日线数据")
    parser.add_argument("--weekly", action="store_true", help="仅下载周线数据")
    parser.add_argument("--output", "-o", type=str, default="data/market/stocks", 
                        help="输出目录 (默认: data/market/stocks)")
    args = parser.parse_args(argv)
    
    # 如果没有指定，默认都下载
    if not args.daily and not args.weekly:
        args.daily = True
        args.weekly = True
    
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    log.info("=" * 60)
    log.info("开始下载股票历史市场数据")
    log.info("输出目录: %s", output_dir.absolute())
    log.info("=" * 60)
    
    provider = EastmoneyMarketProvider()
    
    for symbol, name, exchange in STOCKS:
        log.info("\n【%s %s】", name, symbol)
        
        if args.daily:
            download_daily_data(provider, symbol, name, output_dir)
        
        if args.weekly:
            download_weekly_data(provider, symbol, name, output_dir)
    
    log.info("\n" + "=" * 60)
    log.info("下载完成!")
    log.info("=" * 60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
