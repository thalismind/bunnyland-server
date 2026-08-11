"""Plan and validate the frozen trace-retained tutorial-v5 matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = Path(__file__).with_name("tutorial_v5.json")


@dataclass(frozen=True)
class Cell:
    group: str
    provider: str
    model: str
    sessions: int
    thinking: str | None
    repeat_guard: bool
    retries: int
    enabled: bool


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object")
    return value


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be non-empty text")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def load_cells(path: Path) -> tuple[dict[str, object], tuple[Cell, ...]]:
    config = _object(json.loads(path.read_text(encoding="utf-8")), "matrix")
    if _integer(config.get("schema_version"), "schema_version") != 1:
        raise ValueError("unsupported matrix schema")
    if _integer(config.get("session_timeout"), "session_timeout") <= 0:
        raise ValueError("session_timeout must be positive")
    if _integer(config.get("turn_limit"), "turn_limit") <= 0:
        raise ValueError("turn_limit must be positive")
    cells: list[Cell] = []
    seen: set[str] = set()
    for raw_group in _array(config.get("groups"), "groups"):
        group = _object(raw_group, "group")
        group_id = _text(group.get("id"), "group.id")
        if group.get("log_thinking") is not True:
            raise ValueError(f"{group_id} must retain thinking traces")
        if group.get("repeat_command_guard") is not True:
            raise ValueError(f"{group_id} must enable the repeat-command guard")
        provider = _text(group.get("provider"), "group.provider")
        thinking_value = group.get("thinking")
        if thinking_value is not None and thinking_value not in {"low", "medium", "high"}:
            raise ValueError(f"{group_id} has invalid thinking level")
        enabled = group.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"{group_id}.enabled must be boolean")
        for raw_model in _array(group.get("models"), "group.models"):
            model = _text(raw_model, "model")
            if model in seen:
                raise ValueError(f"duplicate model id: {model}")
            seen.add(model)
            cells.append(
                Cell(
                    group=group_id,
                    provider=provider,
                    model=model,
                    sessions=_integer(group.get("sessions"), "group.sessions"),
                    thinking=thinking_value if isinstance(thinking_value, str) else None,
                    repeat_guard=group.get("repeat_command_guard") is True,
                    retries=_integer(
                        group.get("provider_session_retries"),
                        "group.provider_session_retries",
                    ),
                    enabled=enabled,
                )
            )
    if len(cells) != 40:
        raise ValueError(f"matrix must contain exactly 40 historical model ids, got {len(cells)}")
    panel_bytes = ("\n".join(sorted(cell.model for cell in cells)) + "\n").encode()
    panel_digest = hashlib.sha256(panel_bytes).hexdigest()
    expected_digest = _text(config.get("model_panel_sha256"), "model_panel_sha256")
    if panel_digest != expected_digest:
        raise ValueError(
            f"model panel digest is {panel_digest}, expected {expected_digest}"
        )
    return config, tuple(cells)


def command(config: dict[str, object], cell: Cell, output_root: Path) -> list[str]:
    tutorials = tuple(
        _text(value, "tutorial")
        for value in _array(config.get("tutorials"), "tutorials")
    )
    output = output_root / cell.group / cell.model.replace("/", "__").replace(":", "_")
    args = [
        "scripts/benchmark-tutorials",
        "--provider",
        cell.provider,
        "--model",
        cell.model,
        "--sessions",
        str(cell.sessions),
        "--session-timeout",
        str(_integer(config.get("session_timeout"), "session_timeout")),
        "--turn-limit",
        str(_integer(config.get("turn_limit"), "turn_limit")),
        "--log-thinking",
        "--provider-session-retries",
        str(cell.retries),
        "--output",
        str(output),
    ]
    for tutorial in tutorials:
        args.extend(("--tutorial", tutorial))
    if cell.thinking is not None:
        args.extend(("--thinking", cell.thinking))
    if cell.repeat_guard:
        args.append("--repeat-command-guard")
    return args


def _validate_artifacts(
    config: dict[str, object],
    cells: tuple[Cell, ...],
    output_root: Path,
) -> tuple[str, ...]:
    errors: list[str] = []
    expected_commit = _text(config.get("server_commit"), "server_commit")
    expected_tutorials = _array(config.get("tutorials"), "tutorials")
    for cell in cells:
        if not cell.enabled:
            continue
        args = command(config, cell, output_root)
        output = Path(args[args.index("--output") + 1])
        manifest_path = output / "manifest.json"
        sessions_path = output / "sessions.jsonl"
        responses_path = output / "responses.jsonl"
        if not manifest_path.is_file():
            errors.append(f"{cell.model}: missing manifest")
            continue
        manifest = _object(
            json.loads(manifest_path.read_text(encoding="utf-8")),
            f"{cell.model} manifest",
        )
        models = _array(manifest.get("models"), f"{cell.model} manifest.models")
        model_ids = [
            _text(_object(item, "manifest model").get("model"), "manifest model id")
            for item in models
        ]
        expected = {
            "commit": expected_commit,
            "provider": cell.provider,
            "sessions_per_model_tutorial": cell.sessions,
            "session_timeout_seconds": config.get("session_timeout"),
            "turn_limit": config.get("turn_limit"),
            "tutorials": expected_tutorials,
            "thinking": cell.thinking,
            "temperature": config.get("temperature"),
            "max_output_tokens": config.get("max_output_tokens"),
            "log_thinking": True,
            "repeat_command_guard": cell.repeat_guard,
            "provider_session_retries": cell.retries,
            "seed_helpful_memory": False,
        }
        if model_ids != [cell.model]:
            errors.append(f"{cell.model}: manifest model ids are {model_ids!r}")
        for key, value in expected.items():
            if manifest.get(key) != value:
                errors.append(
                    f"{cell.model}: {key}={manifest.get(key)!r}, expected {value!r}"
                )
        if not sessions_path.is_file():
            errors.append(f"{cell.model}: missing sessions.jsonl")
            continue
        completed = sum(
            1 for line in sessions_path.read_text(encoding="utf-8").splitlines() if line
        )
        expected_sessions = cell.sessions * len(expected_tutorials)
        if completed != expected_sessions:
            errors.append(
                f"{cell.model}: completed sessions={completed}, expected {expected_sessions}"
            )
        if not responses_path.is_file():
            errors.append(f"{cell.model}: missing responses.jsonl")
    return tuple(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/benchmarks/tutorials/v5-trace-retained"),
    )
    parser.add_argument("--include-disabled", action="store_true")
    parser.add_argument(
        "--validate-artifacts",
        type=Path,
        help="validate a completed per-model output tree instead of printing commands",
    )
    args = parser.parse_args()
    config, cells = load_cells(args.matrix)
    if args.validate_artifacts is not None:
        errors = _validate_artifacts(config, cells, args.validate_artifacts)
        for error in errors:
            print(error)
        return 1 if errors else 0
    print(f"# experiment_id={_text(config.get('experiment_id'), 'experiment_id')}")
    print(f"# server_commit={_text(config.get('server_commit'), 'server_commit')}")
    for cell in cells:
        if cell.enabled or args.include_disabled:
            print(shlex.join(command(config, cell, args.output_root)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
