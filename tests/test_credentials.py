from __future__ import annotations

import os
from pathlib import Path

import pytest

from bunnyland.credentials import read_credential


def test_read_credential_accepts_raw_and_absent_values() -> None:
    assert read_credential("TOKEN", environ={}) == ""
    assert read_credential("TOKEN", environ={"TOKEN": "  raw-secret  "}) == "raw-secret"
    assert (
        read_credential(
            "TOKEN",
            environ={"TOKEN": "ignored"},
            explicit_value="explicit-secret",
        )
        == "explicit-secret"
    )


def test_read_credential_accepts_safe_file(tmp_path: Path) -> None:
    secret = tmp_path / "provider-token"
    secret.write_text("file-secret\n", encoding="utf-8")
    secret.chmod(0o400)

    assert read_credential("TOKEN", environ={"TOKEN_FILE": str(secret)}) == "file-secret"


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("", "exactly one non-empty line"),
        ("  \n", "exactly one non-empty line"),
        ("first\nsecond\n", "exactly one non-empty line"),
    ],
)
def test_read_credential_rejects_invalid_file_content(
    tmp_path: Path,
    contents: str,
    message: str,
) -> None:
    secret = tmp_path / "provider-token"
    secret.write_text(contents, encoding="utf-8")
    secret.chmod(0o400)

    with pytest.raises(ValueError, match=message):
        read_credential("TOKEN", environ={"TOKEN_FILE": str(secret)})


def test_read_credential_rejects_raw_and_file_together(tmp_path: Path) -> None:
    secret = tmp_path / "provider-token"
    secret.write_text("file-secret\n", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot both be set"):
        read_credential(
            "TOKEN",
            environ={"TOKEN": "raw-secret", "TOKEN_FILE": str(secret)},
        )


def test_read_credential_rejects_missing_symlink_directory_and_writable_file(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="not readable"):
        read_credential("TOKEN", environ={"TOKEN_FILE": str(missing)})

    target = tmp_path / "target"
    target.write_text("secret\n", encoding="utf-8")
    symlink = tmp_path / "link"
    symlink.symlink_to(target)
    with pytest.raises(ValueError, match="regular non-symlink"):
        read_credential("TOKEN", environ={"TOKEN_FILE": str(symlink)})
    with pytest.raises(ValueError, match="regular non-symlink"):
        read_credential("TOKEN", environ={"TOKEN_FILE": str(tmp_path)})

    target.chmod(0o620)
    with pytest.raises(ValueError, match="group- or world-writable"):
        read_credential("TOKEN", environ={"TOKEN_FILE": str(target)})


def test_read_credential_rejects_non_utf8_file(tmp_path: Path) -> None:
    secret = tmp_path / "provider-token"
    secret.write_bytes(b"\xff")
    os.chmod(secret, 0o400)

    with pytest.raises(ValueError, match="not readable UTF-8"):
        read_credential("TOKEN", environ={"TOKEN_FILE": str(secret)})
