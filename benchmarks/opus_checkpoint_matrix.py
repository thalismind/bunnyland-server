"""Run a frozen Claude Opus 4.8 versus Opus 5 tutorial matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

OPENROUTER_HOST = "https://openrouter.ai/api/v1"
OPUS_48_MODEL = "anthropic/claude-opus-4.8"
OPUS_5_MODEL = "anthropic/claude-opus-5"
SESSIONS_PER_CELL = 2
PYTHON_VERSION = "3.12"
HISTORICAL_OPENROUTER_VERSION = "0.9.1"
V5_OPENROUTER_VERSION = "1.1.9"
V5_CATALOGUE_ADAPTER = "openrouter-1.1.9-result-data"

V5_CATALOGUE_ADAPTER_CODE = """
async def _opus_catalogue_preflight(models, host, api_key):
    from openrouter import OpenRouter

    client = OpenRouter(api_key=api_key, server_url=host)
    response = await client.models.list_async()
    result = getattr(response, "result", None)
    items = getattr(result, "data", None)
    if items is None:
        raise RuntimeError("OpenRouter 1.1.9 catalogue response has no result.data")
    available = {item.id: item for item in items}
    missing = [model for model in models if model not in available]
    if missing:
        raise RuntimeError(f"OpenRouter model(s) not found: {', '.join(missing)}")
    metadata = []
    for model in models:
        architecture = getattr(available[model], "architecture", None)
        family = getattr(architecture, "tokenizer", None)
        metadata.append(tutorials.ModelMetadata(model=model, family=family))
    return tuple(metadata)

tutorials.preflight_openrouter_models = _opus_catalogue_preflight
"""


@dataclass(frozen=True)
class OpusRun:
    name: str
    cohort: str
    commit: str
    schema_version: int
    tutorials: tuple[str, ...]
    provider_session_retries: int | None
    seed_helpful_memory: bool | None
    reference_manifest: str | None


OPUS_RUNS = (
    OpusRun(
        name="v1-all",
        cohort="v1",
        commit="5b33e2a69301edbe1c650c1ee2bebb01aabd99e6",
        schema_version=5,
        tutorials=("apple", "bell", "clover"),
        provider_session_retries=None,
        seed_helpful_memory=None,
        reference_manifest=(
            "benchmarks/reference_manifests/"
            "frontier-openrouter-v1-5b33e2a-claude-opus-5-2x-2026-07-26/manifest.json"
        ),
    ),
    OpusRun(
        name="v2-all",
        cohort="v2",
        commit="3a662413e64e28ae3852a17dde10ea73d2c22f67",
        schema_version=6,
        tutorials=("apple", "bell", "clover"),
        provider_session_retries=None,
        seed_helpful_memory=None,
        reference_manifest=(
            "benchmarks/reference_manifests/"
            "frontier-openrouter-v2-3a66241-claude-opus-5-2x-2026-07-26/manifest.json"
        ),
    ),
    OpusRun(
        name="v3-bell",
        cohort="v3",
        commit="a6dc96449c3d023cc7d1f1944278eb93c62306f4",
        schema_version=6,
        tutorials=("bell",),
        provider_session_retries=2,
        seed_helpful_memory=False,
        reference_manifest=(
            "benchmarks/reference_manifests/"
            "frontier-openrouter-v3-a6dc964-claude-opus-5-2x-2026-07-26/manifest.json"
        ),
    ),
    OpusRun(
        name="v4-bell",
        cohort="v4",
        commit="0abb32bd0b8da1f20c50fb838416cc85c61cb21b",
        schema_version=6,
        tutorials=("bell",),
        provider_session_retries=2,
        seed_helpful_memory=False,
        reference_manifest=(
            "benchmarks/reference_manifests/"
            "frontier-openrouter-v4-0abb32b-claude-opus-5-2x-2026-07-26/manifest.json"
        ),
    ),
    OpusRun(
        name="v5-bell",
        cohort="v5",
        commit="00c46639b8877646d02484621f8d1861e38314ec",
        schema_version=6,
        tutorials=("bell",),
        provider_session_retries=0,
        seed_helpful_memory=False,
        reference_manifest=None,
    ),
)

MODEL_OUTPUT_NAMES = {
    OPUS_48_MODEL: "claude-opus-4-8",
    OPUS_5_MODEL: "claude-opus-5",
}


class OpusMatrixError(RuntimeError):
    """The Opus comparison does not match its frozen treatment."""


def _manifest(path: Path) -> dict[str, object]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise OpusMatrixError(f"manifest must be an object: {path}")
    return raw


def _models(value: object, path: Path) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise OpusMatrixError(f"manifest models must be an array: {path}")
    models: list[str] = []
    for raw_model in value:
        if not isinstance(raw_model, dict):
            raise OpusMatrixError(f"manifest model must be an object: {path}")
        model = raw_model.get("model")
        if not isinstance(model, str):
            raise OpusMatrixError(f"manifest model id must be a string: {path}")
        models.append(model)
    return tuple(models)


def validate_manifest(path: Path, run: OpusRun, model: str) -> None:
    manifest = _manifest(path)
    expected: dict[str, object] = {
        "commit": run.commit,
        "provider": "openrouter",
        "host": OPENROUTER_HOST,
        "tutorials": list(run.tutorials),
        "sessions_per_model_tutorial": SESSIONS_PER_CELL,
        "thinking": "high",
        "temperature": None,
        "max_output_tokens": None,
        "log_thinking": False,
        "repeat_command_guard": False,
        "provider_session_retries": run.provider_session_retries,
        "seed_helpful_memory": run.seed_helpful_memory,
        "session_timeout_seconds": 3600.0,
        "turn_limit": 60,
        "turn_game_seconds": 600.0,
        "schema_version": run.schema_version,
    }
    for key, expected_value in expected.items():
        actual = manifest.get(key)
        if actual != expected_value:
            raise OpusMatrixError(
                f"{path}: {key} is {actual!r}, expected {expected_value!r}"
            )
    if _models(manifest.get("models"), path) != (model,):
        raise OpusMatrixError(f"{path}: expected only model {model!r}")


def validate_sessions(path: Path, run: OpusRun, model: str) -> None:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw: object = json.loads(line)
        if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
            raise OpusMatrixError(f"{path}:{line_number}: session must be an object")
        records.append(raw)
    expected = {
        (tutorial, run_number)
        for tutorial in run.tutorials
        for run_number in range(1, SESSIONS_PER_CELL + 1)
    }
    actual: set[tuple[str, int]] = set()
    for record in records:
        tutorial = record.get("tutorial")
        run_number = record.get("run")
        if not isinstance(tutorial, str) or not isinstance(run_number, int):
            raise OpusMatrixError(f"{path}: session tutorial/run is invalid")
        if record.get("model") != model:
            raise OpusMatrixError(f"{path}: session model does not match {model!r}")
        actual.add((tutorial, run_number))
    if len(records) != len(expected) or actual != expected:
        raise OpusMatrixError(
            f"{path}: session cells are {sorted(actual)!r}, "
            f"expected {sorted(expected)!r}"
        )


def benchmark_arguments(run: OpusRun, model: str, output: Path) -> tuple[str, ...]:
    arguments = [
        "-m",
        "benchmarks.tutorials",
        "--provider",
        "openrouter",
        "--host",
        OPENROUTER_HOST,
        "--model",
        model,
    ]
    for tutorial in run.tutorials:
        arguments.extend(("--tutorial", tutorial))
    arguments.extend(
        (
            "--sessions",
            str(SESSIONS_PER_CELL),
            "--session-timeout",
            "3600",
            "--turn-limit",
            "60",
            "--thinking",
            "high",
        )
    )
    if run.provider_session_retries is not None:
        arguments.extend(("--provider-session-retries", str(run.provider_session_retries)))
    if run.seed_helpful_memory:
        arguments.append("--seed-helpful-memory")
    arguments.extend(("--output", str(output)))
    return tuple(arguments)


def validate_references(repo: Path) -> None:
    for run in OPUS_RUNS:
        if run.reference_manifest is not None:
            validate_manifest(repo / run.reference_manifest, run, OPUS_5_MODEL)


def validate_dependency_locks(repo: Path) -> None:
    lock_digests: list[str] = []
    for run in OPUS_RUNS:
        result = subprocess.run(
            ("git", "show", f"{run.commit}:uv.lock"),
            cwd=repo,
            check=True,
            capture_output=True,
        )
        lock_digests.append(hashlib.sha256(result.stdout).hexdigest())
    if len(set(lock_digests[:-1])) != 1:
        raise OpusMatrixError("v1-v4 dependency locks differ")
    if lock_digests[-1] == lock_digests[0]:
        raise OpusMatrixError("v5 dependency lock unexpectedly matches v1-v4")


def _planned_cells() -> tuple[tuple[str, OpusRun], ...]:
    return tuple((OPUS_48_MODEL, run) for run in OPUS_RUNS) + ((OPUS_5_MODEL, OPUS_RUNS[-1]),)


def _cell_key(model: str, run: OpusRun) -> str:
    return f"{MODEL_OUTPUT_NAMES[model]}-{run.cohort}"


def _protocol() -> dict[str, object]:
    runs = []
    for run in OPUS_RUNS:
        run_data = asdict(run)
        run_data["tutorials"] = list(run.tutorials)
        runs.append(run_data)
    return {
        "schema_version": 1,
        "purpose": "claude-opus-4.8-versus-opus-5",
        "models": [OPUS_48_MODEL, OPUS_5_MODEL],
        "reference_model": OPUS_5_MODEL,
        "provider": "openrouter",
        "host": OPENROUTER_HOST,
        "sessions_per_model_tutorial": SESSIONS_PER_CELL,
        "thinking": "high",
        "temperature": None,
        "max_output_tokens": None,
        "log_thinking": False,
        "repeat_command_guard": False,
        "session_timeout_seconds": 3600.0,
        "turn_limit": 60,
        "turn_game_seconds": 600.0,
        "python_version": PYTHON_VERSION,
        "openrouter_sdk_versions": {
            "v1-v4": HISTORICAL_OPENROUTER_VERSION,
            "v5": V5_OPENROUTER_VERSION,
        },
        "v5_catalogue_adapter": V5_CATALOGUE_ADAPTER,
        "runs": runs,
        "planned_cells": [
            {"model": model, "run": run.name} for model, run in _planned_cells()
        ],
    }


def _cell_path(root: Path, model: str, run: OpusRun) -> Path:
    return root / MODEL_OUTPUT_NAMES[model] / run.name


def _validate_cell(path: Path, model: str, run: OpusRun) -> None:
    validate_manifest(path / "manifest.json", run, model)
    validate_sessions(path / "sessions.jsonl", run, model)
    if not (path / "responses.jsonl").is_file():
        raise OpusMatrixError(f"{path}: responses.jsonl is missing")


def validate_output(output: Path) -> None:
    protocol_path = output / "protocol.json"
    protocol = _manifest(protocol_path)
    if protocol != _protocol():
        raise OpusMatrixError(f"{protocol_path}: protocol does not match the frozen matrix")
    for model, run in _planned_cells():
        _validate_cell(_cell_path(output, model, run), model, run)


def _planned_by_key() -> dict[str, tuple[str, OpusRun]]:
    return {_cell_key(model, run): (model, run) for model, run in _planned_cells()}


def promote_cell(matrix: Path, cell: str, output: Path) -> None:
    protocol_path = matrix / "protocol.json"
    if _manifest(protocol_path) != _protocol():
        raise OpusMatrixError(f"{protocol_path}: protocol does not match the frozen matrix")
    planned_by_key = _planned_by_key()
    if cell not in planned_by_key:
        raise OpusMatrixError(f"unknown Opus cell: {cell}")
    if output.exists():
        raise OpusMatrixError(f"output already exists: {output}")
    model, run = planned_by_key[cell]
    source = _cell_path(matrix, model, run)
    _validate_cell(source, model, run)
    promotion = output.parent / "in-progress" / f"{output.name}-promotion"
    if promotion.exists():
        raise OpusMatrixError(f"promotion directory already exists: {promotion}")
    promotion.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, promotion)
    _validate_cell(promotion, model, run)
    shutil.move(promotion, output)


def _unique_incomplete_destination(output: Path, model: str, run: OpusRun) -> Path:
    root = output.parent / "incomplete" / f"{output.name}-incomplete-cells"
    root.mkdir(parents=True, exist_ok=True)
    name = f"{MODEL_OUTPUT_NAMES[model]}-{run.name}"
    destination = root / name
    attempt = 1
    while destination.exists():
        attempt += 1
        destination = root / f"{name}-attempt-{attempt}"
    return destination


def _remove_worktree(repo: Path, worktree: Path) -> None:
    subprocess.run(
        ("git", "worktree", "remove", "--force", str(worktree)),
        cwd=repo,
        check=True,
    )


def _prepare_locked_python(worktree: Path, expected_openrouter: str) -> Path:
    check = (
        "import importlib.metadata, sys; "
        f"assert sys.version_info[:2] == (3, 12); "
        f"assert importlib.metadata.version('openrouter') == {expected_openrouter!r}"
    )
    subprocess.run(
        (
            "uv",
            "run",
            "--frozen",
            "--extra",
            "llm",
            "--python",
            PYTHON_VERSION,
            "python",
            "-c",
            check,
        ),
        cwd=worktree,
        check=True,
    )
    python = worktree / ".venv" / "bin" / "python"
    if not python.is_file():
        raise OpusMatrixError(f"locked Python executable is missing: {python}")
    return python


def _preflight_locked_models(
    python: Path,
    worktree: Path,
    models: tuple[str, ...],
    environment: dict[str, str],
    *,
    use_v5_adapter: bool = False,
) -> None:
    setup = "import benchmarks.tutorials as tutorials\n"
    if use_v5_adapter:
        setup += V5_CATALOGUE_ADAPTER_CODE
    code = setup + (
        "import asyncio, os\n"
        "asyncio.run(tutorials.preflight_openrouter_models("
        f"{models!r}, {OPENROUTER_HOST!r}, os.environ['OPENROUTER_API_KEY']))\n"
    )
    locked_environment = environment.copy()
    locked_environment["PYTHONPATH"] = str(worktree / "src")
    subprocess.run(
        (str(python), "-c", code),
        cwd=worktree,
        env=locked_environment,
        check=True,
    )


def _benchmark_command(
    python: Path,
    arguments: tuple[str, ...],
    *,
    use_v5_adapter: bool,
) -> tuple[str, ...]:
    if not use_v5_adapter:
        return (str(python), *arguments)
    code = (
        "import benchmarks.tutorials as tutorials\n"
        + V5_CATALOGUE_ADAPTER_CODE
        + "raise SystemExit(tutorials.main())\n"
    )
    return (str(python), "-c", code, *arguments[2:])


def _relocate_superseded_empty_staging(output: Path, staging: Path) -> None:
    artifact_entries = tuple(path for path in staging.rglob("*") if not path.is_dir())
    if artifact_entries != (staging / "protocol.json",):
        raise OpusMatrixError(f"{staging}: in-progress protocol differs; inspect it")
    root = output.parent / "incomplete" / f"{output.name}-incomplete-ledgers"
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "preflight-only"
    attempt = 1
    while destination.exists():
        attempt += 1
        destination = root / f"preflight-only-attempt-{attempt}"
    shutil.move(staging, destination)


def preflight_environments(repo: Path) -> None:
    validate_references(repo)
    validate_dependency_locks(repo)
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise OpusMatrixError("OPENROUTER_API_KEY is required")
    temporary_root = Path(tempfile.mkdtemp(prefix="bunnyland-opus-preflight-"))
    worktrees: list[Path] = []
    try:
        for run in (OPUS_RUNS[0], OPUS_RUNS[-1]):
            worktree = temporary_root / run.commit[:8]
            subprocess.run(
                ("git", "worktree", "add", "--detach", str(worktree), run.commit),
                cwd=repo,
                check=True,
            )
            worktrees.append(worktree)
        historical_python = _prepare_locked_python(
            worktrees[0],
            HISTORICAL_OPENROUTER_VERSION,
        )
        v5_python = _prepare_locked_python(
            worktrees[1],
            V5_OPENROUTER_VERSION,
        )
        environment = os.environ.copy()
        _preflight_locked_models(
            historical_python,
            worktrees[0],
            (OPUS_48_MODEL,),
            environment,
        )
        _preflight_locked_models(
            v5_python,
            worktrees[1],
            (OPUS_48_MODEL, OPUS_5_MODEL),
            environment,
            use_v5_adapter=True,
        )
    finally:
        for worktree in reversed(worktrees):
            _remove_worktree(repo, worktree)
        shutil.rmtree(temporary_root)


def run_matrix(
    repo: Path,
    output: Path,
    only_cells: tuple[str, ...] = (),
) -> None:
    validate_references(repo)
    validate_dependency_locks(repo)
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise OpusMatrixError("OPENROUTER_API_KEY is required")
    if output.exists():
        raise OpusMatrixError(f"output already exists: {output}")
    planned_by_key = _planned_by_key()
    unknown = sorted(set(only_cells) - set(planned_by_key))
    if unknown:
        raise OpusMatrixError(f"unknown Opus cell(s): {', '.join(unknown)}")
    execution_plan = (
        tuple(planned_by_key[key] for key in dict.fromkeys(only_cells))
        if only_cells
        else _planned_cells()
    )

    staging = output.parent / "in-progress" / output.name
    if staging.exists():
        protocol = _manifest(staging / "protocol.json")
        if protocol != _protocol():
            _relocate_superseded_empty_staging(output, staging)
    if not staging.exists():
        staging.mkdir(parents=True)
        (staging / "protocol.json").write_text(
            json.dumps(_protocol(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    temporary_root = Path(tempfile.mkdtemp(prefix="bunnyland-opus-matrix-"))
    worktrees: dict[str, Path] = {}
    try:
        for commit in dict.fromkeys(run.commit for run in OPUS_RUNS):
            worktree = temporary_root / commit[:8]
            subprocess.run(
                ("git", "worktree", "add", "--detach", str(worktree), commit),
                cwd=repo,
                check=True,
            )
            worktrees[commit] = worktree
        historical_python = _prepare_locked_python(
            worktrees[OPUS_RUNS[0].commit],
            HISTORICAL_OPENROUTER_VERSION,
        )
        v5_python = _prepare_locked_python(
            worktrees[OPUS_RUNS[-1].commit],
            V5_OPENROUTER_VERSION,
        )
        environment = os.environ.copy()
        _preflight_locked_models(
            historical_python,
            worktrees[OPUS_RUNS[0].commit],
            (OPUS_48_MODEL,),
            environment,
        )
        _preflight_locked_models(
            v5_python,
            worktrees[OPUS_RUNS[-1].commit],
            (OPUS_48_MODEL, OPUS_5_MODEL),
            environment,
            use_v5_adapter=True,
        )
        for model, run in execution_plan:
            destination = _cell_path(staging, model, run)
            if destination.exists():
                try:
                    _validate_cell(destination, model, run)
                    continue
                except (FileNotFoundError, json.JSONDecodeError, OpusMatrixError):
                    shutil.move(
                        destination,
                        _unique_incomplete_destination(output, model, run),
                    )
            worktree = worktrees[run.commit]
            python = v5_python if run is OPUS_RUNS[-1] else historical_python
            environment["PYTHONPATH"] = str(worktree / "src")
            try:
                subprocess.run(
                    _benchmark_command(
                        python,
                        benchmark_arguments(run, model, destination),
                        use_v5_adapter=run is OPUS_RUNS[-1],
                    ),
                    cwd=worktree,
                    env=environment,
                    check=True,
                )
                _validate_cell(destination, model, run)
            except (
                subprocess.CalledProcessError,
                FileNotFoundError,
                json.JSONDecodeError,
                OpusMatrixError,
            ) as error:
                if destination.exists():
                    shutil.move(
                        destination,
                        _unique_incomplete_destination(output, model, run),
                    )
                raise OpusMatrixError(
                    f"exact Opus cell failed and remains incomplete: "
                    f"{model}/{run.name}"
                ) from error
    finally:
        for worktree in reversed(tuple(worktrees.values())):
            _remove_worktree(repo, worktree)
        shutil.rmtree(temporary_root)

    if only_cells:
        for model, run in execution_plan:
            _validate_cell(_cell_path(staging, model, run), model, run)
    else:
        validate_output(staging)
        shutil.move(staging, output)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-reference")
    subparsers.add_parser("preflight")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--output", required=True, type=Path)
    run_parser.add_argument("--only-cell", action="append", default=[])
    validate_parser = subparsers.add_parser("validate-output")
    validate_parser.add_argument("--output", required=True, type=Path)
    promote_parser = subparsers.add_parser("promote-cell")
    promote_parser.add_argument("--matrix", required=True, type=Path)
    promote_parser.add_argument("--cell", required=True)
    promote_parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo = Path(__file__).resolve().parent.parent
    if args.command == "validate-reference":
        validate_references(repo)
        return
    if args.command == "validate-output":
        validate_output(args.output.resolve())
        return
    if args.command == "promote-cell":
        promote_cell(args.matrix.resolve(), args.cell, args.output.resolve())
        return
    if args.command == "preflight":
        preflight_environments(repo)
        return
    run_matrix(repo, args.output.resolve(), tuple(args.only_cell))


if __name__ == "__main__":
    main()
