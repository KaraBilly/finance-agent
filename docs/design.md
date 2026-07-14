# 系统设计说明

> 约 2 页。回答三件事：**为什么这样设计、边界在哪里、有更多时间会先补什么**。

---

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                        User Question                          │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Agent Loop (finance_agent/agent/loop.py)                   │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────────┐ │
│  │ Planner │ → │ Tools   │ → │ Synth   │ → │ Verifier    │ │
│  │ (doubao)│   │ (APIs)  │   │(deepseek│   │ (doubao)    │ │
│  └─────────┘   └─────────┘   └─────────┘   └─────────────┘ │
│                                              │              │
│                                              ▼              │
│                                    ┌─────────────────────┐  │
│                                    │ Memory Extractor    │  │
│                                    │ (doubao)            │  │
│                                    └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Multi-turn Conversation                                     │
│  - Conversation state persistence                           │
│  - Turn-by-turn history tracking                            │
│  - PydanticAI-inspired RunContext dependency injection        │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Render Layer (finance_agent/render/)                       │
│  - Markdown output                                            │
│  - HTML output                                                │
│  - sources.json (provenance)                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 核心设计原则

### 2.1 两模型分工

| 角色 | 模型 | 为什么 |
|---|---|---|
| Planner / Reranker / Verifier / Memory | **doubao** | 中文优势、思考型、相对便宜。结构化输出（JSON），对成本敏感。 |
| Synthesizer | **deepseek** | 长上下文推理稳，擅长多源证据 → 结构化+带引用的答案。 |
| Verifier | **doubao** | 关键：**和 Synthesizer 不同模型**，避免自我确认偏差。 |

### 2.2 Capability-Provider 分层

```
Agent Loop (只依赖 Capability 接口)
    │
    ├──► LLMCapability        ←── DoubaoProvider / DeepSeekProvider
    ├──► MarketDataCapability ←── ExternalAshareMarketProvider / FinnhubMarketProvider
    ├──► FinancialsCapability ←── ExternalAshareFinancialsProvider / FinnhubFinancialsProvider
    ├──► FilingsCapability    ←── ExternalAshareFilingsProvider / FinnhubFilingsProvider
    ├──► WebSearchCapability  ←── TavilyWebProvider
    └──► StorageCapability    ←── SQLiteStorageProvider
```

**关键**：Agent 代码只导入 `capabilities/`，不导入 `providers/`。Provider 通过 `registry.py` 注入。

**为什么**：
- 替换 Provider 不需要改 Agent 代码
- 便于测试 — 可注入 Mock Provider

### 2.3 多轮对话架构

```
┌─────────────────────────────────────────────────────────────┐
│  AgentContext (PydanticAI-inspired)                          │
│  ┌───────────────────────────────────────────────────────┐ │
│  │  registry: ProviderRegistry                             │ │
│  │  conversation_manager: ConversationManager               │ │
│  │  conversation_id: str | None                           │ │
│  │  max_history_turns: int = 10                           │ │
│  └───────────────────────────────────────────────────────┘ │
│                          │                                   │
│                          ▼                                   │
│  ┌───────────────────────────────────────────────────────┐ │
│  │  ConversationContext                                    │ │
│  │  ├─ get_history() → list[dict]                       │ │
│  │  ├─ add_user_turn()                                    │ │
│  │  └─ add_assistant_turn()                               │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.4 证据溯源 (Provenance)

SQLite 表：
- `sources` — 外部产物（URL / API 调用 / 抓取时间 / SHA256 / 本地快照）
- `chunks` — 从 source 切出的文本片段
- `answers` — 一次问答（question / answer_md / trace_json）
- `citations` — `[S1]..[S#]` 映射到 `chunk_id`
- `user_prefs` — 长期偏好
- `conversations` / `conversation_turns` — 多轮对话

---

## 3. 数据流

```
1. Load prefs — SQLite user_prefs 注入 Planner/Synthesizer prompt
         │
2. Plan — doubao JSON mode 输出 {intent, entities, tools[], answer_sections[]}
         │
3. Run tools — 顺序执行（对 demo 够用，并行是后续优化）
   - market: Finnhub API / 本地文件 → DataFrame → Evidence
   - financials: Finnhub API / 本地文件 → 财务报表 → Evidence
   - filings: Finnhub API / 本地文件 → 公告列表 → Evidence
   - web: Tavily → Trafilatura → BM25 → LLM rerank → Evidence
   所有产出落 SQLite，拿到 [S1..Sn]
         │
4. Synthesize — deepseek 收到 evidence + question + prefs + history
   被约束"只能引用给定 [S#]，未知处写'证据不足'"
         │
5. Verify — doubao 双重校验：
   - 程序性：段落必须含 [S#]，引用编号在范围内
   - LLM 事实性：采样强断言，检查原文是否支持
   不通过 → feedback 回喂 Synthesizer 最多 1 次 repair
         │
6. Memory — doubao 抽取偏好增量，EMA(α=0.4) 合并到 user_prefs
         │
7. Render — Markdown / HTML / sources.json
```

---

## 4. 数据接入分层

```
Tier 1  结构化 API（确定性高）
        美股: Finnhub API → 实时报价 / 财务指标 / 完整财报 / SEC 文件
        A股: 本地文件 → 日线 / 财报 / 公告
Tier 2  非结构化 Web（兜底，置信度较低）
        Tavily → Trafilatura → chunk → BM25 → LLM rerank
```

**为什么分层**：结构化数据是"硬事实"，web 是"软信息"。

---

## 5. 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| **CLI** | `cli.py` | 命令行入口 |
| **Config** | `config.py` | 从 `.env` 加载配置 |
| **Registry** | `registry.py` | Provider 工厂，市场切换 (cn/us) |
| **Planner** | `agent/planner.py` | 意图分析，工具选择 |
| **Synthesizer** | `agent/synthesizer.py` | 答案生成，强制引用 |
| **Verifier** | `agent/verifier.py` | 引用校验，反事实检查 |
| **Memory** | `agent/memory.py` | 用户偏好提取与持久化 |
| **Loop** | `agent/loop.py` | 编排完整流程 |
| **Retrieval** | `retrieval/` | BM25 + Embedding + LLM rerank |
| **Storage** | `providers/storage_sqlite.py` | SQLite 数据库操作 |
| **Render** | `render/writer.py` | 输出文件生成 |

---

## 6. 扩展点

### 6.1 新增数据源

1. 在 `capabilities/` 新增 Capability 接口
2. 在 `providers/` 实现 Provider
3. 在 `registry.py` 注册
4. 在 `planner.py` 的 prompt 中新增工具描述

### 6.2 切换 LLM 后端

修改 `registry.py`：

```python
def create_default_registry(market="cn"):
    return ProviderRegistry(
        planner_llm=YourProvider(),      # 替换
        synthesizer_llm=YourProvider(),  # 替换
        ...
    )
```

### 6.3 新增市场

1. 在 `providers/` 下新建市场目录（如 `hk/`）
2. 实现对应的 Market/Financials/Filings Provider
3. 在 `registry.py` 的 `_build_data_providers()` 中新增分支

---

## 7. 边界与已知失败模式

1. **A股依赖外挂数据** — 需提前准备数据文件，无实时 API 调用
2. **Finnhub free tier 限制** — 60 次/分钟，15 分钟延迟，无历史 K 线
3. **filings 深度不够** — 目前只到"标题+URL"级别，未做 PDF 正文抽取
4. **Verifier 只能验一致性，不能验真伪** — 证据本身错了发现不了
5. **Preference drift** — EMA 缓解但不完全
6. **成本** — 每次问答约 5-8 次 LLM 调用
7. **Tavily 免费额度** — 命中 rate limit 会抛异常

---

## 8. 后续改进

按 ROI 从高到低：

1. **并行工具调用** — `asyncio.gather` 或线程池，延迟砍半
2. **Embedding + FAISS 二级检索** — 当 web pipeline 抓到几百 chunks 时，BM25 会显得粗
3. **cninfo PDF 深度抽取** — 拆年报的"重大风险提示"/"行业竞争"章节
4. **量化指标计算工具** — max drawdown / rolling sharpe / turnover
5. **PydanticAI 深度集成** — 用 `Agent` 类和 `RunContext` 获得自动重试、流式输出
6. **交叉验证多个数据源** — 财务数据从多份对比，不一致时警告
7. **PPT 输出 + 可视化图表** — python-pptx + matplotlib

---

## 9. 为什么这些不算"过度设计"

- **可解释**: SQLite provenance + sources.json → 每条断言可追
- **可验证**: Verifier + repair loop → hallucination 时**答案自带警告**
- **多模型协同**: doubao + deepseek 有明确分工
- **用户偏好**: `user_prefs` 表 + EMA + planner 注入 = 完整闭环
- **多轮对话**: PydanticAI 风格依赖注入 + ConversationManager

功能数量刻意收敛在 4 个工具，每个都能讲清楚"为什么在，为什么不做得更深"。
