"""Run the August 2026 Ollama model panel across frozen tutorial cohorts v1-v5."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .deepseek_checkpoint_matrix import (
    MATRIX_RUNS,
    OLLAMA_CLOUD_HOST,
    OLLAMA_LOCAL_HOST,
    V5_DESCRIPTION_COMMITS,
    V5_RUN,
    MatrixRun,
    MatrixValidationError,
    _incomplete_destination,
    _installed_local_model_capabilities,
    _manifest,
    _models,
    _quarantine_destination,
    _remove_worktree,
    benchmark_arguments,
    local_benchmark_arguments,
    python_executable,
    validate_manifest,
    validate_references,
    validate_session_records,
)

NEW_MODEL_RUNS = MATRIX_RUNS + (V5_RUN,)


@dataclass(frozen=True)
class NewModel:
    model: str
    provider: str
    output_name: str


NEW_MODELS = (
    NewModel("kimi-k3:cloud", "ollama-cloud", "kimi-k3-cloud"),
    NewModel("muse-glimmer:30b", "ollama-local", "muse-glimmer-30b"),
    NewModel(
        "nemotron-3.5-lightning:30b",
        "ollama-local",
        "nemotron-3-5-lightning-30b",
    ),
    NewModel("qwen3.8:27b", "ollama-local", "qwen3-8-27b"),
)


def _run_record(run: MatrixRun) -> dict[str, object]:
    record: dict[str, object] = asdict(run)
    record["tutorials"] = list(run.tutorials)
    return record


def matrix_protocol() -> dict[str, object]:
    return {
        "schema_version": 1,
        "purpose": "august-2026-new-ollama-models-v1-v5",
        "models": [asdict(model) for model in NEW_MODELS],
        "runs": [_run_record(run) for run in NEW_MODEL_RUNS],
        "sessions_per_model_tutorial": 5,
        "thinking": "high",
        "temperature": None,
        "max_output_tokens": None,
        "session_timeout_seconds": 3600.0,
        "turn_limit": 60,
        "turn_game_seconds": 600.0,
    }


def matrix_plan() -> list[dict[str, object]]:
    cells: list[dict[str, object]] = []
    for candidate in NEW_MODELS:
        for run in NEW_MODEL_RUNS:
            cells.append(
                {
                    "model": candidate.model,
                    "provider": candidate.provider,
                    "host": (
                        OLLAMA_CLOUD_HOST
                        if candidate.provider == "ollama-cloud"
                        else OLLAMA_LOCAL_HOST
                    ),
                    "cohort": run.cohort,
                    "run": run.name,
                    "commit": run.commit,
                    "tutorials": list(run.tutorials),
                    "sessions": 5,
                    "output": f"{candidate.output_name}/{run.name}",
                }
            )
    return cells


def _cell_arguments(candidate: NewModel, run: MatrixRun, output: Path) -> tuple[str, ...]:
    if candidate.provider == "ollama-local":
        return local_benchmark_arguments(run, candidate.model, output)
    return benchmark_arguments(run, candidate.model, output)


def _validate_cell(destination: Path, candidate: NewModel, run: MatrixRun) -> None:
    host = OLLAMA_CLOUD_HOST if candidate.provider == "ollama-cloud" else OLLAMA_LOCAL_HOST
    manifest_path = destination / "manifest.json"
    manifest = _manifest(manifest_path)
    if _models(manifest.get("models"), manifest_path) != (candidate.model,):
        raise MatrixValidationError(
            f"{manifest_path}: expected only model {candidate.model!r}"
        )
    validate_manifest(
        manifest_path,
        run,
        candidate.model,
        provider=candidate.provider,
        host=host,
    )
    validate_session_records(destination / "sessions.jsonl", run, candidate.model)
    if not (destination / "responses.jsonl").is_file():
        raise MatrixValidationError(f"{destination}: responses.jsonl is missing")


def _has_parameter_drift(destination: Path, candidate: NewModel, run: MatrixRun) -> bool:
    host = OLLAMA_CLOUD_HOST if candidate.provider == "ollama-cloud" else OLLAMA_LOCAL_HOST
    manifest_path = destination / "manifest.json"
    try:
        manifest = _manifest(manifest_path)
        if _models(manifest.get("models"), manifest_path) != (candidate.model,):
            return True
        validate_manifest(
            manifest_path,
            run,
            candidate.model,
            provider=candidate.provider,
            host=host,
        )
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    except MatrixValidationError:
        return True
    return False


def _relocate_invalid_cell(
    destination: Path,
    output: Path,
    candidate: NewModel,
    run: MatrixRun,
) -> None:
    name = f"{candidate.output_name}-{run.name}"
    target = (
        _quarantine_destination(output, name)
        if _has_parameter_drift(destination, candidate, run)
        else _incomplete_destination(output, name)
    )
    shutil.move(destination, target)


def validate_output(output: Path) -> None:
    protocol_path = output / "protocol.json"
    raw: object = json.loads(protocol_path.read_text(encoding="utf-8"))
    expected = matrix_protocol()
    if raw != expected:
        raise MatrixValidationError(f"{protocol_path}: matrix protocol differs")
    for candidate in NEW_MODELS:
        for run in NEW_MODEL_RUNS:
            _validate_cell(output / candidate.output_name / run.name, candidate, run)


def _validate_prerequisites(repo: Path, python: Path) -> None:
    validate_references(repo)
    if not python.is_file():
        raise MatrixValidationError(f"Python executable is missing: {python}")
    if not os.environ.get("OLLAMA_CLOUD_API_KEY"):
        raise MatrixValidationError("OLLAMA_CLOUD_API_KEY is required")
    for description_commit in V5_DESCRIPTION_COMMITS:
        subprocess.run(
            ("git", "merge-base", "--is-ancestor", description_commit, V5_RUN.commit),
            cwd=repo,
            check=True,
        )
    capabilities = _installed_local_model_capabilities()
    required = {
        candidate.model for candidate in NEW_MODELS if candidate.provider == "ollama-local"
    }
    missing = required - set(capabilities)
    if missing:
        raise MatrixValidationError(f"local models are not installed: {sorted(missing)!r}")
    unsupported = {
        model
        for model in required
        if not {"tools", "thinking"}.issubset(capabilities[model])
    }
    if unsupported:
        raise MatrixValidationError(
            "local models must advertise tools and thinking: "
            f"{sorted(unsupported)!r}"
        )


def _prepare_locked_python(worktree: Path, bootstrap_python: Path) -> Path:
    subprocess.run(
        (
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
        ),
        cwd=worktree,
        check=True,
    )
    python = worktree / ".venv" / "bin" / "python"
    if not python.is_file():
        raise MatrixValidationError(f"locked Python executable is missing: {python}")
    return python


def run_matrix(repo: Path, output: Path, bootstrap_python: Path) -> None:
    _validate_prerequisites(repo, bootstrap_python)
    if output.exists():
        raise MatrixValidationError(f"output already exists: {output}")

    staging = output.parent / "in-progress" / output.name
    protocol_path = staging / "protocol.json"
    expected_protocol = matrix_protocol()
    if staging.exists():
        raw: object = json.loads(protocol_path.read_text(encoding="utf-8"))
        if raw != expected_protocol:
            raise MatrixValidationError(f"{protocol_path}: in-progress protocol differs")
    else:
        staging.mkdir(parents=True)
        protocol_path.write_text(
            json.dumps(expected_protocol, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    temporary_root = Path(tempfile.mkdtemp(prefix="bunnyland-new-model-matrix-"))
    worktrees: dict[str, Path] = {}
    pythons: dict[str, Path] = {}
    try:
        for commit in dict.fromkeys(run.commit for run in NEW_MODEL_RUNS):
            worktree = temporary_root / commit[:8]
            subprocess.run(
                ("git", "worktree", "add", "--detach", str(worktree), commit),
                cwd=repo,
                check=True,
            )
            worktrees[commit] = worktree
            pythons[commit] = _prepare_locked_python(worktree, bootstrap_python)

        for candidate in NEW_MODELS:
            for run in NEW_MODEL_RUNS:
                destination = staging / candidate.output_name / run.name
                if destination.exists():
                    try:
                        _validate_cell(destination, candidate, run)
                        continue
                    except (
                        FileNotFoundError,
                        json.JSONDecodeError,
                        MatrixValidationError,
                    ):
                        _relocate_invalid_cell(destination, output, candidate, run)
                worktree = worktrees[run.commit]
                environment = os.environ.copy()
                environment["PYTHONPATH"] = str(worktree / "src")
                subprocess.run(
                    (
                        str(pythons[run.commit]),
                        *_cell_arguments(candidate, run, destination),
                    ),
                    cwd=worktree,
                    env=environment,
                    check=True,
                )
                _validate_cell(destination, candidate, run)
    finally:
        for worktree in reversed(tuple(worktrees.values())):
            _remove_worktree(repo, worktree)
        shutil.rmtree(temporary_root)

    validate_output(staging)
    shutil.move(staging, output)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan", help="print the frozen v1-v5 run plan")
    run_parser = subparsers.add_parser("run", help="run or resume the complete matrix")
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--python", type=Path)
    validate_parser = subparsers.add_parser(
        "validate-output",
        help="validate a complete matrix",
    )
    validate_parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo = Path(__file__).resolve().parent.parent
    if args.command == "plan":
        print(json.dumps(matrix_plan(), indent=2, sort_keys=True))
        return
    if args.command == "validate-output":
        validate_output(args.output.resolve())
        return
    run_matrix(
        repo,
        args.output.resolve(),
        python_executable(repo, args.python),
    )


if __name__ == "__main__":
    main()
