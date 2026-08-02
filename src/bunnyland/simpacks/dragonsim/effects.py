"""Typed, reusable magic effect resolution for adventure simulation packs."""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from pydantic.dataclasses import dataclass
from relics import Edge, Entity, World

from ...core.components import HealthComponent
from ...core.mutations import SetComponent

EffectType = Literal["heal", "harm"]
EffectTargetMode = Literal["self", "single", "room"]

MIN_EFFECT_MULTIPLIER = 0.1
MAX_EFFECT_MULTIPLIER = 4.0


@dataclass(frozen=True)
class EffectSpec:
    """A supported effect, separate from legacy free-form flavor strings."""

    effect_type: EffectType
    magnitude: float
    tags: tuple[str, ...] = ()
    target_mode: EffectTargetMode = "single"


@dataclass(frozen=True)
class EffectModifier(Edge):
    """A repeatable weakness/resistance attached from a target to its source."""

    tags: tuple[str, ...] = ()
    multiplier: float = 1.0


@dataclass(frozen=True)
class EffectResolution:
    target_id: str
    effect_type: EffectType
    magnitude: float
    tags: tuple[str, ...]
    target_mode: EffectTargetMode
    multiplier: float
    before: float
    after: float


def effect_spec(
    effect_type: str,
    magnitude: float,
    *,
    tags: tuple[str, ...] = (),
    target_mode: EffectTargetMode = "single",
) -> EffectSpec | None:
    """Convert a legacy effect name only when the resolver supports it."""

    if effect_type == "heal":
        return EffectSpec("heal", magnitude, tags, target_mode)
    if effect_type == "harm":
        return EffectSpec("harm", magnitude, tags, target_mode)
    return None


def _effect_multiplier(target: Entity, tags: tuple[str, ...]) -> float:
    matching = sorted(
        (
            (str(source_id), modifier)
            for modifier, source_id in target.get_relationships(EffectModifier)
            if set(modifier.tags).intersection(tags)
        ),
        key=lambda entry: (
            entry[0],
            entry[1].tags,
            entry[1].multiplier,
        ),
    )
    multiplier = 1.0
    for _source_id, modifier in matching:
        multiplier *= max(0.0, modifier.multiplier)
    return min(MAX_EFFECT_MULTIPLIER, max(MIN_EFFECT_MULTIPLIER, multiplier))


def resolve_effect(
    world: World,
    target: Entity,
    effect: EffectSpec,
    *,
    current: float | None = None,
) -> tuple[EffectResolution, SetComponent] | None:
    """Resolve a supported health effect without mutating the world directly."""

    del world
    if not target.has_component(HealthComponent):
        return None
    health = target.get_component(HealthComponent)
    before = health.current if current is None else min(health.maximum, max(0.0, current))
    multiplier = _effect_multiplier(target, effect.tags)
    magnitude = max(0.0, effect.magnitude) * multiplier
    if effect.effect_type == "heal":
        after = min(health.maximum, before + magnitude)
    else:
        after = max(0.0, before - magnitude)
    resolution = EffectResolution(
        target_id=str(target.id),
        effect_type=effect.effect_type,
        magnitude=effect.magnitude,
        tags=effect.tags,
        target_mode=effect.target_mode,
        multiplier=multiplier,
        before=before,
        after=after,
    )
    return resolution, SetComponent(target.id, replace(health, current=after))


__all__ = [
    "EffectModifier",
    "EffectResolution",
    "EffectSpec",
    "EffectTargetMode",
    "EffectType",
    "MAX_EFFECT_MULTIPLIER",
    "MIN_EFFECT_MULTIPLIER",
    "effect_spec",
    "resolve_effect",
]
