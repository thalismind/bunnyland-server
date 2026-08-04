"""Shared sleep and ordinary-rest recovery lifecycle."""

from __future__ import annotations

from relics import Entity, EntityId, World

from .components import (
    AffectComponent,
    AffectDelta,
    DeadComponent,
    DownedComponent,
    HealthComponent,
    RestingComponent,
    SleepingComponent,
    SuspendedComponent,
    ThoughtComponent,
)
from .ecs import replace_component, spawn_entity
from .edges import HasThought
from .events import (
    CharacterAttackedEvent,
    CharacterWokeEvent,
    DomainEvent,
    EventVisibility,
    RecoveryEndReason,
    RestEndedEvent,
    event_base,
)
from .mutations import (
    AddEdge,
    AddEntity,
    EntityReference,
    MutationOperation,
    RemoveComponent,
    SetComponent,
)

SECONDS_PER_HOUR = 3600
REST_STRESS_RELIEF_PER_HOUR = 4.0
SLEEP_STRESS_RELIEF_PER_HOUR = 6.0
REST_STRESS_RELIEF_CAP = 12.0
SLEEP_STRESS_RELIEF_CAP = 18.0
RESTED_THOUGHT_TTL_SECONDS = 2 * SECONDS_PER_HOUR


def sleep_session_id(character_id: EntityId, sleeping: SleepingComponent) -> str:
    """Return the stable persisted identifier for one sleep session."""

    return f"sleep:{character_id}:{sleeping.started_at_epoch}"


def _stress_relief(
    *, started_at_epoch: int, end_epoch: float, rate: float, cap: float
) -> float:
    elapsed_hours = max(0.0, end_epoch - started_at_epoch) / SECONDS_PER_HOUR
    return -min(cap, rate * elapsed_hours)


def _rested_thought(character: Entity, world: World, session_id: str):
    for _edge, thought_id in character.get_relationships(HasThought):
        thought_entity = world.get_entity(thought_id)
        if not thought_entity.has_component(ThoughtComponent):
            continue
        thought = thought_entity.get_component(ThoughtComponent)
        if thought.label == "rested" and thought.source_event_id == session_id:
            return thought_entity, thought
    return None


def _thought_component(
    session_id: str,
    *,
    started_at_epoch: int,
    stress_relief: float,
    expires_at_epoch: int | None,
) -> ThoughtComponent:
    return ThoughtComponent(
        label="rested",
        text="I feel restored by taking time to recover.",
        affect_delta=AffectDelta(stress=stress_relief),
        created_at_epoch=started_at_epoch,
        expires_at_epoch=expires_at_epoch,
        source_event_id=session_id,
    )


def _thought_operations(
    world: World,
    character: Entity,
    session_id: str,
    *,
    started_at_epoch: int,
    stress_relief: float,
    expires_at_epoch: int | None,
) -> tuple[MutationOperation, ...]:
    if not character.has_component(AffectComponent) or stress_relief >= 0:
        return ()
    existing = _rested_thought(character, world, session_id)
    component = _thought_component(
        session_id,
        started_at_epoch=started_at_epoch,
        stress_relief=stress_relief,
        expires_at_epoch=expires_at_epoch,
    )
    if existing is not None:
        thought_entity, _thought = existing
        return (SetComponent(thought_entity.id, component),)
    reference = EntityReference()
    return (
        AddEntity((component,), reference=reference),
        AddEdge(character.id, reference, HasThought()),
    )


def end_rest_operations(
    world: World,
    character: Entity,
    rest: RestingComponent,
    *,
    epoch: int,
) -> tuple[MutationOperation, ...]:
    end_epoch = min(float(epoch), rest.until_epoch or float(epoch))
    relief = _stress_relief(
        started_at_epoch=rest.started_at_epoch,
        end_epoch=end_epoch,
        rate=REST_STRESS_RELIEF_PER_HOUR,
        cap=REST_STRESS_RELIEF_CAP,
    )
    return (
        *_thought_operations(
            world,
            character,
            rest.session_id,
            started_at_epoch=rest.started_at_epoch,
            stress_relief=relief,
            expires_at_epoch=epoch + RESTED_THOUGHT_TTL_SECONDS,
        ),
        RemoveComponent(character.id, RestingComponent),
    )


def end_sleep_operations(
    world: World,
    character: Entity,
    sleeping: SleepingComponent,
    *,
    epoch: int,
) -> tuple[MutationOperation, ...]:
    session_id = sleep_session_id(character.id, sleeping)
    end_epoch = min(float(epoch), sleeping.until_epoch or float(epoch))
    relief = _stress_relief(
        started_at_epoch=sleeping.started_at_epoch,
        end_epoch=end_epoch,
        rate=SLEEP_STRESS_RELIEF_PER_HOUR,
        cap=SLEEP_STRESS_RELIEF_CAP,
    )
    return (
        *_thought_operations(
            world,
            character,
            session_id,
            started_at_epoch=sleeping.started_at_epoch,
            stress_relief=relief,
            expires_at_epoch=epoch + RESTED_THOUGHT_TTL_SECONDS,
        ),
        RemoveComponent(character.id, SleepingComponent),
    )


def rest_ended_event(
    epoch: int,
    character: Entity,
    rest: RestingComponent,
    reason: RecoveryEndReason,
) -> RestEndedEvent:
    return RestEndedEvent(
        **event_base(
            epoch,
            default_visibility=EventVisibility.PRIVATE,
            actor_id=str(character.id),
            session_id=rest.session_id,
            reason=reason,
        )
    )


def woke_event(
    epoch: int,
    character: Entity,
    sleeping: SleepingComponent,
    reason: RecoveryEndReason,
) -> CharacterWokeEvent:
    return CharacterWokeEvent(
        **event_base(
            epoch,
            default_visibility=EventVisibility.PRIVATE,
            actor_id=str(character.id),
            session_id=sleep_session_id(character.id, sleeping),
            reason=reason,
        )
    )


def _update_active_thought(
    world: World,
    character: Entity,
    session_id: str,
    *,
    started_at_epoch: int,
    end_epoch: float,
    rate: float,
    cap: float,
    expires_at_epoch: int | None,
) -> None:
    relief = _stress_relief(
        started_at_epoch=started_at_epoch,
        end_epoch=end_epoch,
        rate=rate,
        cap=cap,
    )
    if not character.has_component(AffectComponent) or relief >= 0:
        return
    component = _thought_component(
        session_id,
        started_at_epoch=started_at_epoch,
        stress_relief=relief,
        expires_at_epoch=expires_at_epoch,
    )
    existing = _rested_thought(character, world, session_id)
    if existing is None:
        thought_entity = spawn_entity(world, [component])
        character.add_relationship(HasThought(), thought_entity.id)
        return
    thought_entity, thought = existing
    if thought != component:
        replace_component(thought_entity, component)


class RecoveryInterruptions:
    """Damage observations shared by the two indexed recovery consequences."""

    def __init__(self) -> None:
        self.attacked_ids: set[str] = set()
        self.health: dict[tuple[str, str], float] = {}

    def subscribe(self, actor) -> None:
        actor.bus.subscribe(CharacterAttackedEvent, self._on_attack)
        actor.bus.subscribe(RestEndedEvent, self._on_recovery_ended)
        actor.bus.subscribe(CharacterWokeEvent, self._on_recovery_ended)

    def _on_attack(self, event: CharacterAttackedEvent) -> None:
        if event.damage > 0:
            self.attacked_ids.update(event.target_ids)

    def _on_recovery_ended(self, event: RestEndedEvent | CharacterWokeEvent) -> None:
        if event.actor_id is not None:
            self.finish_id(event.actor_id, event.session_id)

    def danger(self, character: Entity, session_id: str) -> bool:
        key = (str(character.id), session_id)
        current = (
            character.get_component(HealthComponent).current
            if character.has_component(HealthComponent)
            else None
        )
        previous = self.health.get(key)
        if current is not None:
            self.health[key] = current
        attacked = str(character.id) in self.attacked_ids
        self.attacked_ids.discard(str(character.id))
        return attacked or (
            previous is not None and current is not None and current < previous
        )

    def finish(self, character: Entity, session_id: str) -> None:
        self.finish_id(str(character.id), session_id)

    def finish_id(self, character_id: str, session_id: str) -> None:
        self.health.pop((character_id, session_id), None)
        self.attacked_ids.discard(character_id)


def _forced_end(character: Entity) -> bool:
    return any(
        character.has_component(component_type)
        for component_type in (DownedComponent, DeadComponent, SuspendedComponent)
    )


class RestRecoveryConsequence:
    """Advance and end ordinary rest from the RestingComponent index."""

    def __init__(self, interruptions: RecoveryInterruptions) -> None:
        self.interruptions = interruptions

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for character in world.query().with_all([RestingComponent]).execute_entities():
            rest = character.get_component(RestingComponent)
            danger = _forced_end(character) or self.interruptions.danger(
                character, rest.session_id
            )
            duration = rest.until_epoch is not None and epoch >= rest.until_epoch
            end_epoch = min(float(epoch), rest.until_epoch or float(epoch))
            _update_active_thought(
                world,
                character,
                rest.session_id,
                started_at_epoch=rest.started_at_epoch,
                end_epoch=end_epoch,
                rate=REST_STRESS_RELIEF_PER_HOUR,
                cap=REST_STRESS_RELIEF_CAP,
                expires_at_epoch=(
                    epoch + RESTED_THOUGHT_TTL_SECONDS if danger or duration else None
                ),
            )
            reason: RecoveryEndReason | None = (
                RecoveryEndReason.DANGER
                if danger
                else RecoveryEndReason.DURATION
                if duration
                else None
            )
            if reason is None:
                continue
            character.remove_component(RestingComponent)
            self.interruptions.finish(character, rest.session_id)
            events.append(rest_ended_event(epoch, character, rest, reason))
        return events


class SleepRecoveryConsequence:
    """Advance and end sleep from the SleepingComponent index."""

    def __init__(self, interruptions: RecoveryInterruptions) -> None:
        self.interruptions = interruptions

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for character in world.query().with_all([SleepingComponent]).execute_entities():
            sleeping = character.get_component(SleepingComponent)
            session_id = sleep_session_id(character.id, sleeping)
            danger = _forced_end(character) or self.interruptions.danger(
                character, session_id
            )
            duration = sleeping.until_epoch is not None and epoch >= sleeping.until_epoch
            end_epoch = min(float(epoch), sleeping.until_epoch or float(epoch))
            _update_active_thought(
                world,
                character,
                session_id,
                started_at_epoch=sleeping.started_at_epoch,
                end_epoch=end_epoch,
                rate=SLEEP_STRESS_RELIEF_PER_HOUR,
                cap=SLEEP_STRESS_RELIEF_CAP,
                expires_at_epoch=(
                    epoch + RESTED_THOUGHT_TTL_SECONDS if danger or duration else None
                ),
            )
            reason: RecoveryEndReason | None = (
                RecoveryEndReason.DANGER
                if danger
                else RecoveryEndReason.DURATION
                if duration
                else None
            )
            if reason is None:
                continue
            character.remove_component(SleepingComponent)
            self.interruptions.finish(character, session_id)
            events.append(woke_event(epoch, character, sleeping, reason))
        return events


def install_recovery(actor, context=None) -> None:
    """Install recovery last so damage/downing consequences run before interruption."""

    del context
    interruptions = RecoveryInterruptions()
    interruptions.subscribe(actor)
    actor.register_consequence(RestRecoveryConsequence(interruptions))
    actor.register_consequence(SleepRecoveryConsequence(interruptions))


def recovery_fragments(world: World, character: Entity) -> tuple[str, ...]:
    del world
    if character.has_component(RestingComponent):
        rest = character.get_component(RestingComponent)
        if rest.until_epoch is not None:
            return (f"I am resting until epoch {rest.until_epoch:g}.",)
        return ("I am resting.",)
    if character.has_component(SleepingComponent):
        sleeping = character.get_component(SleepingComponent)
        if sleeping.until_epoch is not None:
            return (f"I am asleep until epoch {sleeping.until_epoch:g}.",)
    return ()


__all__ = [
    "RecoveryEndReason",
    "RecoveryInterruptions",
    "RestRecoveryConsequence",
    "SleepRecoveryConsequence",
    "end_rest_operations",
    "end_sleep_operations",
    "install_recovery",
    "recovery_fragments",
    "rest_ended_event",
    "sleep_session_id",
    "woke_event",
]
