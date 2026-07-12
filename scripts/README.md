# Data Download Scripts

This directory contains scripts to download A-share market data and save it to local files.

## Prerequisites

```bash
pip install akshare pandas pyarrow
```

## Market Data Download

### Download Indices (past 20 years)
```bash
python download_market_data.py --source akshare --indices --start 20050101 --end 20241231
```

### Download Sample Stocks
```bash
python download_market_data.py --source akshare --stocks --start 20050101 --end 20241231
```

### Download Both
```bash
python download_market_data.py --source akshare --indices --stocks --start 20050101 --end 20241231
```

## Financial Data Download

```bash
python download_financials_data.py --source akshare
```

## Filings Data Download

```bash
python download_filings_data.py --source akshare
```

## Data Structure

After running the scripts, the data will be organized as:

```
data/
├── market/
│   ├── indices/          # Index data (000001.parquet, etc.)
│   └── stocks/             # Stock data (600000.parquet, etc.)
├── financials/           # Financial statements
│   ├── 600000.parquet      # Income statement
│   ├── 600000_balance.parquet
│   └── 600000_cashflow.parquet
└── filings/              # Company filings
    ├── 600000_annual.parquet
    └── 600000_announcement.parquet
```

## Supported Data Sources

- **akshare**: Chinese financial data library (requires installation)
- **yahoo**: Yahoo Finance (requires `yfinance` package)

## Notes

- The first run may take a while as it downloads historical data
- Data is cached locally in parquet format for fast access
- Run the scripts periodically to update the data
