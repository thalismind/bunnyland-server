"""Typed domain events and a lightweight event bus (spec section 18).

Events are typed Pydantic models. Handlers subscribe to concrete event classes (or a
base class to receive a whole hierarchy). The bus is owned by the world actor and
dispatched synchronously within a tick; async handlers are awaited.

These are bunnyland's own domain events, distinct from Relics' internal ``CustomEvent``
observer system. The world actor is the single emitter, so ordering is deterministic.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .components import GenerationIntentComponent


class EventVisibility(StrEnum):
    PUBLIC = "public"
    ROOM = "room"
    DIRECTED = "directed"
    PRIVATE = "private"
    SYSTEM = "system"


class DomainEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    world_epoch: int
    created_at: datetime

    visibility: EventVisibility = EventVisibility.SYSTEM
    actor_id: str | None = None
    room_id: str | None = None
    target_ids: tuple[str, ...] = ()

    causation_id: str | None = None
    correlation_id: str | None = None


# --------------------------------------------------------------------------------------
# Command lifecycle events (spec 18.3)
# --------------------------------------------------------------------------------------


class CommandSubmittedEvent(DomainEvent):
    command_id: str
    command_type: str


class CommandAcceptedEvent(DomainEvent):
    command_id: str
    command_type: str


class CommandRejectedEvent(DomainEvent):
    command_id: str
    command_type: str
    reason: str


class CommandQueuedEvent(DomainEvent):
    command_id: str
    command_type: str
    lane: str


class CommandExecutedEvent(DomainEvent):
    command_id: str
    command_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    result_events: tuple[dict[str, Any], ...] = ()


class CommandExpiredEvent(DomainEvent):
    command_id: str
    command_type: str


# --------------------------------------------------------------------------------------
# Points and controller events
# --------------------------------------------------------------------------------------


class ActionPointsChangedEvent(DomainEvent):
    current: float
    maximum: float


class FocusPointsChangedEvent(DomainEvent):
    current: float
    maximum: float


class ControllerChangedEvent(DomainEvent):
    generation: int
    controller_kind: str


class CharacterClaimedEvent(DomainEvent):
    character_id: str
    controller_id: str
    generation: int


class WorldPauseStatusChangedEvent(DomainEvent):
    paused: bool
    state: str
    message: str


# --------------------------------------------------------------------------------------
# Health / downed / death events (spec 18.3)
# --------------------------------------------------------------------------------------


class CharacterDownedEvent(DomainEvent):
    cause: str


class CharacterRevivedEvent(DomainEvent):
    pass


class CharacterDiedEvent(DomainEvent):
    cause: str


class EncumbranceChangedEvent(DomainEvent):
    current_load: float
    capacity: float
    overburdened: bool
    speed_multiplier: float


class InjuryAddedEvent(DomainEvent):
    injury_id: str
    body_part: str
    severity: float
    bleeding_rate: float = 0.0


class PainChangedEvent(DomainEvent):
    current: float


class BleedingChangedEvent(DomainEvent):
    rate: float
    accumulated_loss: float


class EntitySeenEvent(DomainEvent):
    entity_id: str


class NoiseHeardEvent(DomainEvent):
    noise_id: str
    source_entity_id: str | None = None
    text: str = ""


class AttentionShiftedEvent(DomainEvent):
    focus_entity_id: str | None = None
    focus_room_id: str | None = None
    score: float


class AffectChangedEvent(DomainEvent):
    labels: tuple[str, ...] = ()


class PartnershipStartedEvent(DomainEvent):
    partner_id: str


class PartnershipEndedEvent(DomainEvent):
    partner_id: str


class PregnancyStartedEvent(DomainEvent):
    pregnant_id: str
    co_parent_ids: tuple[str, ...] = ()
    due_at_epoch: int


class BirthDueEvent(DomainEvent):
    pregnant_id: str
    due_since_epoch: int


class BirthResolvedEvent(DomainEvent):
    child_id: str
    parent_ids: tuple[str, ...] = ()


class AdoptionCompletedEvent(DomainEvent):
    child_id: str
    parent_id: str


class ReservationCreatedEvent(DomainEvent):
    target_id: str


class ReservationReleasedEvent(DomainEvent):
    target_id: str


class ResourceGatheredEvent(DomainEvent):
    node_id: str
    resource_type: str
    quantity: int
    stack_id: str


class StockpileCreatedEvent(DomainEvent):
    stockpile_id: str
    capacity: int


class StorageFilterChangedEvent(DomainEvent):
    stockpile_id: str
    allowed_types: tuple[str, ...] = ()


class ItemForbiddenEvent(DomainEvent):
    item_id: str
    forbidden: bool


class ItemHauledEvent(DomainEvent):
    item_id: str
    target_container_id: str


class StackSplitEvent(DomainEvent):
    source_stack_id: str
    new_stack_id: str
    quantity: int


class StackMergedEvent(DomainEvent):
    source_stack_id: str
    target_stack_id: str
    quantity: int


class ItemCraftedEvent(DomainEvent):
    recipe_id: str
    output_ids: tuple[str, ...] = ()


class JobAssignedEvent(DomainEvent):
    job_id: str


class JobCompletedEvent(DomainEvent):
    job_id: str


class OwnershipClaimedEvent(DomainEvent):
    target_id: str


class OwnershipReleasedEvent(DomainEvent):
    target_id: str


class CharacterAttackedEvent(DomainEvent):
    target_id: str
    weapon_id: str | None = None
    damage: float
    lethal: bool = False
    sparring: bool = False


class CharacterDefendedEvent(DomainEvent):
    reduction: float


class CombatChallengeEvent(DomainEvent):
    target_id: str
    terms: str = ""


class FortificationBuiltEvent(DomainEvent):
    target_id: str
    durability: float
    rating: float


class RaidStartedEvent(DomainEvent):
    target_id: str
    intensity: float
    damage: float


class CharacterPickpocketedEvent(DomainEvent):
    target_id: str
    item_id: str


# --------------------------------------------------------------------------------------
# Movement / world events
# --------------------------------------------------------------------------------------


class ActorMovedEvent(DomainEvent):
    from_room_id: str
    to_room_id: str
    direction: str | None = None


# --------------------------------------------------------------------------------------
# Inventory / object events (spec 18.3)
# --------------------------------------------------------------------------------------


class ItemTakenEvent(DomainEvent):
    item_id: str
    from_container_id: str


class ItemPutEvent(DomainEvent):
    item_id: str
    to_container_id: str


class ItemDroppedEvent(DomainEvent):
    item_id: str
    room_id_dropped: str


class ItemUsedEvent(DomainEvent):
    item_id: str
    affordance: str
    tool_id: str | None = None


class PhysicalWriteEvent(DomainEvent):
    item_id: str
    text: str


# --------------------------------------------------------------------------------------
# Speech events (spec 14, 18.3). Visibility distinguishes room speech from directed.
# --------------------------------------------------------------------------------------


class SpeechSaidEvent(DomainEvent):
    text: str
    author_intent: str | None = None
    inferred_intent: str | None = None
    final_interpretation: str | None = None
    approach: str | None = None


class SpeechToldEvent(DomainEvent):
    text: str
    author_intent: str | None = None
    inferred_intent: str | None = None
    final_interpretation: str | None = None
    approach: str | None = None
    overhearer_ids: tuple[str, ...] = ()


# --------------------------------------------------------------------------------------
# Private notes / memory events (spec 15, 18.4). Always private to the character.
# --------------------------------------------------------------------------------------


class NoteTakenEvent(DomainEvent):
    note_id: str
    text: str
    scope: str = "private"
    collection: str | None = None


class NotesSearchedEvent(DomainEvent):
    query: str | None
    mode: str
    results: tuple[str, ...] = ()
    note_ids: tuple[str, ...] = ()
    scope: str = "private"
    collection: str | None = None


class NoteForgottenEvent(DomainEvent):
    note_id: str
    scope: str = "private"
    collection: str | None = None


class ReflectionCreatedEvent(DomainEvent):
    note_id: str
    text: str
    source_note_ids: tuple[str, ...] = ()


# --------------------------------------------------------------------------------------
# World generation events (spec 18.3, 22)
# --------------------------------------------------------------------------------------


class WorldGeneratedEvent(DomainEvent):
    seed: str
    room_count: int
    character_count: int


class GeneratedEntityEvent(DomainEvent):
    seed: str
    entity_id: str
    entity_key: str
    entity_kind: str
    generation: GenerationIntentComponent = Field(default_factory=GenerationIntentComponent)

    @property
    def intent(self) -> str:
        return self.generation.description

    @property
    def tags(self) -> tuple[str, ...]:
        return self.generation.tags

    @property
    def wants(self) -> tuple[str, ...]:
        return self.generation.wants

    @property
    def needs(self) -> tuple[str, ...]:
        return self.generation.needs


class RoomGeneratedEvent(GeneratedEntityEvent):
    room_key: str
    biome: str = "unknown"
    indoor: bool = False


class ObjectGeneratedEvent(GeneratedEntityEvent):
    object_key: str
    room_id: str | None = None
    container_id: str | None = None
    containment_mode: str = "room_content"


class CharacterGeneratedEvent(GeneratedEntityEvent):
    character_key: str
    room_id: str
    species: str = "bunny"


class WorldGenerationStartedEvent(DomainEvent):
    job_id: str
    seed: str
    generator: str


class WorldGenerationCompletedEvent(DomainEvent):
    job_id: str
    seed: str
    generator: str
    room_count: int
    character_count: int


class WorldGenerationFailedEvent(DomainEvent):
    job_id: str
    seed: str
    generator: str
    error: str


# --------------------------------------------------------------------------------------
# Event bus
# --------------------------------------------------------------------------------------

E = TypeVar("E", bound=DomainEvent)
Handler = Callable[[DomainEvent], None | Awaitable[None]]


class EventBus:
    """Synchronous-ordered dispatch with support for async handlers.

    Subscriptions are keyed by event class. Subscribing to a base class (e.g.
    ``DomainEvent``) receives every subclass, enabling audit/logging sinks.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[E], handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: type[E], handler: Handler) -> None:
        handlers = self._handlers.get(event_type)
        if not handlers:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            return

    async def publish(self, event: DomainEvent) -> None:
        for event_type, handlers in self._handlers.items():
            if isinstance(event, event_type):
                for handler in handlers:
                    result = handler(event)
                    if isinstance(result, Awaitable):
                        await result


__all__ = [
    "ActionPointsChangedEvent",
    "AdoptionCompletedEvent",
    "ActorMovedEvent",
    "AffectChangedEvent",
    "AttentionShiftedEvent",
    "BleedingChangedEvent",
    "BirthDueEvent",
    "BirthResolvedEvent",
    "CharacterDiedEvent",
    "CharacterDownedEvent",
    "CharacterAttackedEvent",
    "CharacterDefendedEvent",
    "CharacterPickpocketedEvent",
    "CharacterClaimedEvent",
    "CharacterRevivedEvent",
    "CombatChallengeEvent",
    "CommandAcceptedEvent",
    "CommandExecutedEvent",
    "CommandExpiredEvent",
    "CommandQueuedEvent",
    "CommandRejectedEvent",
    "CommandSubmittedEvent",
    "ControllerChangedEvent",
    "DomainEvent",
    "EncumbranceChangedEvent",
    "EntitySeenEvent",
    "EventBus",
    "EventVisibility",
    "FortificationBuiltEvent",
    "FocusPointsChangedEvent",
    "GeneratedEntityEvent",
    "InjuryAddedEvent",
    "ItemDroppedEvent",
    "ItemCraftedEvent",
    "ItemPutEvent",
    "ItemTakenEvent",
    "ItemUsedEvent",
    "JobAssignedEvent",
    "JobCompletedEvent",
    "ItemForbiddenEvent",
    "ItemHauledEvent",
    "NoiseHeardEvent",
    "NoteTakenEvent",
    "NotesSearchedEvent",
    "OwnershipClaimedEvent",
    "OwnershipReleasedEvent",
    "PainChangedEvent",
    "PartnershipEndedEvent",
    "PartnershipStartedEvent",
    "PregnancyStartedEvent",
    "ReservationCreatedEvent",
    "ReservationReleasedEvent",
    "RaidStartedEvent",
    "ResourceGatheredEvent",
    "StackMergedEvent",
    "StackSplitEvent",
    "StockpileCreatedEvent",
    "StorageFilterChangedEvent",
    "PhysicalWriteEvent",
    "ReflectionCreatedEvent",
    "RoomGeneratedEvent",
    "SpeechSaidEvent",
    "SpeechToldEvent",
    "WorldPauseStatusChangedEvent",
    "WorldGenerationCompletedEvent",
    "WorldGenerationFailedEvent",
    "WorldGenerationStartedEvent",
    "WorldGeneratedEvent",
    "ObjectGeneratedEvent",
    "CharacterGeneratedEvent",
]
