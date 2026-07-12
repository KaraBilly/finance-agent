# Finnhub API 免费/付费接口调查报告

> 调查时间：2025年7月12日
> 调查人：Finance Agent Team
> API Key：d99ou21r01qh9urkvmhgd99ou21r01qh9urkvmi0（免费版）

---

## 一、调查背景

本项目需要为美股 Finance Agent 寻找合适的数据源。Finnhub 是一个提供美股、外汇和加密货币数据的 API 平台，免费版提供 60 calls/minute 的额度。本次调查旨在明确免费版可用的 API 接口，为后续开发提供依据。

---

## 二、调查方法

1. 注册 Finnhub 免费账号，获取 API Key
2. 使用 Python requests 库逐一测试各端点
3. 根据 HTTP 状态码判断接口可用性：
   - `200` + JSON 数据 → 免费可用
   - `403` → 付费接口
   - `401` → 认证错误
   - 返回 HTML → 付费接口（重定向到付费页面）

---

## 三、调查结果

### ✅ 免费接口（Free Tier）

#### 1. 市场数据（Market Data）

| 端点 | 路径 | 说明 | 状态 |
|------|------|------|------|
| Quote | `/api/v1/quote` | 实时报价（当前价、涨跌幅、最高最低价） | ✅ 免费 |
| Profile | `/api/v1/stock/profile2` | 公司基本信息（名称、市值、行业等） | ✅ 免费 |
| Metric | `/api/v1/stock/metric` | 财务指标（133个指标，含P/E、P/B、ROE等） | ✅ 免费 |

**Quote 返回示例：**
```json
{
  "c": 315.32,    // 当前价格
  "d": -0.9,      // 涨跌额
  "dp": -0.2846,  // 涨跌幅%
  "h": 316.91,    // 当日最高
  "l": 312.17,    // 当日最低
  "o": 314.72,    // 开盘价
  "pc": 316.22,   // 昨收
  "t": 1783713600 // 时间戳
}
```

**Metric 返回示例：**
```json
{
  "metric": {
    "52WeekHigh": 317.4,
    "52WeekLow": 201.5,
    "marketCapitalization": 4631217.5,
    "peBasicExclExtraTTM": 37.7827,
    "pbQuarterly": 34.0011,
    "roeTTM": 146.69,
    "grossMarginTTM": 47.86
  }
}
```

#### 2. 财务数据（Financials）

| 端点 | 路径 | 说明 | 状态 |
|------|------|------|------|
| Financials Reported | `/api/v1/stock/financials-reported` | 完整财务报表（SEC原始数据） | ✅ 免费 |

**Financials Reported 返回示例：**
```json
{
  "cik": "0000320193",
  "data": [
    {
      "accessNumber": "0000320193-25-000079",
      "symbol": "AAPL",
      "year": 2025,
      "quarter": 0,
      "form": "10-K",
      "report": {
        "bs": [...],  // 资产负债表
        "ic": [...],  // 利润表
        "cf": [...]   // 现金流量表
      }
    }
  ],
  "symbol": "AAPL"
}
```

**注意：** 此接口返回 SEC 原始 XBRL 数据，包含完整的财务报表项目。

#### 3. 新闻（News）

| 端点 | 路径 | 说明 | 状态 |
|------|------|------|------|
| General News | `/api/v1/news` | 通用新闻（100条） | ✅ 免费 |
| Company News | `/api/v1/company-news` | 公司新闻 | ✅ 免费 |

**Company News 返回示例：**
```json
[
  {
    "category": "company",
    "datetime": 1783815682,
    "headline": "Google vs Apple: Which of the 2 Biggest AI Stocks...",
    "source": "Yahoo",
    "url": "https://...",
    "summary": "..."
  }
]
```

#### 4. 分析数据（Analysis）

| 端点 | 路径 | 说明 | 状态 |
|------|------|------|------|
| Peers | `/api/v1/stock/peers` | 同行公司 | ✅ 免费 |
| Recommendation | `/api/v1/stock/recommendation` | 分析师推荐 | ✅ 免费 |
| Earnings | `/api/v1/stock/earnings` | 盈利数据 | ✅ 免费 |
| Insider Transactions | `/api/v1/stock/insider-transactions` | 内部交易 | ✅ 免费 |
| Insider Sentiment | `/api/v1/stock/insider-sentiment` | 内部人情绪 | ✅ 免费 |

**Recommendation 返回示例：**
```json
[
  {
    "symbol": "AAPL",
    "period": "2026-07-01",
    "strongBuy": 13,
    "buy": 23,
    "hold": 16,
    "sell": 2,
    "strongSell": 0
  }
]
```

#### 5. 日历（Calendar）

| 端点 | 路径 | 说明 | 状态 |
|------|------|------|------|
| IPO Calendar | `/api/v1/calendar/ipo` | IPO日历 | ✅ 免费 |
| Earnings Calendar | `/api/v1/calendar/earnings` | 财报日历 | ✅ 免费 |

#### 6. SEC文件（Filings）

| 端点 | 路径 | 说明 | 状态 |
|------|------|------|------|
| Filings | `/api/v1/stock/filings` | SEC文件列表 | ✅ 免费 |

**Filings 返回示例：**
```json
[
  {
    "accessNumber": "0001140361-26-025622",
    "symbol": "AAPL",
    "cik": "320193",
    "form": "4",
    "filedDate": "2026-06-17 00:00:00",
    "reportUrl": "https://www.sec.gov/Archives/edgar/data/...",
    "filingUrl": "https://www.sec.gov/Archives/edgar/data/..."
  }
]
```

---

### ❌ 付费接口（Paid Only）

| 端点 | 路径 | 说明 | 状态 |
|------|------|------|------|
| Candles | `/api/v1/stock/candle` | 历史K线数据 | ❌ 付费 |
| Financials | `/api/v1/stock/financials` | 简化财务报表 | ❌ 付费 |
| Social Sentiment | `/api/v1/stock/social-sentiment` | 社交情绪 | ❌ 付费 |
| News Sentiment | `/api/v1/news-sentiment` | 新闻情绪 | ❌ 付费 |
| Price Target | `/api/v1/stock/price-target` | 价格目标 | ❌ 付费 |
| Upgrade/Downgrade | `/api/v1/stock/upgrade-downgrade` | 评级变化 | ❌ 付费 |
| Fund Ownership | `/api/v1/stock/fund-ownership` | 基金持仓 | ❌ 付费 |
| Institutional Ownership | `/api/v1/stock/institutional-ownership` | 机构持仓 | ❌ 付费 |
| CEO Compensation | `/api/v1/stock/ceo-compensation` | CEO薪酬 | ❌ 付费 |

**付费接口返回示例：**
```json
{"error": "You don't have access to this resource."}
```

---

## 四、免费版核心限制

### 1. 历史数据缺失
- **Candles（历史K线）** 是付费功能
- 无法获取历史日线、周线、月线数据
- **影响**：无法计算历史收益率、波动率、技术指标等

### 2. 实时性
- 免费版数据有 **15分钟延迟**
- 适合非高频交易场景

### 3. 请求频率
- **60 calls/minute**
- 对于多股票分析需要节流控制

### 4. ETF 数据限制
- ETF（如 QQQ）没有传统财务报表
- Profile2 对 ETF 返回空数据
- 部分分析接口（如 recommendation、earnings）对 ETF 返回空

---

## 五、替代方案

### 1. 历史数据替代
由于 Finnhub 免费版不提供历史K线，可考虑：

| 方案 | 说明 | 限制 |
|------|------|------|
| **Alpha Vantage** | 提供免费历史日线数据 | 25 calls/day |
| **Yahoo Finance** | yfinance 库获取历史数据 | 非官方API，可能不稳定 |
| **Polygon.io** | 提供免费历史数据 | 5 calls/min |

### 2. 实时数据替代
| 方案 | 说明 | 限制 |
|------|------|------|
| **WebSocket** | Finnhub 提供实时 WebSocket | 需要付费订阅 |
| **IEX Cloud** | 提供免费实时数据 | 有限额度 |

---

## 六、实施建议

### 1. 当前实现（MVP）
使用 Finnhub 免费版提供：
- ✅ 实时报价
- ✅ 公司基本信息
- ✅ 财务指标（P/E、P/B、ROE等）
- ✅ 完整财务报表
- ✅ 新闻
- ✅ 分析师推荐
- ✅ 内部交易
- ✅ SEC文件

### 2. 后续优化
- 集成 Alpha Vantage 获取历史数据
- 使用 yfinance 作为历史数据补充
- 考虑升级到 Finnhub 付费版（如需历史K线）

---

## 七、测试记录

### 测试环境
- Python: 3.8.8
- requests: 2.32.4
- 网络：中国大陆

### 测试代码
```python
import requests

token = 'd99ou21r01qh9urkvmhgd99ou21r01qh9urkvmi0'

# 测试免费接口
url = f'https://finnhub.io/api/v1/quote?symbol=AAPL&token={token}'
response = requests.get(url)
print(response.json())

# 测试付费接口
url = f'https://finnhub.io/api/v1/stock/candle?symbol=AAPL&resolution=D&from=1749331200&to=1783862400&token={token}'
response = requests.get(url)
print(response.status_code)  # 403
```

### 测试结果汇总

| 接口类别 | 免费接口数 | 付费接口数 | 总计 |
|---------|-----------|-----------|------|
| 市场数据 | 3 | 1 | 4 |
| 财务数据 | 1 | 1 | 2 |
| 新闻 | 2 | 0 | 2 |
| 分析 | 5 | 2 | 7 |
| 日历 | 2 | 0 | 2 |
| SEC文件 | 1 | 0 | 1 |
| **总计** | **14** | **9** | **23** |

---

## 八、参考链接

- Finnhub 官网：https://finnhub.io
- API 文档：https://finnhub.io/docs/api
- 定价页面：https://finnhub.io/pricing

---

## 九、附录：完整接口清单

### 免费接口（14个）
1. `/api/v1/quote` - 实时报价
2. `/api/v1/stock/profile2` - 公司信息
3. `/api/v1/stock/metric` - 财务指标
4. `/api/v1/stock/financials-reported` - 完整财报
5. `/api/v1/stock/filings` - SEC文件
6. `/api/v1/news` - 通用新闻
7. `/api/v1/company-news` - 公司新闻
8. `/api/v1/stock/peers` - 同行公司
9. `/api/v1/stock/recommendation` - 分析师推荐
10. `/api/v1/stock/earnings` - 盈利数据
11. `/api/v1/stock/insider-transactions` - 内部交易
12. `/api/v1/stock/insider-sentiment` - 内部人情绪
13. `/api/v1/calendar/ipo` - IPO日历
14. `/api/v1/calendar/earnings` - 财报日历

### 付费接口（9个）
1. `/api/v1/stock/candle` - 历史K线
2. `/api/v1/stock/financials` - 简化财报
3. `/api/v1/stock/social-sentiment` - 社交情绪
4. `/api/v1/news-sentiment` - 新闻情绪
5. `/api/v1/stock/price-target` - 价格目标
6. `/api/v1/stock/upgrade-downgrade` - 评级变化
7. `/api/v1/stock/fund-ownership` - 基金持仓
8. `/api/v1/stock/institutional-ownership` - 机构持仓
9. `/api/v1/stock/ceo-compensation` - CEO薪酬

---

*文档结束*
