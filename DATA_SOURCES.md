# 数据源方案

Agent 只依赖 `finance_agent/capabilities/*` 抽象层，替换数据源 = 换 `providers/*.py` + `registry.py` 一次绑定，Agent 代码零改动。

---

## 美股 — Finnhub API

| Capability | 端点 | 说明 |
|---|---|---|
| `MarketDataCapability` | `/api/v1/quote`, `/api/v1/stock/metric` | 实时报价、财务指标（133个） |
| `FinancialsCapability` | `/api/v1/stock/financials-reported` | 完整财务报表（SEC 原始 XBRL） |
| `FilingsCapability` | `/api/v1/stock/filings` | SEC 文件列表（10-K, 10-Q, 8-K） |
| `WebSearchCapability` | Tavily | web 搜索（保留） |

**免费版限制：**
- 60 calls/minute
- 15 分钟延迟
- 无历史 K 线（candle 付费）

**环境变量：**
- `FINNHUB_API_KEY` — 必需

---

## A股 — 外挂本地数据

| Capability | 数据源 |
|---|---|
| `MarketDataCapability` | 本地 CSV 文件（`data/market/`） |
| `FinancialsCapability` | 本地 CSV 文件（`data/financials/`） |
| `FilingsCapability` | 本地 MD/TXT 文件（`data/filings/`） |
| `WebSearchCapability` | Tavily（保留） |

**文件格式：**
- CSV: 自动按行分块
- JSON/JSONL: 自动按条目分块
- Markdown/Text: 按段落分块

**环境变量：**
- `FA_USE_EXTERNAL_DATA=true` — 启用外挂数据
- `FA_EXTERNAL_MARKET_DIR` — 自定义市场数据目录
- `FA_EXTERNAL_FINANCIALS_DIR` — 自定义财务数据目录
- `FA_EXTERNAL_FILINGS_DIR` — 自定义公告数据目录

---

## Provider 迁移

Capability 接口不变，已实现的 Provider：

- `providers/us/market_finnhub.py` — Finnhub 美股行情
- `providers/us/financials_finnhub.py` — Finnhub 美股财务
- `providers/us/filings_finnhub.py` — Finnhub SEC 文件
- `providers/cn/market_external.py` — A股外挂市场数据
- `providers/cn/financials_external.py` — A股外挂财务数据
- `providers/cn/filings_external.py` — A股外挂公告
- `registry.py` — 默认绑定（根据 `FA_MARKET` 自动切换）

---

*文档版本: 2026-07-14*
