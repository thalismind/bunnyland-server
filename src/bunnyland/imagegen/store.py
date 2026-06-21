"""Runtime-loadable store of ComfyUI workflow templates (spec 27).

Built-in templates ship as package data under ``imagegen/workflows/``; players may provide
their own and edit them like scripts and behavior trees. The store keeps the two sources
separate: defaults come from code/package data, user templates load from (and persist to) a
JSON file, and a user template shadows a default of the same name. Only user templates are
written back to disk so the shipped defaults stay code-owned.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from importlib import resources
from pathlib import Path
from typing import Any

from .spec import ImagePurpose, WorkflowTemplate

logger = logging.getLogger("bunnyland.imagegen")


def load_templates_from(directory: Any) -> list[WorkflowTemplate]:
    """Load every ``*.json`` workflow template in a Traversable/Path directory, sorted by name."""
    templates: list[WorkflowTemplate] = []
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if not entry.name.endswith(".json"):
            continue
        templates.append(WorkflowTemplate.model_validate(json.loads(entry.read_text())))
    return templates


def default_templates() -> list[WorkflowTemplate]:
    """The built-in templates shipped as package data (one per purpose)."""
    return load_templates_from(resources.files("bunnyland.imagegen").joinpath("workflows"))


class WorkflowTemplateStore:
    """Holds built-in and player-provided workflow templates and persists the latter."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        defaults: Iterable[WorkflowTemplate] = (),
    ) -> None:
        self.path = Path(path) if path is not None else None
        self._defaults: dict[str, WorkflowTemplate] = {t.name: t for t in defaults}
        self._user: dict[str, WorkflowTemplate] = {}

    @property
    def persistent(self) -> bool:
        return self.path is not None

    def load(self) -> int:
        """Read the user template file and register each template. Returns the count loaded.

        A missing file is treated as empty; individual templates that fail to validate are
        logged and skipped so one bad entry cannot stop the server from booting.
        """
        if self.path is None or not self.path.exists():
            return 0
        raw = json.loads(self.path.read_text())
        loaded = 0
        for entry in raw.get("templates", ()):
            try:
                template = WorkflowTemplate.model_validate(entry)
            except Exception as exc:  # noqa: BLE001 - skip one bad entry, keep booting
                logger.warning("skipping invalid workflow template: %s", exc)
                continue
            self._user[template.name] = template
            loaded += 1
        return loaded

    def add_template(self, template: WorkflowTemplate) -> WorkflowTemplate:
        """Register a user template (shadowing any default of the same name) and persist it."""
        self._user[template.name] = template
        self.save()
        return template

    def save(self) -> None:
        """Write the user templates to disk atomically (no-op when no path is configured)."""
        if self.path is None:
            return
        payload = {"templates": [t.model_dump(mode="json") for t in self._user.values()]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(tmp, self.path)

    def get(self, name: str) -> WorkflowTemplate | None:
        """Return the named template, preferring a user template over a default."""
        return self._user.get(name) or self._defaults.get(name)

    def for_purpose(self, purpose: ImagePurpose) -> WorkflowTemplate | None:
        """Return a template for the given purpose, preferring user templates."""
        for template in self._user.values():
            if template.purpose == purpose:
                return template
        for template in self._defaults.values():
            if template.purpose == purpose:
                return template
        return None

    def snapshot(self) -> dict[str, list[str]]:
        """Names of all templates (defaults plus user) this store can resolve."""
        return {"templates": sorted({**self._defaults, **self._user})}


__all__ = [
    "WorkflowTemplateStore",
    "default_templates",
    "load_templates_from",
]
