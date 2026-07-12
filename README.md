# Finance Personal Agent — A股

一个聚焦 **A 股** 的个人金融交易 Agent。回答问题时:
- 优先使用**结构化数据源** (akshare 指数/行情/财务、cninfo 公告)
- 需要时再走 **Tavily 搜索 + Trafilatura 抽正文 + BM25 粗筛 + LLM rerank**
- 使用 **两个模型协同**:
  - `doubao-seed-evolving` (火山方舟 Ark) — 规划、rerank、事实校验、偏好抽取
  - `deepseek` — 最终答案合成 (强制引用 `[S#]`)
- **完整 provenance**: 每条证据都落 SQLite,可以从答案里的 `[S3]` 反查到 URL + 快照文件 + 抓取时间
- **长期用户偏好**: 用户强调过的关注点(如 liquidity_risk / debt_maturity / cash_flow) 会持久化并影响后续 planning 与 answer 结构

设计详解 → [`DESIGN.md`](./DESIGN.md)

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

**必填 API keys:**

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
├── config.py
├── registry.py           # Provider 注册 (切换 LLM 后端)
├── capabilities/         # 抽象接口层 (Agent 只依赖这层)
│   ├── llm.py           # LLMCapability
│   ├── market_data.py   # MarketDataCapability
│   └── ...
├── providers/            # 具体实现层 (可替换)
│   ├── llm_openai.py    # DoubaoProvider, DeepSeekProvider
│   └── ...  # market_akshare, financials_akshare, filings_cninfo, web_tavily, storage_sqlite
├── agent/                # planner / synthesizer / verifier / memory / loop
├── retrieval/            # bm25 + llm rerank
├── storage/              # SQLite provenance
└── render/               # md + html + sources.json 输出
```

## CLI 参考
```
python -m finance_agent ask "..."          # 问一个问题
python -m finance_agent ask "..." --quiet  # 不打印 plan 表格
python -m finance_agent prefs              # 查看学到的偏好
python -m finance_agent clear-prefs        # 清空
python -m finance_agent init               # 建库
python -m finance_agent bootstrap-indices  # 拉 20 年指数
```

## 已知限制 & 后续改进

见 [`DESIGN.md`](./DESIGN.md) 最后一节。要点:
- filings 目前只用 cninfo 的标题+URL(不下载 PDF 原文抽风险因子章节)
- Verifier 只查引用一致性,不判证据真伪
- akshare 若访问受限或格式变动会降级到 web fallback
- 未做 embedding 向量检索,BM25+LLM rerank 对 demo 规模够用
