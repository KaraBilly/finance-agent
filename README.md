# Finance Agent — 美股/A股

一个支持**美股**和**A股**的个人金融交易 Agent，支持**多轮对话**。

- **美股**：Finnhub 官方 API（行情/财务/SEC 公告），无爬虫中间层
- **A股**：外挂本地数据（本地文件），无 API 调用
- **Web 搜索**：Tavily + Trafilatura 抽正文 + BM25 粗筛 + LLM rerank
- **双模型协同**：
  - `doubao-seed-evolving`（火山方舟）— 规划、rerank、事实校验、偏好抽取
  - `deepseek` — 最终答案合成（强制引用 `[S#]`）
- **完整 provenance**：每条证据落 SQLite，可反查 URL + 快照
- **长期用户偏好**：用户关注点持久化，影响后续 planning
- **多轮对话**：上下文感知，自动维护对话历史

设计详解 → [`docs/design.md`](./docs/design.md)

---

## 快速开始

### 1. 环境

**要求 Python >= 3.10**

```bash
git clone <this-repo> finance-agent
cd finance-agent
python3.10 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 2. 配置密钥

```bash
cp .env.example .env
# 编辑 .env，填入 API keys
```

**必填 API key：**

| 后端 | 环境变量 | 说明 |
|------|---------|------|
| **Doubao** | `ARK_API_KEY` | doubao-seed-evolving，负责 planner/verifier/memory |
| **DeepSeek** | `DEEPSEEK_API_KEY` | deepseek-chat，负责 synthesizer |
| **Tavily** | `TAVILY_API_KEY` | web 搜索 |
| **Finnhub** | `FINNHUB_API_KEY` | 美股行情/财务/公告（免费版 60 次/分钟） |

### 3. 初始化

```bash
python -m finance_agent init
```

### 4. 提问

```bash
# 单轮
python -m finance_agent ask "Apple(AAPL) 的主要风险因素有哪些?"

# 多轮对话
python -m finance_agent chat
# 输入 `new` 开始新对话，`exit` 退出
```

答案输出到 `outputs/`：
- `<ts>-ans<id>.md` — Markdown
- `<ts>-ans<id>.html` — 浏览器打开
- `<ts>-ans<id>.sources.json` — 完整 provenance

---

## 架构一览

```
question ─► [doubao] Planner ─► {market, financials, filings, web} 工具
                                   │
                                   ▼
                    Evidence Pool (SQLite → [S1..Sn])
                                   │
                                   ▼
                    [deepseek] Synthesizer ── 强制 [S#] 引用
                                   │
                                   ▼
                    [doubao] Verifier ── 校验引用 / 反事实
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

---

## 目录

```
finance_agent/
├── cli.py                    # 入口
├── config.py                 # 配置加载
├── registry.py               # Provider 注册（市场切换 cn/us）
├── capabilities/             # 抽象接口层
│   ├── llm.py
│   ├── market_data.py
│   ├── financials.py
│   ├── filings.py
│   └── web_search.py
├── providers/                # 具体实现层
│   ├── cn/                   # A股 Provider（外挂数据）
│   │   ├── market_external.py
│   │   ├── financials_external.py
│   │   └── filings_external.py
│   ├── us/                   # 美股 Provider（Finnhub API）
│   │   ├── market_finnhub.py
│   │   ├── financials_finnhub.py
│   │   └── filings_finnhub.py
│   ├── llm_openai.py         # Doubao + DeepSeek
│   ├── web_tavily.py         # Tavily 搜索
│   └── storage_sqlite.py     # SQLite 存储
├── agent/                    # planner / synthesizer / verifier / memory / loop
│   ├── conversation.py
│   ├── conversation_manager.py
│   └── pydantic_agent.py
├── retrieval/                # bm25 + embedding + llm rerank
│   ├── external_data_store.py
│   └── unified_retriever.py
├── storage/                  # SQLite provenance
└── render/                   # md + html + sources.json
```

---

## CLI 参考

### `chat` — 多轮对话

```bash
python -m finance_agent chat                    # 启动交互式对话
python -m finance_agent chat --conversation-id  # 继续已有对话
```

**示例：**
```
You: AAPL 的股价是多少?
Agent: AAPL 当前股价为 $150.23... [S1]

You: 那它的市盈率呢?
Agent: 基于刚才的数据,AAPL 的市盈率为 28.5x... [S2]
```

### `ask` — 单轮提问

```bash
python -m finance_agent ask "..."          # 问一个问题
python -m finance_agent ask "..." --quiet  # 不打印 plan 表格
```

### `init` — 初始化

```bash
python -m finance_agent init
```

### `prefs` / `clear-prefs` — 用户偏好

```bash
python -m finance_agent prefs        # 查看偏好
python -m finance_agent clear-prefs  # 清空偏好
```

---

## 市场切换

通过环境变量切换市场：

```bash
export FA_MARKET=us   # 默认，美股（Finnhub API）
export FA_MARKET=cn   # A股（外挂本地数据）
```

或在 `.env` 中设置 `FA_MARKET`。

**A股数据源：**
- 外挂本地文件（`data/market/`, `data/financials/`, `data/filings/`）
- 无 API 调用，纯本地数据

**美股数据源：**
- Finnhub API（免费版 60 次/分钟）
- 实时报价、财务指标、完整财报、SEC 文件、新闻、分析师推荐

---

## 已知限制

- Finnhub free tier 限制 60 次/分钟
- A股依赖外挂数据，需提前准备数据文件
- Verifier 只查引用一致性，不判证据真伪
- 每次问答约 5-8 次 LLM 调用

更多 → [`docs/design.md`](./docs/design.md)
