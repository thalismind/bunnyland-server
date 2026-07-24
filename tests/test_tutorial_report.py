"""Tests for tutorial report and diagram generation."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.tutorial_report import TUTORIAL_MAPS, build_report, render_map_svg
from benchmarks.tutorials import (
    SCHEMA_VERSION,
    BenchmarkConfig,
    ModelMetadata,
    SessionResult,
    summarize,
    write_artifacts,
)


def _result(model: str, tutorial: str, *, passed: bool) -> SessionResult:
    return SessionResult(
        schema_version=SCHEMA_VERSION,
        session_id=f"{tutorial}-{model}-01",
        model=model,
        tutorial=tutorial,
        run=1,
        world_seed=f"seed-{tutorial}-{model}",
        status="completed" if passed else "turn_limit",
        passed=passed,
        elapsed_seconds=10,
        turns=4,
        milestone_results=(("start", True), ("finish", passed)),
        valid_actions=3,
        rejected_actions=1,
        recovered_rejections=1,
        first_confusion_signal=None,
        repeated_blockers=(),
    )


def _source(path: Path) -> None:
    tutorials = ("apple", "bell", "clover")
    models = ("small", "large")
    results = tuple(
        _result(model, tutorial, passed=model == "large")
        for model in models
        for tutorial in tutorials
    )
    metadata = (
        ModelMetadata("small", parameter_count=4_000_000_000),
        ModelMetadata("large", parameter_count=20_000_000_000),
    )
    config = BenchmarkConfig(models=models, tutorials=tutorials, sessions=1, output=path)
    write_artifacts(
        config,
        summarize(results, metadata, tutorials),
        results,
        (),
        (),
        metadata,
    )


def test_build_report_writes_copy_ready_table_and_svg_diagrams(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "report"
    _source(source)

    build_report((source,), output, title="Test ladder")

    assert {path.name for path in output.iterdir()} == {
        "comparison-table.md",
        "diagrams",
        "report.md",
        "report.typ",
    }
    assert len(tuple((output / "diagrams").glob("*.svg"))) == 6
    assert len(tuple((output / "diagrams").glob("*-tabletop.png"))) == 3
    markdown = (output / "report.md").read_text(encoding="utf-8")
    assert "# Test ladder" in markdown
    assert f"[`source`]({source.resolve()})" in markdown
    assert "| `large` | 3/3 | 6/6 | 75.0% | 0.500 |" in markdown
    assert "{{" not in markdown
    heatmap = (output / "diagrams/apple-milestones.svg").read_text(encoding="utf-8")
    assert "Models reaching milestone" in heatmap
    assert "2/2" in heatmap
    typst = (output / "report.typ").read_text(encoding="utf-8")
    assert '#image("diagrams/apple-tabletop.png"' in typst
    assert '#image("diagrams/apple-map.svg"' in typst
    assert '#text("large")' in typst


def test_map_svg_contains_diegetic_clues_and_valid_root():
    svg = render_map_svg(TUTORIAL_MAPS["bell"])

    assert svg.startswith("<svg ")
    assert "persistent route board" in svg
    assert "most common missed destination" in svg
    assert svg.endswith("</svg>\n")


def test_report_source_manifest_stays_valid_json(tmp_path):
    source = tmp_path / "source"
    _source(source)

    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["benchmark"] == "ollama-tutorial-ladder"
