# 外挂数据接入 RAG 指南

## 概述

Finance Agent 现在支持将外挂的市场数据和财报等数据接入 RAG（检索增强生成）流程。

## 数据流

```
用户问题
    ↓
Planner 分析意图
    ↓
工具调用 (API 获取实时数据)
    ↓
外挂数据 RAG 检索 (BM25 + LLM Rerank)
    ↓
合并证据 → 去重 → 排序
    ↓
Synthesizer 生成答案
```

## 目录结构

将外挂数据放入以下目录：

```
data/
├── market/          # 市场数据 (K线、行情等)
│   ├── AAPL_2024.csv
│   ├── 000001_daily.csv
│   └── indices.json
├── financials/      # 财报数据
│   ├── AAPL_income.csv
│   ├── 000001_balance.json
│   └── reports.md
└── filings/         # 公告/SEC文件
    ├── AAPL_10K_2024.txt
    └── 贵州茅台_2023年报.md
```

## 支持的文件格式

- **CSV** - 自动按行分块，转换为 Markdown 表格
- **JSON/JSONL** - 自动按条目分块
- **Markdown/Text** - 按段落分块

## 配置

在 `.env` 文件中配置：

```bash
# 启用外挂数据（默认 true）
FA_USE_EXTERNAL_DATA=true

# 自定义目录（可选，默认使用 data/{market,financials,filings}）
FA_EXTERNAL_MARKET_DIR=/path/to/your/market/data
FA_EXTERNAL_FINANCIALS_DIR=/path/to/your/financials
FA_EXTERNAL_FILINGS_DIR=/path/to/your/filings
```

## 文件名规范

系统会尝试从文件名提取股票代码：

- **美股**: `AAPL_2024.csv` → symbol = `AAPL`
- **A股**: `000001_财务数据.csv` → symbol = `000001`

## 工作原理

### 1. 数据加载 (`ExternalDataStore`)

- 启动时自动扫描数据目录
- 将文件内容转换为文本块
- 维护 `(text, metadata, source_kind)` 列表

### 2. 检索流程 (`UnifiedRetriever`)

```
用户查询
    ↓
BM25 预过滤 (选出 top-20)
    ↓
LLM Rerank (Doubao 评分 0-10)
    ↓
返回 top-6 证据
```

### 3. 与工具调用结合

Agent Loop 的工作流程：

1. **工具调用** - 调用 API 获取实时数据（如 Finnhub）
2. **外挂数据检索** - 根据工具类型推断需要的外挂数据源
   - `market.index` / `market.stock` → 搜索 `market` 数据
   - `financials` → 搜索 `financials` 数据
   - `filings` → 搜索 `filings` 数据
3. **合并证据** - 合并 API 数据和外挂数据
4. **去重排序** - 跨源去重，BM25 + LLM 排序
5. **生成答案** - 使用所有证据生成回答

## 代码示例

### 直接使用 ExternalDataStore

```python
from finance_agent.retrieval.external_data_store import ExternalDataStore

store = ExternalDataStore()
store.load_all()

# 搜索市场数据
evidences = store.search(
    "苹果公司最新股价",
    source_kinds=["market"],
    final_top=5
)

for ev in evidences:
    print(f"[{ev.source_kind}] {ev.title}")
    print(ev.text[:200])
```

### 使用 UnifiedRetriever

```python
from finance_agent.retrieval.unified_retriever import UnifiedRetriever
from finance_agent.registry import create_default_registry

registry = create_default_registry()
retriever = UnifiedRetriever(registry)

# 检索所有来源
evidences = retriever.retrieve(
    "特斯拉财报分析",
    use_external=True,
    use_web=True,
    external_kinds=["financials", "filings"],
    final_top=10
)
```

### 查看统计信息

```python
# 查看外挂数据统计
stats = retriever.get_stats()
print(stats)
# Output: {'external_data': {'market': 150, 'financials': 80, 'filings': 200, 'total': 430}}
```

## 性能优化

- **懒加载**: `ExternalDataStore` 首次使用时才加载数据
- **缓存**: 数据加载后缓存在内存中
- **分块策略**: 
  - CSV: 约 10 块/文件
  - JSON: 约 10 块/文件
  - Text: 800 字符/块，100 字符重叠

## 故障排查

### 外挂数据未被使用

1. 检查 `FA_USE_EXTERNAL_DATA=true` 是否设置
2. 检查数据目录是否存在: `ls data/market/`
3. 检查文件格式是否支持 (csv, json, jsonl, md, txt)
4. 查看日志: `FA_LOG_LEVEL=DEBUG`

### 检索结果不准确

1. 检查文件名是否包含股票代码
2. 确保文件内容包含关键词
3. 调整 `_CHUNK_SIZE` 和 `_CHUNK_OVERLAP`

## 进阶：自定义数据加载

可以继承 `ExternalDataStore` 实现自定义加载逻辑：

```python
from finance_agent.retrieval.external_data_store import ExternalDataStore

class MyDataStore(ExternalDataStore):
    def _load_csv(self, file_path, source_kind):
        # 自定义 CSV 加载逻辑
        # 返回 list of (text, metadata, source_kind)
        ...
```

## 架构图

```
┌─────────────────────────────────────────┐
│           UnifiedRetriever              │
├─────────────────────────────────────────┤
│  ExternalDataStore    │  Web Search     │
│  ├─ market/           │  (Tavily)       │
│  ├─ financials/       │                 │
│  └─ filings/          │                 │
└─────────────────────────────────────────┘
           │                    │
           └────────┬───────────┘
                    ↓
            ┌───────────────┐
            │  BM25 + Rerank │
            └───────────────┘
                    ↓
            ┌───────────────┐
            │  Deduplicate   │
            └───────────────┘
                    ↓
            ┌───────────────┐
            │   Evidence[]   │
            └───────────────┘
```

## 更新日志

- **2024-XX-XX**: 初始实现外挂数据 RAG 集成
  - `ExternalDataStore`: 外挂数据存储和检索
  - `UnifiedRetriever`: 统一检索器
  - Agent Loop 集成: 自动推断数据源并检索
