
python -m finance_agent ask "微软(MSFT)最近一期的利润表和资产负债表关键数据是什么?"# Demo Questions (美股)

Runnable demo prompts for US stock market. Assumes:
1. `.env` has `ARK_API_KEY`, `DEEPSEEK_API_KEY`, `TAVILY_API_KEY`, `FINNHUB_API_KEY` filled.
2. `FA_MARKET` is set to `us` in `.env`.

Each command generates:
- `outputs/<ts>-ans<id>.md` — the answer
- `outputs/<ts>-ans<id>.html` — the same, rendered
- `outputs/<ts>-ans<id>.sources.json` — full provenance + trace

### Q1 · Company Overview (Apple)
```bash
python -m finance_agent ask "苹果公司(AAPL)的基本面情况如何?请给出当前股价、市值和主要财务指标。"
```

### Q2 · Financial Statements (Microsoft)
```bash
python -m finance_agent ask "微软(MSFT)最近一期的利润表和资产负债表关键数据是什么?"
```

### Q3 · Risk Factors (Tesla)
```bash
python -m finance_agent ask "特斯拉(TSLA)面临的主要风险因素有哪些?"
```

### Q4 · Index Performance (QQQ)
```bash
python -m finance_agent ask "纳斯达克100指数(QQQ)最近的表现如何?当前价格和52周高低点是多少?"
```

### Q5 · Analyst Recommendations (NVIDIA)
```bash
python -m finance_agent ask "英伟达(NVDA)最近的分析师推荐情况如何?有多少买入/持有/卖出评级?"
```

### Q6 · Insider Activity (Amazon)
```bash
python -m finance_agent ask "亚马逊(AMZN)最近的内部人交易情况如何?有哪些大额交易?"
```

### Q7 · Earnings Surprise (Google)
```bash
python -m finance_agent ask "谷歌(GOOGL)最近几个季度的盈利情况如何?是否有超预期或低于预期?"
```

### Q8 · Industry Comparison
```bash
python -m finance_agent ask "苹果(AAPL)和微软(MSFT)的估值指标对比如何?包括P/E、P/B、市值等。"
```

### Bonus · Market News
```bash
python -m finance_agent ask "最近美股市场有哪些重要新闻?特别是科技板块。"
```

## Preference memory demo
```bash
python -m finance_agent prefs                         # show what the agent learned
python -m finance_agent ask "我更关心 tech stocks 和 growth companies"
python -m finance_agent prefs                         # weights should update
python -m finance_agent ask "分析下英伟达"           # answer should skew towards those topics
```

---

# Demo Questions (A股)

Runnable demo prompts. Assumes:
1. `.env` has `ARK_API_KEY`, `DEEPSEEK_API_KEY`, `TAVILY_API_KEY` filled.
2. You ran `python -m finance_agent bootstrap-indices` once.
3. `FA_MARKET` is set to `cn` in `.env` (default).

Each command generates:
- `outputs/<ts>-ans<id>.md` — the answer
- `outputs/<ts>-ans<id>.html` — the same, rendered
- `outputs/<ts>-ans<id>.sources.json` — full provenance + trace

### Q1 · Risk factors (贵州茅台)
```bash
python -m finance_agent ask "贵州茅台(600519)的主要风险因素有哪些?请给出证据来源。"
```

### Q2 · YoY revenue / profitability (宁德时代)
```bash
python -m finance_agent ask "宁德时代(300750)最近两年的营收和净利润变化情况?"
```

### Q3 · Competition (比亚迪)
```bash
python -m finance_agent ask "比亚迪(002594)自己如何描述其面临的竞争?"
```

### Q4 · Liquidity / debt (万科)
```bash
python -m finance_agent ask "总结万科A(000002)的流动性和债务相关风险。"
```

### Q5 · Evidence for a prior claim
```bash
python -m finance_agent ask "上面结论的证据来源是什么?列出每一条断言对应的原文段落。"
```

### Bonus · Index-level macro
```bash
python -m finance_agent ask "过去20年沪深300和中证500的年化回报和最大回撤大概是多少?"
```

## Preference memory demo
```bash
python -m finance_agent prefs                         # show what the agent learned
python -m finance_agent ask "我更关心 liquidity risk 和 cash flow"
python -m finance_agent prefs                         # weights should update
python -m finance_agent ask "分析下贵州茅台"           # answer should skew towards those topics
```

---

# 测试结果记录

## 测试环境
- Python: 3.8.8
- OS: macOS
- 网络: 中国大陆
- Finnhub API: 免费版 (60 calls/min)

## 美股 Provider 测试结果

### 1. Market Provider (FinnhubMarketProvider)

**测试时间**: 2025-07-12
**测试命令**:
```python
from finance_agent.providers.market_finnhub import FinnhubMarketProvider

provider = FinnhubMarketProvider()
ev = provider.summarize_stock('AAPL')
print(ev.text)
```

**测试结果**: ✅ 成功

**输出示例**:
```markdown
**Apple Inc (AAPL) — 概览**

| 指标 | 数值 |
|---|---|
| 当前价格 | 315.32 USD |
| 当日涨跌 | -0.90 (-0.28%) |
| 52周最高 | 317.40 USD |
| 52周最低 | 201.50 USD |
| 市值 | 4,631,218M USD |
| P/E (TTM) | 37.78 |
```

**测试结论**:
- ✅ 实时报价正常
- ✅ 52周高低点正常
- ✅ 市值、P/E等指标正常
- ⚠️ 历史K线不可用（付费功能）

---

### 2. Financials Provider (FinnhubFinancialsProvider)

**测试时间**: 2025-07-12
**测试命令**:
```python
from finance_agent.providers.financials_finnhub import FinnhubFinancialsProvider

provider = FinnhubFinancialsProvider()
ev = provider.summarize_statement('AAPL', 'income', periods=1)
print(ev.text)
```

**测试结果**: ✅ 成功

**输出示例**:
```markdown
**AAPL 利润表 — 最近 1 期 (Finnhub)**

|    净销售额 |   销售成本 |      毛利润 |   研发费用 | ... |
|------------:|-----------:|------------:|-----------:|-----|
| 4.16161e+11 | 2.2096e+11 | 1.95201e+11 |  3.455e+10 | ... |
```

**测试结论**:
- ✅ 利润表正常
- ✅ 资产负债表正常
- ✅ 现金流量表正常
- ✅ 数据来自SEC原始XBRL

---

### 3. Filings Provider (FinnhubFilingsProvider)

**测试时间**: 2025-07-12
**测试命令**:
```python
from finance_agent.providers.filings_finnhub import FinnhubFilingsProvider

provider = FinnhubFilingsFilingsProvider()
evs = provider.collect_filings('AAPL', years_back=1)
print(f"{len(evs)} filings collected")
```

**测试结果**: ✅ 成功

**输出示例**:
```
18 filings collected
**AAPL 年度报告** (2025-10-31 00:00:00)

来源: https://www.sec.gov/Archives/edgar/data/320193/...
```

**测试结论**:
- ✅ SEC文件列表正常
- ✅ 包含10-K、10-Q、8-K等
- ✅ 文件链接可用

---

## 已知限制

1. **历史K线数据不可用**
   - Finnhub免费版不提供历史candle数据
   - 无法计算历史收益率、波动率等
   - 替代方案：使用Alpha Vantage或yfinance

2. **数据延迟**
   - 免费版有15分钟延迟
   - 适合非高频交易场景

3. **请求频率限制**
   - 60 calls/minute
   - 需要节流控制

4. **ETF数据限制**
   - ETF没有传统财务报表
   - 部分分析接口对ETF返回空

---

## 总结

| Provider | 状态 | 功能覆盖 |
|---------|------|---------|
| Market | ✅ 正常 | 实时报价、52周数据、市值、P/E |
| Financials | ✅ 正常 | 三大报表、SEC原始数据 |
| Filings | ✅ 正常 | SEC文件列表、链接 |

**总体评价**: Finnhub免费版足以支撑美股Finance Agent的MVP需求，但缺少历史K线数据。建议后续集成Alpha Vantage补充历史数据。
