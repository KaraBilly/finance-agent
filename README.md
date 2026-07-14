# Finance Agent — 美股 / A 股

一个支持**美股**和**A 股**的个人金融分析 Agent，支持**多轮对话**、**完整证据链**、**长期用户偏好**。

- **美股**：Finnhub 官方 API（行情 / 财务 / SEC 公告）
- **A 股**：本地文件（K 线 CSV + 财报 PDF/HTML）+ Milvus 向量检索
- **Web 搜索**：Tavily + Trafilatura 抽正文 + BM25 粗筛 + LLM rerank
- **双模型协同**：
  - `doubao-seed-evolving`（火山方舟）— planner / rerank / verifier / memory
  - `deepseek-chat` — synthesizer（强制 `[S#]` 引用）
- **结构化 Agent 框架**：`pydantic-ai` `Agent` + `BaseModel` 输出 schema 驱动 planner / verifier / memory，自动 schema 校验 + 重试
- **Provenance**：每条证据落 SQLite，可反查 URL / 文件 / 原文片段

设计详解 → [docs/design.md](docs/design.md) · 可执行 demo → [demos/README.md](demos/README.md)

---

## 快速开始（TL;DR）

**只想跑美股 demo**（最短路径，无需 Docker）：

```bash
git clone <this-repo> finance-agent && cd finance-agent
python3.10 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env      # 编辑 .env 填入 4 个 API key（见下表）
python -m finance_agent init
python -m finance_agent ask "苹果公司(AAPL)的基本面情况如何?"
python -m finance_agent chat
```

**要跑 A 股 demo**：在上面基础上再执行 `./setup_all.sh`（需要 Docker Desktop 已运行）。

下面是**详细步骤**，从零到能跑通 demo，每一步都可复制粘贴。

---

## 0 · 前置条件

| 项目 | 要求 | 备注 |
|---|---|---|
| 操作系统 | macOS / Linux | Windows 建议用 WSL2 |
| Python | **3.10 – 3.13** | `python3 --version` 验证 |
| Docker Desktop | 4.x+，**只有 A 股路径需要** | 需保证 Docker daemon 在跑 |
| 磁盘空间 | ≥ 5 GB | A 股财报 PDF ~2 GB + Milvus volumes ~1 GB |
| 网络 | 可访问 Finnhub / Tavily / 火山方舟 / DeepSeek | 大陆网络访问 Finnhub / Tavily 可能需科学上网 |

**验证 Python 版本**：
```bash
python3 --version   # 期望 Python 3.10.x 或更高
```

如缺 Python 3.10+，macOS 可用 `brew install python@3.10`，Ubuntu 可用 `sudo apt install python3.10 python3.10-venv`。

---

## 1 · 克隆代码 & 创建虚拟环境

```bash
git clone <this-repo> finance-agent
cd finance-agent

# 强烈建议用 3.10 精确匹配（faiss-cpu / sentence-transformers 在更新 Python 上偶有轮子缺失）
python3.10 -m venv .venv
source .venv/bin/activate

# 升级 pip 后再装依赖，避免老 pip 解不出 pydantic-ai
python -m pip install --upgrade pip setuptools wheel
pip install -e .
```

安装约需 3–5 分钟（`sentence-transformers` / `torch` 下载较慢）。安装成功后，`finance-agent` 命令与 `python -m finance_agent` 二者等价。

**Apple Silicon 用户**：如遇 `faiss-cpu` 或 `torch` 装不上，请确认 Python 是 arm64 的（`python -c "import platform; print(platform.machine())"` 应输出 `arm64`），Rosetta 下的 x86 Python 会失败。

---

## 2 · 配置 API Key

复制模板：
```bash
cp .env.example .env
```

编辑 `.env` 填入以下 4 个 key。**其中 3 个是两条路径都必填，`FINNHUB_API_KEY` 只有跑美股才需要**：

| 变量 | 是否必填 | 从哪申请 | 说明 |
|---|---|---|---|
| `ARK_API_KEY` | ✅ 必填 | <https://console.volcengine.com/ark> | 火山方舟；planner / verifier / memory 都用它。新账号有免费额度 |
| `DEEPSEEK_API_KEY` | ✅ 必填 | <https://platform.deepseek.com> | 答案 synthesizer；充值 5 元就够跑几十个 demo |
| `TAVILY_API_KEY` | ✅ 必填 | <https://tavily.com> | Web 搜索；免费版 1000 次/月 |
| `FINNHUB_API_KEY` | 美股才需要 | <https://finnhub.io/register> | 免费版 60 次/分钟；A 股路径可留空 |

其它变量（`FA_*`）均有合理默认值，通常不用改。

**验证 key 已加载**：
```bash
python -c "from finance_agent.config import CONFIG; print('ark:', bool(CONFIG.ark_api_key), 'deepseek:', bool(CONFIG.deepseek_api_key), 'tavily:', bool(CONFIG.tavily_api_key), 'finnhub:', bool(CONFIG.finnhub_api_key))"
```
每一项都应为 `True`（若走 A 股路径 `finnhub` 允许 `False`）。

---

## 3 · 初始化 SQLite provenance 库

```bash
python -m finance_agent init
```

会在 `./data/finance_agent.db` 建 provenance 表 + 用户偏好表。**这一步两条路径都要跑**。

---

## 4 · 路径 A · 美股（最快）

只依赖 Finnhub API，**无需 Docker，无需 Milvus，无需下载**。直接跑：

```bash
# 单轮
python -m finance_agent ask "苹果公司(AAPL)的基本面情况如何?请给出当前股价、市值和主要财务指标。"

# 多轮对话（回车 `new` 开新对话，`exit` 退出）
python -m finance_agent chat
```

**首次运行**会下载 embedding / rerank 模型（`sentence-transformers/*`，约 500 MB → `~/.cache/huggingface/`），耐心等待即可。

更多美股 demo 问题 → [demos/README.md](demos/README.md)。

---

## 5 · 路径 B · A 股（需要 Docker + Milvus）

A 股没有官方 API，全部依赖本地文件（K 线 CSV + 财报 PDF/HTML）经 Milvus 向量化后检索。一条命令搞定：

### 5.1 确认 Docker 在运行
```bash
docker info >/dev/null && echo "docker OK"   # 应输出 docker OK
```
若失败，请启动 Docker Desktop 后再继续。

### 5.2 一键 setup

```bash
./setup_all.sh                 # 首次全流程；若 Milvus 已有旧数据会交互提示 r/a/s/q
./setup_all.sh --yes           # 非交互（CI），默认 recreate
./setup_all.sh --skip-download # 数据已在磁盘，只重灌 Milvus
./setup_all.sh --skip-milvus   # 只下载不灌库
```

脚本会依次执行：

1. 拉取**比亚迪 / 宁德时代 / 中际旭创** 20 年日线 + 周线 → `data/market/stocks/`
2. 拉取**比亚迪 / 寒武纪 / 中际旭创 / 宁德时代**近 10 年财报 → `data/financials/downloads/`
3. `docker compose -f docker-compose.milvus.yml up -d`（etcd + MinIO + Milvus）
4. 轮询 `http://localhost:9091/healthz` 直到就绪
5. `scripts/import_to_milvus.py --recreate` — 分块 + 向量化 + 写入 collection `finance_docs`

首次跑约 **5–15 分钟**（大头是财报下载 + embedding）。

### 5.3 验证 Milvus 就绪

```bash
docker ps | grep milvus                             # 期望看到 3 个容器 Up
curl -fsS http://localhost:9091/healthz && echo OK  # 期望输出 OK
```

collection 行数：
```bash
python -c "from pymilvus import connections, Collection; connections.connect(host='localhost', port='19530'); c=Collection('finance_docs'); c.flush(); print('rows:', c.num_entities)"
```
应看到几千到几万行；如为 `0` 说明导入失败，重跑 `./setup_all.sh --skip-download`。

### 5.4 跑 A 股 demo

```bash
python -m finance_agent ask "宁德时代(300750)最近两年的营收和净利润变化情况?"
python -m finance_agent ask "比亚迪(002594)自己如何描述其面临的竞争?"
```

### 5.5 停止 Milvus（数据保留在 `volumes/`）

```bash
./stop_milvus.sh
```

---

## 6 · 输出与验证

每次 `ask` / `chat` 都会在 `outputs/` 生成三个同名文件：

| 文件 | 用途 |
|---|---|
| `<ts>-ans<id>.md` | 最终 Markdown 答案（含 `[S#]` 引用） |
| `<ts>-ans<id>.html` | 浏览器渲染版，直接双击打开 |
| `<ts>-ans<id>.sources.json` | 完整 provenance：每条 `[S#]` 的 URL / 文件 / 原文片段 / trace |

**成功判据**：
- `<ts>-ans<id>.md` 中出现 `[S1]` / `[S2]` … 等引用标记
- `<ts>-ans<id>.sources.json` 中的 `sources` 数组非空
- HTML 打开无 500

若 `sources.json` 为空 → 证据池为空，见下面 [故障排查](#故障排查)。

---

## 架构一览

```
question ─► [doubao · pydantic-ai Agent[ToolPlan]] Planner
                                   │  → 验证后的 ToolPlan (BaseModel)
                                   ▼
              {market, financials, filings, web} 工具
                                   │
                                   ▼
                    Evidence Pool (SQLite → [S1..Sn])
                                   │
                                   ▼
                    [deepseek] Synthesizer ── 强制 [S#] 引用
                                   │
                                   ▼
              [doubao · pydantic-ai Agent[VerifyVerdict]] Verifier
                                   │  → 结构化的 passed + issues[]
                                   ▼
              [doubao · pydantic-ai Agent[PrefExtractionResult]] Memory
                                   │  → EMA 更新 user_prefs
                                   ▼
                    Multi-turn Conversation ── 对话历史持久化
                                   │
                                   ▼
                    Render: Markdown / HTML / sources.json
```

三个 `pydantic-ai` Agent 共享同一个底层 [pydantic_runtime.py](finance_agent/agent/pydantic_runtime.py)：把任意 `OpenAICompatibleLLM`（Doubao / DeepSeek）包成 `pydantic_ai.Agent[None, TOut]`，带自动 schema 校验 + 失败重试。下游拿到的已经是 `BaseModel` 实例而不是手拼 JSON。

市场（美股 / A 股）**按问题自动推断**（见 `agent/loop.py::_infer_market`）：出现 `AAPL`/`MSFT` 等 ticker 或英文 → US；出现 `002594`/`比亚迪` 等 A 股代码或中文公司名 → CN。**不需要设 `FA_MARKET`**。

---

## 目录结构

### 仓库根目录

```
finance-agent/
├── finance_agent/            # 核心包（见下）
├── scripts/                  # 一次性脚本（下载 / 灌库 / 引导指数）
├── tests/                    # pytest 测试
├── demos/                    # 可复制粘贴的 demo 问题
├── docs/                     # 设计文档
├── data/                     # 运行时数据（K 线 / 财报 / SQLite / 缓存）
├── outputs/                  # 每次 ask 生成的 md / html / sources.json
├── volumes/                  # Docker volumes（etcd / minio / milvus）
├── docker-compose.milvus.yml # Milvus + etcd + MinIO 编排
├── setup_all.sh              # 一键：下载 → 启 Milvus → 灌库
├── start_milvus.sh           # 仅启动 Milvus
├── stop_milvus.sh            # 停 Milvus（保留 volumes）
├── pyproject.toml            # 依赖 + 入口点
├── pytest.ini
├── .env.example              # 环境变量模板
└── README.md
```

### `finance_agent/` — 核心包

```
finance_agent/
├── __main__.py               # `python -m finance_agent` 入口
├── cli.py                    # click 命令：ask / chat / init / prefs / bootstrap-indices
├── config.py                 # 从 .env 加载 CONFIG（api key / 路径 / 开关）
├── registry.py               # Provider 注册；按 market={cn,us} 切换实现
├── download_models.py        # 预热 sentence-transformers 模型缓存
├── agent/                    # ★ Agent 主循环
├── capabilities/             # 抽象接口层（每个 provider 必须实现的协议）
├── providers/                # 具体实现层
├── retrieval/                # 检索层：bm25 / embedding / rerank / milvus
└── render/                   # 输出层：md → html + sources.json
```

### `finance_agent/agent/` — Agent 主循环

```
agent/
├── loop.py                   # AgentLoop：串起 plan → tools → synth → verify → memory
├── pydantic_runtime.py       # ★ 底层适配：OpenAICompatibleLLM → pydantic_ai.Agent
├── planner.py                # doubao · Agent[None, ToolPlan]     — 结构化工具调用计划
├── synthesizer.py            # deepseek：evidence → 带 [S#] 引用的 markdown
├── verifier.py               # doubao · Agent[None, VerifyVerdict]  — 引用 / 事实校验
├── memory.py                 # doubao · Agent[None, PrefExtractionResult] — 偏好抽取 + EMA 持久化
├── conversation.py           # 单次对话状态
└── conversation_manager.py   # 多轮对话历史持久化 + 上下文拼装
```

### `finance_agent/capabilities/` — 抽象接口层

```
capabilities/
├── base.py                   # Provider 通用基类
├── llm.py                    # ChatLLM 协议（doubao / deepseek 都实现它）
├── market_data.py            # MarketDataProvider（行情 / 报价）
├── financials.py             # FinancialsProvider（三大表）
├── filings.py                # FilingsProvider（公告 / 财报文本）
├── web_search.py             # WebSearchProvider（Tavily）
└── storage.py                # StorageProvider（provenance / prefs / 对话）
```

### `finance_agent/providers/` — 具体实现层

```
providers/
├── llm_openai.py             # Doubao + DeepSeek（OpenAI 兼容 API）
├── web_tavily.py             # Tavily + Trafilatura 抽正文
├── storage_sqlite.py         # SQLite 后端（provenance / prefs / conversations）
├── cn/                       # A 股实现
│   ├── market_eastmoney.py       # 东方财富 API（备用）
│   ├── market_external.py        # 本地 CSV（默认，setup_all.sh 下载）
│   ├── financials_eastmoney.py   # 东方财富财报（备用）
│   ├── financials_external.py    # 本地财报文件（默认）
│   ├── filings_cninfo_api.py     # 巨潮资讯 API（备用）
│   └── filings_external.py       # 本地财报 PDF / HTML（默认）
└── us/                       # 美股实现（全部走 Finnhub API）
    ├── market_finnhub.py
    ├── financials_finnhub.py
    └── filings_finnhub.py
```

### `finance_agent/retrieval/` — 检索层

```
retrieval/
├── bm25.py                   # 关键词粗筛（rank-bm25）
├── embedding_search.py       # 向量检索（sentence-transformers + faiss）
├── milvus_store.py           # Milvus 客户端封装
├── external_data_store.py    # 本地文件 → 向量库的桥
├── semantic_chunker.py       # PDF/HTML 语义分块
├── rerank.py                 # LLM rerank（doubao）
└── unified_retriever.py      # 编排：bm25 → embed → rerank
```

### `finance_agent/render/` — 输出层

```
render/
└── writer.py                 # md → html（jinja2）+ sources.json
```

### `scripts/` — 一次性脚本

```
scripts/
├── download_stock_market_data.py    # 下载 A 股日线 / 周线 CSV
├── download_financial_reports.py    # 下载财报 PDF / HTML
├── import_to_milvus.py              # 分块 + 向量化 + 灌入 finance_docs collection
└── bootstrap_indices.py             # 预下载主要 A 股指数 20 年数据
```

### `tests/` — 测试

```
tests/
├── test_bm25.py
├── test_capabilities.py
├── test_evidence.py
├── test_provider_structure.py
├── test_registry.py
├── test_render_writer.py
├── test_storage_sqlite.py
├── agent/                    # AgentLoop / conversation / memory 单测
├── providers/                # cn / us provider 单测
└── retrieval/                # milvus / embedding / external_data 单测
```

跑测试：`pytest -q`。

### `data/` — 运行时数据（`.gitignore`）

```
data/
├── finance_agent.db          # SQLite：provenance + prefs + conversations
├── cache/                    # HTTP / LLM 响应缓存
├── indices/                  # 预下载的 A 股指数 CSV
├── market/stocks/            # A 股日线 / 周线 CSV（setup_all.sh 生成）
│   ├── 002594_比亚迪_daily.csv
│   ├── 300308_中际旭创_daily.csv
│   └── 300750_宁德时代_daily.csv
└── financials/downloads/     # 财报 PDF / HTML（setup_all.sh 生成）
    ├── 比亚迪/
    ├── 宁德时代/
    ├── 寒武纪/
    └── 中际旭创/
```

### `docs/` & `demos/`

```
docs/
├── design.md                 # 架构 / 设计决策
├── EXTERNAL_DATA_RAG.md      # A 股本地数据 → Milvus 的检索管线
└── FINNHUB_API_SURVEY.md     # 美股 Finnhub API 调研

demos/
└── README.md                 # 可复制粘贴的美股 / A 股 demo 问题集
```

### `volumes/` — Docker 持久化（`.gitignore`）

```
volumes/
├── etcd/                     # Milvus 元数据
├── milvus/                   # 向量数据 + 索引
└── minio/                    # Milvus 段文件（object storage）
```

`./stop_milvus.sh` 只停容器，`volumes/` 会保留；要彻底清空数据请 `rm -rf volumes/`。

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

## 故障排查

### 安装阶段

**Q: `pip install -e .` 报 `Could not find a version that satisfies faiss-cpu` / `torch`**  
A: 确认 Python 版本在 3.10–3.13 之间；Apple Silicon 用户还要确认是 arm64 版本（`python -c "import platform; print(platform.machine())"` 应输出 `arm64`）。

**Q: `pip install -e .` 卡在 `sentence-transformers` / `torch` 下载**  
A: 首次要下 ~2 GB，慢是正常的；国内可先设 `pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple`。

**Q: `python -m finance_agent init` 报 `No module named finance_agent`**  
A: 忘了激活 venv 或 `pip install -e .` 没成功。跑 `which python` 确认指向 `.venv/bin/python`。

### 配置 / API key 阶段

**Q: 运行时报 `ARK_API_KEY not set` / `401 Unauthorized`**  
A: `.env` 是否放在项目根目录？key 前后有没有多余空格 / 引号？用第 2 节末尾的 `python -c` 命令验证。

**Q: 火山方舟 / DeepSeek 报 `model not found`**  
A: 默认 `DOUBAO_MODEL=doubao-seed-evolving` 需要在火山控制台开通对应推理接入点；用自定义 endpoint id（`ep-xxxx`）也可以，直接改 `.env` 里的 `DOUBAO_MODEL`。

### 运行阶段

**Q: `ask` 报错 / 答案里没有 `[S#]` / `sources.json` 为空**  
A: 证据池为空。分场景排查：
- **美股**：跑 `python -c "from finance_agent.providers import FinnhubMarketProvider as P; print(P().get_quote('AAPL'))"` 直接试 Finnhub。403 → key 无效；429 → 触发 60 次/分钟限流，等一分钟。
- **A 股**：用 5.3 节的 `pymilvus` 命令确认 collection 行数 > 0；若为 0 重跑 `./setup_all.sh --skip-download`。

**Q: `setup_all.sh` 报 `Milvus 在 120s 内未就绪`**  
A: 看 `docker logs milvus-standalone` 前 20 行；常见原因：内存不足（Docker Desktop 建议给 ≥ 4 GB）、9091/19530 端口被占。

**Q: `setup_all.sh` 报 `Milvus 已有 N 行数据`**  
A: 脚本会问 `r/a/s/q`：**`r`**ecreate（推荐）/ **`a`**ppend（会产生重复，慎选）/ **`s`**kip / **`q`**uit。非交互场景加 `--yes` 默认 recreate。

**Q: 只想跑美股 demo，需要装 Docker / Milvus 吗？**  
A: **不需要**。美股完全走 Finnhub API，跳过第 5 节即可。

**Q: 端口冲突（19530 / 9091 / 9000 / 9001 被占）**  
A: 改 `docker-compose.milvus.yml` 里的端口映射，同时改 `.env` 里的 `FA_MILVUS_PORT`。

### 输出阶段

**Q: `outputs/*.html` 打开一片空白**  
A: 用文本编辑器打开对应 `.md`，若也为空说明 synthesizer 失败；看终端里的 stderr / `data/finance_agent.db` 里的 `runs` 表的 `error` 字段。

---

## 已知限制

- Finnhub free tier 限制 60 次/分钟
- A 股依赖本地数据，首次需运行 `./setup_all.sh`（约 5–15 分钟）
- Verifier 只查引用一致性，不判证据真伪
- 每次问答约 5–8 次 LLM 调用

更多 → [`docs/design.md`](./docs/design.md)
