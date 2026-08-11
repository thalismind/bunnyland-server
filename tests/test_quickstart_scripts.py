"""Behavioral checks for the player-facing local quickstart scripts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("script_name", "extra", "client"),
    (
        ("quickstart-tui", "tui", "tui"),
        ("quickstart-repl", "repl", "repl"),
    ),
)
def test_local_quickstart_uses_offline_tutorial_defaults(
    tmp_path: Path,
    script_name: str,
    extra: str,
    client: str,
) -> None:
    fake_uv = tmp_path / "uv"
    fake_uv.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    fake_uv.chmod(0o755)

    result = subprocess.run(
        [str(ROOT / "scripts" / script_name), "--generator", "bell-green"],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
    )

    assert result.stdout.splitlines() == [
        "run",
        "--extra",
        extra,
        "--extra",
        "llm",
        "bunnyland",
        client,
        "--generator",
        "apple-crossing",
        "--llm",
        "--chat-provider",
        "ollama-local",
        "--chat-model",
        "qwen3.5:9b",
        "--generator",
        "bell-green",
    ]
