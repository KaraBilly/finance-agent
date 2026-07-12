# 数据外挂改造总结

## 改造目标

将原有的 akshare 爬虫数据源替换为**本地文件外挂**形式，实现：
1. **China Market Data**: 包含过去20年的指数、成交量、成交价等
2. **Financial Data & Company Filing Data**: 上交所、深交所、创业板、科创板各5家

## 改造内容

### 1. 新增本地文件数据源 Provider

#### `finance_agent/providers/market_local.py`
- **LocalMarketProvider**: 从本地 parquet 文件读取市场数据
- 支持指数和个股数据
- 自动按日期过滤
- 数据目录: `data/market/indices/` 和 `data/market/stocks/`

#### `finance_agent/providers/financials_local.py`
- **LocalFinancialsProvider**: 从本地 parquet 文件读取财务报表
- 支持利润表、资产负债表、现金流量表
- 数据目录: `data/financials/`

#### `finance_agent/providers/filings_local.py`
- **LocalFilingsProvider**: 从本地 parquet 文件读取公司公告
- 支持年报和公告
- 数据目录: `data/filings/`

### 2. 数据下载脚本

#### `scripts/download_market_data.py`
- 下载指数和个股历史数据
- 支持 akshare 和 Yahoo Finance 数据源
- 自动保存为 parquet 格式

#### `scripts/download_financials_data.py`
- 下载财务报表数据
- 支持 akshare 数据源

#### `scripts/download_filings_data.py`
- 下载公司公告数据
- 支持 akshare 数据源

#### `scripts/download_all_data.py`
- 一键下载所有数据

### 3. 样本股票

从四个板块各选取5家代表性公司：

| 板块 | 股票代码 | 公司名称 |
|------|----------|----------|
| **SSE (上交所)** | 600000 | 浦发银行 |
| | 600519 | 贵州茅台 |
| | 601318 | 中国平安 |
| | 600036 | 招商银行 |
| | 600276 | 恒瑞医药 |
| **SZSE (深交所)** | 000001 | 平安银行 |
| | 000002 | 万科A |
| | 000333 | 美的集团 |
| | 000568 | 泸州老窖 |
| | 000725 | 京东方A |
| **GEM (创业板)** | 300001 | 特锐德 |
| | 300002 | 神州泰岳 |
| | 300003 | 乐普医疗 |
| | 300004 | 南风股份 |
| | 300005 | 探路者 |
| **STAR (科创板)** | 688001 | 华兴源创 |
| | 688002 | 睿创微纳 |
| | 688003 | 天准科技 |
| | 688004 | 博汇科技 |
| | 688005 | 容百科技 |

### 4. 支持的指数

| 代码 | 名称 |
|------|------|
| 000001 | 上证指数 |
| 399001 | 深证成指 |
| 000300 | 沪深300 |
| 000905 | 中证500 |
| 399006 | 创业板指 |
| 000016 | 上证50 |
| 000852 | 中证1000 |

### 5. 更新 Registry

修改 `finance_agent/registry.py`，使用新的本地 Provider：

```python
def _build_data_providers():
    from .providers import (
        LocalMarketProvider,
        LocalFinancialsProvider,
        LocalFilingsProvider,
        TavilyWebProvider,
        SQLiteStorageProvider,
    )
    return {
        "market_data": LocalMarketProvider(),
        "financials": LocalFinancialsProvider(),
        "filings": LocalFilingsProvider(),
        "web_search": TavilyWebProvider(),
        "storage": SQLiteStorageProvider(),
    }
```

### 6. 更新 CLI

修改 `finance_agent/cli.py`，使用新的 Provider：

```python
@cli.command("bootstrap-indices")
def bootstrap_indices(symbols):
    from .providers import LocalMarketProvider
    market = LocalMarketProvider()
    # ...
```

### 7. 数据下载指南

#### 使用 akshare（推荐）

```bash
# 安装 akshare
pip install akshare

# 下载指数数据（过去20年）
python scripts/download_market_data.py --source akshare --indices --start 20050101 --end 20241231

# 下载样本股票数据
python scripts/download_market_data.py --source akshare --stocks --start 20050101 --end 20241231

# 下载财务报表
python scripts/download_financials_data.py --source akshare

# 下载公司公告
python scripts/download_filings_data.py --source akshare
```

#### 使用 Yahoo Finance

```bash
# 安装 yfinance
pip install yfinance

# 下载数据
python scripts/download_market_data.py --source yahoo --indices --stocks
```

### 8. 数据文件格式

#### 市场数据格式 (parquet)

```
data/market/
├── indices/
│   ├── 000001.parquet    # 上证指数
│   ├── 399001.parquet    # 深证成指
│   └── ...
└── stocks/
    ├── 600000.parquet    # 浦发银行
    ├── 600519.parquet    # 贵州茅台
    └── ...
```

必需列：
- `date`: datetime
- `open`, `high`, `low`, `close`: float
- `volume`, `amount`: float (可选)
- `pct_change`: float (可选)

#### 财务数据格式 (parquet)

```
data/financials/
├── 600000.parquet           # 利润表
├── 600000_balance.parquet   # 资产负债表
└── 600000_cashflow.parquet  # 现金流量表
```

#### 公告数据格式 (parquet)

```
data/filings/
├── 600000_annual.parquet       # 年报
└── 600000_announcement.parquet # 公告
```

必需列：
- `title`: string
- `ann_date` 或 `date`: datetime
- `url`: string (可选)

## 使用说明

### 1. 安装依赖

```bash
pip install -r requirements.txt
pip install akshare  # 或其他数据源
```

### 2. 下载数据

```bash
# 一键下载所有数据
python scripts/download_all_data.py --source akshare
```

### 3. 运行 Agent

```bash
python -m finance_agent ask "分析上证指数近20年走势"
```

## 优势

1. **离线可用**: 下载后无需网络连接
2. **速度更快**: 本地文件读取比 API 调用快得多
3. **数据可控**: 完全掌控数据质量和更新频率
4. **合规安全**: 不依赖第三方数据提供商
5. **成本更低**: 无需支付 API 费用

## 注意事项

1. **首次下载**: 需要运行下载脚本获取初始数据
2. **数据更新**: 定期运行下载脚本更新数据
3. **数据缺失**: 如果文件不存在，会抛出 FileNotFoundError 并提示运行下载脚本
4. **Web Search**: 保持不变，仍然使用 TavilyWebProvider

## 文件变更

### 新增文件
- `finance_agent/providers/market_local.py`
- `finance_agent/providers/financials_local.py`
- `finance_agent/providers/filings_local.py`
- `scripts/download_market_data.py`
- `scripts/download_financials_data.py`
- `scripts/download_filings_data.py`
- `scripts/download_all_data.py`
- `scripts/README.md`
- `README_DATA_SOURCES.md`

### 修改文件
- `finance_agent/providers/__init__.py`
- `finance_agent/registry.py`
- `finance_agent/cli.py`
- `requirements.txt`
- `.env.example`

### 保留文件（未改动）
- `finance_agent/providers/llm_openai.py`
- `finance_agent/providers/web_tavily.py`
- `finance_agent/providers/storage_sqlite.py`
- `finance_agent/capabilities/` (所有文件)
- `finance_agent/agent/` (所有文件)
