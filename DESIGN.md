# Design Notes — Finance Personal Agent (A股)

约 2 页。回答三件事:**为什么这样设计、边界在哪里、有更多时间会先补什么**。

---

## 1. 目标与硬约束

- 领域: A 股个人交易辅助 (为什么只做 A 股: 中文语料对 doubao 更友好, 数据源 akshare + cninfo 免费且成熟, 时间受限时聚焦一个市场比"看起来什么都能做"更能讲清楚取舍)。
- 硬约束: 主力推理必须用 **doubao-seed-evolving + deepseek** 两个模型。
- 评分导向: "功能少但每处取舍讲得清" > "功能多但说不清"。所以下面每个决策都配了"考虑过但没采用"的另一条路。

---

## 2. 两模型分工 (核心设计)

| 角色 | 模型 | 为什么 |
|---|---|---|
| Planner / Reranker / Verifier / Memory Extractor | **doubao-seed-evolving** | 中文优势、思考型且相对便宜。这些环节都是**结构化输出**(JSON),对成本敏感,doubao 的速度和 JSON mode 稳定性够用。 |
| Synthesizer (最终 Markdown 答案) | **deepseek** | 长上下文推理稳,擅长把多源证据 → 结构化+带引用的答案。同时它"没参与规划",相对独立。 |
| Verifier | **doubao** | 关键: **和 Synthesizer 不同模型**,避免自我确认偏差。 |

**考虑过但没用**:
- 全 deepseek: 成本翻倍,且失去 doubao 的中文/成本优势。
- 两模型辩论 (Debate): 时间不够,而且辩论收益在事实性问答上不明显,更适合开放式生成。
- 让两个模型独立生成再由第三方合并: 需要引入第三个 checker 或对齐规则,超出时间预算。

---

## 3. 三层架构 (Capability-Provider 模式)

```
┌─────────────────────────────────────────────────────────────────┐
│                      Finance Agent (loop.py)                    │
│   Planner → Tools → Synthesizer → Verifier → Memory → Render    │
└─────────────────────────────────────────────────────────────────┘
                              │ depends on
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Capability Layer (抽象接口)                   │
│  LLMCapability │ MarketDataCapability │ FinancialsCapability    │
│  FilingsCapability │ WebSearchCapability │ StorageCapability    │
└─────────────────────────────────────────────────────────────────┘
                              │ implemented by
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Provider Layer (具体实现)                     │
│  DoubaoProvider, DeepSeekProvider     (LLM)                     │
│  AkshareMarketProvider                (市场数据)                 │
│  AkshareFinancialsProvider            (财务报表)                 │
│  CninfoFilingsProvider                (公告/年报)                │
│  TavilyWebProvider                    (Web搜索)                  │
│  SQLiteStorageProvider                (持久化)                   │
└─────────────────────────────────────────────────────────────────┘
                              │ calls
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      External APIs                              │
│  Volcengine Ark │ DeepSeek API │ akshare │ Tavily │ SQLite      │
└─────────────────────────────────────────────────────────────────┘
```

**为什么这样分层**:
- **Agent 层只依赖 Capability 接口**, 不直接调用 akshare/Tavily 等具体实现
- **替换 Provider 不需要改 Agent 代码** — 例如把 akshare 换成 tushare, 只需新建 `TushareMarketProvider` 并在 `registry.py` 里注册
- **便于测试** — 可以注入 Mock Provider 做单元测试, 不需要真实 API Key

## 4. 数据接入分层

```
Tier 1  结构化 API (确定性高)
        akshare  →  A 股指数 20 年日线 / 单股票日线 / 三张财务报表 (Sina)
        akshare  →  cninfo 年报索引 + 公告
Tier 2  非结构化 Web (兜底, 置信度较低)
        Tavily(search) → Trafilatura(extract) → chunk → BM25(粗筛) → doubao rerank
```

**为什么分层**: 结构化数据是"硬事实"(股价、财报数字), web 是"软信息"(观点、新闻)。答案里我们通过 `source_kind` 隐式区分,合成时更信任 Tier 1。

**考虑过但没用**:
- 用 Tushare pro (数据更规整) — 需要付费/注册积分,增加 reviewer 的复现成本。
- 直接下载 cninfo 年报 PDF 并抽风险因子章节 — 时间上做不完;PDF 抽取质量对答案影响很大,不做不如不做。后续改进的第 1 优先级。
- 用向量库 (Chroma/FAISS) 做 semantic retrieval — 对目前的 evidence 规模 (每问 <30 chunks) BM25 + LLM rerank 已经够用, 加向量库反而带来 embedding 模型选择和维度存储的复杂度。

---

## 5. Provenance / 引用信息

SQLite 中四张表把"答案 → 证据"这条链完整存下来:

- `sources` — 每个外部产物一行 (URL / API 调用 / 抓取时间 / SHA256 / 本地快照路径 / meta)
- `chunks` — 从 source 切出的可引用文本片段
- `answers` — 一次问答 (question / answer_md / trace_json)
- `citations` — 把 answer 里的 `[S1]..[S#]` 映射到具体 `chunk_id`
- `user_prefs` — 长期偏好

**为什么这么设计**: 任何 reviewer 拿到答案里的 `[S3]`, 都能顺 `citations → chunks → sources` 反查到"哪个 URL 的哪一段, 什么时候抓的, 本地快照在哪"。这不仅是"引用透明度", 也是**唯一能可靠调试 hallucination 的方式**。每次 answer 还会把整个 trace (planner 决策 / 工具调用 / verifier 结果) 写进 `trace_json`。

Web 原文快照落在 `data/cache/web_<hash>.txt`,即使原链接失效也能追溯。

---

## 6. Agent Loop

1. **Load prefs** — SQLite 里的 user_prefs 按 weight 排序,注入到 Planner 与 Synthesizer 的 prompt。
2. **Plan** — doubao JSON mode 输出 `{intent, entities, tools[], answer_sections[]}`。
3. **Run tools** — 顺序执行 (对 demo 够用,并行是后续优化)。所有产出经 `register_evidence` 落 SQLite,拿到稳定的 `chunk_id`,同时得到 `[S1..Sn]` 标签。
4. **Synthesize** — deepseek 收到 evidence + question + prefs + sections, 被 system prompt **硬约束"只能引用给定 [S#], 每条断言必须 [S#]"**, 未知/不足处必须写"证据不足"。
5. **Verify** — doubao 双重校验:
   - 程序性: 段落必须含 `[S#]` (排除标题/表格/Evidence 段落); 引用编号必须在证据池范围内。
   - LLM 事实性: 采样强断言,检查引用的原文是否真的支持。
   若不通过,把 feedback 回喂 Synthesizer **最多一次** repair。仍不通过就在答案末尾附警告 (不隐瞒问题)。
6. **Memory** — doubao 从本轮 Q/A 中抽取偏好增量 (delta ∈ [-1,1]),用 EMA (α=0.4) 合并到 `user_prefs`。
7. **Render** — Markdown / HTML / sources.json 三件套写盘。

---

## 7. 边界与已知失败模式

1. **filings 深度不够** — 目前只到"年报标题 + 公告 URL"级别, 没做 PDF 正文抽取。对"竞争"/"风险因素"这类问题会**过度依赖 web**。
2. **akshare 稳定性** — 上游接口列名偶尔变动;我在 financials/filings 里做了"列名启发式匹配"和 try/except 降级,但仍可能返回空 DataFrame 触发 web fallback。
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
5. **多轮对话上下文** — 目前每个 `ask` 是独立的; 应该把 last-N answers 的摘要放进 planner, 让"上面结论的证据来源是什么"这类追问真正 work (当前只能靠 memory 里的偏好间接影响)。
6. **交叉验证多个数据源** — 财务数据从 akshare(Sina) + Eastmoney 拉两份对比, 不一致时警告。这是 real-money 应用必备。
7. **PPT 输出 + 可视化图表** — python-pptx + matplotlib 生成分析报告 deck。功能层面收益中等,但演示价值高。

---

## 9. 为什么这些不算"过度设计"

在这个规模上, 加 SQLite / Verifier / Memory / 双模型看起来"重",但每一个都直接对应评分维度:
- **可解释**: SQLite provenance + sources.json → 每一条断言可追。
- **可验证**: Verifier + repair loop → hallucination 出现时**答案自带警告**, 不静默失败。
- **多模型协同**: doubao + deepseek 有明确分工, 不是两个模型都做同一件事。
- **用户偏好**: `user_prefs` 表 + EMA + planner 注入 = 完整闭环, 不是把对话历史整段塞进 prompt 那种伪长期记忆。

功能数量刻意收敛在 4 个工具, 每个都能讲清楚"为什么在,为什么不做得更深"。
