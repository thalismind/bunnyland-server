"""Tests for room-summary, perception, and recent-context projections."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainerComponent,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    LightComponent,
    RoomSummaryComponent,
    SayHandler,
    SleepingComponent,
    TemperatureComponent,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.projections import (
    RecentContextProjection,
    RoomSummaryProjection,
    build_room_facts,
    perceive,
)

HOUR = 3600.0


def move_cmd(scenario):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "north"},
    )


def add_object(scenario, room_id, components):
    obj = spawn_entity(scenario.actor.world, components)
    scenario.actor.world.get_entity(room_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), obj.id
    )
    return obj


# -- room facts -------------------------------------------------------------------------


def test_build_room_facts_reflects_occupants_objects_exits_and_bands():
    scenario = build_scenario()
    world = scenario.actor.world
    scenario.actor.world.get_entity(scenario.room_a).add_component(LightComponent(level=0.3))
    scenario.actor.world.get_entity(scenario.room_a).add_component(TemperatureComponent(celsius=28))
    add_object(
        scenario,
        scenario.room_a,
        [IdentityComponent(name="oak chest", kind="container"), ContainerComponent(open=False)],
    )

    facts = build_room_facts(world, scenario.room_a)

    assert facts.title == "Mosslit Burrow"
    assert ("entity_" not in facts.title)
    assert any(name == "Juniper" for _id, name in facts.occupants)
    assert any(o.name == "oak chest" and "closed" in o.states for o in facts.objects)
    assert [e.direction for e in facts.exits] == ["north"]
    assert facts.bands == {"light": "dim", "temperature": "warm"}


def test_render_summary_is_deterministic_template():
    scenario = build_scenario()
    facts = build_room_facts(scenario.actor.world, scenario.room_a)
    from bunnyland.projections import render_summary

    text = render_summary(facts)
    assert text.startswith("Mosslit Burrow")
    assert "Exits: north." in text


# -- projection dirty/rebuild -----------------------------------------------------------


async def test_move_marks_rooms_dirty_and_rebuild_reflects_new_occupant():
    scenario = build_scenario()
    projection = RoomSummaryProjection(scenario.actor.world)
    projection.subscribe(scenario.actor.bus)

    # Build once so room_a has a clean cached summary mentioning Juniper.
    summary_a = projection.summary(scenario.room_a, scenario.actor.epoch)
    assert summary_a.dirty is False
    assert "Juniper" in summary_a.visible_summary

    await scenario.actor.submit(move_cmd(scenario))
    await scenario.actor.tick(HOUR)

    # Move dirtied both rooms.
    room_a = scenario.actor.world.get_entity(scenario.room_a)
    assert room_a.get_component(RoomSummaryComponent).dirty is True

    # Rebuilding room_b now shows Juniper; room_a no longer does.
    rebuilt_b = projection.summary(scenario.room_b, scenario.actor.epoch)
    rebuilt_a = projection.summary(scenario.room_a, scenario.actor.epoch)
    assert "Juniper" in rebuilt_b.visible_summary
    assert "Juniper" not in rebuilt_a.visible_summary
    assert rebuilt_a.version >= 2  # rebuilt at least twice (initial + after move)


async def test_summary_rebuilds_lazily_only_when_dirty():
    scenario = build_scenario()
    projection = RoomSummaryProjection(scenario.actor.world)
    projection.subscribe(scenario.actor.bus)

    first = projection.summary(scenario.room_a, scenario.actor.epoch)
    second = projection.summary(scenario.room_a, scenario.actor.epoch)
    assert first.version == second.version  # not rebuilt while clean


# -- perception -------------------------------------------------------------------------


def test_perceive_lists_room_entities_and_exits_excluding_self():
    scenario = build_scenario()
    world = scenario.actor.world
    add_object(scenario, scenario.room_a, [IdentityComponent(name="a pebble", kind="item")])

    perception = perceive(world, world.get_entity(scenario.character))

    assert perception.can_perceive is True
    names = {e.name for e in perception.entities}
    assert "a pebble" in names
    assert "Juniper" not in names  # self excluded
    assert [e.direction for e in perception.exits] == ["north"]


def test_closed_opaque_container_hides_contents():
    scenario = build_scenario()
    world = scenario.actor.world
    chest = add_object(
        scenario,
        scenario.room_a,
        [IdentityComponent(name="oak chest", kind="container"), ContainerComponent(open=False)],
    )
    ruby = spawn_entity(world, [IdentityComponent(name="ruby", kind="item")])
    chest.add_relationship(Contains(mode=ContainmentMode.CONTAINER), ruby.id)

    perception = perceive(world, world.get_entity(scenario.character))
    chest_view = next(e for e in perception.entities if e.name == "oak chest")
    assert chest_view.contents == ()  # closed + opaque -> hidden


def test_open_container_reveals_contents():
    scenario = build_scenario()
    world = scenario.actor.world
    chest = add_object(
        scenario,
        scenario.room_a,
        [IdentityComponent(name="open crate", kind="container"), ContainerComponent(open=True)],
    )
    ruby = spawn_entity(world, [IdentityComponent(name="ruby", kind="item")])
    chest.add_relationship(Contains(mode=ContainmentMode.CONTAINER), ruby.id)

    perception = perceive(world, world.get_entity(scenario.character))
    crate_view = next(e for e in perception.entities if e.name == "open crate")
    assert any(c.name == "ruby" for c in crate_view.contents)


def test_sleeping_character_perceives_nothing():
    scenario = build_scenario()
    world = scenario.actor.world
    char = world.get_entity(scenario.character)
    char.add_component(SleepingComponent(started_at_epoch=0))

    perception = perceive(world, char)
    assert perception.can_perceive is False
    assert perception.entities == ()


# -- recent context ---------------------------------------------------------------------


async def test_recent_context_records_speech_and_movement():
    scenario = build_scenario()
    scenario.actor.register_handler(SayHandler())
    # Another character to hear/observe.
    listener = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), listener.id
    )
    recent = RecentContextProjection(scenario.actor.world)
    recent.subscribe(scenario.actor.bus)

    say = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="say",
        cost=CommandCost(action=1, focus=1),
        lane=Lane.WORLD,
        payload={"text": "Hello there."},
    )
    await scenario.actor.submit(say)
    await scenario.actor.tick(HOUR)

    log = recent.recent(scenario.room_a)
    assert any('Juniper said: "Hello there."' == entry for entry in log)
