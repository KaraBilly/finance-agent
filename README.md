# Finance Personal Agent — 美股

一个聚焦 **美股** 的个人金融交易 Agent, 支持**多轮对话**。回答问题时:
- 优先使用 **Finnhub 官方 API** 获取行情、财务报表和 SEC 公告, 均**无爬虫中间层**
- 需要时再走 **Tavily 搜索 + Trafilatura 抽正文 + BM25 粗筛 + LLM rerank**
- 使用 **两个模型协同**:
  - `doubao-seed-evolving` (火山方舟 Ark) — 规划、rerank、事实校验、偏好抽取
  - `deepseek` — 最终答案合成 (强制引用 `[S#]`)
- **完整 provenance**: 每条证据都落 SQLite,可以从答案里的 `[S3]` 反查到 URL + 快照文件 + 抓取时间
- **长期用户偏好**: 用户强调过的关注点(如 liquidity_risk / debt_maturity / cash_flow) 会持久化并影响后续 planning 与 answer 结构
- **多轮对话**: 支持上下文感知的连续对话,自动维护对话历史

设计详解 → [`docs/design.md`](./docs/design.md)

---

## 快速开始 (5 分钟)

### 1. 环境

**要求 Python >= 3.10** (PydanticAI 需要)

```bash
git clone <this-repo> finance-agent
cd finance-agent
python3.10 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 2. 配置密钥

```bash
cp .env.example .env
# 编辑 .env,填入 API keys:
```

**必填 API key:**

| 后端 | 环境变量 | 说明 |
|------|---------|------|
| **Doubao (火山方舟)** | `ARK_API_KEY` | doubao-seed-evolving,负责 planner/verifier/memory |
| **DeepSeek** | `DEEPSEEK_API_KEY` | deepseek-chat,负责 synthesizer |
| **Tavily** | `TAVILY_API_KEY` | web 搜索 |
| **Finnhub** | `FINNHUB_API_KEY` | 美股行情/财务/公告 |

### 3. 初始化

```bash
python -m finance_agent init
```

### 4. 提问 (单轮)

```bash
python -m finance_agent ask "Apple(AAPL) 的主要风险因素有哪些?"
```

### 5. 多轮对话

```bash
# 启动交互式对话
python -m finance_agent chat

# 继续已有对话
python -m finance_agent chat --conversation-id <id>
```

在 `chat` 模式中:
- 输入 `new` 开始新对话
- 输入 `exit` 或 `quit` 退出
- 对话历史自动持久化到 SQLite

答案会在终端渲染,并同时写到 `outputs/`:
- `<ts>-ans<id>.md` — Markdown
- `<ts>-ans<id>.html` — 浏览器直接打开
- `<ts>-ans<id>.sources.json` — 完整 provenance(每条 `[S#]` 对应的 URL / title / 本地快照)

更多 demo → [`demos/README.md`](./demos/README.md)

---

## 架构一览

```
question ─► [doubao] Planner ─► {market_us, financials_us, filings_us, web} 工具
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
                      Multi-turn Conversation ── 对话历史持久化
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
│   └── us/              # 美股 Provider (Finnhub)
│       ├── market_finnhub.py
│       ├── financials_finnhub.py
│       └── filings_finnhub.py
├── agent/                # planner / synthesizer / verifier / memory / loop / conversation
│   ├── conversation.py           # 对话数据模型
│   ├── conversation_manager.py   # 对话管理器 (PydanticAI 风格)
│   └── pydantic_agent.py         # PydanticAI 原生 Agent 实现
├── retrieval/            # bm25 + llm rerank
├── storage/              # SQLite provenance
└── render/               # md + html + sources.json 输出
```

## CLI 参考

### `chat` — 多轮对话

```bash
python -m finance_agent chat                    # 启动交互式对话
python -m finance_agent chat --conversation-id   # 继续已有对话
```

**作用**: 启动交互式多轮对话模式,自动维护对话上下文。支持:
- 连续追问 (如"上面的数据来源是什么?")
- 对话历史自动持久化到 SQLite
- 随时输入 `new` 开始新对话
- 输入 `exit` 或 `quit` 退出

**示例**:
```
You: AAPL 的股价是多少?
Agent: AAPL 当前股价为 $150.23... [S1]

You: 那它的市盈率呢?
Agent: 基于刚才的数据,AAPL 的市盈率为 28.5x... [S2]
(Agent 自动理解"刚才的数据"指代前一轮的 AAPL)
```

### `ask` — 单轮提问

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

本项目支持**多市场** (美股 / A 股) 和**多数据源** (官方 API / Web 搜索)。

### 数据源接入方式

| 类型 | 数据源 | 接入方式 | 说明 |
|------|--------|---------|------|
| **美股行情** | Finnhub | REST API | 需 `FINNHUB_API_KEY`,免费 tier 60 次/分钟 |
| **美股财务** | Finnhub | REST API | 利润表/资产负债表/现金流量表 (financials-reported) |
| **美股公告** | Finnhub | REST API | SEC filings (10-K, 10-Q, 8-K 等) |
| **Web 搜索** | Tavily | REST API | 需 `TAVILY_API_KEY` |

### 数据源加载流程

```
用户提问
    │
    ▼
[Planner] 分析意图 → 选择工具
    │
    ├──► market_us → Finnhub API → 指数/个股行情数据
    ├──► financials_us → Finnhub API → 财务报表 (income/balance/cashflow)
    ├──► filings_us → Finnhub API → SEC filings (10-K/10-Q/8-K)
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

通过环境变量切换美股/A 股:

```bash
export FA_MARKET=us   # 默认,美股
export FA_MARKET=cn   # A 股 (需东财/cninfo API)
```

或修改 `.env` 文件中的 `FA_MARKET`。

## 已知限制 & 后续改进

见 [`docs/design.md`](./docs/design.md) 最后一节。要点:
- Finnhub free tier 限制 60 次/分钟,高频使用需考虑缓存
- filings 目前只获取 SEC 公告标题+URL,未抽取 PDF 正文中的风险因子章节
- Verifier 只查引用一致性,不判证据真伪
- 多轮对话已实现 PydanticAI 风格依赖注入,但尚未使用 PydanticAI 的 `Agent` 类和 `RunContext` 获得自动重试、流式输出等高级功能
- 未做 embedding 向量检索,BM25+LLM rerank 对 demo 规模够用
