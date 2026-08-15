"""Frozen-plan checks for the August 2026 Ollama model panel."""

from __future__ import annotations

from pathlib import Path

from benchmarks.deepseek_checkpoint_matrix import MATRIX_RUNS, V5_RUN
from benchmarks.new_model_checkpoint_matrix import (
    NEW_MODEL_RUNS,
    NEW_MODELS,
    _cell_arguments,
    _prepare_locked_python,
    matrix_plan,
    matrix_protocol,
)


def test_new_model_roster_and_v1_v5_runs_are_frozen() -> None:
    assert tuple((model.model, model.provider) for model in NEW_MODELS) == (
        ("kimi-k3:cloud", "ollama-cloud"),
        ("muse-glimmer:30b", "ollama-local"),
        ("nemotron-3.5-lightning:30b", "ollama-local"),
        ("qwen3.8:27b", "ollama-local"),
    )
    assert NEW_MODEL_RUNS == MATRIX_RUNS + (V5_RUN,)
    assert tuple(run.cohort for run in NEW_MODEL_RUNS) == (
        "v1",
        "v2",
        "v2",
        "v3",
        "v4",
        "v5",
    )


def test_new_model_plan_has_45_sessions_per_model() -> None:
    plan = matrix_plan()
    assert len(plan) == 24
    for model in NEW_MODELS:
        cells = [cell for cell in plan if cell["model"] == model.model]
        assert sum(len(cell["tutorials"]) * cell["sessions"] for cell in cells) == 45


def test_new_model_protocol_records_exact_treatment() -> None:
    protocol = matrix_protocol()
    assert protocol["thinking"] == "high"
    assert protocol["temperature"] is None
    assert protocol["max_output_tokens"] is None
    assert protocol["sessions_per_model_tutorial"] == 5
    assert len(protocol["models"]) == 4
    assert len(protocol["runs"]) == 6


def test_new_model_arguments_select_matching_provider(tmp_path: Path) -> None:
    cloud = _cell_arguments(NEW_MODELS[0], NEW_MODEL_RUNS[0], tmp_path / "cloud")
    local = _cell_arguments(NEW_MODELS[1], NEW_MODEL_RUNS[0], tmp_path / "local")
    assert cloud[cloud.index("--provider") + 1] == "ollama-cloud"
    assert cloud[cloud.index("--host") + 1] == "https://ollama.com"
    assert local[local.index("--provider") + 1] == "ollama-local"
    assert local[local.index("--host") + 1] == "http://127.0.0.1:11435"


def test_new_model_runner_prepares_checkout_local_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    worktree = tmp_path / "historical-checkout"
    worktree.mkdir()
    bootstrap_python = tmp_path / "bootstrap" / "python"
    locked_python = worktree / ".venv" / "bin" / "python"

    def fake_run(command, *, cwd, check):
        assert command == (
            "uv",
            "run",
            "--frozen",
            "--extra",
            "llm",
            "--python",
            str(bootstrap_python),
            "python",
            "-c",
            "import bunnyland",
        )
        assert cwd == worktree
        assert check is True
        locked_python.parent.mkdir(parents=True)
        locked_python.touch()

    monkeypatch.setattr(
        "benchmarks.new_model_checkpoint_matrix.subprocess.run",
        fake_run,
    )

    assert _prepare_locked_python(worktree, bootstrap_python) == locked_python
