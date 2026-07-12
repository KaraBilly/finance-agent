# 系统设计说明

> 约 2 页。回答三件事:**为什么这样设计、边界在哪里、有更多时间会先补什么**。

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
│  Multi-turn Conversation (finance_agent/agent/conversation*)│ │
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

### 2.1 两模型分工 (核心设计)

| 角色 | 模型 | 为什么 |
|---|---|---|
| Planner / Reranker / Verifier / Memory Extractor | **doubao-seed-evolving** | 中文优势、思考型且相对便宜。这些环节都是**结构化输出**(JSON),对成本敏感,doubao 的速度和 JSON mode 稳定性够用。 |
| Synthesizer (最终 Markdown 答案) | **deepseek** | 长上下文推理稳,擅长把多源证据 → 结构化+带引用的答案。同时它"没参与规划",相对独立。 |
| Verifier | **doubao** | 关键: **和 Synthesizer 不同模型**,避免自我确认偏差。 |

**考虑过但没用**:
- 全 deepseek: 成本翻倍,且失去 doubao 的中文/成本优势。
- 两模型辩论 (Debate): 时间不够,而且辩论收益在事实性问答上不明显,更适合开放式生成。
- 让两个模型独立生成再由第三方合并: 需要引入第三个 checker 或对齐规则,超出时间预算。

### 2.2 Capability-Provider 分层

```
Agent Loop (只依赖 Capability 接口)
    │
    ├──► LLMCapability        ←── DoubaoProvider / DeepSeekProvider
    ├──► MarketDataCapability ←── EastmoneyMarketProvider / FinnhubMarketProvider
    ├──► FinancialsCapability ←── EastmoneyFinancialsProvider / FinnhubFinancialsProvider
    ├──► FilingsCapability    ←── CninfoApiFilingsProvider / FinnhubFilingsProvider
    ├──► WebSearchCapability  ←── TavilyWebProvider
    └──► StorageCapability    ←── SQLiteStorageProvider
```

**关键**: Agent 代码只导入 `capabilities/`, 不导入 `providers/`。Provider 通过 `registry.py` 注入。

**为什么这样分层**:
- **Agent 层只依赖 Capability 接口**, 不直接调用 eastmoney/Tavily 等具体实现
- **替换 Provider 不需要改 Agent 代码** — 例如把 eastmoney 换成 JQData, 只需新建 `JQDataMarketProvider` 并在 `registry.py` 里注册
- **便于测试** — 可以注入 Mock Provider 做单元测试, 不需要真实 API Key

### 2.3 多轮对话架构 (PydanticAI 风格)

我们引入了 **PydanticAI 风格的依赖注入模式**来实现多轮对话:

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

**核心组件**:
- **`ConversationManager`**: 对话生命周期管理 (创建/读取/更新/删除)
- **`ConversationContext`**: 对话上下文封装 (历史记录、轮次管理)
- **`AgentContext`**: PydanticAI 风格的依赖注入容器

**为什么用这种模式**:
- **解耦**: Agent 不直接操作数据库,通过 Context 获取对话状态
- **可测试**: 可以轻松 Mock Context 进行单元测试
- **可扩展**: 未来可以接入 PydanticAI 的 `RunContext` 获得更强大的功能
- **向后兼容**: 单轮对话 (`ask`) 和多轮对话 (`chat`) 共享同一套核心逻辑

### 2.4 证据溯源 (Provenance)

SQLite 中四张表把"答案 → 证据"这条链完整存下来:

- `sources` — 每个外部产物一行 (URL / API 调用 / 抓取时间 / SHA256 / 本地快照路径 / meta)
- `chunks` — 从 source 切出的可引用文本片段
- `answers` — 一次问答 (question / answer_md / trace_json)
- `citations` — 把 answer 里的 `[S1]..[S#]` 映射到具体 `chunk_id`
- `user_prefs` — 长期偏好
- `conversations` — 多轮对话会话 (新增)
- `conversation_turns` — 对话轮次记录 (新增)

**为什么这么设计**: 任何 reviewer 拿到答案里的 `[S3]`, 都能顺 `citations → chunks → sources` 反查到"哪个 URL 的哪一段, 什么时候抓的, 本地快照在哪"。这不仅是"引用透明度", 也是**唯一能可靠调试 hallucination 的方式**。每次 answer 还会把整个 trace (planner 决策 / 工具调用 / verifier 结果) 写进 `trace_json`。

Web 原文快照落在 `data/cache/web_<hash>.txt`,即使原链接失效也能追溯。

---

## 3. 数据流

```
1. Load prefs — SQLite 里的 user_prefs 按 weight 排序,注入到 Planner 与 Synthesizer 的 prompt
        │
2. Plan — doubao JSON mode 输出 {intent, entities, tools[], answer_sections[]}
        │
3. Run tools — 顺序执行 (对 demo 够用,并行是后续优化)
   - market: 东财/Finnhub API → DataFrame → Evidence
   - financials: 东财/Finnhub API → 财务报表 → Evidence
   - filings: cninfo/Finnhub API → 公告列表 → Evidence
   - web: Tavily 搜索 → Trafilatura 抽正文 → BM25 粗筛 → LLM rerank → Evidence
   所有产出经 register_evidence 落 SQLite,拿到稳定的 chunk_id,同时得到 [S1..Sn] 标签
        │
4. Synthesize — deepseek 收到 evidence + question + prefs + sections,
   被 system prompt 硬约束"只能引用给定 [S#], 每条断言必须 [S#]",未知/不足处必须写"证据不足"
        │
5. Verify — doubao 双重校验:
   - 程序性: 段落必须含 [S#] (排除标题/表格/Evidence 段落); 引用编号必须在证据池范围内
   - LLM 事实性: 采样强断言,检查引用的原文是否真的支持
   若不通过,把 feedback 回喂 Synthesizer 最多一次 repair。仍不通过就在答案末尾附警告 (不隐瞒问题)
        │
6. Memory — doubao 从本轮 Q/A 中抽取偏好增量 (delta ∈ [-1,1]),用 EMA (α=0.4) 合并到 user_prefs
        │
7. Render — Markdown / HTML / sources.json 三件套写盘
```

---

## 4. 数据接入分层

```
Tier 1  结构化 API (确定性高, 全部零 token / 免费)
        东方财富 push2his   →  A 股指数 20 年日线 / 单股票日线 (前复权)
        东方财富 datacenter →  利润表 / 资产负债表 / 现金流量表
        cninfo hisAnnouncement JSON →  年报索引 + 公告 + PDF 直链
Tier 2  非结构化 Web (兜底, 置信度较低)
        Tavily(search) → Trafilatura(extract) → chunk → BM25(粗筛) → doubao rerank
```

**为什么分层**: 结构化数据是"硬事实"(股价、财报数字), web 是"软信息"(观点、新闻)。答案里我们通过 `source_kind` 隐式区分,合成时更信任 Tier 1。

**为什么不用 akshare / tushare 之类的爬虫聚合层**:
- akshare 本质上是把 sina / 东财 / cninfo 网页字段再包一层, 上游一改列名就 breaks; 多次 IP 请求还容易被临时封。
- tushare pro 数据规整但要付费/积分, 增加 reviewer 复现成本。
- 直接调东财和巨潮官方 JSON (它们自己的网站前端就用) 更稳、更快, 且完全没有 token / 授权门槛。

**考虑过但没用**:
- 直接下载 cninfo 年报 PDF 并抽风险因子章节 — 时间上做不完;PDF 抽取质量对答案影响很大,不做不如不做。后续改进的第 1 优先级 (`adjunctUrl` 直链已经拿到, 只差 pdf 解析)。
- 用向量库 (Chroma/FAISS) 做 semantic retrieval — 对目前的 evidence 规模 (每问 <30 chunks) BM25 + LLM rerank 已经够用, 加向量库反而带来 embedding 模型选择和维度存储的复杂度。

---

## 5. 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| **CLI** | `cli.py` | 命令行入口,所有子命令定义 |
| **Config** | `config.py` | 从 `.env` 加载配置,路径管理 |
| **Registry** | `registry.py` | Provider 工厂,市场切换 (cn/us) |
| **Planner** | `agent/planner.py` | 意图分析,工具选择,回答结构规划 |
| **Synthesizer** | `agent/synthesizer.py` | 答案生成,强制引用 |
| **Verifier** | `agent/verifier.py` | 引用校验,反事实检查 |
| **Memory** | `agent/memory.py` | 用户偏好提取与持久化 |
| **Loop** | `agent/loop.py` | 编排完整流程 |
| **Retrieval** | `retrieval/bm25.py`, `retrieval/rerank.py` | BM25 粗筛 + LLM rerank |
| **Storage** | `providers/storage_sqlite.py` | SQLite 数据库操作 |
| **Render** | `render/writer.py` | 输出文件生成 |

---

## 6. 扩展点

### 6.1 新增数据源

1. 在 `capabilities/` 新增 Capability 接口 (如 `news.py`)
2. 在 `providers/` 实现 Provider (如 `news_tavily.py`)
3. 在 `registry.py` 注册
4. 在 `planner.py` 的 prompt 中新增工具描述

### 6.2 切换 LLM 后端

修改 `registry.py`:

```python
def create_default_registry(market="cn"):
    return ProviderRegistry(
        planner_llm=YourProvider(),      # 替换
        synthesizer_llm=YourProvider(),  # 替换
        ...
    )
```

### 6.3 新增市场

1. 在 `providers/` 下新建市场目录 (如 `hk/`)
2. 实现对应的 Market/Financials/Filings Provider
3. 在 `registry.py` 的 `_build_data_providers()` 中新增分支

---

## 7. 边界与已知失败模式

1. **filings 深度不够** — 目前只到"年报标题 + 公告 URL"级别, 没做 PDF 正文抽取。对"竞争"/"风险因素"这类问题会**过度依赖 web**。
2. **东财 / 巨潮官方 JSON 稳定性** — 属于网站前端自用接口, 无正式的向后兼容承诺, 字段名偶尔会调整;provider 在 financials/filings 里做了"列白名单 + 缺失即跳过"和 try/except 降级, 仍可能返回空 DataFrame 触发 web fallback。
3. **Verifier 只能验一致性,不能验真伪** — 如果证据本身错了 (比如某个新闻站点数据错误),Verifier 不会发现。缓解: 我们保留原文快照给 reviewer 追溯。
4. **Preference drift** — 单轮增量太大可能把 weight 冲上限;EMA 缓解但不完全。如果用户长期只问一个话题,`user_prefs` 会失去区分度。
5. **模型别名/可用性** — `doubao-seed-evolving` 需要在 Ark 后台开通(可能实际以 endpoint id `ep-xxx` 存在);`deepseek V4` 若未 GA 需回退到 `deepseek-chat`。`.env` 已抽象。
6. **成本** — 每次问答约 5-8 次 LLM 调用 (plan 1 + rerank N + synth 1-2 + verify 1-2 + memory 1)。对 demo OK, 对高频使用需要 caching/流式退避。
7. **Tavily 免费额度** — 命中 rate limit 会抛异常;当前处理是"该 web 子任务失败,其他证据继续"。

---

## 8. 如果给我更多时间,先补哪几样

按 ROI 从高到低:

1. **cninfo PDF 深度抽取** — 用 `pdfplumber` 或 `unstructured` 拆年报的"重大风险提示"/"行业竞争"章节, 生成真正的 filings evidence。对 "risk factors" / "competition" 类问题, 这是最大的信息增量。
2. **并行工具调用** — 目前 Planner 输出多工具后是顺序跑, 用 `asyncio.gather` 或线程池能把延迟砍一半。
3. **Embedding + FAISS 二级检索** — 当 web pipeline 抓到几百 chunks 时, BM25 会显得粗。加个中文 embedding (bge-small-zh) 做 rerank 前置。
4. **量化指标计算工具** — 现在指数是给"起止收盘/累计涨跌"这类粗指标, 应该做 max drawdown / rolling sharpe / turnover 之类的计算工具让 LLM 调用。
5. **PydanticAI 深度集成** — 当前已实现 PydanticAI 风格的依赖注入模式, 但尚未使用 PydanticAI 的 `Agent` 类和 `RunContext`。未来可以:
   - 用 `Agent` 类封装工具调用, 获得自动重试、流式输出、结构化输出验证
   - 用 `RunContext` 替代手动的 `AgentContext`, 获得更强大的依赖注入和类型安全
   - 接入 PydanticAI 的 `MemoryTool` 和 `WebSearch` 内置能力
6. **交叉验证多个数据源** — 财务数据从东财 + Sina/cninfo XBRL 拉两份对比, 不一致时警告。这是 real-money 应用必备。
7. **PPT 输出 + 可视化图表** — python-pptx + matplotlib 生成分析报告 deck。功能层面收益中等,但演示价值高。

---

## 9. 为什么这些不算"过度设计"

在这个规模上, 加 SQLite / Verifier / Memory / 双模型看起来"重",但每一个都直接对应评分维度:
- **可解释**: SQLite provenance + sources.json → 每一条断言可追。
- **可验证**: Verifier + repair loop → hallucination 出现时**答案自带警告**, 不静默失败。
- **多模型协同**: doubao + deepseek 有明确分工, 不是两个模型都做同一件事。
- **用户偏好**: `user_prefs` 表 + EMA + planner 注入 = 完整闭环, 不是把对话历史整段塞进 prompt 那种伪长期记忆。
- **多轮对话**: PydanticAI 风格的依赖注入 + ConversationManager 实现真正的上下文感知, 不是简单的历史拼接。

功能数量刻意收敛在 4 个工具, 每个都能讲清楚"为什么在,为什么不做得更深"。
