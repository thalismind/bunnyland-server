"""Combine completed tutorial benchmark batches into one comparison report."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from benchmarks.tutorials import (
    SCHEMA_VERSION,
    TUTORIAL_NAMES,
    BenchmarkConfig,
    ModelMetadata,
    Provider,
    SessionResult,
    ThinkingLevel,
    render_report,
    summarize,
)


class ComparisonError(RuntimeError):
    """The requested artifact sets cannot form a fair comparison."""


@dataclass(frozen=True)
class SourceManifest:
    schema_version: int
    benchmark: str
    provider: Provider
    host: str
    models: tuple[ModelMetadata, ...]
    tutorials: tuple[str, ...]
    sessions_per_model_tutorial: int
    session_timeout_seconds: float
    turn_limit: int
    thinking: ThinkingLevel | None = None
    temperature: float | None = None
    log_thinking: bool = False
    repeat_command_guard: bool = False


@dataclass(frozen=True)
class TraceIdentity:
    session_id: str
    turn: int


@dataclass(frozen=True)
class ResponseIdentity:
    session_id: str
    turn: int


@dataclass(frozen=True)
class IncompleteAttempt:
    source: str
    session_id: str
    trace_rows: int
    response_rows: int


@dataclass(frozen=True)
class LoadedSource:
    path: Path
    selected_models: tuple[str, ...]
    manifest: SourceManifest
    results: tuple[SessionResult, ...]
    trace_rows: int
    response_rows: int
    incomplete_attempts: tuple[IncompleteAttempt, ...]


def _read_json[T](path: Path, item_type: type[T]) -> T:
    try:
        return TypeAdapter(item_type).validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise ComparisonError(f"could not read {path}: {exc}") from exc


def _read_jsonl[T](path: Path, item_type: type[T]) -> tuple[T, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        adapter = TypeAdapter(item_type)
        return tuple(adapter.validate_json(line) for line in lines if line.strip())
    except (OSError, ValidationError) as exc:
        raise ComparisonError(f"could not read {path}: {exc}") from exc


@dataclass(frozen=True)
class SourceSelection:
    path: Path
    models: tuple[str, ...] = ()


def load_source(selection: SourceSelection) -> LoadedSource:
    path = selection.path
    manifest = _read_json(path / "manifest.json", SourceManifest)
    if manifest.benchmark != "ollama-tutorial-ladder":
        raise ComparisonError(f"{path} is not a tutorial-ladder benchmark")
    all_results = _read_jsonl(path / "sessions.jsonl", SessionResult)
    unknown_models = sorted(set(selection.models) - {item.model for item in manifest.models})
    if unknown_models:
        raise ComparisonError(
            f"{path} does not contain model metadata for {', '.join(unknown_models)}"
        )
    results = tuple(
        result
        for result in all_results
        if not selection.models or result.model in selection.models
    )
    traces = _read_jsonl(path / "traces.jsonl", TraceIdentity)
    responses = _read_jsonl(path / "responses.jsonl", ResponseIdentity)
    completed_ids = {result.session_id for result in all_results}
    trace_counts = Counter(trace.session_id for trace in traces)
    response_counts = Counter(response.session_id for response in responses)
    incomplete = tuple(
        IncompleteAttempt(
            source=str(path),
            session_id=session_id,
            trace_rows=trace_counts[session_id],
            response_rows=response_counts[session_id],
        )
        for session_id in sorted(trace_counts.keys() - completed_ids)
    )
    return LoadedSource(
        path=path,
        selected_models=selection.models,
        manifest=manifest,
        results=results,
        trace_rows=len(traces),
        response_rows=len(responses),
        incomplete_attempts=incomplete,
    )


def _ensure_compatible(sources: Sequence[LoadedSource]) -> SourceManifest:
    first = sources[0].manifest
    settings = (
        "provider",
        "session_timeout_seconds",
        "turn_limit",
        "thinking",
        "temperature",
        "log_thinking",
        "repeat_command_guard",
    )
    for source in sources[1:]:
        for name in settings:
            if getattr(source.manifest, name) != getattr(first, name):
                raise ComparisonError(f"source artifacts disagree on {name}")
    return first


def _metadata(sources: Sequence[LoadedSource], models: Sequence[str]) -> tuple[ModelMetadata, ...]:
    by_model: dict[str, ModelMetadata] = {}
    for source in sources:
        for item in source.manifest.models:
            previous = by_model.get(item.model)
            if previous is not None and previous != item:
                raise ComparisonError(f"source artifacts disagree on metadata for {item.model}")
            by_model[item.model] = item
    missing = [model for model in models if model not in by_model]
    if missing:
        raise ComparisonError(f"missing model metadata: {', '.join(missing)}")
    return tuple(by_model[model] for model in models)


def _ordered_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: Sequence[object]) -> None:
    path.write_text(
        "".join(json.dumps(value, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )


def write_comparison(selections: Sequence[SourceSelection], output: Path) -> None:
    if not selections:
        raise ComparisonError("at least one --input artifact directory is required")
    resolved = tuple(
        SourceSelection(selection.path.resolve(), selection.models)
        for selection in selections
    )
    sources = tuple(load_source(selection) for selection in resolved)
    results = tuple(result for source in sources for result in source.results)
    if not results:
        raise ComparisonError("source artifacts contain no completed sessions")
    models = _ordered_unique(tuple(result.model for result in results))
    tutorials = tuple(
        tutorial
        for tutorial in TUTORIAL_NAMES
        if any(tutorial in source.manifest.tutorials for source in sources)
    )
    counts = Counter((result.model, result.tutorial) for result in results)
    expected_cells = {(model, tutorial) for model in models for tutorial in tutorials}
    missing_cells = sorted(expected_cells - counts.keys())
    if missing_cells:
        rendered = ", ".join(f"{model}/{tutorial}" for model, tutorial in missing_cells)
        raise ComparisonError(f"comparison matrix has missing cells: {rendered}")
    session_counts = {counts[cell] for cell in expected_cells}
    if len(session_counts) != 1:
        raise ComparisonError("comparison matrix has unequal sessions per model/tutorial")
    sessions = next(iter(session_counts))
    settings = _ensure_compatible(sources)
    metadata = _metadata(sources, models)
    config = BenchmarkConfig(
        models=models,
        tutorials=tutorials,
        provider=settings.provider,
        sessions=sessions,
        timeout_seconds=settings.session_timeout_seconds,
        turn_limit=settings.turn_limit,
        output=output,
        thinking=settings.thinking,
        temperature=settings.temperature,
        log_thinking=settings.log_thinking,
        repeat_command_guard=settings.repeat_command_guard,
    )
    summary = summarize(results, metadata, tutorials)
    incomplete = tuple(
        attempt for source in sources for attempt in source.incomplete_attempts
    )
    output.mkdir(parents=True, exist_ok=True)
    _write_json(
        output / "manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "benchmark": "ollama-tutorial-ladder-comparison",
            "sources": [
                {
                    "path": str(source.path),
                    "selected_models": list(source.selected_models),
                }
                for source in sources
            ],
            "models": [asdict(item) for item in metadata],
            "tutorials": list(tutorials),
            "sessions_per_model_tutorial": sessions,
            "provider": settings.provider,
            "session_timeout_seconds": settings.session_timeout_seconds,
            "turn_limit": settings.turn_limit,
            "thinking": settings.thinking,
            "temperature": settings.temperature,
            "log_thinking": settings.log_thinking,
            "repeat_command_guard": settings.repeat_command_guard,
        },
    )
    _write_json(
        output / "summary.json",
        {**summary, "incomplete_attempts": [asdict(item) for item in incomplete]},
    )
    _write_jsonl(output / "sessions.jsonl", [asdict(result) for result in results])
    report = render_report(config, summary, metadata)
    source_lines = [
        "",
        "## Evidence sources",
        "",
        "The source directories retain the full prompts, raw responses, optional thinking, "
        "turn traces, and lifecycle logs. Incomplete attempts are retained but excluded from "
        "rankings.",
        "",
        "| Source | Model selection | Completed sessions | Trace rows | Response rows | "
        "Incomplete attempts |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for source in sources:
        source_lines.append(
            f"| `{source.path}` | "
            f"{', '.join(source.selected_models) if source.selected_models else 'all'} | "
            f"{len(source.results)} | {source.trace_rows} | {source.response_rows} | "
            f"{len(source.incomplete_attempts)} |"
        )
    (output / "report.md").write_text(
        report.rstrip() + "\n" + "\n".join(source_lines) + "\n", encoding="utf-8"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Combine compatible tutorial benchmark artifact directories."
    )
    parser.add_argument("--input", action="append", default=[], type=Path)
    parser.add_argument(
        "--input-model",
        action="append",
        default=[],
        metavar="MODEL=PATH",
        help="include only MODEL's completed sessions from PATH (repeatable)",
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        selections = [SourceSelection(path) for path in args.input]
        for value in args.input_model:
            if "=" not in value:
                raise ComparisonError("--input-model must use MODEL=PATH")
            model, path = value.split("=", 1)
            if not model or not path:
                raise ComparisonError("--input-model must use MODEL=PATH")
            selections.append(SourceSelection(Path(path), (model,)))
        write_comparison(selections, args.output)
    except ComparisonError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
