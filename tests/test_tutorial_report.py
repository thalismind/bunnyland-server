"""Tests for tutorial report and diagram generation."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from benchmarks.tutorial_comparison import SourceSelection, write_comparison
from benchmarks.tutorial_report import (
    TUTORIAL_MAPS,
    CohortInput,
    build_report,
    package_report,
    render_map_svg,
)
from benchmarks.tutorials import (
    MILESTONE_REPLACEMENTS,
    SCHEMA_VERSION,
    BenchmarkConfig,
    ModelMetadata,
    ModelResponseTrace,
    SessionResult,
    TurnTrace,
    summarize,
    write_artifacts,
)


def _result(model: str, tutorial: str, *, passed: bool, run: int = 1) -> SessionResult:
    return SessionResult(
        schema_version=SCHEMA_VERSION,
        session_id=f"{tutorial}-{model}-{run:02}",
        model=model,
        tutorial=tutorial,
        run=run,
        world_seed=f"seed-{tutorial}-{model}-{run}",
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
    responses = tuple(
        ModelResponseTrace(
            schema_version=SCHEMA_VERSION,
            session_id=result.session_id,
            turn=1,
            response={"prompt_eval_count": 100, "eval_count": 20},
        )
        for result in results
    )
    traces = tuple(
        TurnTrace(
            schema_version=SCHEMA_VERSION,
            session_id=result.session_id,
            turn=1,
            prompt="prompt",
            selected_tool="look",
            arguments={},
            decision_latency_seconds=2 if result.model == "small" else 4,
            candidate_actions=("look",),
            command_id="command",
            submission_accepted=True,
            submission_reason="",
            receipt_status="committed",
            receipt_reason="",
            decision_summary="look",
            policy_rejections=(),
            provider_error="",
            consecutive_repeat_count=0,
            repeat_guard_warning=False,
            result_events=(),
            milestones=("start",),
        )
        for result in results
    )
    write_artifacts(
        config,
        summarize(results, metadata, tutorials),
        results,
        traces,
        responses,
        metadata,
    )


def _threshold_source(path: Path) -> None:
    pass_counts = {
        "zero": 0,
        "possible": 1,
        "likely": 3,
        "consistent": 4,
    }
    results = tuple(
        _result(model, "apple", passed=run <= passes, run=run)
        for model, passes in pass_counts.items()
        for run in range(1, 6)
    )
    metadata = tuple(
        ModelMetadata(model, parameter_count=4_000_000_000) for model in pass_counts
    )
    config = BenchmarkConfig(
        models=tuple(pass_counts),
        tutorials=("apple",),
        sessions=5,
        output=path,
    )
    write_artifacts(
        config,
        summarize(results, metadata, ("apple",)),
        results,
        (),
        (),
        metadata,
    )


def _single_cell_source(path: Path) -> None:
    result = _result("large", "bell", passed=True)
    metadata = (ModelMetadata("large", parameter_count=20_000_000_000),)
    config = BenchmarkConfig(
        models=("large",),
        tutorials=("bell",),
        sessions=1,
        output=path,
    )
    write_artifacts(
        config,
        summarize((result,), metadata, ("bell",)),
        (result,),
        (),
        (),
        metadata,
    )


def _complete_source(path: Path) -> None:
    tutorials = ("apple", "bell", "clover")
    models = ("small", "large")
    results = tuple(
        _result(model, tutorial, passed=model == "large", run=run)
        for model in models
        for tutorial in tutorials
        for run in range(1, 6)
    )
    metadata = (
        ModelMetadata("small", parameter_count=4_000_000_000),
        ModelMetadata("large", parameter_count=20_000_000_000),
    )
    config = BenchmarkConfig(
        models=models,
        tutorials=tutorials,
        sessions=5,
        output=path,
    )
    write_artifacts(
        config,
        summarize(results, metadata, tutorials),
        results,
        (),
        (),
        metadata,
    )


def _complete_bell_source(path: Path) -> None:
    models = ("small", "large")
    results = tuple(
        _result(model, "bell", passed=model == "large", run=run)
        for model in models
        for run in range(1, 6)
    )
    metadata = (
        ModelMetadata("small", parameter_count=4_000_000_000),
        ModelMetadata("large", parameter_count=20_000_000_000),
    )
    config = BenchmarkConfig(
        models=models,
        tutorials=("bell",),
        sessions=5,
        output=path,
    )
    write_artifacts(
        config,
        summarize(results, metadata, ("bell",)),
        results,
        (),
        (),
        metadata,
    )


def _make_v1_coverage_gaps(path: Path) -> None:
    sessions_path = path / "sessions.jsonl"
    retained = []
    for line in sessions_path.read_text(encoding="utf-8").splitlines():
        session = json.loads(line)
        if session["model"] != "large":
            continue
        if session["tutorial"] == "bell" and session["run"] > 2:
            continue
        retained.append(session)
    sessions_path.write_text(
        "".join(json.dumps(session) + "\n" for session in retained),
        encoding="utf-8",
    )


def _as_schema_five_baseline(path: Path) -> None:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 5
    manifest.pop("milestone_replacements")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    session_path = path / "sessions.jsonl"
    old_by_tutorial = {
        "apple": "looked_in_apple_crossing",
        "bell": "looked_in_bell_green",
        "clover": "looked_in_clover_city_lobby",
    }
    sessions = []
    for line in session_path.read_text(encoding="utf-8").splitlines():
        session = json.loads(line)
        session["schema_version"] = 5
        session["milestone_results"][0][0] = old_by_tutorial[session["tutorial"]]
        sessions.append(session)
    session_path.write_text(
        "".join(json.dumps(session) + "\n" for session in sessions),
        encoding="utf-8",
    )


def _use_replacement_milestones(path: Path) -> None:
    session_path = path / "sessions.jsonl"
    new_by_tutorial = {
        "apple": "oriented_in_apple_crossing",
        "bell": "oriented_in_bell_green",
        "clover": "oriented_in_clover_city_lobby",
    }
    sessions = []
    for line in session_path.read_text(encoding="utf-8").splitlines():
        session = json.loads(line)
        session["milestone_results"][0][0] = new_by_tutorial[session["tutorial"]]
        sessions.append(session)
    session_path.write_text(
        "".join(json.dumps(session) + "\n" for session in sessions),
        encoding="utf-8",
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
        "token-stats.md",
    }
    assert len(tuple((output / "diagrams").glob("*.svg"))) == 6
    assert len(tuple((output / "diagrams").glob("*-tabletop.png"))) == 3
    markdown = (output / "report.md").read_text(encoding="utf-8")
    assert "# Test ladder" in markdown
    assert "`source` — 6 completed sessions" in markdown
    assert str(source.resolve()) not in markdown
    assert "720 tokens" in markdown
    assert "| `large` | 300 | 60 | 360 | 3/3 (100.0%) | 2.50 | 16,666.67 |" in markdown
    assert "| `large` | 3/3 | 6/6 | 75.0% | 0.500 |" in markdown
    assert "## Latency distribution" in markdown
    assert (
        "Across **6 scored decisions**, median end-to-end decision latency was **3.00s**"
        in markdown
    )
    assert (
        "| `large` | `Unlabeled` | `ollama-local` | 3 | 4.00 | 4.00 | 4.00 | "
        "3/3 | 0.2000 | 5.0000 |"
    ) in markdown
    assert "## Additional analytical questions" in markdown
    assert "### How broadly were cohort gains shared?" in markdown
    assert "### Where does tutorial progress break?" in markdown
    assert "### Are failures mostly invalid actions?" in markdown
    assert "### How sensitive is Qwen 3.6 35B to quantization?" in markdown
    assert "{{" not in markdown
    heatmap = (output / "diagrams/apple-milestones.svg").read_text(encoding="utf-8")
    assert "Models reaching milestone" in heatmap
    assert "2/2" in heatmap
    typst = (output / "report.typ").read_text(encoding="utf-8")
    assert '#image("diagrams/apple-tabletop.png"' in typst
    assert '#image("diagrams/apple-map.svg"' in typst
    assert '#text("large")' in typst
    assert 'set table(inset: 4pt, stroke: 0.5pt + rgb("ccd3dc"))' in typst
    assert "== Latency distribution" in typst
    assert "== Additional analytical questions" in typst
    assert "=== How broadly were cohort gains shared?" in typst
    assert str(source.resolve()) not in typst


def test_build_report_accepts_derived_comparison_artifact(tmp_path):
    source = tmp_path / "source"
    comparison = tmp_path / "comparison"
    output = tmp_path / "report"
    _source(source)
    write_comparison((SourceSelection(source),), comparison)

    build_report((comparison,), output, title="Combined ladder")

    markdown = (output / "report.md").read_text(encoding="utf-8")
    assert "# Combined ladder" in markdown
    assert "6 completed sessions" in markdown
    assert "| `large` | 3/3 |" in markdown


def test_report_classifies_possible_likely_and_consistent_passes(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "report"
    _threshold_source(source)

    build_report((source,), output, title="Thresholds")

    markdown = (output / "report.md").read_text(encoding="utf-8")
    assert "Possible pass means at least 1/5" in markdown
    assert "| `apple` | 4 | 3/4 | 2/4 | 1/4 |" in markdown
    typst = (output / "report.typ").read_text(encoding="utf-8")
    assert "== Difficulty distribution" in typst
    assert "[*Possible ≥1/5*]" in typst
    assert "[#text(\"3/4\")]" in typst


def test_cohort_difficulty_table_sorts_by_tutorial_then_version(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    third = tmp_path / "third"
    output = tmp_path / "report"
    _complete_source(first)
    _complete_source(second)
    _complete_source(third)

    build_report(
        (),
        output,
        title="Ordered cohorts",
        cohorts=(
            CohortInput("v1", first),
            CohortInput("v2", second),
            CohortInput("v3", third),
        ),
    )

    markdown = (output / "report.md").read_text(encoding="utf-8")
    difficulty = markdown.split("## Difficulty distribution", maxsplit=1)[1].split(
        "## Cohort deltas", maxsplit=1
    )[0]
    assert difficulty.index("| `v1` | `apple` |") < difficulty.index(
        "| `v2` | `apple` |"
    )
    assert difficulty.index("| `v2` | `apple` |") < difficulty.index(
        "| `v3` | `apple` |"
    )
    assert difficulty.index("| `v3` | `apple` |") < difficulty.index(
        "| `v1` | `bell` |"
    )


def test_cohort_report_distinguishes_gaps_from_not_applicable_cells(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    third = tmp_path / "third"
    output = tmp_path / "report"
    _complete_source(first)
    _complete_source(second)
    _complete_bell_source(third)
    _make_v1_coverage_gaps(first)

    build_report(
        (),
        output,
        title="Coverage gaps",
        cohorts=(
            CohortInput("v1", first),
            CohortInput("v2", second),
            CohortInput("v3", third),
        ),
    )

    markdown = (output / "report.md").read_text(encoding="utf-8")
    assert "## Data coverage gaps" in markdown
    assert "2 exact model identifiers" in markdown
    assert "Tutorials absent from a cohort's manifest are **not applicable (N/A)**" in markdown
    assert "| `v1` | `apple`, `bell`, `clover` | 12/30 | 2 | 1 | 3 | 0 |" in markdown
    assert "| `v2` | `apple`, `bell`, `clover` | 30/30 | 6 | 0 | 0 | 0 |" in markdown
    assert "| `v3` | `bell` | 10/10 | 2 | 0 | 0 | 4 |" in markdown
    large_gap = "| `large` | `v1` | 12/15 | 3 | `bell 2/5` |"
    small_gap = (
        "| `small` | `v1` | 0/15 | 15 | "
        "`apple 0/5`, `bell 0/5`, `clover 0/5` |"
    )
    assert large_gap in markdown
    assert small_gap in markdown
    assert markdown.index(large_gap) < markdown.index(small_gap)
    gap_table = markdown.split(
        "### Missing and partial in-scope coverage", maxsplit=1
    )[1].split("## Runtime and token use", maxsplit=1)[0]
    assert "| `large` | `v3` |" not in gap_table
    assert "| `small` | `v3` |" not in gap_table

    typst = (output / "report.typ").read_text(encoding="utf-8")
    assert "== Data coverage gaps" in typst
    assert '#text("10/10")' in typst
    assert '#text("4")' in typst
    assert '#text("bell 2/5")' in typst
    assert "not applicable (N/A), not missing" in typst


def test_cohort_report_separates_versions_and_styles_replacement_columns(tmp_path):
    baseline = tmp_path / "baseline"
    post_one = tmp_path / "post-one"
    post_two = tmp_path / "post-two"
    latest = tmp_path / "latest"
    output = tmp_path / "report"
    _source(baseline)
    _source(post_one)
    _source(post_two)
    _single_cell_source(latest)
    _as_schema_five_baseline(baseline)
    _use_replacement_milestones(post_one)
    _use_replacement_milestones(post_two)

    build_report(
        (),
        output,
        title="Before and after",
        cohorts=(
            CohortInput("v1", baseline),
            CohortInput("v2", post_one),
            CohortInput("v2", post_two),
            CohortInput("v3", latest),
        ),
    )

    markdown = (output / "report.md").read_text(encoding="utf-8")
    assert "| Cohort | Model | Passes |" in markdown
    assert "| `v1` | `large` |" in markdown
    assert "| `v2` | `large` |" in markdown
    assert "`v2` / `post-one`" in markdown
    assert "`v2` / `post-two`" in markdown
    assert "## Cohort deltas" in markdown
    assert "| Tutorial | Transition | Shared models | Improved | Tied | Regressed |" in markdown
    assert "| `v1 → v2` | `apple` | 1/2 (50.0%) | 2/4 (50.0%) | +0.0 pp |" in markdown
    assert "| `v2 → v3` | `small` | `bell` | 0/2 (0.0%) | — | — |" in markdown
    aggregate_deltas = markdown.split("### Tutorial totals", maxsplit=1)[1].split(
        "### Matching model/tutorial cells", maxsplit=1
    )[0]
    assert aggregate_deltas.index(
        "| `v1 → v2` | `bell` |"
    ) < aggregate_deltas.index("| `v2 → v3` | `bell` |")
    assert aggregate_deltas.index(
        "| `v2 → v3` | `bell` |"
    ) < aggregate_deltas.index("| `v1 → v2` | `clover` |")
    for table_name in ("comparison-table.md", "token-stats.md"):
        table = (output / table_name).read_text(encoding="utf-8")
        assert table.index("| `v1` | `large` |") < table.index(
            "| `v2` | `large` |"
        )
        assert table.index("| `v2` | `large` |") < table.index(
            "| `v3` | `large` |"
        )
        assert table.index("| `v3` | `large` |") < table.index(
            "| `v1` | `small` |"
        )
    model_deltas = markdown.split("### Matching model/tutorial cells", maxsplit=1)[1]
    assert model_deltas.index(
        "| `v1 → v2` | `large` | `apple` |"
    ) < model_deltas.index("| `v1 → v2` | `large` | `bell` |")
    assert model_deltas.index(
        "| `v1 → v2` | `large` | `bell` |"
    ) < model_deltas.index("| `v2 → v3` | `large` | `bell` |")
    assert model_deltas.index(
        "| `v2 → v3` | `large` | `bell` |"
    ) < model_deltas.index("| `v1 → v2` | `large` | `clover` |")
    assert model_deltas.index(
        "| `v1 → v2` | `large` | `clover` |"
    ) < model_deltas.index("| `v1 → v2` | `small` | `apple` |")
    heatmap = (output / "diagrams/apple-milestones.svg").read_text(encoding="utf-8")
    assert "large / v1" in heatmap
    assert "large / v2" in heatmap
    assert heatmap.index("large / v1") < heatmap.index("large / v2")
    assert heatmap.index("large / v2") < heatmap.index("small / v1")
    assert "replaced-column" in heatmap
    assert "replacement-column" in heatmap
    assert "opacity:.72" in heatmap
    assert "saturate(.35)" in heatmap
    assert "stroke-width:4" in heatmap
    assert "looked_in_apple_crossing → oriented_in_apple_crossing" in heatmap
    assert "—" in heatmap
    assert "Completed sessions · ColorBrewer RdYlGn" in heatmap
    for color in ("#d73027", "#fc8d59", "#fee08b", "#d9ef8b", "#91cf60", "#1a9850"):
        assert color in heatmap
    typst = (output / "report.typ").read_text(encoding="utf-8")
    assert "== Cohort deltas" in typst
    assert '#text("v1 → v2")' in typst
    assert '#text("—")' in typst


def test_non_cohort_report_rejects_mixed_schema_versions(tmp_path):
    baseline = tmp_path / "baseline"
    current = tmp_path / "current"
    _source(baseline)
    _source(current)
    _as_schema_five_baseline(baseline)

    with pytest.raises(ValueError, match="use --cohort"):
        build_report((baseline, current), tmp_path / "report", title="Mixed")


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
    assert manifest["milestone_replacements"] == MILESTONE_REPLACEMENTS


def test_package_report_includes_only_shareable_report_files(tmp_path):
    report = tmp_path / "tutorial-report"
    output = tmp_path / "tutorial-report.zip"
    _source(tmp_path / "source")
    build_report((tmp_path / "source",), report, title="Test ladder")
    (report / "report.pdf").write_bytes(b"%PDF-1.7\n")
    (report / "private-traces.jsonl").write_text("private", encoding="utf-8")

    package_report(report, output)

    with zipfile.ZipFile(output) as bundle:
        names = set(bundle.namelist())
    assert "tutorial-report/report.md" in names
    assert "tutorial-report/report.pdf" in names
    assert "tutorial-report/token-stats.md" in names
    assert "tutorial-report/private-traces.jsonl" not in names
    assert "tutorial-report/report.typ" not in names
