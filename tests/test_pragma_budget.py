"""Ratchet guard: ``# pragma: no cover`` must never increase.

Every ``# pragma: no cover`` is a line we have *given up on* covering. This test
pins the total number of them in ``src/bunnyland`` to a fixed budget so the count
can only ever go DOWN: recover a pragma'd path with a real test, delete the
pragma, and lower ``MAX_PRAGMA_NO_COVER`` to match. Adding a new pragma (or
recovering one without lowering the budget) fails this test on purpose.

The current residual is the OpenTelemetry OTLP exporter wiring in
``telemetry.py``, which needs the optional ``otel`` extra installed plus a live
collector to exercise. When that is wired into CI (or mocked), drop the budget.
"""

from __future__ import annotations

from pathlib import Path

# Pin: only ever lower this. See module docstring.
MAX_PRAGMA_NO_COVER = 6

# The marker, assembled so this file does not match its own scan target.
_MARKER = "# pragma:" + " no cover"

_SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "bunnyland"


def _find_pragmas() -> list[str]:
    hits: list[str] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if _MARKER in line:
                rel = path.relative_to(_SRC_ROOT.parent.parent)
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    return hits


def test_pragma_no_cover_count_does_not_increase() -> None:
    hits = _find_pragmas()
    detail = "\n".join(hits)
    assert len(hits) <= MAX_PRAGMA_NO_COVER, (
        f"Found {len(hits)} '{_MARKER}' markers in src/bunnyland, but the budget is "
        f"{MAX_PRAGMA_NO_COVER}. Ignored code may only decrease: recover the new path "
        f"with a real test and delete its pragma, or do not add one.\n{detail}"
    )
    # If you recovered a pragma, lower MAX_PRAGMA_NO_COVER to len(hits) so the
    # ratchet tightens and the gain cannot silently regress.
    assert len(hits) == MAX_PRAGMA_NO_COVER, (
        f"Only {len(hits)} '{_MARKER}' markers remain (budget {MAX_PRAGMA_NO_COVER}). "
        f"Lower MAX_PRAGMA_NO_COVER in this file to {len(hits)} to lock in the recovery."
    )
