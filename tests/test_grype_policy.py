from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "scripts/check-grype-findings"


def _finding(
    *,
    advisory: str = "CVE-2026-15308",
    severity: str = "High",
    package: str = "python",
    installed: str = "3.14.6",
    fix_state: str = "fixed",
    fixes: list[str] | None = None,
) -> dict[str, object]:
    return {
        "vulnerability": {
            "id": advisory,
            "severity": severity,
            "fix": {
                "state": fix_state,
                "versions": fixes if fixes is not None else ["3.15.0"],
            },
        },
        "artifact": {
            "name": package,
            "version": installed,
        },
    }


def _run_policy(
    tmp_path: Path,
    findings: list[dict[str, object]],
) -> subprocess.CompletedProcess[str]:
    report = tmp_path / "grype.json"
    report.write_text(json.dumps({"matches": findings}), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(POLICY), str(report)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_grype_policy_allows_cross_minor_python_fix(tmp_path: Path) -> None:
    result = _run_policy(tmp_path, [_finding(fixes=["3.15.0"])])

    assert result.returncode == 0
    assert "no fix is available in its supported release line" in result.stdout


def test_grype_policy_rejects_python_fix_in_runtime_line(tmp_path: Path) -> None:
    result = _run_policy(tmp_path, [_finding(fixes=["3.14.7", "3.15.0"])])

    assert result.returncode == 1
    assert "CVE-2026-15308: python 3.14.6 has an actionable high fix" in result.stdout


def test_grype_policy_rejects_other_fixable_high_findings(tmp_path: Path) -> None:
    result = _run_policy(
        tmp_path,
        [
            _finding(
                advisory="CVE-2026-00001",
                package="openssl",
                installed="1.0",
                fixes=["1.1"],
            )
        ],
    )

    assert result.returncode == 1
    assert "CVE-2026-00001: openssl 1.0 has an actionable high fix" in result.stdout


@pytest.mark.parametrize("severity", ["Medium", "Low", "Negligible"])
def test_grype_policy_allows_findings_below_high(
    tmp_path: Path,
    severity: str,
) -> None:
    result = _run_policy(tmp_path, [_finding(severity=severity)])

    assert result.returncode == 0
    assert result.stdout == ""


def test_grype_policy_fails_closed_on_malformed_report(tmp_path: Path) -> None:
    report = tmp_path / "grype.json"
    report.write_text('{"matches": {}}', encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(POLICY), str(report)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "invalid Grype report" in result.stderr
