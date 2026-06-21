"""Shared terminal formatting for local world generator lists."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .worldgen import WorldGenerator


def available_generators() -> list[WorldGenerator]:
    """World generators a local terminal client can use, sorted by name."""
    from .plugins import bunnyland_plugins, select
    from .worldgen import collect_generators

    plugins = select(list(bunnyland_plugins()), None)
    return sorted(collect_generators(plugins).values(), key=lambda generator: generator.name)


def _generator_group(generator: WorldGenerator) -> str:
    return getattr(generator, "group", "") or "custom"


def _generator_group_label(group: str) -> str:
    return group.replace("-", " ").title()


def format_generator_lines(generators: Iterable[WorldGenerator]) -> list[str]:
    """Human-readable grouped lines for ``--list-generators`` output."""
    grouped: dict[str, list[WorldGenerator]] = {}
    for generator in generators:
        grouped.setdefault(_generator_group(generator), []).append(generator)

    lines: list[str] = []
    seedless = False
    for group in sorted(grouped):
        if lines:
            lines.append("")
        lines.append(f"{_generator_group_label(group)}:")
        for generator in sorted(grouped[group], key=lambda item: item.name):
            marker = ""
            if not generator.uses_seed:
                marker = " *"
                seedless = True
            lines.append(f"  {generator.name}{marker}")
            if generator.description:
                lines.append(f"      {generator.description}")
    if seedless:
        # ``seedless`` is only set while appending generator lines, so ``lines``
        # is always non-empty here; the blank separator is unconditional.
        lines.append("")
        lines.append("* ignores --seed")
    return lines
