"""Package an illustrated tutorial report without raw benchmark evidence."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from benchmarks.tutorial_report import package_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("archive", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    package_report(args.report, args.archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
