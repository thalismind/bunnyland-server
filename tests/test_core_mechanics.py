"""End-to-end checks for core simulation mechanics."""

from __future__ import annotations

import pytest
from conftest import build_scenario

from bunnyland.core import (
    ContainmentMode,
    Contains,
    EncumbranceComponent,
    IdentityComponent,
    WeightComponent,
    spawn_entity,
)
from bunnyland.core.events import EncumbranceChangedEvent

HOUR = 3600.0


def collect(actor, event_type):
    seen = []
    actor.bus.subscribe(event_type, seen.append)
    return seen


async def test_carried_weight_updates_load_and_reduces_speed_when_over_capacity():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(EncumbranceComponent(capacity=5.0))
    boulder = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="basalt boulder", kind="item"),
            WeightComponent(weight=10.0),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), boulder.id)
    changes = collect(scenario.actor, EncumbranceChangedEvent)

    await scenario.actor.tick(HOUR)

    encumbrance = character.get_component(EncumbranceComponent)
    assert encumbrance.current_load == pytest.approx(10.0)
    assert encumbrance.overburdened is True
    assert encumbrance.speed_multiplier == pytest.approx(0.5)
    assert changes[-1].actor_id == str(scenario.character)
    assert changes[-1].speed_multiplier == pytest.approx(0.5)


async def test_dropping_heavy_item_restores_encumbrance_speed():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(EncumbranceComponent(capacity=5.0))
    boulder = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="basalt boulder", kind="item"),
            WeightComponent(weight=10.0),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), boulder.id)

    await scenario.actor.tick(HOUR)
    character.remove_relationship(Contains, boulder.id)
    await scenario.actor.tick(HOUR)

    encumbrance = character.get_component(EncumbranceComponent)
    assert encumbrance.current_load == pytest.approx(0.0)
    assert encumbrance.overburdened is False
    assert encumbrance.speed_multiplier == pytest.approx(1.0)
