# 数据源方案 — 直连东方财富 / 巨潮官方 JSON

akshare 是"网页/JSON 反解聚合器"(Sina / 东财 / cninfo 网页),字段不稳、易被封 IP。本项目**只**使用下列两个官方 JSON 前端接口(网站自己就靠它们渲染),全部**免费、无 token、无注册**。

Agent 只依赖 `finance_agent/capabilities/*` 抽象层,替换数据源 = 换 `providers/*.py` + `registry.py` 一次绑定,Agent 代码零改动。

---

## 1. Capability × 数据源

| Capability | 数据源 |
|---|---|
| `MarketDataCapability` | 东方财富 API (`push2his.eastmoney.com`) |
| `FinancialsCapability` | 东方财富 API (`datacenter-web.eastmoney.com`) |
| `FilingsCapability` | 巨潮 API (`www.cninfo.com.cn/new/hisAnnouncement/query`) |
| `WebSearchCapability` | Tavily (保留,不改) |

---

## 2. 东方财富 API

东方财富网站前端使用的 JSON API,**无需 token**。

### 2.1 行情数据 (market)

**个股日线**:
```python
import requests, pandas as pd

def get_stock_daily_eastmoney(symbol: str, start: str = "19900101", end: str = "20991231") -> pd.DataFrame:
    prefix = "1" if symbol.startswith("6") else "0"   # 1.xxxxxx=沪 / 0.xxxxxx=深
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={prefix}.{symbol}"
        f"&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt=101"   # 101=日 / 102=周 / 103=月
        f"&fqt=1"     # 0=不复权 / 1=前复权 / 2=后复权
        f"&beg={start}&end={end}"
    )
    data = requests.get(url, timeout=15).json()
    klines = (data.get("data") or {}).get("klines") or []
    if not klines:
        return pd.DataFrame()
    df = pd.DataFrame([ln.split(",") for ln in klines], columns=[
        "date","open","close","high","low","volume","amount",
        "amplitude","pct_change","change","turnover",
    ])
    for c in ["open","close","high","low","volume","amount","pct_change"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    return df
```

**指数日线**: 同一个 endpoint,`secid` 变成 `1.000300`(沪深300)/ `0.399001`(深证成指)等。

### 2.2 财务报表 (financials)

三大报表 (income / balance / cashflow):
```python
_REPORT = {
    "income":   "RPT_LICO_FN_CPD",         # 利润表
    "balance":  "RPT_DMSK_FN_BALANCE",     # 资产负债表
    "cashflow": "RPT_DMSK_FN_CASHFLOW",    # 现金流量表
}

def get_financials_eastmoney(symbol: str, kind: str = "income") -> pd.DataFrame:
    url = (
        f"https://datacenter-web.eastmoney.com/api/data/v1/get"
        f"?reportName={_REPORT[kind]}"
        f"&columns=ALL"
        f"&filter=(SECURITY_CODE=\"{symbol}\")"
        f"&pageNumber=1&pageSize=10"
        f"&sortColumns=REPORT_DATE&sortTypes=-1"
    )
    payload = requests.get(url, timeout=15).json() or {}
    rows = (payload.get("result") or {}).get("data") or []
    return pd.DataFrame(rows)
```

### 2.3 接口特点

- **无需 token**: 东财网站前端公开调用
- **复权**: `fqt=1` 前复权 / `fqt=2` 后复权 / `fqt=0` 不复权
- **频率**: 无明确限制,建议 0.3–0.5s 间隔避免被临时封
- **范围**: 日线可拉到 1990 年,财报可拉到上市以来
- **请求头**: 需要带一个正常浏览器 UA 和 `Referer: https://quote.eastmoney.com/`

---

## 3. 巨潮 (cninfo) API

- **公告查询 API**: `POST http://www.cninfo.com.cn/new/hisAnnouncement/query`
- **是否官方**: **是**。巨潮网站自己的前端就走这个接口。

**请求示例**:
```python
r = requests.post(
    "http://www.cninfo.com.cn/new/hisAnnouncement/query",
    data={
        "stock": "600519,9900023863",       # code,orgId
        "tabName": "fulltext",
        "pageSize": 30,
        "pageNum": 1,
        "column": "sse",                     # sse / szse / bj
        "category": "category_ndbg_szsh;",   # 年报
        "seDate": "2023-01-01~2025-01-01",
        "isHLtitle": "true",
    },
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=15,
)
# r.json()["announcements"] -> [{secName, announcementTitle, adjunctUrl, announcementTime, ...}]
```

- **orgId 映射**: 巨潮内部 ID,通过 `http://www.cninfo.com.cn/new/data/szse_stock.json` **一次性下载全表,本地缓存**(provider 已实现,存到 `data/cache/cninfo_stock_catalogue.json`)。
- **PDF 直链**: `http://static.cninfo.com.cn/` + `adjunctUrl`,可直接下载做 PDF 抽取。
- **category 常用值**:
  - `category_ndbg_szsh` 年报
  - `category_bndbg_szsh` 半年报
  - `category_yjdbg_szsh` 一季报
  - `category_sjdbg_szsh` 三季报
  - `category_dshgg_szsh` 董事会公告

---

## 4. 落地组合

```
market      → 东方财富 API (push2his.eastmoney.com)
financials  → 东方财富 API (datacenter-web.eastmoney.com)
filings     → cninfo hisAnnouncement API
web         → Tavily (保留)
```

- `.env` 增量: **无**(东财和巨潮都不需要 token)
- `requirements.txt`: 仅需 `requests`、`pandas`、`tabulate`(已在依赖里)

---

## 5. Provider 迁移清单 (已完成 ✅)

Capability 接口不变,已切换到直连官方 JSON 的 provider:

- [x] `providers/market_eastmoney.py` — 实现 `MarketDataCapability` (调 push2his.eastmoney.com)
- [x] `providers/financials_eastmoney.py` — 实现 `FinancialsCapability` (调 datacenter-web.eastmoney.com)
- [x] `providers/filings_cninfo_api.py` — `requests` 直连巨潮 `hisAnnouncement` API,`orgId` 一次性缓存到 `data/cache/cninfo_stock_catalogue.json`
- [x] `registry.py` — 默认绑定改为上述三个 provider
- [x] `requirements.txt` — 移除 `akshare`,新增 `tabulate`(`DataFrame.to_markdown()` 需要)
- [x] `scripts/bootstrap_indices.py` — 改用 `EastmoneyMarketProvider`
- [x] `DESIGN.md` §4 数据接入分层 — 同步更新

旧的 `providers/market_akshare.py` / `financials_akshare.py` / `filings_cninfo.py` 三个文件已删除,避免"表面切换但代码里还导入 akshare"的错觉。原 capability 接口和 Evidence 契约完全不变,agent 代码零改动。

---

*文档版本: 2026-07-12。若接口变动请参考东财/巨潮网站前端 Network 抓包。*
