from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

import pytest

from bunnyland import secure_files


def test_secure_directory_rejects_broken_symlink_file_and_foreign_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    broken = tmp_path / "broken"
    broken.symlink_to(tmp_path / "missing")
    with pytest.raises(PermissionError, match="regular directory"):
        secure_files.secure_directory(broken / "child")

    plain = tmp_path / "plain"
    plain.write_text("not a directory", encoding="utf-8")
    with pytest.raises(PermissionError, match="regular directory"):
        secure_files.secure_directory(plain)

    owned = tmp_path / "owned"
    owned.mkdir()
    monkeypatch.setattr(secure_files.os, "getuid", lambda: owned.stat().st_uid + 1)
    with pytest.raises(PermissionError, match="not owned"):
        secure_files.secure_directory(owned)


def test_secure_directory_rejects_creation_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "created"
    original_lstat = Path.lstat

    def missing_after_create(candidate: Path):
        if candidate == path and candidate.exists():
            raise FileNotFoundError
        return original_lstat(candidate)

    monkeypatch.setattr(Path, "lstat", missing_after_create)
    with pytest.raises(PermissionError, match="could not create"):
        secure_files.secure_directory(path)


def test_secure_read_rechecks_descriptor_type_and_closes_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "credential"
    path.write_text("secret\n", encoding="utf-8")
    closed: list[int] = []
    original_close = secure_files.os.close
    monkeypatch.setattr(
        secure_files.os,
        "fstat",
        lambda _descriptor: SimpleNamespace(st_mode=0, st_uid=os.getuid()),
    )

    def record_close(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(secure_files.os, "close", record_close)
    with pytest.raises(PermissionError, match="regular file"):
        secure_files.secure_read_text(path)
    assert len(closed) == 1


def test_secure_write_cleans_temporary_file_when_opened_stream_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "credential"

    def fail_fdopen(
        _descriptor: int, *_args: object, **_kwargs: object
    ) -> NoReturn:
        raise OSError("stream failed")

    monkeypatch.setattr(secure_files.os, "fdopen", fail_fdopen)
    with pytest.raises(OSError, match="stream failed"):
        secure_files.secure_write_text(path, "secret\n")
    assert not list(tmp_path.glob(".credential.*.tmp"))
