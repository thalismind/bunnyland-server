"""Runtime-loadable store of scripted/behavioral controller definitions (spec 7).

The script editor authors scripts and behavior trees as data; this store compiles them into
the in-memory registries so controllers can reference them by name, and persists them to a
JSON file so they survive a restart. On boot, ``load`` re-registers everything in the file.

The store holds only editor-loaded definitions; code-defined built-ins live in the registries
directly and are not persisted here.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .behavior_tree import register_behavior_spec
from .scripts import register_script_spec
from .specs import BehaviorTreeSpec, ScriptSpec

logger = logging.getLogger("bunnyland.controller_definitions")


class ControllerDefinitionStore:
    """Holds editor-loaded controller definitions, registers them, and persists them."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._scripts: dict[str, ScriptSpec] = {}
        self._behaviors: dict[str, BehaviorTreeSpec] = {}

    @property
    def persistent(self) -> bool:
        return self.path is not None

    def load(self) -> tuple[int, int]:
        """Read the store file and register every definition. Returns ``(scripts, behaviors)``.

        Missing files are treated as empty. Individual definitions that fail to compile are
        logged and skipped so one bad entry cannot stop the server from booting.
        """
        if self.path is None or not self.path.exists():
            return (0, 0)
        raw = json.loads(self.path.read_text())
        scripts = 0
        for entry in raw.get("scripts", ()):
            try:
                self._register_script(ScriptSpec.model_validate(entry))
                scripts += 1
            except Exception as exc:  # noqa: BLE001 - skip one bad entry, keep booting
                logger.warning("skipping invalid stored script: %s", exc)
        behaviors = 0
        for entry in raw.get("behaviors", ()):
            try:
                self._register_behavior(BehaviorTreeSpec.model_validate(entry))
                behaviors += 1
            except Exception as exc:  # noqa: BLE001 - skip one bad entry, keep booting
                logger.warning("skipping invalid stored behavior tree: %s", exc)
        return (scripts, behaviors)

    def add_script(self, spec: ScriptSpec) -> ScriptSpec:
        """Compile, register, persist, and return a script spec. Raises ``ValueError`` if bad."""
        self._register_script(spec)
        self.save()
        return spec

    def add_behavior(self, spec: BehaviorTreeSpec) -> BehaviorTreeSpec:
        """Compile, register, persist, and return a behavior spec. Raises ``ValueError`` if bad."""
        self._register_behavior(spec)
        self.save()
        return spec

    def save(self) -> None:
        """Write the store to disk atomically (no-op when no path is configured)."""
        if self.path is None:
            return
        payload = {
            "scripts": [spec.model_dump(mode="json") for spec in self._scripts.values()],
            "behaviors": [spec.model_dump(mode="json") for spec in self._behaviors.values()],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(tmp, self.path)

    def snapshot(self) -> dict[str, list[str]]:
        """Names of the editor-loaded scripts and behavior trees this store persists."""
        return {
            "scripts": sorted(self._scripts),
            "behaviors": sorted(self._behaviors),
        }

    def _register_script(self, spec: ScriptSpec) -> None:
        register_script_spec(spec)  # raises ValueError on a bad spec before we store it
        self._scripts[spec.name] = spec

    def _register_behavior(self, spec: BehaviorTreeSpec) -> None:
        register_behavior_spec(spec)  # raises ValueError on a bad spec before we store it
        self._behaviors[spec.name] = spec


__all__ = ["ControllerDefinitionStore"]
