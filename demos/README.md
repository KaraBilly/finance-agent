# Demo Questions (A股)

Runnable demo prompts. Assumes:
1. `.env` has `ARK_API_KEY`, `DEEPSEEK_API_KEY`, `TAVILY_API_KEY` filled.
2. You ran `python -m finance_agent bootstrap-indices` once.

Each command generates:
- `outputs/<ts>-ans<id>.md` — the answer
- `outputs/<ts>-ans<id>.html` — the same, rendered
- `outputs/<ts>-ans<id>.sources.json` — full provenance + trace

### Q1 · Risk factors (贵州茅台)
```bash
python -m finance_agent ask "贵州茅台(600519)的主要风险因素有哪些?请给出证据来源。"
```

### Q2 · YoY revenue / profitability (宁德时代)
```bash
python -m finance_agent ask "宁德时代(300750)最近两年的营收和净利润变化情况?"
```

### Q3 · Competition (比亚迪)
```bash
python -m finance_agent ask "比亚迪(002594)自己如何描述其面临的竞争?"
```

### Q4 · Liquidity / debt (万科)
```bash
python -m finance_agent ask "总结万科A(000002)的流动性和债务相关风险。"
```

### Q5 · Evidence for a prior claim
```bash
python -m finance_agent ask "上面结论的证据来源是什么?列出每一条断言对应的原文段落。"
```

### Bonus · Index-level macro
```bash
python -m finance_agent ask "过去20年沪深300和中证500的年化回报和最大回撤大概是多少?"
```

## Preference memory demo
```bash
python -m finance_agent prefs                         # show what the agent learned
python -m finance_agent ask "我更关心 liquidity risk 和 cash flow"
python -m finance_agent prefs                         # weights should update
python -m finance_agent ask "分析下贵州茅台"           # answer should skew towards those topics
```
