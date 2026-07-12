# Finance Personal Agent — A股

一个聚焦 **A 股** 的个人金融交易 Agent。回答问题时:
- 优先使用**结构化数据源** (东财官方 JSON: 指数/行情/财务报表 + cninfo 巨潮官方 JSON: 公告年报, 均**无 token / 零爬虫中间层**)
- 需要时再走 **Tavily 搜索 + Trafilatura 抽正文 + BM25 粗筛 + LLM rerank**
- 使用 **两个模型协同**:
  - `doubao-seed-evolving` (火山方舟 Ark) — 规划、rerank、事实校验、偏好抽取
  - `deepseek` — 最终答案合成 (强制引用 `[S#]`)
- **完整 provenance**: 每条证据都落 SQLite,可以从答案里的 `[S3]` 反查到 URL + 快照文件 + 抓取时间
- **长期用户偏好**: 用户强调过的关注点(如 liquidity_risk / debt_maturity / cash_flow) 会持久化并影响后续 planning 与 answer 结构

设计详解 → [`docs/design.md`](./docs/design.md)

---

## 快速开始 (5 分钟)

### 1. 环境

```bash
git clone <this-repo> finance-agent
cd finance-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置密钥

```bash
cp .env.example .env
# 编辑 .env,选择一种 LLM 后端:
```

**必填 API key:**

| 后端 | 环境变量 | 说明 |
|------|---------|------|
| **Doubao (火山方舟)** | `ARK_API_KEY` | doubao-seed-evolving,负责 planner/verifier/memory |
| **DeepSeek** | `DEEPSEEK_API_KEY` | deepseek-chat,负责 synthesizer |
| **Tavily** | `TAVILY_API_KEY` | web 搜索 |

### 3. 初始化 + 拉 20 年 A 股指数

```bash
python -m finance_agent init
python -m finance_agent bootstrap-indices
# ↑ 拉上证/深证/沪深300/中证500/创业板/上证50/中证1000 的日线到 data/indices/*.parquet
```

### 4. 提问

```bash
python -m finance_agent ask "贵州茅台(600519)的主要风险因素有哪些?"
```

答案会在终端渲染,并同时写到 `outputs/`:
- `<ts>-ans<id>.md` — Markdown
- `<ts>-ans<id>.html` — 浏览器直接打开
- `<ts>-ans<id>.sources.json` — 完整 provenance(每条 `[S#]` 对应的 URL / title / 本地快照)

更多 demo → [`demos/README.md`](./demos/README.md)

---

## 架构一览

```
question ─► [doubao] Planner ─► {market_cn, financials, filings, web} 工具
                                     │
                                     ▼
                      Evidence Pool  (每条落 SQLite → [S1..Sn])
                                     │
                                     ▼
                      [deepseek] Synthesizer  ── 强制 [S#] 引用
                                     │
                                     ▼
                      [doubao] Verifier ── 校验引用 / 反事实 (最多 1 次 repair)
                                     │
                                     ▼
                      [doubao] Memory Extractor ── 更新 user_prefs
                                     │
                                     ▼
                      Render: Markdown / HTML / sources.json
```

## 目录

```
finance_agent/
├── cli.py                # 入口
├── config.py             # 配置加载
├── registry.py           # Provider 注册 (切换 LLM 后端)
├── capabilities/         # 抽象接口层 (Agent 只依赖这层)
│   ├── llm.py           # LLMCapability
│   ├── market_data.py   # MarketDataCapability
│   └── ...
├── providers/            # 具体实现层 (可替换)
│   ├── llm_openai.py    # DoubaoProvider, DeepSeekProvider
│   └──  # market_eastmoney, financials_eastmoney, filings_cninfo_api, web_tavily, storage_sqlite
├── agent/                # planner / synthesizer / verifier / memory / loop
├── retrieval/            # bm25 + llm rerank
├── storage/              # SQLite provenance
└── render/               # md + html + sources.json 输出
```

## CLI 参考

### `ask` — 提问

```bash
python -m finance_agent ask "..."          # 问一个问题
python -m finance_agent ask "..." --quiet  # 不打印 plan 表格
```

**作用**: 运行完整的 Agent 循环: Planner → 工具调用 → Synthesizer → Verifier → Memory Extractor。
**输出**: 终端渲染答案 + `outputs/` 目录下的 `.md` / `.html` / `.sources.json` 文件。

### `init` — 初始化

```bash
python -m finance_agent init
```

**作用**: 创建 SQLite 数据库和 `data/` 目录结构。首次运行前必须执行。

### `bootstrap-indices` — 拉取指数数据

```bash
python -m finance_agent bootstrap-indices
```

**作用**: 预下载主要 A 股指数(上证/深证/沪深300/中证500/创业板/上证50/中证1000) 近 20 年日线数据到 `data/indices/*.parquet`。

### `prefs` — 查看用户偏好

```bash
python -m finance_agent prefs
```

**作用**: 展示 Agent 从过往对话中学习到的用户偏好(如关注的财务指标、风险维度等)。

### `clear-prefs` — 清空用户偏好

```bash
python -m finance_agent clear-prefs
```

**作用**: 删除所有已存储的用户偏好,让 Agent 重新学习。

## 文档接入和加载说明

本项目支持**多市场** (A 股 / 美股) 和**多数据源** (官方 API / Web 搜索)。

### 数据源接入方式

| 类型 | 数据源 | 接入方式 | 说明 |
|------|--------|---------|------|
| **A 股行情** | 东方财富 | 官方 JSON API | 无 token,零爬虫中间层 |
| **A 股财务** | 东方财富 | 官方 JSON API | 利润表/资产负债表/现金流量表 |
| **A 股公告** | cninfo 巨潮 | 官方 JSON API | 公告标题+URL,PDF 直链 |
| **美股行情** | Finnhub | REST API | 需 `FINNHUB_API_KEY` |
| **美股财务** | Finnhub | REST API | 需 `FINNHUB_API_KEY` |
| **Web 搜索** | Tavily | REST API | 需 `TAVILY_API_KEY` |

### 数据源加载流程

```
用户提问
    │
    ▼
[Planner] 分析意图 → 选择工具
    │
    ├──► market_cn.index / market_us.index → 东财/Finnhub API → 指数/个股数据
    ├──► financials / financials_us → 东财/Finnhub API → 财务报表
    ├──► filings / filings_us → cninfo/Finnhub API → 公告年报
    └──► web → Tavily 搜索 → Trafilatura 抽正文 → BM25 粗筛 → LLM rerank
    │
    ▼
[Evidence Pool] 所有证据写入 SQLite,分配 [S1]..[Sn] 编号
    │
    ▼
[Synthesizer] DeepSeek 合成答案,强制引用 [S#]
```

### 证据溯源 (Provenance)

每条证据在 SQLite 中记录:
- `chunk_id`: 唯一标识
- `source`: 来源类型 (market/financials/filings/web)
- `url`: 原始 URL
- `title`: 标题
- `timestamp`: 抓取时间
- `local_snapshot`: 本地快照文件路径

答案中的 `[S3]` 可直接反查到对应的完整元数据。

### 切换市场

通过环境变量切换 A 股/美股:

```bash
export FA_MARKET=cn   # 默认,A 股
export FA_MARKET=us   # 美股
```

或修改 `.env` 文件中的 `FA_MARKET`。

## 已知限制 & 后续改进

见 [`doc/design.md`](./doc/design.md) 最后一节。要点:
- filings 目前只用 cninfo 的标题+URL (`adjunctUrl` PDF 直链已拿到, 下一步才抽风险因子章节)
- Verifier 只查引用一致性,不判证据真伪
- 东财 / cninfo JSON 字段偶变 → provider 降级为空 DataFrame, agent 会自动切 web fallback
- 未做 embedding 向量检索,BM25+LLM rerank 对 demo 规模够用
