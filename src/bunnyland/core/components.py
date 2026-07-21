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
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DescriptionComponent(Component):
    short: str
    long: str = ""
    appearance: str = ""


@dataclass(frozen=True)
class GenerationIntentComponent(Component):
    """Semantic generation metadata shared by proposals, events, and ECS entities.

    ``wants`` are optional plugin capabilities to try; ``needs`` are stronger hints that
    a generated entity expects a plugin to satisfy. Both are data, not component names
    the core generator has to understand.
    """

    description: str = ""
    tags: tuple[str, ...] = ()
    wants: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    source_seed: str = ""
    source_key: str = ""
    entity_kind: str = ""
    unmet_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class LifecycleComponent(Component):
    active: bool = True
    destroyed: bool = False
    created_at_epoch: int = 0


@dataclass(frozen=True)
class EditorDisplayComponent(Component):
    """A custom emoji the web client/graph editor shows instead of the kind default.

    Purely presentational: the engine never reads it. When absent, clients fall back to
    their built-in per-kind iconography.
    """

    emoji: str = ""


@dataclass(frozen=True)
class ControllerOutboxMessageComponent(Component):
    """A pending message for a controller integration to deliver.

    Message history is repeatable, so each message is a separate entity. Transport
    adapters mark delivery by replacing this component; they do not store queues outside
    the ECS.
    """

    controller_id: str
    text: str
    created_at_epoch: int
    delivered_at_epoch: int | None = None


@dataclass(frozen=True)
class AdminComponent(Component):
    """Marks a character or controller entity as allowed to use admin-only verbs."""

    label: str = ""


@dataclass(frozen=True)
class ConversationComponent(Component):
    """Structured state for a bounded, turn-taking conversation micro-loop."""

    topic: str = ""
    active_turn: int = 0
    started_at_epoch: int = 0
    expires_at_epoch: int = 0
    ended: bool = False
    ended_reason: str = ""


# --------------------------------------------------------------------------------------
# Affect, thoughts (spec 11.12). Mood is multidimensional, not a single scalar.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AffectVector:
    valence: float = 0.0
    arousal: float = 0.0
    stress: float = 0.0
    fear: float = 0.0
    anger: float = 0.0
    sadness: float = 0.0
    confidence: float = 0.0
    sociability: float = 0.0
    curiosity: float = 0.0
    focus: float = 0.0


@dataclass(frozen=True)
class AffectDelta:
    valence: float = 0.0
    arousal: float = 0.0
    stress: float = 0.0
    fear: float = 0.0
    anger: float = 0.0
    sadness: float = 0.0
    confidence: float = 0.0
    sociability: float = 0.0
    curiosity: float = 0.0
    focus: float = 0.0


@dataclass(frozen=True)
class AffectComponent(Component):
    baseline: AffectVector = AffectVector()
    current: AffectVector = AffectVector()
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThoughtComponent(Component):
    label: str
    text: str
    affect_delta: AffectDelta
    created_at_epoch: int
    expires_at_epoch: int | None = None
    source_event_id: str | None = None


# --------------------------------------------------------------------------------------
# World state (spec 11.2)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WorldInfoComponent(Component):
    """Singleton player-facing identity and welcome text for this world."""

    title: str = ""
    description: str = ""
    content_flags: frozenset[str] = frozenset()


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
class RegionComponent(Component):
    """A named geographic or structural area above room scale.

    ``kind`` is intentionally data-driven so worlds can model a planet/continent/country
    chain, a station/deck/sector chain, or other setting-specific hierarchies without
    new component classes.
    """

    name: str
    kind: str = "region"
    population: int | None = None
    climate: str = ""
    terrain: str = ""


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


# --------------------------------------------------------------------------------------
# Perception, attention, noise, stealth (spec 11.14)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PerceptionComponent(Component):
    active: bool = True
    visible_entities: frozenset[str] = frozenset()
    audible_entities: frozenset[str] = frozenset()


@dataclass(frozen=True)
class HearingComponent(Component):
    sensitivity: float = 1.0


@dataclass(frozen=True)
class StimulusComponent(Component):
    stimulus_type: str
    source_entity_id: str | None
    room_id: str | None
    intensity: float = 1.0
    created_at_epoch: int = 0
    expires_at_epoch: int | None = None
    text: str = ""


@dataclass(frozen=True)
class AttentionComponent(Component):
    score: float = 0.0
    focus_entity_id: str | None = None
    focus_room_id: str | None = None
    decay_rate: float = 0.1
    time_since_stimulus: float = 0.0
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class NoiseComponent(Component):
    loudness: float
    text: str
    source_entity_id: str | None = None
    room_id: str | None = None
    created_at_epoch: int = 0
    expires_at_epoch: int | None = None


@dataclass(frozen=True)
class StealthComponent(Component):
    visibility_level: float = 1.0
    hidden_threshold: float = 0.1
    hiding: bool = False


@dataclass(frozen=True)
class CharacterComponent(Component):
    species: str = "bunny"
    biography: str = ""
    public: bool = True


@dataclass(frozen=True)
class HealthComponent(Component):
    current: float = 100.0
    maximum: float = 100.0


@dataclass(frozen=True)
class BodyPlanComponent(Component):
    parts: tuple[str, ...] = ("body",)
    vital_parts: tuple[str, ...] = ("body",)


@dataclass(frozen=True)
class InjuryComponent(Component):
    body_part: str = "body"
    severity: float = 0.0
    pain: float = 0.0
    bleeding_rate: float = 0.0
    treated: bool = False
    applied_at_epoch: int = 0
    source_event_id: str | None = None


@dataclass(frozen=True)
class PainComponent(Component):
    current: float = 0.0
    updated_at_epoch: int = 0


@dataclass(frozen=True)
class BleedingComponent(Component):
    rate: float = 0.0
    accumulated_loss: float = 0.0
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class WeightComponent(Component):
    weight: float = 1.0


@dataclass(frozen=True)
class EncumbranceComponent(Component):
    current_load: float = 0.0
    capacity: float = 10.0
    overburdened: bool = False
    speed_multiplier: float = 1.0
    updated_at_epoch: int = 0


@dataclass(frozen=True)
class MemoryProfileComponent(Component):
    """Names a character's private memory/notes collection (spec 11.16)."""

    vector_collection: str
    shared_collections: tuple[str, ...] = ()
    last_event_seen_id: str | None = None
    last_reflection_epoch: int = 0


# --------------------------------------------------------------------------------------
# Physical objects and inventory (spec 11.5)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PortableComponent(Component):
    can_pick_up: bool = True
    min_strength: float = 0.0
    requires_tool: bool = False


@dataclass(frozen=True)
class HoldableComponent(Component):
    slot: str = "hand"


@dataclass(frozen=True)
class WearableComponent(Component):
    slot: str = "body"


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

    def prompt_fragments(self, ctx) -> tuple[str, ...]:
        del ctx
        return (f"Key nearby: {self.key_name}.",)


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
    "AdminComponent",
    "ActionPointsComponent",
    "AffectComponent",
    "AffectDelta",
    "AffectVector",
    "AttentionComponent",
    "BleedingComponent",
    "BodyPlanComponent",
    "ButtonComponent",
    "CharacterComponent",
    "ContainerComponent",
    "ConversationComponent",
    "DeadComponent",
    "DescriptionComponent",
    "DoorComponent",
    "DownedComponent",
    "EncumbranceComponent",
    "FocusPointsComponent",
    "GenerationIntentComponent",
    "HearingComponent",
    "HealthComponent",
    "HoldableComponent",
    "IdentityComponent",
    "InitiativeComponent",
    "InventoryComponent",
    "InjuryComponent",
    "KeyComponent",
    "LifecycleComponent",
    "LightComponent",
    "LockableComponent",
    "MemoryProfileComponent",
    "NoiseComponent",
    "PerceptionComponent",
    "PainComponent",
    "PortableComponent",
    "ReadableComponent",
    "RegionComponent",
    "RoomComponent",
    "RoomSummaryComponent",
    "SleepingComponent",
    "StealthComponent",
    "StimulusComponent",
    "SuspendedComponent",
    "TemperatureComponent",
    "ThoughtComponent",
    "WorldClockComponent",
    "WorldInfoComponent",
    "WritableComponent",
    "WeightComponent",
    "WearableComponent",
]
