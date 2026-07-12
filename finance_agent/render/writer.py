"""Persist a run's outputs: Markdown, HTML, and a sources.json for reviewers."""
from __future__ import annotations
import json
import time
from pathlib import Path

import markdown as mdlib

from ..config import CONFIG

_HTML_TMPL = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Segoe UI", sans-serif;
          max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #222; }}
  h1,h2,h3 {{ border-bottom: 1px solid #eee; padding-bottom: 4px; }}
  table {{ border-collapse: collapse; margin: 1em 0; }}
  th, td {{ border: 1px solid #ccc; padding: 4px 8px; }}
  code {{ background: #f4f4f4; padding: 1px 4px; border-radius: 3px; }}
  blockquote {{ border-left: 3px solid #ffb; background: #fff8e1; padding: 6px 12px; }}
  .meta {{ color: #888; font-size: 0.9em; }}
</style>
</head>
<body>
<p class="meta">Answer #{aid} · generated {ts}</p>
{body}
</body></html>
"""


def write_outputs(result) -> dict[str, str]:
    """Write MD, HTML and sources.json under FA_OUTPUT_DIR. Returns file paths."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    base = CONFIG.output_dir / f"{ts}-ans{result.answer_id}"
    md_path = base.with_suffix(".md")
    html_path = base.with_suffix(".html")
    json_path = Path(str(base) + ".sources.json")

    header = (
        f"# Q: {result.question}\n\n"
        f"*Answer id: {result.answer_id} · planner={result.trace.get('model_planner')} · "
        f"synthesizer={result.trace.get('model_synthesizer')} · "
        f"elapsed={result.trace.get('elapsed_s')}s*\n\n---\n\n"
    )
    md_path.write_text(header + result.answer_md, encoding="utf-8")

    body_html = mdlib.markdown(result.answer_md, extensions=["tables", "fenced_code"])
    html_path.write_text(_HTML_TMPL.format(
        title=result.question[:80], aid=result.answer_id, ts=ts, body=body_html,
    ), encoding="utf-8")

    sources = []
    for i, e in enumerate(result.evidences, 1):
        sources.append({
            "label": f"S{i}",
            "chunk_id": e.chunk_id,
            "source_id": e.source_id,
            "kind": e.source_kind,
            "title": e.title,
            "url": e.url,
            "publisher": e.publisher,
            "meta": e.meta,
        })
    json_path.write_text(json.dumps({
        "answer_id": result.answer_id,
        "question": result.question,
        "plan": result.plan,
        "prefs_updated": result.prefs_updated,
        "sources": sources,
        "trace": result.trace,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"md": str(md_path), "html": str(html_path), "sources": str(json_path)}
