"""Parse and validate Bunnyland's narrow image-scanner exceptions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


@dataclass(frozen=True)
class ScannerException:
    advisory: str
    scanner: str
    package: str
    image_ref: str
    expired_at: date
    last_reviewed_at: date
    review_interval_days: int
    tracking_issue: str

    def key(self) -> tuple[str, str, str]:
        return self.advisory, self.package, self.image_ref

    def validate(self, today: date, source: Path) -> None:
        if self.scanner != "grype":
            raise ValueError(f"{source}: {self.advisory} scanner must be grype")
        if re.fullmatch(r".+@sha256:[0-9a-f]{64}", self.image_ref) is None:
            raise ValueError(
                f"{source}: {self.advisory} image_ref must use an immutable digest"
            )
        if not self.tracking_issue.startswith("docs/") or "#" not in self.tracking_issue:
            raise ValueError(
                f"{source}: {self.advisory} tracking_issue must link to documentation"
            )
        if today > self.expired_at:
            raise ValueError(
                f"{source}: {self.advisory} exception expired on "
                f"{self.expired_at.isoformat()}"
            )
        if self.review_interval_days < 1:
            raise ValueError(
                f"{source}: {self.advisory} review_interval_days must be positive"
            )
        review_due = self.last_reviewed_at + timedelta(
            days=self.review_interval_days
        )
        if today > review_due:
            raise ValueError(
                f"{source}: {self.advisory} review overdue since "
                f"{review_due.isoformat()}"
            )


def _field(block: str, name: str, source: Path) -> str:
    match = re.search(rf"(?m)^\s+{re.escape(name)}:\s+(\S+)\s*$", block)
    if match is None:
        advisory = re.search(r"(?m)^\s*-\s+id:\s+(\S+)\s*$", block)
        label = advisory.group(1) if advisory is not None else "exception"
        raise ValueError(f"{source}: {label} missing {name}")
    return match.group(1)


def load_scanner_exceptions(
    source: Path,
    *,
    today: date | None = None,
) -> list[ScannerException]:
    text = source.read_text(encoding="utf-8")
    starts = list(re.finditer(r"(?m)^  - id:\s+(\S+)\s*$", text))
    if not starts:
        raise ValueError(f"{source}: no scanner exceptions found")

    checked_on = date.today() if today is None else today
    entries: list[ScannerException] = []
    seen: set[tuple[str, str, str]] = set()
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[start.start() : end]
        entry = ScannerException(
            advisory=start.group(1),
            scanner=_field(block, "scanner", source),
            package=_field(block, "package", source).lower(),
            image_ref=_field(block, "image_ref", source),
            expired_at=date.fromisoformat(_field(block, "expired_at", source)),
            last_reviewed_at=date.fromisoformat(
                _field(block, "last_reviewed_at", source)
            ),
            review_interval_days=int(
                _field(block, "review_interval_days", source)
            ),
            tracking_issue=_field(block, "tracking_issue", source),
        )
        entry.validate(checked_on, source)
        if entry.key() in seen:
            raise ValueError(
                f"{source}: duplicate exception for "
                f"{entry.advisory}/{entry.package}/{entry.image_ref}"
            )
        seen.add(entry.key())
        entries.append(entry)
    return entries
