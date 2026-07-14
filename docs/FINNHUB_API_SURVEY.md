# Finnhub API 接口清单

> 调查时间：2025年7月12日

---

## 免费接口（14个）

| 类别 | 端点 | 说明 |
|------|------|------|
| 市场数据 | `/api/v1/quote` | 实时报价 |
| 市场数据 | `/api/v1/stock/profile2` | 公司信息 |
| 市场数据 | `/api/v1/stock/metric` | 财务指标（133个） |
| 财务数据 | `/api/v1/stock/financials-reported` | 完整财报（SEC 原始 XBRL） |
| SEC文件 | `/api/v1/stock/filings` | SEC 文件列表 |
| 新闻 | `/api/v1/news` | 通用新闻 |
| 新闻 | `/api/v1/company-news` | 公司新闻 |
| 分析 | `/api/v1/stock/peers` | 同行公司 |
| 分析 | `/api/v1/stock/recommendation` | 分析师推荐 |
| 分析 | `/api/v1/stock/earnings` | 盈利数据 |
| 分析 | `/api/v1/stock/insider-transactions` | 内部交易 |
| 分析 | `/api/v1/stock/insider-sentiment` | 内部人情绪 |
| 日历 | `/api/v1/calendar/ipo` | IPO日历 |
| 日历 | `/api/v1/calendar/earnings` | 财报日历 |

## 付费接口（9个）

| 端点 | 说明 |
|------|------|
| `/api/v1/stock/candle` | 历史K线 |
| `/api/v1/stock/financials` | 简化财报 |
| `/api/v1/stock/social-sentiment` | 社交情绪 |
| `/api/v1/news-sentiment` | 新闻情绪 |
| `/api/v1/stock/price-target` | 价格目标 |
| `/api/v1/stock/upgrade-downgrade` | 评级变化 |
| `/api/v1/stock/fund-ownership` | 基金持仓 |
| `/api/v1/stock/institutional-ownership` | 机构持仓 |
| `/api/v1/stock/ceo-compensation` | CEO薪酬 |

## 免费版限制

- **60 calls/minute**
- **15 分钟延迟**
- **无历史 K 线**（candle 付费）
- **ETF 数据有限**

## 替代方案

| 需求 | 方案 | 限制 |
|------|------|------|
| 历史数据 | Alpha Vantage | 25 calls/day |
| 历史数据 | yfinance | 非官方API，不稳定 |
| 历史数据 | Polygon.io | 5 calls/min |

---

*完整调查报告见原始文件*
