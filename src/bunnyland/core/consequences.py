"""Consequence systems run after command processing (spec 5.6 phase 6, 8.3, 8.4, 23.4).

Unlike passive simulation systems (which run inside ``world.tick`` before commands), a
consequence reads the post-command world, applies state transitions, and returns the
domain events it produced for the actor to publish. This keeps event emission on the
single async emitter while the mutation stays synchronous.

The cooperative health model: an active character at/below zero health is *downed*, not
killed. A downed character revives if healed, otherwise fails recovery checks and dies.
Suspended and dead characters are excluded throughout, so a suspended character can never
die (spec 8.3).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from relics import World

from ..projections.perception import perceive
from .components import (
    AttentionComponent,
    BleedingComponent,
    CharacterComponent,
    DeadComponent,
    DownedComponent,
    EncumbranceComponent,
    HealthComponent,
    HearingComponent,
    InjuryComponent,
    NoiseComponent,
    PainComponent,
    PerceptionComponent,
    StimulusComponent,
    SuspendedComponent,
    WeightComponent,
)
from .ecs import container_of, replace_component
from .edges import ContainmentMode, Contains, HasInjury
from .events import (
    AttentionShiftedEvent,
    BleedingChangedEvent,
    CharacterDiedEvent,
    CharacterDownedEvent,
    CharacterRevivedEvent,
    DomainEvent,
    EncumbranceChangedEvent,
    EntitySeenEvent,
    NoiseHeardEvent,
    PainChangedEvent,
)
from .events import EventVisibility as _Vis

DEFAULT_RECOVERY_CHECKS = 3


class Consequence(Protocol):
    def process(self, world: World, epoch: int) -> list[DomainEvent]: ...


def _event_base(epoch: int, **kwargs) -> dict:
    from datetime import UTC, datetime
    from uuid import uuid4

    base = {"event_id": uuid4().hex, "world_epoch": epoch, "created_at": datetime.now(UTC)}
    base.update(kwargs)
    return base


class HealthConsequence:
    """Down, revive, and kill characters based on ``HealthComponent`` (spec 8.3-8.4)."""

    def __init__(self, recovery_checks: int = DEFAULT_RECOVERY_CHECKS) -> None:
        self.recovery_checks = recovery_checks

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        events.extend(self._down_newly_injured(world, epoch))
        events.extend(self._resolve_downed(world, epoch))
        return events

    def _down_newly_injured(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        query = (
            world.query()
            .with_all([CharacterComponent, HealthComponent])
            .with_none([SuspendedComponent, DeadComponent, DownedComponent])
        )
        for entity in query.execute_entities():
            if entity.get_component(HealthComponent).current <= 0:
                entity.add_component(
                    DownedComponent(
                        downed_at_epoch=epoch,
                        cause="injury",
                        checks_remaining=self.recovery_checks,
                    )
                )
                events.append(
                    CharacterDownedEvent(
                        **_event_base(
                            epoch,
                            visibility=_Vis.ROOM,
                            actor_id=str(entity.id),
                            cause="injury",
                        )
                    )
                )
        return events

    def _resolve_downed(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        query = (
            world.query()
            .with_all([DownedComponent])
            .with_none([SuspendedComponent, DeadComponent])
        )
        for entity in query.execute_entities():
            downed = entity.get_component(DownedComponent)
            health = (
                entity.get_component(HealthComponent)
                if entity.has_component(HealthComponent)
                else None
            )
            # Healed back above zero -> revive.
            if health is not None and health.current > 0:
                entity.remove_component(DownedComponent)
                events.append(
                    CharacterRevivedEvent(
                        **_event_base(epoch, visibility=_Vis.ROOM, actor_id=str(entity.id))
                    )
                )
                continue
            if downed.stable:
                continue
            remaining = downed.checks_remaining - 1
            if remaining <= 0:
                entity.remove_component(DownedComponent)
                entity.add_component(DeadComponent(died_at_epoch=epoch, cause=downed.cause))
                events.append(
                    CharacterDiedEvent(
                        **_event_base(
                            epoch,
                            visibility=_Vis.ROOM,
                            actor_id=str(entity.id),
                            cause=downed.cause,
                        )
                    )
                )
            else:
                replace_component(entity, replace(downed, checks_remaining=remaining))
        return events


class EncumbranceConsequence:
    """Aggregate inventory weight into character load state."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for character in world.query().with_all([CharacterComponent]).execute_entities():
            existing = (
                character.get_component(EncumbranceComponent)
                if character.has_component(EncumbranceComponent)
                else EncumbranceComponent()
            )
            current_load = 0.0
            for edge, item_id in character.get_relationships(Contains):
                if edge.mode is not ContainmentMode.INVENTORY:
                    continue
                item = world.get_entity(item_id)
                if item.has_component(WeightComponent):
                    current_load += max(0.0, item.get_component(WeightComponent).weight)
            overburdened = current_load > existing.capacity
            speed_multiplier = (
                1.0 if current_load <= existing.capacity else existing.capacity / current_load
            )
            updated = replace(
                existing,
                current_load=current_load,
                overburdened=overburdened,
                speed_multiplier=speed_multiplier,
                updated_at_epoch=epoch,
            )
            if (
                not character.has_component(EncumbranceComponent)
                or existing.current_load != updated.current_load
                or existing.overburdened != updated.overburdened
                or existing.speed_multiplier != updated.speed_multiplier
            ):
                replace_component(character, updated)
                events.append(
                    EncumbranceChangedEvent(
                        **_event_base(
                            epoch,
                            visibility=_Vis.PRIVATE,
                            actor_id=str(character.id),
                            current_load=updated.current_load,
                            capacity=updated.capacity,
                            overburdened=updated.overburdened,
                            speed_multiplier=updated.speed_multiplier,
                        )
                    )
                )
        return events


class InjuryConsequence:
    """Aggregate wound pain/bleeding and apply bleeding health loss."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for character in world.query().with_all([CharacterComponent]).execute_entities():
            events.extend(self._process_character(world, character, epoch))
        return events

    def _process_character(self, world: World, character, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        pain_total = 0.0
        bleeding_rate = 0.0
        for _edge, injury_id in character.get_relationships(HasInjury):
            if not world.has_entity(injury_id):
                continue
            injury_entity = world.get_entity(injury_id)
            if not injury_entity.has_component(InjuryComponent):
                continue
            injury = injury_entity.get_component(InjuryComponent)
            if injury.treated:
                continue
            pain_total += max(0.0, injury.pain)
            bleeding_rate += max(0.0, injury.bleeding_rate)

        existing_pain = (
            character.get_component(PainComponent)
            if character.has_component(PainComponent)
            else PainComponent(updated_at_epoch=epoch)
        )
        updated_pain = replace(existing_pain, current=pain_total, updated_at_epoch=epoch)
        if (
            not character.has_component(PainComponent)
            or existing_pain.current != updated_pain.current
        ):
            replace_component(character, updated_pain)
            events.append(
                PainChangedEvent(
                    **_event_base(
                        epoch,
                        visibility=_Vis.PRIVATE,
                        actor_id=str(character.id),
                        current=updated_pain.current,
                    )
                )
            )

        existing_bleeding = (
            character.get_component(BleedingComponent)
            if character.has_component(BleedingComponent)
            else BleedingComponent(last_updated_epoch=epoch)
        )
        elapsed_hours = max(0, epoch - existing_bleeding.last_updated_epoch) / 3600.0
        loss = existing_bleeding.rate * elapsed_hours
        accumulated_loss = existing_bleeding.accumulated_loss
        if (
            loss
            and not character.has_component(SuspendedComponent)
            and character.has_component(HealthComponent)
        ):
            health = character.get_component(HealthComponent)
            replace_component(character, replace(health, current=health.current - loss))
            accumulated_loss += loss
        updated_bleeding = replace(
            existing_bleeding,
            rate=bleeding_rate,
            accumulated_loss=accumulated_loss,
            last_updated_epoch=epoch,
        )
        if (
            not character.has_component(BleedingComponent)
            or existing_bleeding.rate != updated_bleeding.rate
            or existing_bleeding.accumulated_loss != updated_bleeding.accumulated_loss
        ):
            replace_component(character, updated_bleeding)
            events.append(
                BleedingChangedEvent(
                    **_event_base(
                        epoch,
                        visibility=_Vis.PRIVATE,
                        actor_id=str(character.id),
                        rate=updated_bleeding.rate,
                        accumulated_loss=updated_bleeding.accumulated_loss,
                    )
                )
            )
        return events


class PerceptionConsequence:
    """Track visible entities for characters from the room perception projection."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for character in world.query().with_all([CharacterComponent]).execute_entities():
            existing = (
                character.get_component(PerceptionComponent)
                if character.has_component(PerceptionComponent)
                else PerceptionComponent()
            )
            perceived = perceive(world, character)
            visible = (
                frozenset(_perceived_ids(perceived.entities))
                if perceived.can_perceive
                else frozenset()
            )
            if existing.visible_entities == visible and character.has_component(
                PerceptionComponent
            ):
                continue
            replace_component(character, replace(existing, visible_entities=visible))
            for entity_id in sorted(visible - existing.visible_entities):
                events.append(
                    EntitySeenEvent(
                        **_event_base(
                            epoch,
                            visibility=_Vis.PRIVATE,
                            actor_id=str(character.id),
                            target_ids=(entity_id,),
                            entity_id=entity_id,
                        )
                    )
                )
        return events


class HearingConsequence:
    """Track audible noises for characters in the same room."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        noises = [
            noise
            for noise in world.query().with_all([NoiseComponent]).execute_entities()
            if _noise_active(noise.get_component(NoiseComponent), epoch)
        ]
        for character in world.query().with_all([CharacterComponent]).execute_entities():
            existing = (
                character.get_component(PerceptionComponent)
                if character.has_component(PerceptionComponent)
                else PerceptionComponent()
            )
            hearing = (
                character.get_component(HearingComponent)
                if character.has_component(HearingComponent)
                else HearingComponent()
            )
            if not existing.active:
                audible = frozenset()
            else:
                audible = frozenset(
                    str(noise.id)
                    for noise in noises
                    if _can_hear(character, noise.get_component(NoiseComponent), hearing)
                )
            if existing.audible_entities == audible and character.has_component(
                PerceptionComponent
            ):
                continue
            replace_component(character, replace(existing, audible_entities=audible))
            for noise_id in sorted(audible - existing.audible_entities):
                noise = world.get_entity(_entity_id_from_string(world, noise_id))
                component = noise.get_component(NoiseComponent)
                events.append(
                    NoiseHeardEvent(
                        **_event_base(
                            epoch,
                            visibility=_Vis.PRIVATE,
                            actor_id=str(character.id),
                            target_ids=(noise_id,),
                            noise_id=noise_id,
                            source_entity_id=component.source_entity_id,
                            text=component.text,
                        )
                    )
                )
        return events


class AttentionConsequence:
    """Focus characters on the strongest current stimulus or heard noise."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        stimuli = [
            stimulus
            for stimulus in world.query().with_all([StimulusComponent]).execute_entities()
            if _stimulus_active(stimulus.get_component(StimulusComponent), epoch)
        ]
        for character in world.query().with_all([CharacterComponent]).execute_entities():
            existing = (
                character.get_component(AttentionComponent)
                if character.has_component(AttentionComponent)
                else AttentionComponent(last_updated_epoch=epoch)
            )
            updated = self._updated_attention(world, character, existing, stimuli, epoch)
            if updated == existing and character.has_component(AttentionComponent):
                continue
            replace_component(character, updated)
            if (
                updated.focus_entity_id != existing.focus_entity_id
                or updated.focus_room_id != existing.focus_room_id
            ):
                events.append(
                    AttentionShiftedEvent(
                        **_event_base(
                            epoch,
                            visibility=_Vis.PRIVATE,
                            actor_id=str(character.id),
                            focus_entity_id=updated.focus_entity_id,
                            focus_room_id=updated.focus_room_id,
                            score=updated.score,
                        )
                    )
                )
        return events

    def _updated_attention(self, world, character, existing, stimuli, epoch):
        candidates: list[tuple[float, str | None, str | None]] = []
        room_id = str(container_of(character)) if container_of(character) is not None else None
        for entity in stimuli:
            stimulus = entity.get_component(StimulusComponent)
            if stimulus.room_id != room_id or stimulus.source_entity_id == str(character.id):
                continue
            candidates.append(
                (
                    stimulus.intensity,
                    stimulus.source_entity_id or str(entity.id),
                    stimulus.room_id,
                )
            )
        if character.has_component(PerceptionComponent):
            perception = character.get_component(PerceptionComponent)
            for noise_id in perception.audible_entities:
                parsed = _entity_id_from_string(world, noise_id)
                noise = world.get_entity(parsed).get_component(NoiseComponent)
                candidates.append(
                    (noise.loudness, noise.source_entity_id or noise_id, noise.room_id)
                )
        if candidates:
            score, focus_entity_id, focus_room_id = max(candidates, key=lambda item: item[0])
            return replace(
                existing,
                score=score,
                focus_entity_id=focus_entity_id,
                focus_room_id=focus_room_id,
                time_since_stimulus=0.0,
                last_updated_epoch=epoch,
            )

        elapsed_hours = max(0, epoch - existing.last_updated_epoch) / 3600.0
        score = max(0.0, existing.score - existing.decay_rate * elapsed_hours)
        return replace(
            existing,
            score=score,
            focus_entity_id=existing.focus_entity_id if score > 0 else None,
            focus_room_id=existing.focus_room_id if score > 0 else None,
            time_since_stimulus=existing.time_since_stimulus + elapsed_hours,
            last_updated_epoch=epoch,
        )


def _perceived_ids(entities) -> list[str]:
    ids: list[str] = []
    for entity in entities:
        ids.append(entity.id)
        ids.extend(_perceived_ids(entity.contents))
    return ids


def _noise_active(noise: NoiseComponent, epoch: int) -> bool:
    return noise.expires_at_epoch is None or noise.expires_at_epoch >= epoch


def _stimulus_active(stimulus: StimulusComponent, epoch: int) -> bool:
    return stimulus.expires_at_epoch is None or stimulus.expires_at_epoch >= epoch


def _can_hear(character, noise: NoiseComponent, hearing: HearingComponent) -> bool:
    if noise.source_entity_id == str(character.id):
        return False
    return noise.room_id == str(container_of(character)) and noise.loudness >= hearing.sensitivity


def _entity_id_from_string(world: World, entity_id: str):
    from .ecs import parse_entity_id

    parsed = parse_entity_id(entity_id)
    if parsed is None or not world.has_entity(parsed):
        raise KeyError(entity_id)
    return parsed


__all__ = [
    "AttentionConsequence",
    "Consequence",
    "EncumbranceConsequence",
    "HearingConsequence",
    "HealthConsequence",
    "InjuryConsequence",
    "PerceptionConsequence",
]
