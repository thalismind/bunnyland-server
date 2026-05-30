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

from .components import (
    BleedingComponent,
    CharacterComponent,
    DeadComponent,
    DownedComponent,
    EncumbranceComponent,
    HealthComponent,
    InjuryComponent,
    PainComponent,
    SuspendedComponent,
    WeightComponent,
)
from .ecs import replace_component
from .edges import ContainmentMode, Contains, HasInjury
from .events import (
    BleedingChangedEvent,
    CharacterDiedEvent,
    CharacterDownedEvent,
    CharacterRevivedEvent,
    DomainEvent,
    EncumbranceChangedEvent,
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


__all__ = [
    "Consequence",
    "EncumbranceConsequence",
    "HealthConsequence",
    "InjuryConsequence",
]
