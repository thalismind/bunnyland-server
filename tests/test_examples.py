"""Each sim package ships a deterministic example world that instantiates and shows off
its hallmark mechanics (plus the life-sim needs every character inherits)."""

from __future__ import annotations

import re

import pytest

from bunnyland.core import WorldActor
from bunnyland.core.components import (
    DescriptionComponent,
    IdentityComponent,
    ReadableComponent,
    RoomComponent,
)
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
    POP_CULTURE_DEMOS,
    VOIDSIM_DEMO,
)
from bunnyland.worldgen.generators import GenOptions, collect_generators

PACKAGE_DEMOS = [
    LIFESIM_DEMO,
    GARDENSIM_DEMO,
    COLONYSIM_DEMO,
    BARBARIANSIM_DEMO,
    DRAGONSIM_DEMO,
    DAGGERSIM_DEMO,
    VOIDSIM_DEMO,
]
ALL_DEMOS = [*PACKAGE_DEMOS, *POP_CULTURE_DEMOS]

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


def _visible_text(actor: WorldActor) -> str:
    texts: list[str] = []
    for entity in actor.world.query().execute_entities():
        if entity.has_component(IdentityComponent):
            identity = entity.get_component(IdentityComponent)
            texts.extend([identity.name, identity.kind, *identity.tags])
        if entity.has_component(RoomComponent):
            room = entity.get_component(RoomComponent)
            texts.extend([room.title, room.biome])
        if entity.has_component(DescriptionComponent):
            description = entity.get_component(DescriptionComponent)
            texts.extend([description.short, description.long, description.appearance])
        if entity.has_component(ReadableComponent):
            readable = entity.get_component(ReadableComponent)
            texts.extend([readable.title or "", readable.text])
    return "\n".join(text for text in texts if text)


@pytest.mark.parametrize("demo", ALL_DEMOS, ids=lambda d: d.name)
async def test_demo_world_has_rooms_characters_and_needs(demo):
    actor = WorldActor()

    world = await demo.generate(actor, demo.name, GenOptions())

    assert world.rooms, "demo world should have rooms"
    assert world.characters, "demo world should have characters"
    # Every demo builds on life-sim: characters get needs from instantiate.
    assert _has(actor, HungerComponent)


@pytest.mark.parametrize("demo", PACKAGE_DEMOS, ids=lambda d: d.name)
async def test_demo_world_includes_its_hallmark_mechanic(demo):
    actor = WorldActor()

    await demo.generate(actor, demo.name, GenOptions())

    assert _has(actor, HALLMARKS[demo.name])


async def test_voidsim_demo_rooms_are_habitat_modules():
    actor = WorldActor()

    await VOIDSIM_DEMO.generate(actor, "voidsim-demo", GenOptions())

    assert _has(actor, HabitatModuleComponent)


@pytest.mark.parametrize("demo", POP_CULTURE_DEMOS, ids=lambda d: d.name)
async def test_pop_culture_demo_worlds_stay_legally_distinct(demo):
    actor = WorldActor()

    await demo.generate(actor, demo.name, GenOptions())

    protected_terms = (
        "always sunny",
        "chewbacca",
        "charlie",
        "dee",
        "dennis",
        "dracula",
        "frank",
        "han",
        "harker",
        "jedi",
        "leia",
        "luke",
        "mac",
        "mystery machine",
        "paddy",
        "philadelphia",
        "rogers",
        "scooby",
        "shaggy",
        "sith",
        "star wars",
        "vader",
        "van helsing",
    )
    corpus = _visible_text(actor).lower()
    for term in protected_terms:
        assert not re.search(rf"\b{re.escape(term)}\b", corpus), term


def test_every_demo_is_registered_under_its_plugin():
    registry = collect_generators(bunnyland_plugins())
    for demo in ALL_DEMOS:
        assert registry.get(demo.name) is demo
