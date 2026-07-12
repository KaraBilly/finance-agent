# A-Share Data Sources Guide

This guide explains how to download and use local data files for the Finance Agent.

## Overview

The Finance Agent now uses **local file-based data sources** instead of external APIs (like akshare or Tushare). This provides:

- **Offline capability**: No internet required after initial download
- **Faster access**: Local parquet files are much faster than API calls
- **Data control**: You own and control your data
- **Compliance**: No dependency on third-party data providers

## Data Structure

```
data/
├── market/
│   ├── indices/          # Index data (000001.parquet, etc.)
│   └── stocks/           # Stock data (600000.parquet, etc.)
├── financials/           # Financial statements
│   ├── 600000.parquet      # Income statement
│   ├── 600000_balance.parquet
│   └── 600000_cashflow.parquet
└── filings/              # Company filings
    ├── 600000_annual.parquet
    └── 600000_announcement.parquet
```

## Supported Data Sources for Download

### 1. akshare (Recommended)

**Pros:**
- Free and open-source
- Comprehensive A-share data
- Active community

**Cons:**
- Requires installation
- May have rate limits

**Installation:**
```bash
pip install akshare
```

**Usage:**
```bash
# Download indices
python scripts/download_market_data.py --source akshare --indices --start 20050101 --end 20241231

# Download sample stocks
python scripts/download_market_data.py --source akshare --stocks --start 20050101 --end 20241231

# Download financials
python scripts/download_financials_data.py --source akshare

# Download filings
python scripts/download_filings_data.py --source akshare
```

### 2. Yahoo Finance

**Pros:**
- No additional Python package needed (uses yfinance)
- Global coverage

**Cons:**
- Limited A-share data
- May have rate limits

**Installation:**
```bash
pip install yfinance
```

**Usage:**
```bash
python scripts/download_market_data.py --source yahoo --indices --start 20050101 --end 20241231
```

### 3. Tushare Pro

**Pros:**
- Professional-grade data
- Fast and reliable

**Cons:**
- Requires API key
- Paid for advanced features

**Registration:**
1. Visit https://tushare.pro
2. Register and get API token
3. Set environment variable: `export TUSHARE_API_KEY=your_token`

**Usage:**
```bash
python scripts/download_market_data.py --source tushare --indices --start 20050101 --end 20241231
```

### 4. JoinQuant (聚宽)

**Pros:**
- Professional platform
- Rich data types

**Cons:**
- Requires registration
- Paid for advanced features

**Registration:**
1. Visit https://www.joinquant.com
2. Register and get API token

### 5. Baostock

**Pros:**
- Free
- Simple API

**Cons:**
- Limited data types

**Installation:**
```bash
pip install baostock
```

## Sample Stocks

The download scripts include sample stocks from each exchange/board:

### SSE (上交所)
- 600000: 浦发银行
- 600519: 贵州茅台
- 601318: 中国平安
- 600036: 招商银行
- 600276: 恒瑞医药

### SZSE (深交所主板)
- 000001: 平安银行
- 000002: 万科A
- 000333: 美的集团
- 000568: 泸州老窖
- 000725: 京东方A

### GEM (创业板)
- 300001: 特锐德
- 300002: 神州泰岳
- 300003: 乐普医疗
- 300004: 南风股份
- 300005: 探路者

### STAR (科创板)
- 688001: 华兴源创
- 688002: 睿创微纳
- 688003: 天准科技
- 688004: 博汇科技
- 688005: 容百科技

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   pip install akshare  # or your preferred data source
   ```

2. **Download data:**
   ```bash
   # Download all data
   python scripts/download_all_data.py --source akshare
   
   # Or download individually
   python scripts/download_market_data.py --source akshare --indices --stocks
   python scripts/download_financials_data.py --source akshare
   python scripts/download_filings_data.py --source akshare
   ```

3. **Run the agent:**
   ```bash
   python -m finance_agent ask "分析上证指数近20年走势"
   ```

## Data Update

To update the data periodically:

```bash
# Update market data
python scripts/download_market_data.py --source akshare --indices --stocks --start 20240101 --end 20241231

# Update financials
python scripts/download_financials_data.py --source akshare

# Update filings
python scripts/download_filings_data.py --source akshare
```

## Troubleshooting

### "FileNotFoundError: Index data not found"

**Solution:** Run the download script first:
```bash
python scripts/download_market_data.py --source akshare --indices
```

### "akshare not installed"

**Solution:** Install akshare:
```bash
pip install akshare
```

### "No data for symbol"

**Possible causes:**
- Symbol doesn't exist
- Data source doesn't have the symbol
- Date range is incorrect

**Solution:**
- Check the symbol is correct
- Try a different data source
- Adjust the date range

## Custom Data Sources

You can also provide your own data by creating parquet files in the correct format:

### Market Data Format

Required columns:
- `date`: datetime
- `open`: float
- `high`: float
- `low`: float
- `close`: float
- `volume`: float (optional)
- `amount`: float (optional)
- `pct_change`: float (optional)

### Financials Data Format

Required columns:
- `date` or `end_date`: datetime
- Other columns depend on the statement type

### Filings Data Format

Required columns:
- `title`: string
- `ann_date` or `date`: datetime
- `url`: string (optional)

## Contributing

If you add support for a new data source, please:

1. Create a new download script in `scripts/`
2. Update this README
3. Submit a pull request

## License

Data downloaded from external sources is subject to their respective terms of service.
