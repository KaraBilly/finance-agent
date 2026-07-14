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

设计详解 → [`docs/design.md`](./docs/design.md) · 可执行 demo → [`demos/README.md`](./demos/README.md)

---

## 快速开始

下面两条 demo 路径彼此独立，任选其一即可跑通。**美股路径最短**（只要 API key）；**A 股路径**多两步（下载数据 + 灌 Milvus），全部由 [`setup_all.sh`](./setup_all.sh) 完成。

### 0. 前置

- Python **>= 3.10**
- Docker Desktop（仅 A 股路径需要，用来跑 Milvus + etcd + MinIO）
- API keys — 见下表

### 1. 安装

```bash
git clone <this-repo> finance-agent
cd finance-agent
python3.10 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env             # 然后编辑 .env 填入 keys
python -m finance_agent init     # 建 SQLite provenance 库
```

**API key 说明**（`.env`）：

| Key | 何时必填 | 说明 |
|-----|---------|------|
| `ARK_API_KEY`      | 两条路径都必填 | 火山方舟 doubao-seed-evolving — planner / verifier / memory |
| `DEEPSEEK_API_KEY` | 两条路径都必填 | deepseek-chat — synthesizer |
| `TAVILY_API_KEY`   | 两条路径都必填 | Web 搜索 |
| `FINNHUB_API_KEY`  | **仅美股** 必填 | 免费版 60 次/分钟 |

> 市场（美股 / A 股）**按问题自动推断**（见 `agent/loop.py::_infer_market`）——问题里出现 `AAPL`/`MSFT` 等美股 ticker 或英文 → 走 US；出现 `002594`/`比亚迪` 等 A 股代码或中文公司名 → 走 CN。**不需要设 `FA_MARKET` 环境变量**（代码里不读它）。

---

### Demo 路径 A · 美股（推荐先跑这条）

只依赖 Finnhub API，**无需 Docker，无需 Milvus，无需下载**。

```bash
# 单轮
python -m finance_agent ask "苹果公司(AAPL)的基本面情况如何?请给出当前股价、市值和主要财务指标。"

# 多轮对话
python -m finance_agent chat        # `new` 开始新对话，`exit` 退出
```

更多美股 demo 问题 → [`demos/README.md`](./demos/README.md)。

---

### Demo 路径 B · A 股（需要 Milvus + 本地数据）

A 股没有 API，全部靠本地文件（K 线 CSV + 财报 PDF/HTML）+ Milvus 向量检索。一条命令完成下载 + 启 Milvus + 灌入：

```bash
./setup_all.sh                 # 首次全流程；已有旧数据会交互提示 recreate / append / skip
./setup_all.sh --yes           # 非交互 (CI)，自动 recreate
./setup_all.sh --skip-download # 数据已在磁盘上，只重灌 Milvus
```

脚本会依次做：

1. 拉取比亚迪 / 宁德时代 / 中际旭创 20 年日线 + 周线 → `data/market/stocks/`
2. 拉取比亚迪 / 寒武纪 / 中际旭创 / 宁德时代 近 10 年财报 → `data/financials/downloads/`
3. `docker compose up -d`（etcd + MinIO + Milvus），轮询 `/healthz` 直到就绪
4. `scripts/import_to_milvus.py --recreate` — 分块 + 向量化 + 写入 collection `finance_docs`

**验证 Milvus 就绪**：

```bash
docker ps | grep milvus                              # 3 个容器 running
curl -fsS http://localhost:9091/healthz && echo OK   # 应返回 OK
```

**跑 demo 问题**：

```bash
python -m finance_agent ask "宁德时代(300750)最近两年的营收和净利润变化情况?"
python -m finance_agent ask "比亚迪(002594)自己如何描述其面临的竞争?"
```

更多 A 股 demo → [`demos/README.md`](./demos/README.md)。

完事后停 Milvus：`./stop_milvus.sh`（数据保留在 `volumes/`）。

---

### 2. 输出与验证

每次 `ask` / `chat` 都会在 `outputs/` 生成三个同名文件：

| 文件 | 用途 |
|---|---|
| `<ts>-ans<id>.md`            | 最终 Markdown 答案（含 `[S#]` 引用） |
| `<ts>-ans<id>.html`          | 同一份答案的浏览器渲染版 |
| `<ts>-ans<id>.sources.json`  | 完整 provenance：每条 `[S#]` 对应的 URL / 文件 / 原文片段 / trace |

打开 `outputs/<最新>-ans1.html` 即可肉眼验证 demo 是否成功；若 `sources.json` 为空，说明 planner 没抽出证据 —— 先检查 API key 与（A 股场景下）Milvus 是否有数据。

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

## 市场路由

市场是**按问题自动推断**的，无需环境变量：

- 问题里出现美股 ticker（`AAPL` / `MSFT` / `NVDA`…）或纯英文 → 走 **US** provider（Finnhub API）
- 问题里出现 A 股代码（`002594` / `300750`…）或中文公司名 → 走 **CN** provider（本地文件 + Milvus）
- 都推不出来时回退到 `DEFAULT_MARKET = "us"`（见 [`registry.py`](./finance_agent/registry.py)）

**A 股数据源**：`data/market/stocks/*.csv` + `data/financials/downloads/**/*.{pdf,html}`；由 `setup_all.sh` 生成并灌入 Milvus。

**美股数据源**：Finnhub API — 实时报价、财务指标、财报、SEC 文件、新闻、分析师推荐。

---

## 常见问题

**Q: `ask` 报 `sources.json` 为空 / 答案里没有 `[S#]`？**  
A: 多半是证据池为空。美股场景检查 `FINNHUB_API_KEY`；A 股场景先跑 `./setup_all.sh --skip-download` 确认 Milvus 里 `finance_docs` collection 有行数（脚本会打印当前 `num_entities`）。

**Q: Milvus 已经有旧数据，再跑 `setup_all.sh` 会怎样？**  
A: 脚本会先探测 collection 行数，然后提示 `r/a/s/q`：`r`ecreate（丢弃重建，推荐）/ `a`ppend（追加，⚠️ 会产生重复）/ `s`kip / `q`uit。非交互场景加 `--yes` 默认 recreate。

**Q: 只想跑美股 demo，需要装 Docker/Milvus 吗？**  
A: 不需要。美股完全走 Finnhub API，跳过整个"路径 B"即可。

## 已知限制

- Finnhub free tier 限制 60 次/分钟
- A 股依赖本地数据，首次需运行 `./setup_all.sh`（约 5–15 分钟）
- Verifier 只查引用一致性，不判证据真伪
- 每次问答约 5–8 次 LLM 调用

更多 → [`docs/design.md`](./docs/design.md)
