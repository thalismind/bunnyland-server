from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest

from scripts.security_exceptions import load_scanner_exceptions

ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "ghcr.io/thalismind/bunnyland-server@sha256:"
    "29d32c3ab5a3c7b9adc973b6eecc0804e6c5feb98938b1532a48dc936fb43aad"
)


def _entry(advisory: str, *, reviewed: str = "2026-08-07") -> str:
    return (
        f"  - id: {advisory}\n"
        "    scanner: grype\n"
        "    package: chromadb\n"
        f"    image_ref: {IMAGE}\n"
        "    expired_at: 2026-08-28\n"
        f"    last_reviewed_at: {reviewed}\n"
        "    review_interval_days: 7\n"
        "    tracking_issue: docs/admin/security-exceptions.md#sec-2026-001\n"
    )


def test_repository_exception_manifest_is_current_and_narrow() -> None:
    result = subprocess.run(
        [str(ROOT / "scripts/check-security-exceptions")],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    entries = load_scanner_exceptions(
        ROOT / ".scanner-exceptions.yaml", today=date(2026, 8, 9)
    )
    assert [(entry.advisory, entry.package, entry.image_ref) for entry in entries] == [
        (advisory, "chromadb", IMAGE)
        for advisory in (
            "CVE-2026-45829",
            "CVE-2026-45830",
            "CVE-2026-45831",
            "CVE-2026-45833",
        )
    ]


def test_every_exception_entry_is_validated(tmp_path: Path) -> None:
    manifest = tmp_path / "exceptions.yaml"
    manifest.write_text(
        "vulnerabilities:\n"
        + _entry("CVE-2099-0001")
        + _entry("CVE-2099-0002", reviewed="2026-07-01")
    )

    with pytest.raises(ValueError, match="CVE-2099-0002 review overdue"):
        load_scanner_exceptions(manifest, today=date(2026, 8, 9))


def test_exception_requires_an_immutable_image_digest(tmp_path: Path) -> None:
    manifest = tmp_path / "exceptions.yaml"
    manifest.write_text(
        "vulnerabilities:\n" + _entry("CVE-2099-0001").replace(IMAGE, "server:latest")
    )

    with pytest.raises(ValueError, match="image_ref must use an immutable digest"):
        load_scanner_exceptions(manifest, today=date(2026, 8, 9))
