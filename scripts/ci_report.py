#!/usr/bin/env python3
"""Local CI reporting for server pytest results and coverage."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from xml.etree import ElementTree


def summarize(args: argparse.Namespace) -> int:
    junit_path = Path(args.junit)
    coverage_path = Path(args.coverage)

    suite = _parse_junit(junit_path) if junit_path.exists() else _empty_suite(junit_path)
    coverage = _parse_coverage(coverage_path) if coverage_path.exists() else {}
    passed = max(suite["tests"] - suite["failed"] - suite["skipped"], 0)
    markdown = _markdown_report(suite, passed, coverage)
    _write_summary(markdown)
    print(markdown)

    for failure in suite["failures"][:50]:
        _annotation("error", failure["title"], failure["message"])
    if not junit_path.exists():
        _annotation("warning", "Missing pytest report", f"{junit_path} was not found")
    if not coverage_path.exists():
        _annotation("warning", "Missing coverage report", f"{coverage_path} was not found")

    return 1 if suite["failed"] else 0


def _parse_junit(path: Path) -> dict:
    tree = ElementTree.parse(path)
    root = tree.getroot()
    suite_nodes = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    suite = {
        "path": str(path),
        "tests": 0,
        "failed": 0,
        "skipped": 0,
        "time": 0.0,
        "suites": [],
        "failures": [],
    }
    for node in suite_nodes:
        cases = list(node.iter("testcase"))
        tests = _int_attr(node, "tests", len(cases))
        failed = _int_attr(node, "failures", 0) + _int_attr(node, "errors", 0)
        skipped = _int_attr(node, "skipped", 0)
        time = _float_attr(node, "time", 0.0)
        suite["tests"] += tests
        suite["failed"] += failed
        suite["skipped"] += skipped
        suite["time"] += time
        suite["suites"].append(
            {
                "name": node.attrib.get("name", path.stem),
                "tests": tests,
                "failed": failed,
                "skipped": skipped,
                "time": time,
            }
        )
        for case in cases:
            failure = case.find("failure")
            if failure is None:
                failure = case.find("error")
            if failure is None:
                continue
            title = f"{case.attrib.get('classname', node.attrib.get('name', 'pytest'))}.{case.attrib.get('name', '(unknown)')}"
            message = failure.attrib.get("message") or (failure.text or "").strip() or "test failed"
            suite["failures"].append({"title": title, "message": message})
    return suite


def _parse_coverage(path: Path) -> dict:
    tree = ElementTree.parse(path)
    root = tree.getroot()
    files = []
    for class_node in root.findall(".//class"):
        filename = class_node.attrib.get("filename", "")
        line_rate = _float_attr(class_node, "line-rate", 0.0)
        branch_rate = _float_attr(class_node, "branch-rate", 0.0)
        lines = class_node.findall(".//line")
        covered_lines = sum(1 for line in lines if _int_attr(line, "hits", 0) > 0)
        files.append(
            {
                "filename": filename,
                "line_percent": round(line_rate * 100, 2),
                "branch_percent": round(branch_rate * 100, 2),
                "covered_lines": covered_lines,
                "total_lines": len(lines),
            }
        )
    return {
        "line_percent": round(_float_attr(root, "line-rate", 0.0) * 100, 2),
        "branch_percent": round(_float_attr(root, "branch-rate", 0.0) * 100, 2),
        "covered_lines": _int_attr(root, "lines-covered", 0),
        "total_lines": _int_attr(root, "lines-valid", 0),
        "covered_branches": _int_attr(root, "branches-covered", 0),
        "total_branches": _int_attr(root, "branches-valid", 0),
        "files": sorted(files, key=lambda item: (item["line_percent"], item["filename"]))[:12],
    }


def _markdown_report(suite: dict, passed: int, coverage: dict) -> str:
    lines = [
        "## Server Test Report",
        "",
        "| Passed | Failed | Skipped | Total | Time |",
        "| ---: | ---: | ---: | ---: | ---: |",
        f"| {passed} | {suite['failed']} | {suite['skipped']} | {suite['tests']} | {suite['time']:.2f}s |",
        "",
        "### Test Suites",
        "",
        "| Suite | Passed | Failed | Skipped | Total | Time |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in suite["suites"]:
        suite_passed = max(item["tests"] - item["failed"] - item["skipped"], 0)
        lines.append(
            f"| `{item['name']}` | {suite_passed} | {item['failed']} | "
            f"{item['skipped']} | {item['tests']} | {item['time']:.2f}s |"
        )
    if not suite["suites"]:
        lines.append("| No pytest report found | 0 | 0 | 0 | 0 | 0.00s |")

    if coverage:
        lines.extend(
            [
                "",
                "### Coverage",
                "",
                "| Line coverage | Branch coverage | Covered lines | Covered branches |",
                "| ---: | ---: | ---: | ---: |",
                (
                    f"| {coverage['line_percent']}% | {coverage['branch_percent']}% | "
                    f"{coverage['covered_lines']} / {coverage['total_lines']} | "
                    f"{coverage['covered_branches']} / {coverage['total_branches']} |"
                ),
                "",
                "<details><summary>Lowest covered server files</summary>",
                "",
                "| File | Line coverage | Branch coverage | Covered / Total lines |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for item in coverage["files"]:
            lines.append(
                f"| `{item['filename']}` | {item['line_percent']}% | {item['branch_percent']}% | "
                f"{item['covered_lines']} / {item['total_lines']} |"
            )
        lines.extend(["", "</details>"])
    return "\n".join(lines) + "\n"


def _empty_suite(path: Path) -> dict:
    return {
        "path": str(path),
        "tests": 0,
        "failed": 0,
        "skipped": 0,
        "time": 0.0,
        "suites": [],
        "failures": [],
    }


def _write_summary(markdown: str) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    with Path(summary).open("a", encoding="utf-8") as handle:
        handle.write(markdown)


def _annotation(level: str, title: str, message: str) -> None:
    print(f"::{level} title={_escape(title)}::{_escape(message)}")


def _escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _int_attr(node: ElementTree.Element, key: str, default: int) -> int:
    try:
        return int(node.attrib.get(key, default))
    except ValueError:
        return default


def _float_attr(node: ElementTree.Element, key: str, default: float) -> float:
    try:
        return float(node.attrib.get(key, default))
    except ValueError:
        return default


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", default="artifacts/coverage/pytest.xml")
    parser.add_argument("--coverage", default="coverage.xml")
    args = parser.parse_args()
    return summarize(args)


if __name__ == "__main__":
    raise SystemExit(main())
