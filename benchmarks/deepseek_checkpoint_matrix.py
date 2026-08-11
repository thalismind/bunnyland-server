"""Run frozen DeepSeek checkpoint and Ollama Cloud tutorial cohorts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REFERENCE_MODEL = "deepseek-v4-flash:cloud"
DEFAULT_CANDIDATE_MODEL = "deepseek-v4-flash:0731-cloud"
OLLAMA_CLOUD_HOST = "https://ollama.com"
OLLAMA_LOCAL_HOST = "http://127.0.0.1:11435"
V5_SEED_MODELS = (REFERENCE_MODEL, DEFAULT_CANDIDATE_MODEL)
HISTORICAL_OLLAMA_CLOUD_MODELS = (
    REFERENCE_MODEL,
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
V5_CLOUD_PRE_RETIREMENT_MODELS = V5_SEED_MODELS + tuple(
    model for model in HISTORICAL_OLLAMA_CLOUD_MODELS if model != REFERENCE_MODEL
)
V5_CLOUD_RETIRED_MODELS = ("kimi-k2.5",)
V5_CLOUD_RUNTIME_FAILED_MODELS = (
    "mistral-large-3:675b-cloud",
    "qwen3.5:397b-cloud",
    "qwen3.5:cloud",
)
V5_CLOUD_UNAVAILABLE_MODELS = V5_CLOUD_RETIRED_MODELS + V5_CLOUD_RUNTIME_FAILED_MODELS
V5_MODELS = tuple(
    model for model in V5_CLOUD_PRE_RETIREMENT_MODELS if model not in V5_CLOUD_UNAVAILABLE_MODELS
)
V5_ROSTER_MANIFESTS = (
    "artifacts/benchmarks/tutorials/cloud-full-15-model-comparison-2026-07-24/manifest.json",
    "artifacts/benchmarks/tutorials/server-3a662413-cloud-full-cohort-2026-07-25/manifest.json",
    "artifacts/benchmarks/tutorials/server-a6dc9644-cloud-bell-cohort-2026-07-25/manifest.json",
    "artifacts/benchmarks/tutorials/server-0abb32b-cloud-bell-cohort-2026-07-26/manifest.json",
    "artifacts/benchmarks/tutorials/v1-5b33e2a-kimi-k2-5-cloud-2026-07-27/manifest.json",
)
HISTORICAL_OLLAMA_LOCAL_MODELS = (
    "LESSTHANSUPER/RP-INK-Qwen2.5-32b:Q5_K_S",
    "bunnyland-rpmax-llama3.1-8b-q8-tools:latest",
    "bunnyland-stheno-llama3.1-8b-q8-tools:latest",
    "hf.co/Bahushruth/Qwen3.6-35B-A3B-abliterated-v4-GGUF:Q4_K_M",
    "hf.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF:Q4_K_M",
    "hf.co/HauhauCS/Gemma4-31B-QAT-Uncensored-HauhauCS-Balanced-MTP:Q4_K_M",
    "hf.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive:Q4_K_M",
    "hf.co/LuffyTheFox/Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-V5-GGUF:Q8_0",
    "hf.co/bartowski/NousResearch_Hermes-4-14B-GGUF:Q8_0",
    "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:Q8_0",
    "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K",
    "laguna-xs-2.1:latest",
    "ornith:35b",
    "ornith:9b",
    "qwen3.5:4b",
    "qwen3.5:9b",
    "qwen3.6:35b-a3b",
)
V5_LOCAL_NOT_INSTALLED_MODELS = (
    "hf.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF:Q4_K_M",
)
V5_LOCAL_UNSUPPORTED_THINKING_MODELS = (
    "LESSTHANSUPER/RP-INK-Qwen2.5-32b:Q5_K_S",
    "bunnyland-rpmax-llama3.1-8b-q8-tools:latest",
    "bunnyland-stheno-llama3.1-8b-q8-tools:latest",
    "hf.co/Bahushruth/Qwen3.6-35B-A3B-abliterated-v4-GGUF:Q4_K_M",
    "hf.co/HauhauCS/Gemma4-31B-QAT-Uncensored-HauhauCS-Balanced-MTP:Q4_K_M",
    "hf.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive:Q4_K_M",
    "hf.co/LuffyTheFox/Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-V5-GGUF:Q8_0",
    "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:Q8_0",
    "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K",
)
V5_LOCAL_RUNTIME_VALIDATED_MODELS = (
    "hf.co/Bahushruth/Qwen3.6-35B-A3B-abliterated-v4-GGUF:Q4_K_M",
    "hf.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive:Q4_K_M",
    "hf.co/LuffyTheFox/Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-V5-GGUF:Q8_0",
    "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K",
)
V5_LOCAL_RUNTIME_FAILED_MODELS = (
    "LESSTHANSUPER/RP-INK-Qwen2.5-32b:Q5_K_S",
    "bunnyland-rpmax-llama3.1-8b-q8-tools:latest",
    "bunnyland-stheno-llama3.1-8b-q8-tools:latest",
    "hf.co/HauhauCS/Gemma4-31B-QAT-Uncensored-HauhauCS-Balanced-MTP:Q4_K_M",
    "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:Q8_0",
)
V5_LOCAL_PRE_RUNTIME_MODELS = tuple(
    model
    for model in HISTORICAL_OLLAMA_LOCAL_MODELS
    if model
    not in V5_LOCAL_NOT_INSTALLED_MODELS + V5_LOCAL_UNSUPPORTED_THINKING_MODELS
)
V5_LOCAL_UNAVAILABLE_MODELS = (
    V5_LOCAL_NOT_INSTALLED_MODELS + V5_LOCAL_RUNTIME_FAILED_MODELS
)
V5_LOCAL_MODELS = tuple(
    model for model in HISTORICAL_OLLAMA_LOCAL_MODELS if model not in V5_LOCAL_UNAVAILABLE_MODELS
)
V5_LOCAL_ROSTER_MANIFESTS = (
    "artifacts/benchmarks/tutorials/server-3a662413-local-full-cohort-2026-07-25/manifest.json",
    "artifacts/benchmarks/tutorials/server-0abb32b-local-bell-cohort-2026-07-26/manifest.json",
    "artifacts/benchmarks/tutorials/v4-0abb32b-gemma4-31b-hauhaucs-balanced-q4-k-m-2026-07-27/manifest.json",
    "artifacts/benchmarks/tutorials/v4-0abb32b-hermes-4-14b-q8-0-2026-07-28/manifest.json",
    "artifacts/benchmarks/tutorials/v4-0abb32b-llama3-1-8b-arli-rpmax-v1-3-q8-0-2026-07-27/manifest.json",
    "artifacts/benchmarks/tutorials/v4-0abb32b-llama3-1-8b-stheno-v3-4-q8-0-2026-07-27/manifest.json",
    "artifacts/benchmarks/tutorials/v4-0abb32b-ornith-35b-2026-07-27/manifest.json",
    "artifacts/benchmarks/tutorials/v4-0abb32b-ornith-9b-2026-07-27/manifest.json",
    "artifacts/benchmarks/tutorials/v4-0abb32b-rp-ink-qwen2-5-32b-q5-k-s-2026-07-28/manifest.json",
    "artifacts/benchmarks/tutorials/server-c3f2729-qwen3-5-4b-hauhaucs-aggressive-q4-k-m-2026-07-26/manifest.json",
    "artifacts/benchmarks/tutorials/server-c3f2729-qwen3-5-9b-defiant-fable-q4-k-m-2026-07-26/manifest.json",
    "artifacts/benchmarks/tutorials/server-c3f2729-qwen3-6-35b-a3b-bahushruth-abliterated-v4-q4-k-m-2026-07-26/manifest.json",
    "artifacts/benchmarks/tutorials/server-c3f2729-qwen3-6-35b-a3b-genesis-hermes-v5-q8-0-2026-07-26/manifest.json",
)
V5_DESCRIPTION_COMMITS = (
    "30bab131448a449606a059edd1aedf56c726cbd9",
    "ea45eb61268aa47897694d67c9c01722c69d240a",
)


@dataclass(frozen=True)
class MatrixRun:
    name: str
    cohort: str
    commit: str
    schema_version: int
    tutorials: tuple[str, ...]
    reference_manifest: str
    log_thinking: bool
    repeat_command_guard: bool
    provider_session_retries: int | None
    seed_helpful_memory: bool | None


MATRIX_RUNS = (
    MatrixRun(
        name="v1-all",
        cohort="v1",
        commit="fc3ec38db6c1ae0e14323bdcb31f4d0614c0b2d0",
        schema_version=5,
        tutorials=("apple", "bell", "clover"),
        reference_manifest=(
            "artifacts/benchmarks/tutorials/cloud-registry-thinking-5x-2026-07-23/manifest.json"
        ),
        log_thinking=True,
        repeat_command_guard=True,
        provider_session_retries=None,
        seed_helpful_memory=None,
    ),
    MatrixRun(
        name="v2-apple-bell",
        cohort="v2",
        commit="3a662413e64e28ae3852a17dde10ea73d2c22f67",
        schema_version=6,
        tutorials=("apple", "bell"),
        reference_manifest=(
            "artifacts/benchmarks/tutorials/"
            "server-3a662413-deepseek-v4-flash-cloud-apple-bell-2026-07-25/"
            "manifest.json"
        ),
        log_thinking=True,
        repeat_command_guard=True,
        provider_session_retries=None,
        seed_helpful_memory=None,
    ),
    MatrixRun(
        name="v2-clover",
        cohort="v2",
        commit="3a662413e64e28ae3852a17dde10ea73d2c22f67",
        schema_version=6,
        tutorials=("clover",),
        reference_manifest=(
            "artifacts/benchmarks/tutorials/"
            "server-3a662413-deepseek-v4-flash-cloud-clover-2026-07-24/"
            "manifest.json"
        ),
        log_thinking=True,
        repeat_command_guard=True,
        provider_session_retries=None,
        seed_helpful_memory=None,
    ),
    MatrixRun(
        name="v3-bell",
        cohort="v3",
        commit="a6dc96449c3d023cc7d1f1944278eb93c62306f4",
        schema_version=6,
        tutorials=("bell",),
        reference_manifest=(
            "artifacts/benchmarks/tutorials/"
            "server-a6dc9644-bell-unseeded-deepseek-v4-flash-cloud-2026-07-25/"
            "manifest.json"
        ),
        log_thinking=False,
        repeat_command_guard=False,
        provider_session_retries=8,
        seed_helpful_memory=False,
    ),
    MatrixRun(
        name="v4-bell",
        cohort="v4",
        commit="0abb32bd0b8da1f20c50fb838416cc85c61cb21b",
        schema_version=6,
        tutorials=("bell",),
        reference_manifest=(
            "artifacts/benchmarks/tutorials/"
            "server-0abb32b-bell-explicit-mail-deepseek-v4-flash-cloud-2026-07-26/"
            "manifest.json"
        ),
        log_thinking=False,
        repeat_command_guard=False,
        provider_session_retries=0,
        seed_helpful_memory=False,
    ),
)

V5_RUN = MatrixRun(
    name="v5-bell",
    cohort="v5",
    commit="00c46639b8877646d02484621f8d1861e38314ec",
    schema_version=6,
    tutorials=("bell",),
    reference_manifest=MATRIX_RUNS[-1].reference_manifest,
    log_thinking=False,
    repeat_command_guard=False,
    provider_session_retries=0,
    seed_helpful_memory=False,
)

V5_OUTPUT_NAMES = {
    REFERENCE_MODEL: "deepseek-v4-flash-cloud",
    DEFAULT_CANDIDATE_MODEL: "deepseek-v4-flash-0731-cloud",
    "deepseek-v4-pro:cloud": "deepseek-v4-pro-cloud",
    "gemma4:cloud": "gemma4-cloud",
    "glm-5.2:cloud": "glm-5-2-cloud",
    "gpt-oss:120b-cloud": "gpt-oss-120b-cloud",
    "gpt-oss:20b-cloud": "gpt-oss-20b-cloud",
    "kimi-k2.5": "kimi-k2-5",
    "kimi-k2.6:cloud": "kimi-k2-6-cloud",
    "kimi-k2.7-code:cloud": "kimi-k2-7-code-cloud",
    "minimax-m2.7:cloud": "minimax-m2-7-cloud",
    "minimax-m3:cloud": "minimax-m3-cloud",
    "mistral-large-3:675b-cloud": "mistral-large-3-675b-cloud",
    "nemotron-3-nano:30b-cloud": "nemotron-3-nano-30b-cloud",
    "nemotron-3-super:cloud": "nemotron-3-super-cloud",
    "nemotron-3-ultra:cloud": "nemotron-3-ultra-cloud",
    "qwen3.5:397b-cloud": "qwen3-5-397b-cloud",
    "qwen3.5:cloud": "qwen3-5-cloud",
}
V5_LOCAL_OUTPUT_NAMES = {
    "LESSTHANSUPER/RP-INK-Qwen2.5-32b:Q5_K_S": "rp-ink-qwen2-5-32b-q5-k-s",
    "bunnyland-rpmax-llama3.1-8b-q8-tools:latest": "rpmax-llama3-1-8b-q8-tools",
    "bunnyland-stheno-llama3.1-8b-q8-tools:latest": "stheno-llama3-1-8b-q8-tools",
    "hf.co/Bahushruth/Qwen3.6-35B-A3B-abliterated-v4-GGUF:Q4_K_M": (
        "qwen3-6-35b-a3b-bahushruth-q4-k-m"
    ),
    "hf.co/HauhauCS/Gemma4-31B-QAT-Uncensored-HauhauCS-Balanced-MTP:Q4_K_M": (
        "gemma4-31b-hauhaucs-q4-k-m"
    ),
    "hf.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive:Q4_K_M": (
        "qwen3-5-4b-hauhaucs-q4-k-m"
    ),
    "hf.co/LuffyTheFox/Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-V5-GGUF:Q8_0": (
        "qwen3-6-35b-a3b-luffy-q8-0"
    ),
    "hf.co/bartowski/NousResearch_Hermes-4-14B-GGUF:Q8_0": "hermes-4-14b-q8-0",
    "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:Q8_0": "qwen3-6-35b-a3b-q8-0",
    "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K": "qwen3-6-35b-a3b-ud-q6-k",
    "laguna-xs-2.1:latest": "laguna-xs-2-1",
    "ornith:35b": "ornith-35b",
    "ornith:9b": "ornith-9b",
    "qwen3.5:4b": "qwen3-5-4b",
    "qwen3.5:9b": "qwen3-5-9b",
    "qwen3.6:35b-a3b": "qwen3-6-35b-a3b",
}


class MatrixValidationError(RuntimeError):
    """A reference or candidate manifest does not match the frozen matrix."""


def _manifest(path: Path) -> dict[str, object]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise MatrixValidationError(f"manifest must be an object: {path}")
    return raw


def _models(value: object, path: Path) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise MatrixValidationError(f"manifest models must be an array: {path}")
    models = []
    for raw_model in value:
        if not isinstance(raw_model, dict):
            raise MatrixValidationError(f"manifest model must be an object: {path}")
        model = raw_model.get("model")
        if not isinstance(model, str):
            raise MatrixValidationError(f"manifest model id must be a string: {path}")
        models.append(model)
    return tuple(models)


def validate_manifest(
    path: Path,
    run: MatrixRun,
    model: str,
    *,
    provider: str = "ollama-cloud",
    host: str = OLLAMA_CLOUD_HOST,
) -> None:
    manifest = _manifest(path)
    expected: dict[str, object] = {
        "commit": run.commit,
        "provider": provider,
        "host": host,
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
    }
    for key, expected_value in expected.items():
        actual = manifest.get(key)
        if actual != expected_value:
            raise MatrixValidationError(f"{path}: {key} is {actual!r}, expected {expected_value!r}")
    if model not in _models(manifest.get("models"), path):
        raise MatrixValidationError(f"{path}: model {model!r} is missing")


def validate_session_records(path: Path, run: MatrixRun, model: str) -> None:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw: object = json.loads(line)
        if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
            raise MatrixValidationError(f"{path}:{line_number}: session record must be an object")
        records.append(raw)

    expected_cells = {
        (tutorial, run_number) for tutorial in run.tutorials for run_number in range(1, 6)
    }
    actual_cells: set[tuple[str, int]] = set()
    for record in records:
        tutorial = record.get("tutorial")
        run_number = record.get("run")
        if not isinstance(tutorial, str) or not isinstance(run_number, int):
            raise MatrixValidationError(f"{path}: session tutorial/run is invalid")
        if record.get("model") != model:
            raise MatrixValidationError(f"{path}: session model does not match {model!r}")
        actual_cells.add((tutorial, run_number))

    if len(records) != len(expected_cells) or actual_cells != expected_cells:
        raise MatrixValidationError(
            f"{path}: session cells are {sorted(actual_cells)!r}, "
            f"expected {sorted(expected_cells)!r}"
        )


def benchmark_arguments(run: MatrixRun, model: str, output: Path) -> tuple[str, ...]:
    arguments = [
        "-m",
        "benchmarks.tutorials",
        "--provider",
        "ollama-cloud",
        "--host",
        OLLAMA_CLOUD_HOST,
        "--model",
        model,
    ]
    for tutorial in run.tutorials:
        arguments.extend(("--tutorial", tutorial))
    arguments.extend(
        (
            "--sessions",
            "5",
            "--session-timeout",
            "3600",
            "--turn-limit",
            "60",
            "--thinking",
            "high",
        )
    )
    if run.log_thinking:
        arguments.append("--log-thinking")
    if run.repeat_command_guard:
        arguments.append("--repeat-command-guard")
    if run.provider_session_retries is not None:
        arguments.extend(("--provider-session-retries", str(run.provider_session_retries)))
    if run.seed_helpful_memory:
        arguments.append("--seed-helpful-memory")
    arguments.extend(("--output", str(output)))
    return tuple(arguments)


def local_benchmark_arguments(run: MatrixRun, model: str, output: Path) -> tuple[str, ...]:
    arguments = list(benchmark_arguments(run, model, output))
    arguments[arguments.index("ollama-cloud")] = "ollama-local"
    arguments[arguments.index(OLLAMA_CLOUD_HOST)] = OLLAMA_LOCAL_HOST
    return tuple(arguments)


def validate_references(repo: Path) -> None:
    for run in MATRIX_RUNS:
        validate_manifest(repo / run.reference_manifest, run, REFERENCE_MODEL)


def validate_output(output: Path, model: str) -> None:
    for run in MATRIX_RUNS:
        destination = output / run.name
        validate_manifest(destination / "manifest.json", run, model)
        validate_session_records(destination / "sessions.jsonl", run, model)


def _v5_protocol(models: tuple[str, ...] = V5_MODELS) -> dict[str, object]:
    protocol: dict[str, object] = {
        "schema_version": 1,
        "cohort": V5_RUN.cohort,
        "purpose": "action-description-rewrite",
        "server_commit": V5_RUN.commit,
        "harness_commit": V5_RUN.commit,
        "baseline_commit": MATRIX_RUNS[-1].commit,
        "description_commits": list(V5_DESCRIPTION_COMMITS),
        "models": list(models),
        "provider": "ollama-cloud",
        "host": OLLAMA_CLOUD_HOST,
        "tutorials": list(V5_RUN.tutorials),
        "sessions_per_model_tutorial": 5,
        "thinking": "high",
        "temperature": None,
        "max_output_tokens": None,
        "log_thinking": V5_RUN.log_thinking,
        "repeat_command_guard": V5_RUN.repeat_command_guard,
        "provider_session_retries": V5_RUN.provider_session_retries,
        "seed_helpful_memory": V5_RUN.seed_helpful_memory,
        "session_timeout_seconds": 3600.0,
        "turn_limit": 60,
        "turn_game_seconds": 600.0,
        "artifact_schema_version": V5_RUN.schema_version,
    }
    if models == V5_MODELS:
        protocol["historical_models"] = list(HISTORICAL_OLLAMA_CLOUD_MODELS)
        protocol["unavailable_models"] = list(V5_CLOUD_UNAVAILABLE_MODELS)
        protocol["retired_models"] = list(V5_CLOUD_RETIRED_MODELS)
        protocol["runtime_failed_models"] = list(V5_CLOUD_RUNTIME_FAILED_MODELS)
    return protocol


def validate_v5_roster(repo: Path) -> None:
    historical_models: set[str] = set()
    for relative_path in V5_ROSTER_MANIFESTS:
        path = repo / relative_path
        manifest = _manifest(path)
        if manifest.get("provider") != "ollama-cloud":
            raise MatrixValidationError(f"{path}: expected ollama-cloud provider")
        historical_models.update(_models(manifest.get("models"), path))
    expected = set(HISTORICAL_OLLAMA_CLOUD_MODELS)
    if historical_models != expected:
        raise MatrixValidationError(
            f"historical Ollama Cloud roster is {sorted(historical_models)!r}, "
            f"expected {sorted(expected)!r}"
        )


def validate_v5_local_roster(repo: Path) -> None:
    historical_models: set[str] = set()
    for relative_path in V5_LOCAL_ROSTER_MANIFESTS:
        path = repo / relative_path
        manifest = _manifest(path)
        if manifest.get("provider") != "ollama-local":
            raise MatrixValidationError(f"{path}: expected ollama-local provider")
        historical_models.update(_models(manifest.get("models"), path))
    expected = set(HISTORICAL_OLLAMA_LOCAL_MODELS)
    if historical_models != expected:
        raise MatrixValidationError(
            f"historical Ollama Local roster is {sorted(historical_models)!r}, "
            f"expected {sorted(expected)!r}"
        )


def _installed_local_model_capabilities() -> dict[str, set[str]]:
    with urllib.request.urlopen(f"{OLLAMA_LOCAL_HOST}/api/tags", timeout=30) as response:
        raw: object = json.loads(response.read())
    if not isinstance(raw, dict):
        raise MatrixValidationError("Ollama Local tags response must be an object")
    models = raw.get("models")
    if not isinstance(models, list):
        raise MatrixValidationError("Ollama Local tags response must contain a models array")
    installed: dict[str, set[str]] = {}
    for item in models:
        if not isinstance(item, dict):
            raise MatrixValidationError("Ollama Local tag must be an object")
        model = item.get("model")
        if not isinstance(model, str):
            raise MatrixValidationError("Ollama Local model id must be a string")
        raw_capabilities = item.get("capabilities")
        if not isinstance(raw_capabilities, list) or not all(
            isinstance(capability, str) for capability in raw_capabilities
        ):
            raise MatrixValidationError("Ollama Local capabilities must be a string array")
        installed[model] = set(raw_capabilities)
    return installed


def _v5_local_protocol() -> dict[str, object]:
    return {
        "schema_version": 1,
        "cohort": V5_RUN.cohort,
        "purpose": "action-description-rewrite-local-panel",
        "server_commit": V5_RUN.commit,
        "harness_commit": V5_RUN.commit,
        "baseline_commit": MATRIX_RUNS[-1].commit,
        "description_commits": list(V5_DESCRIPTION_COMMITS),
        "models": list(V5_LOCAL_MODELS),
        "historical_models": list(HISTORICAL_OLLAMA_LOCAL_MODELS),
        "unavailable_models": list(V5_LOCAL_UNAVAILABLE_MODELS),
        "not_installed_models": list(V5_LOCAL_NOT_INSTALLED_MODELS),
        "unsupported_thinking_models": list(V5_LOCAL_UNSUPPORTED_THINKING_MODELS),
        "runtime_validated_models": list(V5_LOCAL_RUNTIME_VALIDATED_MODELS),
        "runtime_failed_models": list(V5_LOCAL_RUNTIME_FAILED_MODELS),
        "provider": "ollama-local",
        "host": OLLAMA_LOCAL_HOST,
        "tutorials": list(V5_RUN.tutorials),
        "sessions_per_model_tutorial": 5,
        "thinking": "high",
        "temperature": None,
        "max_output_tokens": None,
        "log_thinking": V5_RUN.log_thinking,
        "repeat_command_guard": V5_RUN.repeat_command_guard,
        "provider_session_retries": V5_RUN.provider_session_retries,
        "seed_helpful_memory": V5_RUN.seed_helpful_memory,
        "session_timeout_seconds": 3600.0,
        "turn_limit": 60,
        "turn_game_seconds": 600.0,
        "artifact_schema_version": V5_RUN.schema_version,
    }


def validate_v5_local_output(output: Path) -> None:
    protocol_path = output / "protocol.json"
    protocol = _manifest(protocol_path)
    expected_protocol = _v5_local_protocol()
    if protocol != expected_protocol:
        raise MatrixValidationError(
            f"{protocol_path}: protocol is {protocol!r}, expected {expected_protocol!r}"
        )
    for model in V5_LOCAL_MODELS:
        destination = output / V5_LOCAL_OUTPUT_NAMES[model]
        manifest_path = destination / "manifest.json"
        manifest = _manifest(manifest_path)
        if _models(manifest.get("models"), manifest_path) != (model,):
            raise MatrixValidationError(f"{manifest_path}: expected only model {model!r}")
        validate_manifest(
            manifest_path,
            V5_RUN,
            model,
            provider="ollama-local",
            host=OLLAMA_LOCAL_HOST,
        )
        validate_session_records(destination / "sessions.jsonl", V5_RUN, model)
        if not (destination / "responses.jsonl").is_file():
            raise MatrixValidationError(f"{destination}: responses.jsonl is missing")


def _validate_v5_output(output: Path, models: tuple[str, ...]) -> None:
    protocol_path = output / "protocol.json"
    protocol = _manifest(protocol_path)
    expected_protocol = _v5_protocol(models)
    if protocol != expected_protocol:
        raise MatrixValidationError(
            f"{protocol_path}: protocol is {protocol!r}, expected {expected_protocol!r}"
        )
    for model in models:
        destination = output / V5_OUTPUT_NAMES[model]
        manifest_path = destination / "manifest.json"
        manifest = _manifest(manifest_path)
        if _models(manifest.get("models"), manifest_path) != (model,):
            raise MatrixValidationError(f"{manifest_path}: expected only model {model!r}")
        validate_manifest(manifest_path, V5_RUN, model)
        validate_session_records(destination / "sessions.jsonl", V5_RUN, model)
        if not (destination / "responses.jsonl").is_file():
            raise MatrixValidationError(f"{destination}: responses.jsonl is missing")


def validate_v5_seed_output(output: Path) -> None:
    _validate_v5_output(output, V5_SEED_MODELS)


def validate_v5_output(output: Path) -> None:
    _validate_v5_output(output, V5_MODELS)


def python_executable(repo: Path, override: Path | None) -> Path:
    python = override or repo / ".venv" / "bin" / "python"
    return python.absolute()


def _remove_worktree(repo: Path, worktree: Path) -> None:
    subprocess.run(
        ("git", "worktree", "remove", "--force", str(worktree)),
        cwd=repo,
        check=True,
    )


def run_matrix(repo: Path, output: Path, model: str, python: Path) -> None:
    validate_references(repo)
    if not os.environ.get("OLLAMA_CLOUD_API_KEY"):
        raise MatrixValidationError("OLLAMA_CLOUD_API_KEY is required")
    if output.exists():
        raise MatrixValidationError(f"output already exists: {output}")
    if not python.is_file():
        raise MatrixValidationError(f"Python executable is missing: {python}")

    output.mkdir(parents=True)
    temporary_root = Path(tempfile.mkdtemp(prefix="bunnyland-checkpoint-matrix-"))
    worktrees: dict[str, Path] = {}
    try:
        for commit in dict.fromkeys(run.commit for run in MATRIX_RUNS):
            worktree = temporary_root / commit[:8]
            subprocess.run(
                ("git", "worktree", "add", "--detach", str(worktree), commit),
                cwd=repo,
                check=True,
            )
            worktrees[commit] = worktree

        for run in MATRIX_RUNS:
            worktree = worktrees[run.commit]
            destination = output / run.name
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(worktree / "src")
            subprocess.run(
                (str(python), *benchmark_arguments(run, model, destination)),
                cwd=worktree,
                env=environment,
                check=True,
            )
            validate_manifest(destination / "manifest.json", run, model)
            validate_session_records(destination / "sessions.jsonl", run, model)
    finally:
        for worktree in reversed(tuple(worktrees.values())):
            _remove_worktree(repo, worktree)
        shutil.rmtree(temporary_root)

    validate_output(output, model)


def run_v5(repo: Path, output: Path, python: Path) -> None:
    validate_manifest(
        repo / MATRIX_RUNS[-1].reference_manifest,
        MATRIX_RUNS[-1],
        REFERENCE_MODEL,
    )
    validate_v5_roster(repo)
    if not os.environ.get("OLLAMA_CLOUD_API_KEY"):
        raise MatrixValidationError("OLLAMA_CLOUD_API_KEY is required")
    if output.exists():
        raise MatrixValidationError(f"output already exists: {output}")
    if not python.is_file():
        raise MatrixValidationError(f"Python executable is missing: {python}")

    for description_commit in V5_DESCRIPTION_COMMITS:
        subprocess.run(
            ("git", "merge-base", "--is-ancestor", description_commit, V5_RUN.commit),
            cwd=repo,
            check=True,
        )

    output.mkdir(parents=True)
    (output / "protocol.json").write_text(
        json.dumps(_v5_protocol(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_root = Path(tempfile.mkdtemp(prefix="bunnyland-checkpoint-v5-"))
    worktree = temporary_root / V5_RUN.commit[:8]
    try:
        subprocess.run(
            ("git", "worktree", "add", "--detach", str(worktree), V5_RUN.commit),
            cwd=repo,
            check=True,
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(worktree / "src")
        for model in V5_MODELS:
            destination = output / V5_OUTPUT_NAMES[model]
            subprocess.run(
                (str(python), *benchmark_arguments(V5_RUN, model, destination)),
                cwd=worktree,
                env=environment,
                check=True,
            )
            validate_manifest(destination / "manifest.json", V5_RUN, model)
            validate_session_records(destination / "sessions.jsonl", V5_RUN, model)
    finally:
        if worktree.exists():
            _remove_worktree(repo, worktree)
        shutil.rmtree(temporary_root)

    validate_v5_output(output)


_CLOUD_AVAILABILITY_KEYS = {
    "historical_models",
    "models",
    "retired_models",
    "runtime_failed_models",
    "unavailable_models",
}
_LOCAL_AVAILABILITY_KEYS = {
    "historical_models",
    "models",
    "not_installed_models",
    "runtime_failed_models",
    "runtime_validated_models",
    "unsupported_thinking_models",
    "unavailable_models",
}


def _unique_destination(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    base = root / name
    destination = base
    attempt = 1
    while destination.exists():
        attempt += 1
        destination = root / f"{name}-attempt-{attempt}"
    return destination


def _quarantine_destination(output: Path, name: str) -> Path:
    return _unique_destination(
        output.parent / "quarantine" / f"{output.name}-parameter-mismatch",
        name,
    )


def _incomplete_destination(output: Path, name: str) -> Path:
    return _unique_destination(
        output.parent / "incomplete" / f"{output.name}-incomplete-cells",
        name,
    )


def _validate_v5_cell(
    destination: Path,
    model: str,
    *,
    provider: str,
    host: str,
) -> None:
    manifest_path = destination / "manifest.json"
    manifest = _manifest(manifest_path)
    if _models(manifest.get("models"), manifest_path) != (model,):
        raise MatrixValidationError(f"{manifest_path}: expected only model {model!r}")
    validate_manifest(manifest_path, V5_RUN, model, provider=provider, host=host)
    validate_session_records(destination / "sessions.jsonl", V5_RUN, model)
    if not (destination / "responses.jsonl").is_file():
        raise MatrixValidationError(f"{destination}: responses.jsonl is missing")


def _has_parameter_drift(
    destination: Path,
    model: str,
    *,
    provider: str,
    host: str,
) -> bool:
    manifest_path = destination / "manifest.json"
    try:
        manifest = _manifest(manifest_path)
        if _models(manifest.get("models"), manifest_path) != (model,):
            return True
        validate_manifest(manifest_path, V5_RUN, model, provider=provider, host=host)
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    except MatrixValidationError:
        return True
    return False


def _relocate_invalid_cell(
    destination: Path,
    output: Path,
    model: str,
    output_name: str,
    *,
    provider: str,
    host: str,
) -> None:
    if _has_parameter_drift(destination, model, provider=provider, host=host):
        target = _quarantine_destination(output, output_name)
    else:
        target = _incomplete_destination(output, output_name)
    shutil.move(destination, target)


def _protocol_base(protocol: dict[str, object], availability_keys: set[str]) -> dict[str, object]:
    return {key: value for key, value in protocol.items() if key not in availability_keys}


def _validate_v5_source(source: Path, *, local: bool) -> tuple[str, ...]:
    protocol_path = source / "protocol.json"
    protocol = _manifest(protocol_path)
    raw_models = protocol.get("models")
    if not isinstance(raw_models, list) or not all(isinstance(model, str) for model in raw_models):
        raise MatrixValidationError(f"{protocol_path}: models must be a string array")
    models = tuple(raw_models)
    if len(models) != len(set(models)):
        raise MatrixValidationError(f"{protocol_path}: models must be unique")

    if local:
        allowed_models = V5_LOCAL_MODELS
        availability_keys = _LOCAL_AVAILABILITY_KEYS
        expected_protocol = _v5_local_protocol()
        output_names = V5_LOCAL_OUTPUT_NAMES
        provider = "ollama-local"
        host = OLLAMA_LOCAL_HOST
        historical_models = HISTORICAL_OLLAMA_LOCAL_MODELS
    else:
        allowed_models = V5_MODELS
        availability_keys = _CLOUD_AVAILABILITY_KEYS
        expected_protocol = _v5_protocol()
        output_names = V5_OUTPUT_NAMES
        provider = "ollama-cloud"
        host = OLLAMA_CLOUD_HOST
        historical_models = HISTORICAL_OLLAMA_CLOUD_MODELS

    if not models or not set(models).issubset(allowed_models):
        raise MatrixValidationError(f"{protocol_path}: source models are not a v5 subset")
    if _protocol_base(protocol, availability_keys) != _protocol_base(
        expected_protocol, availability_keys
    ):
        raise MatrixValidationError(f"{protocol_path}: source experiment parameters differ")
    recorded_historical = protocol.get("historical_models")
    if recorded_historical is not None and recorded_historical != list(historical_models):
        raise MatrixValidationError(f"{protocol_path}: historical model roster differs")
    for model in models:
        _validate_v5_cell(
            source / output_names[model],
            model,
            provider=provider,
            host=host,
        )
    return models


def _prepare_staging(
    output: Path,
    protocol: dict[str, object],
    availability_keys: set[str],
) -> Path:
    staging = output.parent / "in-progress" / output.name
    if staging.exists():
        staged_protocol = _manifest(staging / "protocol.json")
        if _protocol_base(staged_protocol, availability_keys) != _protocol_base(
            protocol, availability_keys
        ):
            raise MatrixValidationError(
                f"{staging}: in-progress experiment parameters differ; inspect before quarantine"
            )
    else:
        staging.mkdir(parents=True)
    (staging / "protocol.json").write_text(
        json.dumps(protocol, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return staging


def _check_local_availability() -> None:
    capabilities = _installed_local_model_capabilities()
    installed = set(capabilities)
    missing = set(V5_LOCAL_MODELS) - installed
    if missing:
        raise MatrixValidationError(
            f"required Ollama Local models are missing: {sorted(missing)!r}"
        )
    required_capabilities = {"thinking", "tools"}
    unsupported = {
        model
        for model in V5_LOCAL_MODELS
        if model not in V5_LOCAL_RUNTIME_VALIDATED_MODELS
        if not required_capabilities.issubset(capabilities[model])
    }
    if unsupported:
        raise MatrixValidationError(
            "required Ollama Local models do not support tools and high thinking: "
            f"{sorted(unsupported)!r}"
        )
    unexpectedly_available = set(V5_LOCAL_NOT_INSTALLED_MODELS) & installed
    if unexpectedly_available:
        raise MatrixValidationError(
            "historical models marked not installed are now available; update the frozen local "
            f"panel before running: {sorted(unexpectedly_available)!r}"
        )
    unexpectedly_supported = {
        model
        for model in V5_LOCAL_RUNTIME_FAILED_MODELS
        if model in capabilities and required_capabilities.issubset(capabilities[model])
    }
    if unexpectedly_supported:
        raise MatrixValidationError(
            "historical models marked protocol-incompatible now support tools and thinking; "
            f"update the frozen local panel before running: {sorted(unexpectedly_supported)!r}"
        )


def _run_v5_cells(
    repo: Path,
    staging: Path,
    output: Path,
    models: tuple[str, ...],
    python: Path,
    *,
    local: bool,
) -> None:
    output_names = V5_LOCAL_OUTPUT_NAMES if local else V5_OUTPUT_NAMES
    provider = "ollama-local" if local else "ollama-cloud"
    host = OLLAMA_LOCAL_HOST if local else OLLAMA_CLOUD_HOST
    temporary_root = Path(tempfile.mkdtemp(prefix="bunnyland-v5-extension-"))
    worktree = temporary_root / V5_RUN.commit[:8]
    try:
        subprocess.run(
            ("git", "worktree", "add", "--detach", str(worktree), V5_RUN.commit),
            cwd=repo,
            check=True,
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(worktree / "src")
        for model in models:
            destination = staging / output_names[model]
            if destination.exists():
                try:
                    _validate_v5_cell(
                        destination,
                        model,
                        provider=provider,
                        host=host,
                    )
                    continue
                except (FileNotFoundError, json.JSONDecodeError, MatrixValidationError):
                    _relocate_invalid_cell(
                        destination,
                        output,
                        model,
                        output_names[model],
                        provider=provider,
                        host=host,
                    )
            arguments = (
                local_benchmark_arguments(V5_RUN, model, destination)
                if local
                else benchmark_arguments(V5_RUN, model, destination)
            )
            try:
                subprocess.run(
                    (str(python), *arguments),
                    cwd=worktree,
                    env=environment,
                    check=True,
                )
                _validate_v5_cell(destination, model, provider=provider, host=host)
            except (
                subprocess.CalledProcessError,
                FileNotFoundError,
                json.JSONDecodeError,
                MatrixValidationError,
            ):
                if destination.exists():
                    _relocate_invalid_cell(
                        destination,
                        output,
                        model,
                        output_names[model],
                        provider=provider,
                        host=host,
                    )
                raise
    finally:
        if worktree.exists():
            _remove_worktree(repo, worktree)
        shutil.rmtree(temporary_root)


def _promote_extension(
    source: Path,
    staging: Path,
    output: Path,
    new_models: tuple[str, ...],
    *,
    local: bool,
) -> None:
    promotion = output.parent / "in-progress" / f"{output.name}-promotion"
    if promotion.exists():
        raise MatrixValidationError(f"promotion directory already exists: {promotion}")
    output_names = V5_LOCAL_OUTPUT_NAMES if local else V5_OUTPUT_NAMES
    protocol = _v5_local_protocol() if local else _v5_protocol()
    shutil.copytree(source, promotion)
    (promotion / "protocol.json").write_text(
        json.dumps(protocol, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for model in new_models:
        shutil.copytree(staging / output_names[model], promotion / output_names[model])
    if local:
        validate_v5_local_output(promotion)
    else:
        validate_v5_output(promotion)
    shutil.move(promotion, output)
    shutil.rmtree(staging)


def extend_v5(repo: Path, source: Path, output: Path, python: Path) -> None:
    validate_v5_roster(repo)
    source_models = _validate_v5_source(source, local=False)
    if output.exists():
        raise MatrixValidationError(f"output already exists: {output}")
    if not os.environ.get("OLLAMA_CLOUD_API_KEY"):
        raise MatrixValidationError("OLLAMA_CLOUD_API_KEY is required")
    if not python.is_file():
        raise MatrixValidationError(f"Python executable is missing: {python}")
    new_models = tuple(model for model in V5_MODELS if model not in source_models)
    staging = _prepare_staging(output, _v5_protocol(), _CLOUD_AVAILABILITY_KEYS)
    _run_v5_cells(repo, staging, output, new_models, python, local=False)
    _promote_extension(source, staging, output, new_models, local=False)


def extend_v5_local(repo: Path, source: Path, output: Path, python: Path) -> None:
    validate_v5_local_roster(repo)
    _check_local_availability()
    source_models = _validate_v5_source(source, local=True)
    if output.exists():
        raise MatrixValidationError(f"output already exists: {output}")
    if not python.is_file():
        raise MatrixValidationError(f"Python executable is missing: {python}")
    new_models = tuple(model for model in V5_LOCAL_MODELS if model not in source_models)
    staging = _prepare_staging(output, _v5_local_protocol(), _LOCAL_AVAILABILITY_KEYS)
    _run_v5_cells(repo, staging, output, new_models, python, local=True)
    _promote_extension(source, staging, output, new_models, local=True)


def run_v5_local(repo: Path, output: Path, python: Path) -> None:
    validate_v5_local_roster(repo)
    _check_local_availability()
    if output.exists():
        raise MatrixValidationError(f"output already exists: {output}")
    if not python.is_file():
        raise MatrixValidationError(f"Python executable is missing: {python}")
    staging = _prepare_staging(output, _v5_local_protocol(), _LOCAL_AVAILABILITY_KEYS)
    _run_v5_cells(repo, staging, output, V5_LOCAL_MODELS, python, local=True)
    validate_v5_local_output(staging)
    shutil.move(staging, output)


def _v5_local_attempt_protocol(
    attempted_models: tuple[str, ...],
    completed_models: tuple[str, ...],
    failed_models: tuple[str, ...],
) -> dict[str, object]:
    protocol = _v5_local_protocol()
    protocol["purpose"] = "action-description-rewrite-local-exact-attempts"
    protocol["models"] = list(completed_models)
    protocol["baseline_models"] = list(V5_LOCAL_MODELS)
    protocol["attempted_models"] = list(attempted_models)
    protocol["failed_models"] = list(failed_models)
    return protocol


_LOCAL_ATTEMPT_KEYS = _LOCAL_AVAILABILITY_KEYS | {
    "attempted_models",
    "baseline_models",
    "failed_models",
    "models",
    "purpose",
}


def _protocol_models(protocol: dict[str, object], path: Path, key: str) -> tuple[str, ...]:
    value = protocol.get(key)
    if not isinstance(value, list) or not all(isinstance(model, str) for model in value):
        raise MatrixValidationError(f"{path}: {key} must be a string array")
    models = tuple(value)
    if len(models) != len(set(models)):
        raise MatrixValidationError(f"{path}: {key} must be unique")
    return models


def _validate_v5_local_attempt_source(source: Path) -> tuple[str, ...]:
    protocol_path = source / "protocol.json"
    protocol = _manifest(protocol_path)
    if protocol.get("purpose") != "action-description-rewrite-local-exact-attempts":
        raise MatrixValidationError(f"{protocol_path}: unexpected attempt purpose")
    if _protocol_base(protocol, _LOCAL_ATTEMPT_KEYS) != _protocol_base(
        _v5_local_protocol(), _LOCAL_ATTEMPT_KEYS
    ):
        raise MatrixValidationError(f"{protocol_path}: attempt experiment parameters differ")

    attempted = _protocol_models(protocol, protocol_path, "attempted_models")
    completed = _protocol_models(protocol, protocol_path, "models")
    failed = _protocol_models(protocol, protocol_path, "failed_models")
    baseline = _protocol_models(protocol, protocol_path, "baseline_models")
    if attempted != V5_LOCAL_UNSUPPORTED_THINKING_MODELS:
        raise MatrixValidationError(f"{protocol_path}: attempted model roster differs")
    if completed != V5_LOCAL_RUNTIME_VALIDATED_MODELS:
        raise MatrixValidationError(f"{protocol_path}: runtime-validated model roster differs")
    if failed != V5_LOCAL_RUNTIME_FAILED_MODELS:
        raise MatrixValidationError(f"{protocol_path}: runtime-failed model roster differs")
    if baseline != V5_LOCAL_PRE_RUNTIME_MODELS:
        raise MatrixValidationError(f"{protocol_path}: baseline model roster differs")
    if set(completed) & set(failed) or set(completed) | set(failed) != set(attempted):
        raise MatrixValidationError(
            f"{protocol_path}: completed and failed models must partition attempted models"
        )

    expected_legacy_availability = {
        "historical_models": list(HISTORICAL_OLLAMA_LOCAL_MODELS),
        "not_installed_models": list(V5_LOCAL_NOT_INSTALLED_MODELS),
        "unsupported_thinking_models": list(V5_LOCAL_UNSUPPORTED_THINKING_MODELS),
        "unavailable_models": list(
            V5_LOCAL_NOT_INSTALLED_MODELS + V5_LOCAL_UNSUPPORTED_THINKING_MODELS
        ),
    }
    for key, expected in expected_legacy_availability.items():
        if protocol.get(key) != expected:
            raise MatrixValidationError(f"{protocol_path}: recorded {key} differs")
    for key in ("runtime_failed_models", "runtime_validated_models"):
        if key in protocol:
            raise MatrixValidationError(f"{protocol_path}: unexpected post-attempt field {key}")

    for model in completed:
        _validate_v5_cell(
            source / V5_LOCAL_OUTPUT_NAMES[model],
            model,
            provider="ollama-local",
            host=OLLAMA_LOCAL_HOST,
        )
    return completed


def promote_v5_local_attempts(
    repo: Path,
    source: Path,
    attempts: Path,
    output: Path,
) -> None:
    validate_v5_local_roster(repo)
    source_models = _validate_v5_source(source, local=True)
    completed_models = _validate_v5_local_attempt_source(attempts)
    if output.exists():
        raise MatrixValidationError(f"output already exists: {output}")
    new_models = tuple(model for model in V5_LOCAL_MODELS if model not in source_models)
    if completed_models != new_models:
        raise MatrixValidationError(
            "exact-attempt completions do not exactly fill the validated local source"
        )

    staging = _prepare_staging(output, _v5_local_protocol(), _LOCAL_AVAILABILITY_KEYS)
    for model in completed_models:
        destination = staging / V5_LOCAL_OUTPUT_NAMES[model]
        if destination.exists():
            _validate_v5_cell(
                destination,
                model,
                provider="ollama-local",
                host=OLLAMA_LOCAL_HOST,
            )
            continue
        shutil.copytree(attempts / V5_LOCAL_OUTPUT_NAMES[model], destination)
        _validate_v5_cell(
            destination,
            model,
            provider="ollama-local",
            host=OLLAMA_LOCAL_HOST,
        )
    _promote_extension(source, staging, output, new_models, local=True)


def attempt_v5_local(
    repo: Path,
    output: Path,
    models: tuple[str, ...],
    python: Path,
) -> None:
    validate_v5_local_roster(repo)
    attempted_models = models or V5_LOCAL_UNSUPPORTED_THINKING_MODELS
    if len(attempted_models) != len(set(attempted_models)):
        raise MatrixValidationError("attempted local models must be unique")
    unknown = set(attempted_models) - set(V5_LOCAL_UNSUPPORTED_THINKING_MODELS)
    if unknown:
        raise MatrixValidationError(
            f"attempted models are not in the exact-attempt roster: {sorted(unknown)!r}"
        )
    installed = set(_installed_local_model_capabilities())
    missing = set(attempted_models) - installed
    if missing:
        raise MatrixValidationError(
            f"attempted local models are not installed: {sorted(missing)!r}"
        )
    if output.exists():
        raise MatrixValidationError(f"output already exists: {output}")
    if not python.is_file():
        raise MatrixValidationError(f"Python executable is missing: {python}")

    staging = output.parent / "in-progress" / output.name
    if staging.exists():
        raise MatrixValidationError(f"in-progress output already exists: {staging}")
    staging.mkdir(parents=True)
    protocol_path = staging / "protocol.json"
    protocol_path.write_text(
        json.dumps(
            _v5_local_attempt_protocol(attempted_models, (), ()),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    completed: list[str] = []
    failed: list[str] = []
    temporary_root = Path(tempfile.mkdtemp(prefix="bunnyland-v5-local-exact-attempts-"))
    worktree = temporary_root / V5_RUN.commit[:8]
    try:
        subprocess.run(
            ("git", "worktree", "add", "--detach", str(worktree), V5_RUN.commit),
            cwd=repo,
            check=True,
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(worktree / "src")
        for model in attempted_models:
            output_name = V5_LOCAL_OUTPUT_NAMES[model]
            destination = staging / output_name
            try:
                subprocess.run(
                    (str(python), *local_benchmark_arguments(V5_RUN, model, destination)),
                    cwd=worktree,
                    env=environment,
                    check=True,
                )
                _validate_v5_cell(
                    destination,
                    model,
                    provider="ollama-local",
                    host=OLLAMA_LOCAL_HOST,
                )
            except (
                subprocess.CalledProcessError,
                FileNotFoundError,
                json.JSONDecodeError,
                MatrixValidationError,
            ):
                if destination.exists():
                    _relocate_invalid_cell(
                        destination,
                        output,
                        model,
                        output_name,
                        provider="ollama-local",
                        host=OLLAMA_LOCAL_HOST,
                    )
                failed.append(model)
                continue
            completed.append(model)
    finally:
        if worktree.exists():
            _remove_worktree(repo, worktree)
        shutil.rmtree(temporary_root)

    protocol_path.write_text(
        json.dumps(
            _v5_local_attempt_protocol(
                attempted_models,
                tuple(completed),
                tuple(failed),
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    shutil.move(staging, output)
    print(
        json.dumps(
            {"completed_models": completed, "failed_models": failed},
            indent=2,
            sort_keys=True,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "validate-reference",
        help="validate the original checkpoint cohort manifests",
    )
    run_parser = subparsers.add_parser("run", help="run a matched checkpoint matrix")
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--model", default=DEFAULT_CANDIDATE_MODEL)
    run_parser.add_argument("--python", type=Path)
    validate_parser = subparsers.add_parser(
        "validate-output",
        help="validate a completed matched checkpoint matrix",
    )
    validate_parser.add_argument("--output", type=Path, required=True)
    validate_parser.add_argument("--model", default=DEFAULT_CANDIDATE_MODEL)
    v5_parser = subparsers.add_parser(
        "run-v5",
        help="run the complete matched v5 Ollama Cloud Bell cohort",
    )
    v5_parser.add_argument("--output", type=Path, required=True)
    v5_parser.add_argument("--python", type=Path)
    extend_v5_parser = subparsers.add_parser(
        "extend-v5",
        help="extend a validated two-checkpoint v5 source with the historical cloud roster",
    )
    extend_v5_parser.add_argument("--source", type=Path, required=True)
    extend_v5_parser.add_argument("--output", type=Path, required=True)
    extend_v5_parser.add_argument("--python", type=Path)
    local_v5_parser = subparsers.add_parser(
        "run-v5-local",
        help="run the installed historical Ollama Local v5 Bell panel",
    )
    local_v5_parser.add_argument("--output", type=Path, required=True)
    local_v5_parser.add_argument("--python", type=Path)
    extend_local_v5_parser = subparsers.add_parser(
        "extend-v5-local",
        help="extend a validated local v5 source with newly eligible historical models",
    )
    extend_local_v5_parser.add_argument("--source", type=Path, required=True)
    extend_local_v5_parser.add_argument("--output", type=Path, required=True)
    extend_local_v5_parser.add_argument("--python", type=Path)
    attempt_local_v5_parser = subparsers.add_parser(
        "attempt-v5-local",
        help="attempt exact v5 cells for installed protocol-incompatible historical tags",
    )
    attempt_local_v5_parser.add_argument("--output", type=Path, required=True)
    attempt_local_v5_parser.add_argument("--model", action="append", default=[])
    attempt_local_v5_parser.add_argument("--python", type=Path)
    promote_local_v5_parser = subparsers.add_parser(
        "promote-v5-local-attempts",
        help="promote validated exact-attempt cells into a complete local v5 bundle",
    )
    promote_local_v5_parser.add_argument("--source", type=Path, required=True)
    promote_local_v5_parser.add_argument("--attempts", type=Path, required=True)
    promote_local_v5_parser.add_argument("--output", type=Path, required=True)
    validate_v5_parser = subparsers.add_parser(
        "validate-v5-output",
        help="validate a completed matched v5 output",
    )
    validate_v5_parser.add_argument("--output", type=Path, required=True)
    validate_local_v5_parser = subparsers.add_parser(
        "validate-v5-local-output",
        help="validate a completed matched local v5 output",
    )
    validate_local_v5_parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo = Path(__file__).resolve().parent.parent
    if args.command == "validate-reference":
        validate_references(repo)
        return
    if args.command == "validate-output":
        validate_output(args.output.resolve(), args.model)
        return
    if args.command == "validate-v5-output":
        validate_v5_output(args.output.resolve())
        return
    if args.command == "validate-v5-local-output":
        validate_v5_local_output(args.output.resolve())
        return
    if args.command == "promote-v5-local-attempts":
        promote_v5_local_attempts(
            repo,
            args.source.resolve(),
            args.attempts.resolve(),
            args.output.resolve(),
        )
        return
    python = python_executable(repo, args.python)
    if args.command == "run-v5":
        run_v5(repo, args.output.resolve(), python)
        return
    if args.command == "extend-v5":
        extend_v5(repo, args.source.resolve(), args.output.resolve(), python)
        return
    if args.command == "run-v5-local":
        run_v5_local(repo, args.output.resolve(), python)
        return
    if args.command == "extend-v5-local":
        extend_v5_local(repo, args.source.resolve(), args.output.resolve(), python)
        return
    if args.command == "attempt-v5-local":
        attempt_v5_local(repo, args.output.resolve(), tuple(args.model), python)
        return
    run_matrix(repo, args.output.resolve(), args.model, python)


if __name__ == "__main__":
    main()
