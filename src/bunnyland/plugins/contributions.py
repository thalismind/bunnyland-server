"""Shared helpers for reading plugin contribution fields."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .model import Plugin


def collect_content_items(plugins: Iterable[Plugin], field_name: str) -> tuple[Any, ...]:
    """Collect one ``ContentContribution`` tuple field from plugins in order."""
    items: list[Any] = []
    for plugin in plugins:
        items.extend(getattr(plugin.content, field_name))
    return tuple(items)


def collect_ecs_types(plugins: Iterable[Plugin]) -> tuple[tuple[type, ...], tuple[type, ...]]:
    """Collect plugin-provided component and edge types in order."""
    components: list[type] = []
    edges: list[type] = []
    for plugin in plugins:
        components.extend(plugin.ecs.components)
        edges.extend(plugin.ecs.edges)
    return tuple(components), tuple(edges)


__all__ = ["collect_content_items", "collect_ecs_types"]
