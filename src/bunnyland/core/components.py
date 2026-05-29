"""Core ECS components (spec sections 6, 8, 11).

Components are small, focused, frozen value objects. Mutating state means building a
new component (``dataclasses.replace``) and swapping it in via ``replace_component``.

Only the components needed for the foundational spine live here. Domain mechanics
(hunger, thirst, affect, environment, ...) get their own modules/plugins.
"""

from __future__ import annotations

from pydantic.dataclasses import dataclass
from relics import Component

from .edges import ContainmentMode

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
class RoomSummaryComponent(Component):
    """Event-driven projection cache for a room (spec 11.4, 17).

    The prose ``visible_summary`` is a readability aid rebuilt from structured facts; it
    is never the source of truth. ``dirty`` marks it stale after a relevant world change.
    """

    visible_summary: str = ""
    last_updated_epoch: int = 0
    version: int = 0
    dirty: bool = True


@dataclass(frozen=True)
class TemperatureComponent(Component):
    """Ambient temperature (spec 11.13). The driving system arrives with environment."""

    celsius: float = 20.0


@dataclass(frozen=True)
class LightComponent(Component):
    level: float = 1.0
    enabled: bool = True
    natural: bool = True


@dataclass(frozen=True)
class CharacterComponent(Component):
    species: str = "bunny"
    biography: str = ""
    public: bool = True


@dataclass(frozen=True)
class HealthComponent(Component):
    current: float = 100.0
    maximum: float = 100.0


# --------------------------------------------------------------------------------------
# Physical objects and inventory (spec 11.5)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PortableComponent(Component):
    can_pick_up: bool = True
    min_strength: float = 0.0
    requires_tool: bool = False


@dataclass(frozen=True)
class ContainerComponent(Component):
    allow_add: bool = True
    allow_remove: bool = True
    max_slots: int | None = None
    open: bool = True
    transparent: bool = False
    locked: bool = False


@dataclass(frozen=True)
class InventoryComponent(Component):
    max_slots: int | None = 20
    default_drop_mode: ContainmentMode = ContainmentMode.ROOM_CONTENT


# --------------------------------------------------------------------------------------
# Mechanisms (spec 11.9) and readable/writable objects (spec 11.8)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DoorComponent(Component):
    open: bool = False
    open_on_use: bool = True
    auto_close_after_ticks: int | None = None


@dataclass(frozen=True)
class ButtonComponent(Component):
    active: bool = True
    toggle: bool = False
    pressed: bool = False
    cooldown_ticks: int = 0
    reset_after_ticks: int | None = None


@dataclass(frozen=True)
class LockableComponent(Component):
    locked: bool = True
    key_name: str | None = None
    difficulty: float = 0.0


@dataclass(frozen=True)
class KeyComponent(Component):
    key_name: str


@dataclass(frozen=True)
class ReadableComponent(Component):
    title: str | None = None
    text: str = ""


@dataclass(frozen=True)
class WritableComponent(Component):
    remaining_space: int | None = None
    erasable: bool = False


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
class SleepingComponent(Component):
    """Marker for a sleeping character (spec 11.11).

    Sleeping characters do not act (only ``wake``) and do not perceive speech by default
    (spec 19). Distinct from the fatigue meter, which is a separate need mechanic.
    """

    started_at_epoch: int = 0
    safe_sleep: bool = True
    wake_when_recharged: bool = False


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
    "ButtonComponent",
    "CharacterComponent",
    "ContainerComponent",
    "DeadComponent",
    "DescriptionComponent",
    "DoorComponent",
    "DownedComponent",
    "FocusPointsComponent",
    "HealthComponent",
    "IdentityComponent",
    "InitiativeComponent",
    "InventoryComponent",
    "KeyComponent",
    "LifecycleComponent",
    "LightComponent",
    "LockableComponent",
    "PortableComponent",
    "ReadableComponent",
    "RoomComponent",
    "RoomSummaryComponent",
    "SleepingComponent",
    "SuspendedComponent",
    "TemperatureComponent",
    "WorldClockComponent",
    "WritableComponent",
]
