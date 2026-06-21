"""The hand-built apartment-building showcase world (apartment-demo)."""

from __future__ import annotations

from bunnyland.core import WorldActor
from bunnyland.core.components import (
    CharacterComponent,
    ReadableComponent,
    RegionComponent,
    RoomComponent,
)
from bunnyland.core.edges import ContainmentMode, Contains, ExitTo
from bunnyland.mechanics.lifesim import (
    CareerComponent,
    HomeComponent,
    RoutineComponent,
)
from bunnyland.mechanics.needs import HungerComponent
from bunnyland.plugins.builtin import bunnyland_plugins
from bunnyland.worldgen.apartment import APARTMENT_DEMO
from bunnyland.worldgen.generators import GenOptions, collect_generators


def _entities(actor, component_type):
    return list(actor.world.query().with_all([component_type]).execute_entities())


async def _build() -> WorldActor:
    actor = WorldActor()
    await APARTMENT_DEMO.generate(actor, "apartment-demo", GenOptions())
    return actor


async def test_has_eight_to_twelve_tenants_plus_one_animal():
    actor = await _build()

    characters = _entities(actor, CharacterComponent)
    bunnies = [c for c in characters if c.get_component(CharacterComponent).species == "bunny"]
    animals = [c for c in characters if c.get_component(CharacterComponent).species != "bunny"]

    assert 8 <= len(bunnies) <= 12
    assert len(animals) == 1
    assert animals[0].get_component(CharacterComponent).species == "rat"


async def test_tenants_have_needs_careers_homes_and_routines():
    actor = await _build()

    assert _entities(actor, HungerComponent)  # life-sim needs from instantiate
    assert _entities(actor, CareerComponent)
    # One apartment owned per resident tenant (the animal has no home).
    assert len(_entities(actor, HomeComponent)) == 9
    # Each tenant carries a multi-entry daily schedule as routine entities.
    assert len(_entities(actor, RoutineComponent)) >= 9 * 3


async def test_has_a_hidden_passage_and_findable_secrets():
    actor = await _build()

    hidden_exits = [
        edge
        for room in _entities(actor, RoomComponent)
        for edge, _target in room.get_relationships(ExitTo)
        if edge.hidden
    ]
    assert hidden_exits, "the warren should be reachable only by a hidden passage"

    notes_with_text = [
        e for e in _entities(actor, ReadableComponent)
        if e.get_component(ReadableComponent).text.strip()
    ]
    assert len(notes_with_text) >= 5


async def test_building_sits_under_a_neighborhood_region():
    actor = await _build()

    regions = {
        r.get_component(RegionComponent).name: r for r in _entities(actor, RegionComponent)
    }
    assert {"The Mulberry Walk-up", "Greenwich Warren"} <= set(regions)

    building = regions["The Mulberry Walk-up"]
    rooms_under_building = {
        child_id
        for edge, child_id in building.get_relationships(Contains)
        if edge.mode == ContainmentMode.REGION
        and actor.world.get_entity(child_id).has_component(RoomComponent)
    }
    assert rooms_under_building == {room.id for room in _entities(actor, RoomComponent)}

    # The neighborhood nests the building one level up.
    neighborhood = regions["Greenwich Warren"]
    assert any(
        edge.mode == ContainmentMode.REGION and child_id == building.id
        for edge, child_id in neighborhood.get_relationships(Contains)
    )


def test_apartment_demo_is_registered():
    registry = collect_generators(bunnyland_plugins())
    assert registry.get("apartment-demo") is APARTMENT_DEMO


async def test_residents_without_known_for_get_no_reputation(monkeypatch):
    # ``known_for`` is optional in a tenant dossier; a resident lacking it should
    # simply be left without a ReputationComponent (the false side of the guard).
    from bunnyland.mechanics.lifesim import ReputationComponent
    from bunnyland.worldgen import apartment

    stripped = tuple(
        {k: v for k, v in r.items() if k != "known_for"} for r in apartment._RESIDENTS
    )
    monkeypatch.setattr(apartment, "_RESIDENTS", stripped)

    actor = await _build()

    assert not _entities(actor, ReputationComponent)


async def test_backstory_without_emoji_skips_editor_display():
    from bunnyland.core.components import DescriptionComponent, EditorDisplayComponent
    from bunnyland.core.ecs import spawn_entity
    from bunnyland.worldgen.apartment import _backstory

    actor = WorldActor()
    entity = spawn_entity(actor.world, [DescriptionComponent(short="x", long="y")])

    _backstory(actor, entity.id, short="a courtly rat", long="once a janitor")

    refreshed = actor.world.get_entity(entity.id)
    # The description is replaced...
    assert refreshed.get_component(DescriptionComponent).short == "a courtly rat"
    # ...but with no emoji given, no editor icon is attached.
    assert not refreshed.has_component(EditorDisplayComponent)
