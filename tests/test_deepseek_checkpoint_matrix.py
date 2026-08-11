"""Frozen-setting checks for the DeepSeek V4 Flash checkpoint matrix."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.deepseek_checkpoint_matrix import (
    HISTORICAL_OLLAMA_CLOUD_MODELS,
    HISTORICAL_OLLAMA_LOCAL_MODELS,
    MATRIX_RUNS,
    OLLAMA_CLOUD_HOST,
    OLLAMA_LOCAL_HOST,
    V5_CLOUD_PRE_RETIREMENT_MODELS,
    V5_CLOUD_RETIRED_MODELS,
    V5_CLOUD_RUNTIME_FAILED_MODELS,
    V5_CLOUD_UNAVAILABLE_MODELS,
    V5_DESCRIPTION_COMMITS,
    V5_LOCAL_MODELS,
    V5_LOCAL_NOT_INSTALLED_MODELS,
    V5_LOCAL_OUTPUT_NAMES,
    V5_LOCAL_PRE_RUNTIME_MODELS,
    V5_LOCAL_RUNTIME_FAILED_MODELS,
    V5_LOCAL_RUNTIME_VALIDATED_MODELS,
    V5_LOCAL_UNAVAILABLE_MODELS,
    V5_LOCAL_UNSUPPORTED_THINKING_MODELS,
    V5_MODELS,
    V5_OUTPUT_NAMES,
    V5_RUN,
    V5_SEED_MODELS,
    MatrixValidationError,
    _check_local_availability,
    _has_parameter_drift,
    _incomplete_destination,
    _prepare_staging,
    _quarantine_destination,
    _v5_local_attempt_protocol,
    _v5_local_protocol,
    _v5_protocol,
    benchmark_arguments,
    local_benchmark_arguments,
    promote_v5_local_attempts,
    python_executable,
    validate_manifest,
    validate_session_records,
    validate_v5_local_output,
    validate_v5_local_roster,
    validate_v5_output,
    validate_v5_roster,
)


def _write_v5_local_cell(root: Path, model: str) -> None:
    destination = root / V5_LOCAL_OUTPUT_NAMES[model]
    destination.mkdir(parents=True)
    manifest = {
        "commit": V5_RUN.commit,
        "provider": "ollama-local",
        "host": OLLAMA_LOCAL_HOST,
        "tutorials": ["bell"],
        "sessions_per_model_tutorial": 5,
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
        "models": [{"model": model}],
    }
    (destination / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    sessions = [
        {"model": model, "tutorial": "bell", "run": run_number}
        for run_number in range(1, 6)
    ]
    (destination / "sessions.jsonl").write_text(
        "".join(f"{json.dumps(session)}\n" for session in sessions),
        encoding="utf-8",
    )
    (destination / "responses.jsonl").write_text("", encoding="utf-8")


def _write_legacy_v5_local_attempt_protocol(root: Path) -> None:
    protocol = _v5_local_protocol()
    protocol.update(
        {
            "purpose": "action-description-rewrite-local-exact-attempts",
            "models": list(V5_LOCAL_RUNTIME_VALIDATED_MODELS),
            "baseline_models": list(V5_LOCAL_PRE_RUNTIME_MODELS),
            "attempted_models": list(V5_LOCAL_UNSUPPORTED_THINKING_MODELS),
            "failed_models": list(V5_LOCAL_RUNTIME_FAILED_MODELS),
            "unavailable_models": list(
                V5_LOCAL_NOT_INSTALLED_MODELS + V5_LOCAL_UNSUPPORTED_THINKING_MODELS
            ),
        }
    )
    protocol.pop("runtime_failed_models")
    protocol.pop("runtime_validated_models")
    (root / "protocol.json").write_text(json.dumps(protocol), encoding="utf-8")


def test_matrix_freezes_exact_source_commits_and_settings() -> None:
    assert tuple(run.commit for run in MATRIX_RUNS) == (
        "fc3ec38db6c1ae0e14323bdcb31f4d0614c0b2d0",
        "3a662413e64e28ae3852a17dde10ea73d2c22f67",
        "3a662413e64e28ae3852a17dde10ea73d2c22f67",
        "a6dc96449c3d023cc7d1f1944278eb93c62306f4",
        "0abb32bd0b8da1f20c50fb838416cc85c61cb21b",
    )
    assert tuple(run.tutorials for run in MATRIX_RUNS) == (
        ("apple", "bell", "clover"),
        ("apple", "bell"),
        ("clover",),
        ("bell",),
        ("bell",),
    )
    assert tuple(run.log_thinking for run in MATRIX_RUNS) == (
        True,
        True,
        True,
        False,
        False,
    )
    assert tuple(run.repeat_command_guard for run in MATRIX_RUNS) == (
        True,
        True,
        True,
        False,
        False,
    )
    assert tuple(run.provider_session_retries for run in MATRIX_RUNS) == (
        None,
        None,
        None,
        8,
        0,
    )


def test_benchmark_arguments_preserve_frozen_optional_flags(tmp_path) -> None:
    v1 = benchmark_arguments(MATRIX_RUNS[0], "dated", tmp_path / "v1")
    v3 = benchmark_arguments(MATRIX_RUNS[3], "dated", tmp_path / "v3")
    v4 = benchmark_arguments(MATRIX_RUNS[4], "dated", tmp_path / "v4")

    assert "--log-thinking" in v1
    assert "--repeat-command-guard" in v1
    assert "--provider-session-retries" not in v1
    assert "--log-thinking" not in v3
    assert "--repeat-command-guard" not in v3
    assert v3[v3.index("--provider-session-retries") + 1] == "8"
    assert v4[v4.index("--provider-session-retries") + 1] == "0"


def test_v5_freezes_latest_revision_and_matches_v4_settings(tmp_path) -> None:
    assert V5_RUN.commit == "00c46639b8877646d02484621f8d1861e38314ec"
    assert V5_DESCRIPTION_COMMITS == (
        "30bab131448a449606a059edd1aedf56c726cbd9",
        "ea45eb61268aa47897694d67c9c01722c69d240a",
    )
    assert V5_SEED_MODELS == (
        "deepseek-v4-flash:cloud",
        "deepseek-v4-flash:0731-cloud",
    )
    assert HISTORICAL_OLLAMA_CLOUD_MODELS == (
        "deepseek-v4-flash:cloud",
        "deepseek-v4-pro:cloud",
        "gemma4:cloud",
        "glm-5.2:cloud",
        "gpt-oss:120b-cloud",
        "gpt-oss:20b-cloud",
        "kimi-k2.5",
        "kimi-k2.6:cloud",
        "kimi-k2.7-code:cloud",
        "minimax-m2.7:cloud",
        "minimax-m3:cloud",
        "mistral-large-3:675b-cloud",
        "nemotron-3-nano:30b-cloud",
        "nemotron-3-super:cloud",
        "nemotron-3-ultra:cloud",
        "qwen3.5:397b-cloud",
        "qwen3.5:cloud",
    )
    assert V5_CLOUD_PRE_RETIREMENT_MODELS == (
        V5_SEED_MODELS + HISTORICAL_OLLAMA_CLOUD_MODELS[1:]
    )
    assert V5_CLOUD_RETIRED_MODELS == ("kimi-k2.5",)
    assert V5_CLOUD_RUNTIME_FAILED_MODELS == (
        "mistral-large-3:675b-cloud",
        "qwen3.5:397b-cloud",
        "qwen3.5:cloud",
    )
    assert V5_CLOUD_UNAVAILABLE_MODELS == (
        V5_CLOUD_RETIRED_MODELS + V5_CLOUD_RUNTIME_FAILED_MODELS
    )
    assert V5_MODELS == tuple(
        model
        for model in V5_CLOUD_PRE_RETIREMENT_MODELS
        if model not in V5_CLOUD_UNAVAILABLE_MODELS
    )
    assert set(V5_MODELS).issubset(V5_OUTPUT_NAMES)
    assert len(set(V5_OUTPUT_NAMES.values())) == len(V5_OUTPUT_NAMES)
    v4 = MATRIX_RUNS[-1]
    assert V5_RUN.tutorials == v4.tutorials == ("bell",)
    assert V5_RUN.log_thinking == v4.log_thinking is False
    assert V5_RUN.repeat_command_guard == v4.repeat_command_guard is False
    assert V5_RUN.provider_session_retries == v4.provider_session_retries == 0
    assert V5_RUN.seed_helpful_memory == v4.seed_helpful_memory is False

    args = benchmark_arguments(V5_RUN, V5_MODELS[0], tmp_path / "v5")
    assert "--log-thinking" not in args
    assert "--repeat-command-guard" not in args
    assert args[args.index("--provider-session-retries") + 1] == "0"


def test_v5_protocol_records_full_treatment() -> None:
    assert _v5_protocol() == {
        "schema_version": 1,
        "cohort": "v5",
        "purpose": "action-description-rewrite",
        "server_commit": V5_RUN.commit,
        "harness_commit": V5_RUN.commit,
        "baseline_commit": MATRIX_RUNS[-1].commit,
        "description_commits": list(V5_DESCRIPTION_COMMITS),
        "models": list(V5_MODELS),
        "historical_models": list(HISTORICAL_OLLAMA_CLOUD_MODELS),
        "unavailable_models": list(V5_CLOUD_UNAVAILABLE_MODELS),
        "retired_models": list(V5_CLOUD_RETIRED_MODELS),
        "runtime_failed_models": list(V5_CLOUD_RUNTIME_FAILED_MODELS),
        "provider": "ollama-cloud",
        "host": OLLAMA_CLOUD_HOST,
        "tutorials": ["bell"],
        "sessions_per_model_tutorial": 5,
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
        "artifact_schema_version": 6,
    }


def test_v5_roster_is_derived_from_retained_v1_v2_v3_v4_manifests() -> None:
    validate_v5_roster(Path(__file__).resolve().parent.parent)


def test_v5_local_roster_and_arguments_are_frozen_to_installed_historical_models(
    tmp_path,
) -> None:
    validate_v5_local_roster(Path(__file__).resolve().parent.parent)
    assert set(V5_LOCAL_MODELS).isdisjoint(V5_LOCAL_UNAVAILABLE_MODELS)
    assert set(V5_LOCAL_MODELS) | set(V5_LOCAL_UNAVAILABLE_MODELS) == set(
        HISTORICAL_OLLAMA_LOCAL_MODELS
    )
    assert set(V5_LOCAL_MODELS).issubset(V5_LOCAL_OUTPUT_NAMES)
    assert set(V5_LOCAL_UNSUPPORTED_THINKING_MODELS).issubset(V5_LOCAL_OUTPUT_NAMES)
    assert len(set(V5_LOCAL_OUTPUT_NAMES.values())) == len(V5_LOCAL_OUTPUT_NAMES)

    args = local_benchmark_arguments(V5_RUN, V5_LOCAL_MODELS[0], tmp_path / "local")
    assert args[args.index("--provider") + 1] == "ollama-local"
    assert args[args.index("--host") + 1] == OLLAMA_LOCAL_HOST
    assert args[args.index("--provider-session-retries") + 1] == "0"
    assert "--log-thinking" not in args
    assert "--repeat-command-guard" not in args


def test_v5_validation_rejects_protocol_drift(tmp_path) -> None:
    protocol = _v5_protocol()
    protocol["repeat_command_guard"] = True
    (tmp_path / "protocol.json").write_text(
        json.dumps(protocol),
        encoding="utf-8",
    )

    with pytest.raises(MatrixValidationError, match="protocol is"):
        validate_v5_output(tmp_path)


def test_manifest_validation_rejects_one_setting_drift(tmp_path) -> None:
    run = MATRIX_RUNS[3]
    manifest = {
        "commit": run.commit,
        "provider": "ollama-cloud",
        "host": OLLAMA_CLOUD_HOST,
        "tutorials": list(run.tutorials),
        "sessions_per_model_tutorial": 5,
        "thinking": "high",
        "temperature": None,
        "max_output_tokens": None,
        "log_thinking": run.log_thinking,
        "repeat_command_guard": run.repeat_command_guard,
        "provider_session_retries": run.provider_session_retries,
        "seed_helpful_memory": run.seed_helpful_memory,
        "session_timeout_seconds": 3600.0,
        "turn_limit": 60,
        "turn_game_seconds": 600.0,
        "schema_version": run.schema_version,
        "models": [{"model": "dated"}],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    validate_manifest(path, run, "dated")

    manifest["provider_session_retries"] = 1
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(MatrixValidationError, match="provider_session_retries"):
        validate_manifest(path, run, "dated")


def test_session_validation_requires_five_unique_records_per_cell(tmp_path) -> None:
    run = MATRIX_RUNS[3]
    path = tmp_path / "sessions.jsonl"
    records = [
        {"model": "dated", "tutorial": "bell", "run": run_number} for run_number in range(1, 6)
    ]
    path.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records),
        encoding="utf-8",
    )
    validate_session_records(path, run, "dated")

    records[-1]["run"] = 4
    path.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records),
        encoding="utf-8",
    )
    with pytest.raises(MatrixValidationError, match="session cells"):
        validate_session_records(path, run, "dated")


def test_python_executable_preserves_virtual_environment_symlink(tmp_path) -> None:
    repo = tmp_path / "repo"
    python = repo / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.symlink_to("/usr/bin/python3")

    assert python_executable(repo, None) == python


def test_artifact_lifecycle_quarantines_only_manifest_proven_parameter_drift(
    tmp_path,
) -> None:
    output = tmp_path / "completed"
    cell = tmp_path / "cell"
    cell.mkdir()
    manifest = {
        "commit": V5_RUN.commit,
        "provider": "ollama-local",
        "host": OLLAMA_LOCAL_HOST,
        "tutorials": ["bell"],
        "sessions_per_model_tutorial": 5,
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
        "models": [{"model": "qwen3.6:35b-a3b"}],
    }
    (cell / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert not _has_parameter_drift(
        cell,
        "qwen3.6:35b-a3b",
        provider="ollama-local",
        host=OLLAMA_LOCAL_HOST,
    )
    assert _incomplete_destination(output, "qwen").parent.parent.name == "incomplete"
    assert _quarantine_destination(output, "qwen").parent.parent.name == "quarantine"

    manifest["provider_session_retries"] = 1
    (cell / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert _has_parameter_drift(
        cell,
        "qwen3.6:35b-a3b",
        provider="ollama-local",
        host=OLLAMA_LOCAL_HOST,
    )


def test_staging_uses_in_progress_and_refuses_parameter_drift(tmp_path) -> None:
    output = tmp_path / "completed"
    protocol = _v5_protocol()
    staging = _prepare_staging(output, protocol, {"models"})

    assert staging == tmp_path / "in-progress" / "completed"
    drifted = dict(protocol)
    drifted["repeat_command_guard"] = True
    (staging / "protocol.json").write_text(json.dumps(drifted), encoding="utf-8")

    with pytest.raises(MatrixValidationError, match="inspect before quarantine"):
        _prepare_staging(output, protocol, {"models"})
    assert staging.is_dir()


def test_exact_local_attempt_protocol_preserves_v5_treatment() -> None:
    model = V5_LOCAL_UNSUPPORTED_THINKING_MODELS[0]
    protocol = _v5_local_attempt_protocol((model,), (), (model,))

    assert protocol["attempted_models"] == [model]
    assert protocol["failed_models"] == [model]
    assert protocol["models"] == []
    assert protocol["thinking"] == "high"
    assert protocol["log_thinking"] is False
    assert protocol["repeat_command_guard"] is False
    assert protocol["provider_session_retries"] == 0
    assert protocol["seed_helpful_memory"] is False
    assert protocol["session_timeout_seconds"] == 3600.0
    assert protocol["turn_limit"] == 60
    assert protocol["turn_game_seconds"] == 600.0


def test_local_availability_accepts_only_recorded_runtime_exceptions(monkeypatch) -> None:
    capabilities = {
        model: {"thinking", "tools"} for model in V5_LOCAL_PRE_RUNTIME_MODELS
    }
    capabilities.update(
        {model: {"tools"} for model in V5_LOCAL_UNSUPPORTED_THINKING_MODELS}
    )
    monkeypatch.setattr(
        "benchmarks.deepseek_checkpoint_matrix._installed_local_model_capabilities",
        lambda: capabilities,
    )

    _check_local_availability()

    capabilities[V5_LOCAL_PRE_RUNTIME_MODELS[0]] = {"tools"}
    with pytest.raises(MatrixValidationError, match="do not support tools and high thinking"):
        _check_local_availability()


def test_v5_local_runtime_results_partition_exact_attempt_roster() -> None:
    assert set(V5_LOCAL_RUNTIME_VALIDATED_MODELS).isdisjoint(
        V5_LOCAL_RUNTIME_FAILED_MODELS
    )
    assert set(V5_LOCAL_RUNTIME_VALIDATED_MODELS) | set(
        V5_LOCAL_RUNTIME_FAILED_MODELS
    ) == set(V5_LOCAL_UNSUPPORTED_THINKING_MODELS)
    assert V5_LOCAL_UNAVAILABLE_MODELS == (
        V5_LOCAL_NOT_INSTALLED_MODELS + V5_LOCAL_RUNTIME_FAILED_MODELS
    )
    assert V5_LOCAL_MODELS == tuple(
        model
        for model in HISTORICAL_OLLAMA_LOCAL_MODELS
        if model not in V5_LOCAL_UNAVAILABLE_MODELS
    )


def test_promote_v5_local_attempts_preserves_sources_and_validates_output(
    tmp_path,
) -> None:
    source = tmp_path / "source"
    attempts = tmp_path / "attempts"
    output = tmp_path / "output"
    source.mkdir()
    attempts.mkdir()

    source_protocol = _v5_local_protocol()
    source_protocol["models"] = list(V5_LOCAL_PRE_RUNTIME_MODELS)
    (source / "protocol.json").write_text(
        json.dumps(source_protocol),
        encoding="utf-8",
    )
    for model in V5_LOCAL_PRE_RUNTIME_MODELS:
        _write_v5_local_cell(source, model)

    _write_legacy_v5_local_attempt_protocol(attempts)
    for model in V5_LOCAL_RUNTIME_VALIDATED_MODELS:
        _write_v5_local_cell(attempts, model)

    promote_v5_local_attempts(
        Path(__file__).resolve().parent.parent,
        source,
        attempts,
        output,
    )

    validate_v5_local_output(output)
    assert source.is_dir()
    assert attempts.is_dir()
    assert not (tmp_path / "quarantine").exists()
