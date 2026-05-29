"""Core ECS components (spec sections 6, 8, 11).

Components are small, focused, frozen value objects. Mutating state means building a
new component (``dataclasses.replace``) and swapping it in via ``replace_component``.

Only the components needed for the foundational spine live here. Domain mechanics
(hunger, thirst, affect, environment, ...) get their own modules/plugins.
"""

from __future__ import annotations

from pydantic.dataclasses import dataclass
from relics import Component

# --------------------------------------------------------------------------------------
# Identity and lifecycle (spec 11.1)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentityComponent(Component):
    name: str
    kind: str
    tags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DescriptionComponent(Component):
    short: str
    long: str = ""
    appearance: str = ""


@dataclass(frozen=True)
class LifecycleComponent(Component):
    active: bool = True
    destroyed: bool = False
    created_at_epoch: int = 0


# --------------------------------------------------------------------------------------
# World clock (spec 11.2)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WorldClockComponent(Component):
    game_time_seconds: int = 0
    tick_index: int = 0
    time_scale: float = 1.0


# --------------------------------------------------------------------------------------
# Rooms and characters (spec 11.3, 11.10)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RoomComponent(Component):
    title: str
    biome: str = "unknown"
    indoor: bool = False
    private: bool = False
    safe: bool = True


@dataclass(frozen=True)
class CharacterComponent(Component):
    species: str = "bunny"
    biography: str = ""
    public: bool = True


# --------------------------------------------------------------------------------------
# Action and Focus points (spec 6.1)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionPointsComponent(Component):
    current: float = 0.0
    maximum: float = 5.0
    regen_per_hour: float = 1.0
    overflow_maximum: float | None = None


@dataclass(frozen=True)
class FocusPointsComponent(Component):
    current: float = 0.0
    maximum: float = 3.0
    regen_per_hour: float = 0.5
    overflow_maximum: float | None = None


@dataclass(frozen=True)
class InitiativeComponent(Component):
    """Acting order each tick; ties broken randomly (spec 5.5)."""

    score: float = 0.0


# --------------------------------------------------------------------------------------
# Lifecycle states: suspended / downed / dead (spec 7.7, 8)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SuspendedComponent(Component):
    """Marker for a suspended (no-op-controlled) character. Indexable (spec 8.1)."""

    reason: str = "offline"
    suspended_at_epoch: int = 0


@dataclass(frozen=True)
class DownedComponent(Component):
    downed_at_epoch: int
    cause: str
    checks_remaining: int = 3
    stable: bool = False


@dataclass(frozen=True)
class DeadComponent(Component):
    died_at_epoch: int
    cause: str
    source_event_id: str | None = None


__all__ = [
    "ActionPointsComponent",
    "CharacterComponent",
    "DeadComponent",
    "DescriptionComponent",
    "DownedComponent",
    "FocusPointsComponent",
    "IdentityComponent",
    "InitiativeComponent",
    "LifecycleComponent",
    "RoomComponent",
    "SuspendedComponent",
    "WorldClockComponent",
]
