"""Tests for combining split tutorial benchmark batches."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.tutorial_comparison import (
    ComparisonError,
    SourceSelection,
    write_comparison,
)
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
        elapsed_seconds=10.0,
        turns=2,
        milestone_results=(("done", passed),),
        valid_actions=2,
        rejected_actions=0,
        recovered_rejections=0,
        first_confusion_signal=None,
        repeated_blockers=(),
    )


def _source(path: Path, model: str, *, passed: bool) -> None:
    tutorials = ("apple", "bell", "clover")
    config = BenchmarkConfig(models=(model,), tutorials=tutorials, sessions=1, output=path)
    metadata = (ModelMetadata(model, parameter_count=1_000_000_000),)
    results = tuple(_result(model, tutorial, passed=passed) for tutorial in tutorials)
    write_artifacts(
        config,
        summarize(results, metadata, tutorials),
        results,
        (),
        (),
        metadata,
    )


def test_comparison_combines_balanced_sources_and_retains_provenance(tmp_path):
    small = tmp_path / "small"
    large = tmp_path / "large"
    output = tmp_path / "comparison"
    _source(small, "small", passed=False)
    _source(large, "large", passed=True)

    write_comparison(
        (SourceSelection(small), SourceSelection(large)),
        output,
        notes=("Timing caveat.",),
    )

    assert {path.name for path in output.iterdir()} == {
        "manifest.json",
        "report.md",
        "sessions.jsonl",
        "summary.json",
    }
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["full_ladder_ranking"][0]["model"] == "large"
    assert summary["incomplete_attempts"] == []
    report = (output / "report.md").read_text(encoding="utf-8")
    assert "## Full ladder" in report
    assert "## Evidence sources" in report
    assert str(small.resolve()) in report
    assert "- Timing caveat." in report
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sources"] == [
        {"path": str(small.resolve()), "selected_models": []},
        {"path": str(large.resolve()), "selected_models": []},
    ]
    assert manifest["notes"] == ["Timing caveat."]


def test_comparison_rejects_an_unbalanced_matrix(tmp_path):
    source = tmp_path / "source"
    _source(source, "model", passed=False)
    sessions = (source / "sessions.jsonl").read_text(encoding="utf-8").splitlines()
    (source / "sessions.jsonl").write_text("\n".join(sessions[:-1]) + "\n", encoding="utf-8")

    with pytest.raises(ComparisonError, match="missing cells"):
        write_comparison((SourceSelection(source),), tmp_path / "comparison")


def test_comparison_can_keep_first_n_sessions_per_cell(tmp_path):
    source = tmp_path / "source"
    _source(source, "model", passed=False)
    sessions = (source / "sessions.jsonl").read_text(encoding="utf-8")
    (source / "sessions.jsonl").write_text(sessions + sessions, encoding="utf-8")
    output = tmp_path / "comparison"

    write_comparison(
        (SourceSelection(source),), output, sessions_per_cell=1
    )

    combined_sessions = (output / "sessions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(combined_sessions) == 3
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert len(summary["excluded_completed_sessions"]) == 3
    report = (output / "report.md").read_text(encoding="utf-8")
    assert "Excluded completed sessions: 3" in report


def test_comparison_deduplicates_incomplete_attempts_from_reused_source(tmp_path):
    source = tmp_path / "source"
    _source(source, "model", passed=False)
    trace = '{"session_id":"interrupted","turn":1}\n'
    (source / "traces.jsonl").write_text(trace, encoding="utf-8")
    (source / "responses.jsonl").write_text(trace, encoding="utf-8")
    output = tmp_path / "comparison"

    write_comparison(
        (SourceSelection(source), SourceSelection(source)),
        output,
        sessions_per_cell=1,
    )

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert len(summary["incomplete_attempts"]) == 1
