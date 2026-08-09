from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-doc-links.py"


def run_checker(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_accepts_valid_local_file_and_fragment(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text("# Target heading\n", encoding="utf-8")
    source = tmp_path / "source.md"
    source.write_text("[target](target.md#target-heading)\n", encoding="utf-8")

    result = run_checker(tmp_path)

    assert result.returncode == 0, result.stderr


def test_rejects_missing_local_file(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("[missing](missing.md)\n", encoding="utf-8")

    result = run_checker(source)

    assert result.returncode == 1
    assert "missing local path" in result.stderr


def test_rejects_missing_heading_fragment(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text("# Existing heading\n", encoding="utf-8")
    source = tmp_path / "source.md"
    source.write_text("[missing](target.md#absent)\n", encoding="utf-8")

    result = run_checker(source)

    assert result.returncode == 1
    assert "missing heading fragment" in result.stderr


def test_decodes_url_encoded_paths_and_fragments(tmp_path: Path) -> None:
    target = tmp_path / "space name.md"
    target.write_text("## A spaced heading\n", encoding="utf-8")
    source = tmp_path / "source.md"
    source.write_text("[encoded](space%20name.md#a-spaced-heading)\n", encoding="utf-8")

    result = run_checker(source)

    assert result.returncode == 0, result.stderr


def test_ignores_external_links(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text(
        "[web](https://example.com/missing.md#missing)\n[email](mailto:host@example.com)\n",
        encoding="utf-8",
    )

    result = run_checker(source)

    assert result.returncode == 0, result.stderr


def test_validates_same_page_anchors(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Local section\n\n[jump](#local-section)\n", encoding="utf-8")

    result = run_checker(source)

    assert result.returncode == 0, result.stderr


def test_rejects_missing_same_page_anchor(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Local section\n\n[jump](#missing)\n", encoding="utf-8")

    result = run_checker(source)

    assert result.returncode == 1
    assert "missing heading fragment" in result.stderr


def test_ignores_links_in_fenced_examples(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text(
        "```markdown\n[example](missing.md#missing)\n```\n"
        "~~~markdown\n[other](also-missing.md)\n~~~\n",
        encoding="utf-8",
    )

    result = run_checker(source)

    assert result.returncode == 0, result.stderr
