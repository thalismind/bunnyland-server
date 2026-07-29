"""Tests for tutorial report and diagram generation."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from benchmarks.tutorial_comparison import SourceSelection, write_comparison
from benchmarks.tutorial_report import (
    MODEL_ARCHITECTURES,
    TUTORIAL_MAPS,
    CohortInput,
    FineTuneComparisonRow,
    KimiFamilyRow,
    LabeledResult,
    LatencyRow,
    ParameterScatterMetadata,
    StudyFamilyRow,
    _fine_tune_comparison_rows,
    _spearman_rho,
    build_report,
    package_report,
    render_family_progression_svg,
    render_fine_tune_comparison_svg,
    render_kimi_family_svg,
    render_latency_provider_svg,
    render_map_svg,
    render_parameter_scatter_svg,
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


def _frontier_source(path: Path) -> None:
    models = (
        "anthropic/claude-haiku-4.5",
        "anthropic/claude-opus-5",
        "openai/gpt-5.6-luna",
        "openai/gpt-5.6-sol",
    )
    results = tuple(
        _result(
            model,
            "bell",
            passed=model != "anthropic/claude-opus-5" or run == 1,
            run=run,
        )
        for model in models
        for run in range(1, 3)
    )
    metadata = tuple(ModelMetadata(model) for model in models)
    config = BenchmarkConfig(
        models=models,
        tutorials=("bell",),
        sessions=2,
        provider="openrouter",
        output=path,
    )
    responses = tuple(
        ModelResponseTrace(
            schema_version=SCHEMA_VERSION,
            session_id=result.session_id,
            turn=1,
            response={
                "usage": {
                    "prompt_tokens": 100_000,
                    "completion_tokens": 10_000,
                    "prompt_tokens_details": {
                        "cached_tokens": 80_000,
                        "cache_write_tokens": 10_000,
                    },
                }
            },
        )
        for result in results
    )
    write_artifacts(
        config,
        summarize(results, metadata, ("bell",)),
        results,
        (),
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
        "evidence-sources.md",
        "paper-data.json",
        "report.md",
        "report.typ",
        "token-stats.md",
    }
    assert len(tuple((output / "diagrams").glob("*.svg"))) == 13
    assert len(tuple((output / "diagrams").glob("*-tabletop.png"))) == 3
    markdown = (output / "report.md").read_text(encoding="utf-8")
    assert "# Test ladder" in markdown
    assert "## Evidence sources" not in markdown
    assert str(source.resolve()) not in markdown
    evidence_sources = (output / "evidence-sources.md").read_text(encoding="utf-8")
    assert "`source` — 6 completed sessions" in evidence_sources
    assert str(source.resolve()) not in evidence_sources
    assert "720 tokens" in markdown
    assert "| `large` | 300 | 60 | 360 | 2.50 | 16,666.67 |" in markdown
    runtime_table = markdown.split("## Runtime and token use", maxsplit=1)[1].split(
        "## Performance leaders", maxsplit=1
    )[0]
    assert "Usage coverage" not in runtime_table
    assert "| `large` | 3/3 | 6/6 | 75.0% | 0.500 |" in markdown
    assert "## Performance leaders" in markdown
    assert "### Top 5 fastest models" in markdown
    assert (
        "| 1 | `small` | `ollama-local` | 3 | 2.00 | 2.00 | 10.0000 |"
        in markdown
    )
    assert "### Top 5 most token-efficient models" in markdown
    assert "| 1 | `large` | 6/6 | 360 | 16,666.67 |" in markdown
    leaderboard = markdown.split("## Performance leaders", maxsplit=1)[1].split(
        "## Latency distribution", maxsplit=1
    )[0]
    assert "Usage coverage" not in leaderboard
    assert "## Latency distribution" in markdown
    assert (
        "Across **6 scored decisions**, median end-to-end decision latency was **3.00s**"
        in markdown
    )
    assert "### Local versus cloud latency" in markdown
    assert "| Local | 6 | 3.00 | 4.00 | 4.00 | 4.00 |" in markdown
    assert "diagrams/latency-provider-percentiles-chart.svg" in markdown
    assert (
        "| `large` | `Unlabeled` | `ollama-local` | 3 | 4.00 | 4.00 | 4.00 | "
        "5.0000 |"
    ) in markdown
    latency_section = markdown.split("## Latency distribution", maxsplit=1)[1].split(
        "## Model comparison", maxsplit=1
    )[0]
    assert "Token coverage" not in latency_section
    assert "Sec/output token" not in markdown
    paper_data = json.loads((output / "paper-data.json").read_text(encoding="utf-8"))
    assert paper_data["schema_version"] == 1
    assert paper_data["completed_sessions"] == 6
    assert paper_data["total_tokens"] == 720
    assert paper_data["latest_cohort_by_tutorial"] == {
        "apple": "Unlabeled",
        "bell": "Unlabeled",
        "clover": "Unlabeled",
    }
    assert paper_data["latency"]["provider_rows"][0]["provider"] == "Local"
    assert "## Additional analytical questions" in markdown
    assert "### How broadly were cohort gains shared?" in markdown
    assert "### Where does tutorial progress break?" in markdown
    assert "### Are failures mostly invalid actions?" in markdown
    assert "### How sensitive is Qwen 3.6 35B to quantization?" in markdown
    assert "## Cohort charts" in markdown
    assert "diagrams/tutorial-success-trend-chart.svg" in markdown
    assert "diagrams/threshold-attainment-chart.svg" in markdown
    assert "## Model size and milestone completion" in markdown
    assert "diagrams/apple-parameter-milestone-scatter-chart.svg" in markdown
    assert "diagrams/bell-parameter-milestone-scatter-chart.svg" in markdown
    assert "diagrams/clover-parameter-milestone-scatter-chart.svg" in markdown
    assert "{{" not in markdown
    heatmap = (output / "diagrams/apple-milestones.svg").read_text(encoding="utf-8")
    assert "Models reaching milestone" in heatmap
    assert "2/2" in heatmap
    typst = (output / "report.typ").read_text(encoding="utf-8")
    assert "== Evidence sources" not in typst
    assert '#image("diagrams/apple-tabletop.png"' in typst
    assert '#image("diagrams/apple-map.svg"' in typst
    assert '#image("diagrams/tutorial-success-trend-chart.svg"' in typst
    assert '#image("diagrams/threshold-attainment-chart.svg"' in typst
    assert '#image("diagrams/apple-parameter-milestone-scatter-chart.svg"' in typst
    assert '#image("diagrams/latency-provider-percentiles-chart.svg"' in typst
    assert '#text("large")' in typst
    assert 'set table(inset: 4pt, stroke: 0.5pt + rgb("ccd3dc"))' in typst
    assert "== Latency distribution" in typst
    assert "== Performance leaders" in typst
    assert "=== Top 5 fastest models" in typst
    assert "=== Top 5 most token-efficient models" in typst
    assert "== Additional analytical questions" in typst
    assert "=== How broadly were cohort gains shared?" in typst
    assert str(source.resolve()) not in typst


def test_latency_provider_chart_splits_local_and_cloud():
    rows = (
        LatencyRow(
            cohort=None,
            model="Local",
            provider="ollama-local",
            decisions=100,
            median_seconds=4,
            p95_seconds=20,
            p99_seconds=50,
            maximum_seconds=80,
            token_decisions=0,
            output_tokens=0,
            token_seconds=0,
        ),
        LatencyRow(
            cohort=None,
            model="Cloud",
            provider="ollama-cloud, openrouter",
            decisions=200,
            median_seconds=2,
            p95_seconds=10,
            p99_seconds=30,
            maximum_seconds=60,
            token_decisions=0,
            output_tokens=0,
            token_seconds=0,
        ),
    )

    svg = render_latency_provider_svg(rows)

    assert "Decision latency by execution location" in svg
    assert "Local" in svg
    assert "100 decisions" in svg
    assert "median 4.00s · p95 20.00s · p99 50.00s" in svg
    assert "Cloud" in svg
    assert "200 decisions" in svg
    assert "seconds, log scale" in svg


def test_build_report_accepts_derived_comparison_artifact(tmp_path):
    source = tmp_path / "source"
    comparison = tmp_path / "comparison"
    output = tmp_path / "report"
    _source(source)
    write_comparison((SourceSelection(source),), comparison)

    build_report((comparison,), output, title="Combined ladder")

    markdown = (output / "report.md").read_text(encoding="utf-8")
    evidence_sources = (output / "evidence-sources.md").read_text(encoding="utf-8")
    assert "# Combined ladder" in markdown
    assert "6 completed sessions" in evidence_sources
    assert "| `large` | 3/3 |" in markdown


def test_frontier_report_prices_cached_tokens_and_recommends_luna(tmp_path):
    source = tmp_path / "frontier"
    output = tmp_path / "report"
    _frontier_source(source)

    build_report((source,), output, title="Frontier preview")

    markdown = (output / "report.md").read_text(encoding="utf-8")
    assert "## Frontier API cost and recommendation" in markdown
    assert "use **GPT-5.6 Luna**" in markdown
    assert "avoid **Claude Opus 5**" in markdown
    assert "preliminary" not in markdown
    assert "| `GPT-5.6 Luna` | 2/2 (100.0%) | 4/4 | $0.18 |" in markdown
    assert "| `Claude Opus 5` | 1/2 (50.0%) | 3/4 | $0.81 |" in markdown
    assert "two sessions per applicable model/version/tutorial cell" in markdown
    chart = (
        output / "diagrams" / "frontier-api-cost-performance-chart.svg"
    ).read_text(encoding="utf-8")
    for model in (
        "anthropic/claude-haiku-4.5",
        "anthropic/claude-opus-5",
        "openai/gpt-5.6-luna",
        "openai/gpt-5.6-sol",
    ):
        assert f'data-model="{model}"' in chart
    assert "USD, linear scale" in chart
    assert "log scale" not in chart
    assert "recommended" in chart
    typst = (output / "report.typ").read_text(encoding="utf-8")
    assert "== Frontier API cost and recommendation" in typst
    assert "about 25" not in typst
    assert '#image("diagrams/frontier-api-cost-performance-chart.svg"' in typst


def test_report_classifies_possible_likely_and_consistent_passes(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "report"
    _threshold_source(source)

    build_report((source,), output, title="Thresholds")

    markdown = (output / "report.md").read_text(encoding="utf-8")
    assert "Possible pass means at least 1/5" in markdown
    assert "## Tutorial acceptance policy" in markdown
    assert (
        "| `apple` | Many or most models reach likely pass (at least 3/5). |"
        in markdown
    )
    assert "| `clover` | Retain a meaningful spread" in markdown
    assert "Primary filter point." in markdown
    assert "| `apple` | 4 | 3/4 | 2/4 | 1/4 |" in markdown
    typst = (output / "report.typ").read_text(encoding="utf-8")
    assert "== Tutorial acceptance policy" in typst
    assert '[#text("Primary filter point.")]' in typst
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
    success_chart = (output / "diagrams/tutorial-success-trend-chart.svg").read_text(
        encoding="utf-8"
    )
    assert "Session success rate" in success_chart
    assert 'data-tutorial="apple"' in success_chart
    assert "50.0%" in success_chart
    assert success_chart.index(">v1</text>") < success_chart.index(">v2</text>")
    assert success_chart.index(">v2</text>") < success_chart.index(">v3</text>")
    threshold_chart = (output / "diagrams/threshold-attainment-chart.svg").read_text(
        encoding="utf-8"
    )
    assert "Share of complete model cells" in threshold_chart
    assert "Possible ≥1/5" in threshold_chart
    assert 'data-threshold="likely_passes"' in threshold_chart
    assert "1/2" in threshold_chart


def test_parameter_scatter_uses_latest_applicable_tutorial_cohort(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    latest_bell = tmp_path / "latest-bell"
    output = tmp_path / "report"
    _complete_source(first)
    _complete_source(second)
    _complete_bell_source(latest_bell)

    build_report(
        (),
        output,
        title="Latest applicable cohorts",
        cohorts=(
            CohortInput("v1", first),
            CohortInput("v2", second),
            CohortInput("v3", latest_bell),
        ),
    )

    apple = (
        output / "diagrams" / "apple-parameter-milestone-scatter-chart.svg"
    ).read_text(encoding="utf-8")
    bell = (
        output / "diagrams" / "bell-parameter-milestone-scatter-chart.svg"
    ).read_text(encoding="utf-8")
    clover = (
        output / "diagrams" / "clover-parameter-milestone-scatter-chart.svg"
    ).read_text(encoding="utf-8")

    assert "Latest applicable cohort: v2" in apple
    assert "Latest applicable cohort: v3" in bell
    assert "Latest applicable cohort: v2" in clover
    assert 'data-model="small"' in apple
    assert 'data-parameters="4000000000"' in apple
    assert 'data-milestone-rate="0.500000"' in apple
    assert "Total architecture parameters (log scale)" in apple
    assert "Milestone completion (log shortfall scale)" in apple
    assert "−log10(milestone shortfall)" in apple
    assert "Qwen" not in apple


def test_parameter_scatter_explains_unpublished_sizes():
    results = (
        LabeledResult("v1", _result("small", "apple", passed=True)),
        LabeledResult("v1", _result("undisclosed", "apple", passed=True)),
    )
    metadata = {
        ("v1", "small"): ParameterScatterMetadata(
            display_name="Small",
            parameter_count=4_000_000_000,
            provider="Local",
        ),
    }

    svg = render_parameter_scatter_svg(results, "apple", metadata)

    assert "No published architecture total was available for 1 model(s)" in svg
    assert "sizes were not inferred" in svg


def test_parameter_scatter_catalogue_covers_full_study_roster():
    assert len(MODEL_ARCHITECTURES) == 34
    assert (
        MODEL_ARCHITECTURES[
            "hf.co/bartowski/NousResearch_Hermes-4-14B-GGUF:Q8_0"
        ].total_parameters
        == 14_800_000_000
    )
    assert (
        MODEL_ARCHITECTURES["deepseek-v4-flash:cloud"].total_parameters
        == 284_000_000_000
    )
    assert MODEL_ARCHITECTURES["minimax-m3:cloud"].total_parameters == 428_000_000_000
    assert (
        MODEL_ARCHITECTURES["deepseek-v4-pro:cloud"].total_parameters
        == 1_600_000_000_000
    )
    assert (
        MODEL_ARCHITECTURES[
            "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:Q8_0"
        ].total_parameters
        == 35_000_000_000
    )
    assert MODEL_ARCHITECTURES["moonshotai/kimi-k3"].total_parameters == 2_800_000_000_000
    assert (
        MODEL_ARCHITECTURES[
            "hf.co/HauhauCS/Gemma4-31B-QAT-Uncensored-HauhauCS-Balanced-MTP:Q4_K_M"
        ].display_name
        == "Gemma 4 31B HauhauCS Q4"
    )
    assert (
        MODEL_ARCHITECTURES[
            "LESSTHANSUPER/RP-INK-Qwen2.5-32b:Q5_K_S"
        ].display_name
        == "Qwen 2.5 32B RP-INK Q5"
    )


def test_parameter_scatter_key_fits_all_entries_and_truncates_long_names():
    models = tuple(f"model-{index:02}" for index in range(1, 29))
    long_name = (
        "hf.co/Example/An-Extremely-Long-Roleplaying-Model-Name-With-Quant:Q8_0"
    )
    results = tuple(
        LabeledResult("v2", _result(model, "apple", passed=True))
        for model in models
    )
    metadata = {
        ("v2", model): ParameterScatterMetadata(
            display_name=long_name if index == len(models) else f"Model {index}",
            parameter_count=(index + 3) * 1_000_000_000,
            provider="Local" if index % 2 else "Cloud",
        )
        for index, model in enumerate(models, start=1)
    }

    svg = render_parameter_scatter_svg(results, "apple", metadata)
    root = ElementTree.fromstring(svg)
    key_entries = tuple(
        element
        for element in root.iter()
        if element.attrib.get("class") == "key"
    )

    assert len(key_entries) == 28
    assert max(float(element.attrib["x"]) for element in key_entries) < float(
        root.attrib["width"]
    )
    assert any((element.text or "").startswith("28. ") for element in key_entries)
    assert all(long_name not in (element.text or "") for element in key_entries)
    assert any("…" in (element.text or "") for element in key_entries)
    assert long_name in svg


def test_kimi_family_chart_compares_capability_latency_and_efficiency():
    rows = (
        KimiFamilyRow(
            model="kimi-k2.5",
            display_name="Kimi K2.5",
            provider="Ollama Cloud",
            sessions=40,
            passes=31,
            milestone_hits=400,
            milestone_possible=440,
            median_latency_seconds=3.5,
            total_tokens=20_000_000,
        ),
        KimiFamilyRow(
            model="kimi-k2.7-code:cloud",
            display_name="Kimi K2.7 Code¹",
            provider="Ollama Cloud",
            sessions=40,
            passes=38,
            milestone_hits=430,
            milestone_possible=440,
            median_latency_seconds=1.5,
            total_tokens=15_000_000,
        ),
        KimiFamilyRow(
            model="moonshotai/kimi-k3",
            display_name="Kimi K3",
            provider="OpenRouter",
            sessions=40,
            passes=33,
            milestone_hits=420,
            milestone_possible=440,
            median_latency_seconds=2.5,
            total_tokens=18_000_000,
        ),
    )

    svg = render_kimi_family_svg(rows)

    assert "Capability" in svg
    assert "Median latency" in svg
    assert "Token efficiency" in svg
    assert "code-specialized branch" in svg
    assert "K3 used OpenRouter" in svg
    for row in rows:
        assert f'data-model="{row.model}"' in svg


def test_family_progression_uses_canonical_display_names():
    rows = tuple(
        StudyFamilyRow(
            family="Qwen",
            model=model,
            display_name=display_name,
            order=order,
            tutorial=tutorial,
            cohort="v2",
            sessions=5,
            passes=passes,
            milestone_hits=40 + passes,
            milestone_possible=50,
        )
        for tutorial in ("apple", "bell", "clover")
        for model, display_name, order, passes in (
            ("qwen3.5:9b", "Qwen 3.5 9B", 0, 3),
            ("qwen/qwen3.7-plus", "Qwen 3.7 Plus", 1, 5),
        )
    )

    svg = render_family_progression_svg("Qwen", rows)

    assert "Qwen 3.5 9B" in svg
    assert "Qwen 3.7 Plus" in svg
    assert "qwen/qwen3.7-plus" not in svg
    assert "Lines organize tested releases" in svg


def test_fine_tune_comparison_requires_matched_complete_cells():
    base_model = "qwen3.5:4b"
    tuned_model = (
        "hf.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive:Q4_K_M"
    )
    results = tuple(
        LabeledResult(
            "v2",
            _result(
                model,
                "apple",
                passed=run <= passes,
                run=run,
            ),
        )
        for model, passes in ((base_model, 3), (tuned_model, 4))
        for run in range(1, 6)
    )

    rows = _fine_tune_comparison_rows(results)

    assert len(rows) == 1
    assert rows[0].label == "Qwen 3.5 4B HauhauCS"
    assert rows[0].base_passes == 3
    assert rows[0].tuned_passes == 4
    assert "Qwen 3.5 4B HauhauCS" in render_fine_tune_comparison_svg(rows)


def test_fine_tune_chart_excludes_partial_cells():
    row = FineTuneComparisonRow(
        label="Qwen 3.5 4B HauhauCS",
        cohort="v2",
        tutorial="apple",
        base_model="base",
        tuned_model="tuned",
        base_sessions=5,
        tuned_sessions=4,
        base_passes=3,
        tuned_passes=4,
        base_milestone_rate=0.7,
        tuned_milestone_rate=0.8,
        base_validity=0.9,
        tuned_validity=0.9,
        base_milestones_per_turn=0.2,
        tuned_milestones_per_turn=0.2,
        caveat="",
    )

    svg = render_fine_tune_comparison_svg((row,))

    assert "No matched complete five-session cells" in svg


def test_spearman_handles_ties_and_undefined_inputs():
    assert _spearman_rho((1, 2, 3, 4), (10, 20, 30, 40)) == pytest.approx(1)
    assert _spearman_rho((1, 2, 3, 4), (40, 30, 20, 10)) == pytest.approx(-1)
    assert _spearman_rho((1, 2), (3, 4)) is None
    assert _spearman_rho((1, 1, 1), (1, 2, 3)) is None


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
    threshold_chart = (output / "diagrams/threshold-attainment-chart.svg").read_text(
        encoding="utf-8"
    )
    assert "—" in threshold_chart


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
    evidence_sources = (output / "evidence-sources.md").read_text(encoding="utf-8")
    assert "| Cohort | Model | Passes |" in markdown
    assert "| `v1` | `large` |" in markdown
    assert "| `v2` | `large` |" in markdown
    assert "`v2` / `post-one`" in evidence_sources
    assert "`v2` / `post-two`" in evidence_sources
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
    (report / "diagrams" / "stale-map.png").write_bytes(b"stale")

    package_report(report, output)

    with zipfile.ZipFile(output) as bundle:
        names = set(bundle.namelist())
    assert "tutorial-report/report.md" in names
    assert "tutorial-report/report.pdf" in names
    assert "tutorial-report/token-stats.md" in names
    assert "tutorial-report/evidence-sources.md" in names
    assert "tutorial-report/paper-data.json" in names
    assert "tutorial-report/private-traces.jsonl" not in names
    assert "tutorial-report/report.typ" not in names
    assert "tutorial-report/diagrams/stale-map.png" not in names
