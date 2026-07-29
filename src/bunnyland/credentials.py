"""Strict file-backed credential loading for external providers."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path


def read_credential(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
    explicit_value: str | None = None,
) -> str:
    """Read ``NAME`` or ``NAME_FILE`` while rejecting ambiguous or unsafe input."""

    values = os.environ if environ is None else environ
    raw_value = explicit_value if explicit_value is not None else values.get(name, "")
    raw_value = raw_value.strip()
    file_value = values.get(f"{name}_FILE", "").strip()
    if raw_value and file_value:
        raise ValueError(f"{name} and {name}_FILE cannot both be set")
    if not file_value:
        return raw_value

    path = Path(file_value)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError(f"{name}_FILE is not readable: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{name}_FILE must be a regular non-symlink file: {path}")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ValueError(f"{name}_FILE must not be group- or world-writable: {path}")
    try:
        contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"{name}_FILE is not readable UTF-8: {path}") from exc
    lines = contents.splitlines()
    if len(lines) != 1 or not lines[0].strip():
        raise ValueError(f"{name}_FILE must contain exactly one non-empty line: {path}")
    return lines[0].strip()


__all__ = ["read_credential"]
