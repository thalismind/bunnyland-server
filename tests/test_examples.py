"""Each sim package ships a deterministic example world that instantiates and shows off
its hallmark mechanics (plus the life-sim needs every character inherits)."""

from __future__ import annotations

import pytest

from bunnyland.core import WorldActor
from bunnyland.mechanics.barbariansim import WeaponComponent
from bunnyland.mechanics.colonysim import ResourceNodeComponent
from bunnyland.mechanics.daggersim import BankComponent
from bunnyland.mechanics.dragonsim import QuestComponent
from bunnyland.mechanics.gardensim import CropComponent
from bunnyland.mechanics.lifesim import CareerComponent
from bunnyland.mechanics.needs import HungerComponent
from bunnyland.mechanics.voidsim import HabitatModuleComponent, ShipComponent
from bunnyland.plugins.builtin import bunnyland_plugins
from bunnyland.worldgen.examples import (
    BARBARIANSIM_DEMO,
    COLONYSIM_DEMO,
    DAGGERSIM_DEMO,
    DRAGONSIM_DEMO,
    GARDENSIM_DEMO,
    LIFESIM_DEMO,
    VOIDSIM_DEMO,
)
from bunnyland.worldgen.generators import GenOptions, collect_generators

ALL_DEMOS = [
    LIFESIM_DEMO,
    GARDENSIM_DEMO,
    COLONYSIM_DEMO,
    BARBARIANSIM_DEMO,
    DRAGONSIM_DEMO,
    DAGGERSIM_DEMO,
    VOIDSIM_DEMO,
]

# Each demo's hallmark component — proof its package's mechanics are present.
HALLMARKS = {
    LIFESIM_DEMO.name: CareerComponent,
    GARDENSIM_DEMO.name: CropComponent,
    COLONYSIM_DEMO.name: ResourceNodeComponent,
    BARBARIANSIM_DEMO.name: WeaponComponent,
    DRAGONSIM_DEMO.name: QuestComponent,
    DAGGERSIM_DEMO.name: BankComponent,
    VOIDSIM_DEMO.name: ShipComponent,
}


def _has(actor: WorldActor, component_type) -> bool:
    return bool(list(actor.world.query().with_all([component_type]).execute_entities()))


@pytest.mark.parametrize("demo", ALL_DEMOS, ids=lambda d: d.name)
async def test_demo_world_has_rooms_characters_and_needs(demo):
    actor = WorldActor()

    world = await demo.generate(actor, demo.name, GenOptions())

    assert world.rooms, "demo world should have rooms"
    assert world.characters, "demo world should have characters"
    # Every demo builds on life-sim: characters get needs from instantiate.
    assert _has(actor, HungerComponent)


@pytest.mark.parametrize("demo", ALL_DEMOS, ids=lambda d: d.name)
async def test_demo_world_includes_its_hallmark_mechanic(demo):
    actor = WorldActor()

    await demo.generate(actor, demo.name, GenOptions())

    assert _has(actor, HALLMARKS[demo.name])


async def test_voidsim_demo_rooms_are_habitat_modules():
    actor = WorldActor()

    await VOIDSIM_DEMO.generate(actor, "voidsim-demo", GenOptions())

    assert _has(actor, HabitatModuleComponent)


def test_every_sim_demo_is_registered_under_its_plugin():
    registry = collect_generators(bunnyland_plugins())
    for demo in ALL_DEMOS:
        assert registry.get(demo.name) is demo
