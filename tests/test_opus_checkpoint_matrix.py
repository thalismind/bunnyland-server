"""Frozen-setting checks for the Claude Opus checkpoint matrix."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.opus_checkpoint_matrix import (
    HISTORICAL_OPENROUTER_VERSION,
    OPENROUTER_HOST,
    OPUS_5_MODEL,
    OPUS_48_MODEL,
    OPUS_RUNS,
    PYTHON_VERSION,
    SESSIONS_PER_CELL,
    V5_CATALOGUE_ADAPTER,
    V5_OPENROUTER_VERSION,
    OpusMatrixError,
    _benchmark_command,
    _cell_key,
    _planned_by_key,
    _planned_cells,
    _protocol,
    _relocate_superseded_empty_staging,
    benchmark_arguments,
    validate_dependency_locks,
    validate_manifest,
    validate_references,
    validate_sessions,
)


def test_matrix_freezes_exact_commits_and_treatments() -> None:
    assert SESSIONS_PER_CELL == 2
    assert PYTHON_VERSION == "3.12"
    assert HISTORICAL_OPENROUTER_VERSION == "0.9.1"
    assert V5_OPENROUTER_VERSION == "1.1.9"
    assert V5_CATALOGUE_ADAPTER == "openrouter-1.1.9-result-data"
    assert tuple(run.commit for run in OPUS_RUNS) == (
        "5b33e2a69301edbe1c650c1ee2bebb01aabd99e6",
        "3a662413e64e28ae3852a17dde10ea73d2c22f67",
        "a6dc96449c3d023cc7d1f1944278eb93c62306f4",
        "0abb32bd0b8da1f20c50fb838416cc85c61cb21b",
        "00c46639b8877646d02484621f8d1861e38314ec",
    )
    assert tuple(run.tutorials for run in OPUS_RUNS) == (
        ("apple", "bell", "clover"),
        ("apple", "bell", "clover"),
        ("bell",),
        ("bell",),
        ("bell",),
    )
    assert tuple(run.provider_session_retries for run in OPUS_RUNS) == (
        None,
        None,
        2,
        2,
        0,
    )
    assert tuple(run.seed_helpful_memory for run in OPUS_RUNS) == (
        None,
        None,
        False,
        False,
        False,
    )


def test_plan_adds_opus_48_everywhere_and_only_missing_opus_5_v5() -> None:
    planned = _planned_cells()

    assert planned == tuple((OPUS_48_MODEL, run) for run in OPUS_RUNS) + (
        (OPUS_5_MODEL, OPUS_RUNS[-1]),
    )
    tutorial_cells = sum(len(run.tutorials) for _, run in planned)
    assert tutorial_cells == 10
    assert tutorial_cells * SESSIONS_PER_CELL == 20
    assert _protocol()["planned_cells"] == [
        {"model": model, "run": run.name} for model, run in planned
    ]
    assert json.loads(json.dumps(_protocol())) == _protocol()
    assert _protocol()["python_version"] == "3.12"
    assert _protocol()["openrouter_sdk_versions"] == {
        "v1-v4": "0.9.1",
        "v5": "1.1.9",
    }
    assert _protocol()["v5_catalogue_adapter"] == V5_CATALOGUE_ADAPTER
    assert tuple(_cell_key(model, run) for model, run in planned) == (
        "claude-opus-4-8-v1",
        "claude-opus-4-8-v2",
        "claude-opus-4-8-v3",
        "claude-opus-4-8-v4",
        "claude-opus-4-8-v5",
        "claude-opus-5-v5",
    )
    assert tuple(_planned_by_key()) == tuple(
        _cell_key(model, run) for model, run in planned
    )


def test_arguments_preserve_each_cohorts_exact_optional_flags(tmp_path: Path) -> None:
    for run in OPUS_RUNS:
        arguments = benchmark_arguments(run, OPUS_48_MODEL, tmp_path / run.name)
        assert arguments[arguments.index("--provider") + 1] == "openrouter"
        assert arguments[arguments.index("--host") + 1] == OPENROUTER_HOST
        assert arguments[arguments.index("--sessions") + 1] == "2"
        assert arguments[arguments.index("--thinking") + 1] == "high"
        assert "--log-thinking" not in arguments
        assert "--repeat-command-guard" not in arguments
        assert "--temperature" not in arguments
        assert "--max-output-tokens" not in arguments
        assert "--seed-helpful-memory" not in arguments
        if run.provider_session_retries is None:
            assert "--provider-session-retries" not in arguments
        else:
            assert arguments[
                arguments.index("--provider-session-retries") + 1
            ] == str(run.provider_session_retries)


def test_v5_command_changes_only_the_catalogue_entrypoint(tmp_path: Path) -> None:
    python = tmp_path / "python"
    arguments = benchmark_arguments(OPUS_RUNS[-1], OPUS_48_MODEL, tmp_path / "v5")

    historical = _benchmark_command(python, arguments, use_v5_adapter=False)
    current = _benchmark_command(python, arguments, use_v5_adapter=True)

    assert historical == (str(python), *arguments)
    assert current[0] == str(python)
    assert current[1] == "-c"
    assert V5_CATALOGUE_ADAPTER_CODE_MARKER in current[2]
    assert current[3:] == arguments[2:]


V5_CATALOGUE_ADAPTER_CODE_MARKER = (
    "tutorials.preflight_openrouter_models = _opus_catalogue_preflight"
)


def test_only_empty_superseded_staging_can_move_to_incomplete(tmp_path: Path) -> None:
    output = tmp_path / "matrix"
    staging = tmp_path / "in-progress" / "matrix"
    staging.mkdir(parents=True)
    (staging / "protocol.json").write_text("{}\n", encoding="utf-8")

    _relocate_superseded_empty_staging(output, staging)

    assert not staging.exists()
    assert (
        tmp_path / "incomplete" / "matrix-incomplete-ledgers" / "preflight-only"
    ).is_dir()

    staging.mkdir(parents=True)
    (staging / "protocol.json").write_text("{}\n", encoding="utf-8")
    (staging / "cell").mkdir()
    (staging / "cell" / "sessions.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(OpusMatrixError, match="protocol differs"):
        _relocate_superseded_empty_staging(output, staging)


def test_retained_opus_5_references_match_frozen_v1_v4_settings() -> None:
    repo = Path(__file__).resolve().parent.parent
    validate_references(repo)
    validate_dependency_locks(repo)


def test_manifest_validation_rejects_parameter_drift(tmp_path: Path) -> None:
    run = OPUS_RUNS[-1]
    manifest = {
        "commit": run.commit,
        "provider": "openrouter",
        "host": OPENROUTER_HOST,
        "tutorials": list(run.tutorials),
        "sessions_per_model_tutorial": 2,
        "thinking": "high",
        "temperature": None,
        "max_output_tokens": None,
        "log_thinking": False,
        "repeat_command_guard": False,
        "provider_session_retries": 0,
        "seed_helpful_memory": False,
        "session_timeout_seconds": 3600.0,
        "turn_limit": 60,
        "turn_game_seconds": 600.0,
        "schema_version": 6,
        "models": [{"model": OPUS_48_MODEL}],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    validate_manifest(path, run, OPUS_48_MODEL)

    manifest["provider_session_retries"] = 2
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(OpusMatrixError, match="provider_session_retries"):
        validate_manifest(path, run, OPUS_48_MODEL)


def test_session_validation_requires_two_unique_records_per_tutorial(
    tmp_path: Path,
) -> None:
    run = OPUS_RUNS[0]
    records = [
        {"model": OPUS_48_MODEL, "tutorial": tutorial, "run": run_number}
        for tutorial in run.tutorials
        for run_number in range(1, SESSIONS_PER_CELL + 1)
    ]
    path = tmp_path / "sessions.jsonl"
    path.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records),
        encoding="utf-8",
    )
    validate_sessions(path, run, OPUS_48_MODEL)

    records.pop()
    path.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records),
        encoding="utf-8",
    )
    with pytest.raises(OpusMatrixError, match="session cells"):
        validate_sessions(path, run, OPUS_48_MODEL)
