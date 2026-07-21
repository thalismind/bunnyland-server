"""Authoritative content flags shown before a player joins a world."""

from __future__ import annotations

from collections.abc import Iterable

from .core.world_actor import WorldActor
from .plugins.policy import validate_boundary_scope


def normalize_content_flags(values: Iterable[object]) -> tuple[str, ...]:
    """Validate, de-duplicate, and sort content flags for stable client display."""

    return tuple(sorted({validate_boundary_scope(str(value).strip()) for value in values}))


def world_content_flags(actor: WorldActor) -> tuple[str, ...]:
    """Return plugin-contributed flags plus flags administrators added to the world."""

    flags: set[str] = set()
    if actor.plugins is not None:
        flags.update(actor.plugins.boundary_tags)
    flags.update(actor.world_info.content_flags)
    return normalize_content_flags(flags)


def visible_content_flags(
    content_flags: Iterable[object], ignored_content_flags: Iterable[object]
) -> tuple[str, ...]:
    """Return the flags a player has not explicitly configured the client to ignore."""

    ignored = set(normalize_content_flags(ignored_content_flags))
    return tuple(flag for flag in normalize_content_flags(content_flags) if flag not in ignored)


__all__ = ["normalize_content_flags", "visible_content_flags", "world_content_flags"]
