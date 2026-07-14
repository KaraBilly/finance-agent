"""Tests for render.writer — output file emission."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from finance_agent.capabilities.base import Evidence


@dataclass
class _FakeResult:
    """Minimal duck-typed stand-in for AgentResult."""
    question: str = "What is BYD?"
    answer_md: str = "# BYD\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    evidences: list = field(default_factory=list)
    plan: dict = field(default_factory=lambda: {"tools": []})
    trace: dict = field(default_factory=lambda: {
        "model_planner": "doubao",
        "model_synthesizer": "deepseek",
        "elapsed_s": 1.2,
    })
    answer_id: int = 42
    prefs_updated: list = field(default_factory=list)


class TestWriteOutputs:
    def test_writes_md_html_and_sources_json(self, tmp_path):
        result = _FakeResult(
            evidences=[
                Evidence(
                    text="body",
                    source_kind="web",
                    url="https://ex.com",
                    title="Ex",
                    publisher="Example",
                    meta={"k": 1},
                    chunk_id=11,
                    source_id=7,
                ),
            ],
        )

        with patch("finance_agent.render.writer.CONFIG") as mock_cfg:
            mock_cfg.output_dir = tmp_path
            from finance_agent.render import writer  # import after patch
            paths = writer.write_outputs(result)

        md_path = Path(paths["md"])
        html_path = Path(paths["html"])
        json_path = Path(paths["sources"])

        # All three files land under the configured output_dir.
        assert md_path.exists() and md_path.parent == tmp_path
        assert html_path.exists() and html_path.parent == tmp_path
        assert json_path.exists() and json_path.parent == tmp_path

        # Markdown includes question + provenance header + body.
        md = md_path.read_text(encoding="utf-8")
        assert "Q: What is BYD?" in md
        assert "planner=doubao" in md
        assert "synthesizer=deepseek" in md
        assert "# BYD" in md

        # HTML renders the markdown table via the `tables` extension.
        html = html_path.read_text(encoding="utf-8")
        assert "<table>" in html
        assert "Answer #42" in html

        # sources.json is well-formed and includes evidence records.
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["answer_id"] == 42
        assert payload["question"] == "What is BYD?"
        assert len(payload["sources"]) == 1
        src = payload["sources"][0]
        assert src["label"] == "S1"
        assert src["chunk_id"] == 11
        assert src["source_id"] == 7
        assert src["url"] == "https://ex.com"

    def test_handles_empty_evidences(self, tmp_path):
        result = _FakeResult(evidences=[])
        with patch("finance_agent.render.writer.CONFIG") as mock_cfg:
            mock_cfg.output_dir = tmp_path
            from finance_agent.render import writer
            paths = writer.write_outputs(result)

        payload = json.loads(Path(paths["sources"]).read_text(encoding="utf-8"))
        assert payload["sources"] == []

    def test_filename_includes_answer_id(self, tmp_path):
        result = _FakeResult(answer_id=999)
        with patch("finance_agent.render.writer.CONFIG") as mock_cfg:
            mock_cfg.output_dir = tmp_path
            from finance_agent.render import writer
            paths = writer.write_outputs(result)

        for kind, p in paths.items():
            assert "-ans999" in Path(p).name, (kind, p)
