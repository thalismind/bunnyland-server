#!/usr/bin/env python3
"""Validate local Markdown links and heading fragments."""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$")
HTML_TAG_RE = re.compile(r"<[^>]+>")
MARKDOWN_MARKUP_RE = re.compile(r"[!*_`~\[\]()]")
EXTERNAL_SCHEMES = frozenset({"data", "ftp", "http", "https", "irc", "mailto", "news", "tel"})


@dataclass(frozen=True)
class Link:
    destination: str
    line: int


@dataclass(frozen=True)
class Problem:
    source: Path
    line: int
    destination: str
    reason: str

    def render(self) -> str:
        try:
            display = self.source.relative_to(ROOT)
        except ValueError:
            display = self.source
        return f"{display}:{self.line}: {self.destination}: {self.reason}"


def markdown_files(paths: Iterable[Path]) -> list[Path]:
    files: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved.is_dir():
            files.update(resolved.rglob("*.md"))
        elif resolved.suffix.lower() == ".md" and resolved.is_file():
            files.add(resolved)
    return sorted(files)


def unfenced_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append((number, line))
    return lines


def inline_links(lines: Iterable[tuple[int, str]]) -> list[Link]:
    links: list[Link] = []
    for line_number, line in lines:
        cursor = 0
        while cursor < len(line):
            start = line.find("](", cursor)
            if start < 0:
                break
            depth = 1
            end = start + 2
            escaped = False
            while end < len(line) and depth:
                char = line[end]
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                end += 1
            if depth:
                break
            raw = line[start + 2 : end - 1].strip()
            destination = split_destination(raw)
            if destination:
                links.append(Link(destination=destination, line=line_number))
            cursor = end
    return links


def split_destination(raw: str) -> str:
    if raw.startswith("<"):
        close = raw.find(">")
        return raw[1:close] if close >= 0 else raw
    match = re.match(r"(?:\\.|[^\s])+", raw)
    return match.group(0) if match else ""


def heading_slug(heading: str) -> str:
    value = html.unescape(HTML_TAG_RE.sub("", heading)).strip().lower()
    value = MARKDOWN_MARKUP_RE.sub("", value)
    value = re.sub(r"[^\w\- ]", "", value)
    return re.sub(r"\s+", "-", value)


def heading_fragments(text: str) -> set[str]:
    fragments: set[str] = set()
    counts: dict[str, int] = {}
    lines = unfenced_lines(text)
    for _, line in lines:
        match = HEADING_RE.match(line)
        if not match:
            continue
        base = heading_slug(match.group(1))
        count = counts.get(base, 0)
        counts[base] = count + 1
        fragments.add(base if count == 0 else f"{base}-{count}")
    for index in range(len(lines) - 1):
        _, line = lines[index]
        _, underline = lines[index + 1]
        if line.strip() and re.fullmatch(r"[ \t]{0,3}(?:=+|-+)[ \t]*", underline):
            base = heading_slug(line)
            count = counts.get(base, 0)
            counts[base] = count + 1
            fragments.add(base if count == 0 else f"{base}-{count}")
    return fragments


def validate_file(source: Path) -> list[Problem]:
    text = source.read_text(encoding="utf-8")
    problems: list[Problem] = []
    for link in inline_links(unfenced_lines(text)):
        destination = link.destination
        parsed = urlsplit(destination)
        if parsed.scheme.lower() in EXTERNAL_SCHEMES or parsed.netloc:
            continue
        path_text = unquote(parsed.path)
        fragment = unquote(parsed.fragment)
        target = source if not path_text else (source.parent / path_text).resolve()
        if not target.exists():
            problems.append(Problem(source, link.line, destination, "missing local path"))
            continue
        if fragment and target.is_file() and target.suffix.lower() == ".md":
            target_fragments = heading_fragments(target.read_text(encoding="utf-8"))
            if fragment not in target_fragments:
                problems.append(Problem(source, link.line, destination, "missing heading fragment"))
    return problems


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Markdown files or directories (default: root Markdown and docs/)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = args.paths or [*ROOT.glob("*.md"), ROOT / "docs"]
    problems = [problem for source in markdown_files(paths) for problem in validate_file(source)]
    for problem in problems:
        print(problem.render(), file=sys.stderr)
    if problems:
        print(f"Found {len(problems)} invalid local Markdown link(s).", file=sys.stderr)
        return 1
    print(f"Checked {len(markdown_files(paths))} Markdown files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
