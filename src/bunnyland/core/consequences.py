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
    CharacterComponent,
    DeadComponent,
    DownedComponent,
    HealthComponent,
    SuspendedComponent,
)
from .ecs import replace_component
from .events import (
    CharacterDiedEvent,
    CharacterDownedEvent,
    CharacterRevivedEvent,
    DomainEvent,
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


__all__ = ["Consequence", "HealthConsequence"]
