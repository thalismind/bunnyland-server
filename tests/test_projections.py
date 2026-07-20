"""Tests for room-summary, perception, and recent-context projections."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainerComponent,
    ContainmentMode,
    Contains,
    DoorComponent,
    ExitTo,
    IdentityComponent,
    Lane,
    LightComponent,
    LockableComponent,
    PerceptionComponent,
    RoomComponent,
    RoomSummaryComponent,
    SayHandler,
    SleepingComponent,
    StealthComponent,
    TemperatureComponent,
    build_submitted_command,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.ecs import replace_component
from bunnyland.core.events import (
    CharacterDiedEvent,
    CharacterDownedEvent,
    ItemDroppedEvent,
    ItemTakenEvent,
)
from bunnyland.projections import (
    RecentContextProjection,
    RoomSummaryProjection,
    build_room_facts,
    perceive,
)

HOUR = 3600.0


def event_base(**overrides):
    base = {
        "event_id": "event",
        "world_epoch": 0,
        "created_at": datetime.now(UTC),
        "actor_id": None,
        "room_id": None,
    }
    base.update(overrides)
    return base


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
    assert "entity_" not in facts.title
    assert any(name == "Juniper" for _id, name in facts.occupants)
    assert any(o.name == "oak chest" and "closed" in o.states for o in facts.objects)
    assert [e.direction for e in facts.exits] == ["north"]
    assert facts.bands == {"light": "dim", "temperature": "warm"}


def test_room_fact_bands_and_object_states_cover_thresholds():
    scenario = build_scenario()
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    room.add_component(LightComponent(level=0.9))
    room.add_component(TemperatureComponent(celsius=2))
    add_object(
        scenario,
        scenario.room_a,
        [
            IdentityComponent(name="locked door", kind="door"),
            DoorComponent(open=False),
            LockableComponent(locked=True),
        ],
    )

    facts = build_room_facts(world, scenario.room_a)

    assert facts.bands == {"light": "bright", "temperature": "cold"}
    assert any(
        obj.name == "locked door" and obj.states == ("closed", "locked") for obj in facts.objects
    )

    for light, expected in [(0.05, "dark"), (0.2, "dim"), (0.7, "lit")]:
        replace_component(room, replace(room.get_component(LightComponent), level=light))
        assert build_room_facts(world, scenario.room_a).bands["light"] == expected

    for temp, expected in [(10, "cool"), (20, "mild"), (35, "hot")]:
        replace_component(room, replace(room.get_component(TemperatureComponent), celsius=temp))
        assert build_room_facts(world, scenario.room_a).bands["temperature"] == expected


def test_render_summary_is_deterministic_template():
    scenario = build_scenario()
    facts = build_room_facts(scenario.actor.world, scenario.room_a)
    from bunnyland.projections import render_summary

    text = render_summary(facts)
    assert text.startswith("Mosslit Burrow")
    assert "Exits: north." in text


def test_render_summary_names_destinations_for_codirectional_exits():
    scenario = build_scenario()
    world = scenario.actor.world
    market = spawn_entity(world, [RoomComponent(title="Clover Market")])
    world.get_entity(scenario.room_a).add_relationship(
        ExitTo(direction="north"), market.id
    )

    facts = build_room_facts(world, scenario.room_a)
    from bunnyland.projections import render_summary

    assert render_summary(facts).endswith(
        "Exits: north to Clover Market, north to North Tunnel."
    )


def test_room_summary_projection_accepts_custom_renderer():
    scenario = build_scenario()

    projection = RoomSummaryProjection(
        scenario.actor.world,
        renderer=lambda facts: f"{facts.title}: prose from renderer",
    ).attach()
    summary = projection.summary(scenario.room_a, scenario.actor.epoch)

    assert summary.visible_summary == "Mosslit Burrow: prose from renderer"


def test_room_summary_projection_dirty_edge_cases():
    scenario = build_scenario()
    projection = RoomSummaryProjection(scenario.actor.world).attach()
    projection.summary(scenario.room_a, scenario.actor.epoch)

    assert projection.attach(scenario.actor.world) is projection
    projection.mark_dirty(parse_entity_id("entity_999"))

    item = spawn_entity(scenario.actor.world, [IdentityComponent(name="loose", kind="item")])
    projection.mark_dirty(item.id)
    projection._dirty(item)

    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        item.id,
    )
    projection._dirty(item)
    assert (
        scenario.actor.world.get_entity(scenario.room_a).get_component(RoomSummaryComponent).dirty
        is True
    )

    # An item whose container parent is NOT a room: _dirty walks to the parent, finds
    # it has no RoomComponent, and falls through without marking anything (260->exit).
    chest = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="chest", kind="container"), ContainerComponent(open=True)],
    )
    trinket = spawn_entity(scenario.actor.world, [IdentityComponent(name="trinket", kind="item")])
    chest.add_relationship(Contains(mode=ContainmentMode.CONTAINER), trinket.id)
    projection._dirty(trinket)
    assert not chest.has_component(RoomSummaryComponent)


# -- projection dirty/rebuild -----------------------------------------------------------


async def test_move_marks_rooms_dirty_and_rebuild_reflects_new_occupant():
    scenario = build_scenario()
    projection = RoomSummaryProjection(scenario.actor.world).attach()

    # Build once so room_a has a clean cached summary mentioning Juniper.
    summary_a = projection.summary(scenario.room_a, scenario.actor.epoch)
    assert summary_a.dirty is False
    assert "Juniper" in summary_a.visible_summary

    await scenario.actor.submit(move_cmd(scenario))
    await scenario.actor.tick(HOUR)  # executes the move; its edge changes are queued
    await scenario.actor.tick(HOUR)  # next tick drains the observer queue -> dirties rooms

    # Move dirtied both rooms (via Contains observers).
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
    projection = RoomSummaryProjection(scenario.actor.world).attach()

    first = projection.summary(scenario.room_a, scenario.actor.epoch)
    second = projection.summary(scenario.room_a, scenario.actor.epoch)
    assert first.version == second.version  # not rebuilt while clean


async def test_observer_dirties_room_when_its_light_changes():
    scenario = build_scenario()
    world = scenario.actor.world
    world.get_entity(scenario.room_a).add_component(LightComponent(level=1.0))
    projection = RoomSummaryProjection(world).attach()

    bright = projection.summary(scenario.room_a, scenario.actor.epoch)
    assert "bright" in bright.visible_summary

    # Darken the room; the change is queued and applies on the next tick (spec 5.x).
    room = world.get_entity(scenario.room_a)
    replace_component(room, replace(room.get_component(LightComponent), level=0.05))
    assert room.get_component(RoomSummaryComponent).dirty is False  # not yet observed

    await scenario.actor.tick(0.0)  # drains the observer queue
    assert room.get_component(RoomSummaryComponent).dirty is True
    assert "dark" in projection.summary(scenario.room_a, scenario.actor.epoch).visible_summary


async def test_observer_dirties_room_when_contents_change():
    scenario = build_scenario()
    world = scenario.actor.world
    projection = RoomSummaryProjection(world).attach()
    projection.summary(scenario.room_a, scenario.actor.epoch)  # clean cache

    add_object(scenario, scenario.room_a, [IdentityComponent(name="a brass key", kind="item")])
    await scenario.actor.tick(0.0)  # Contains-added observer dirties the room

    assert world.get_entity(scenario.room_a).get_component(RoomSummaryComponent).dirty is True
    summary = projection.summary(scenario.room_a, scenario.actor.epoch)
    assert "a brass key" in summary.visible_summary


async def test_observer_dirties_room_when_an_exit_is_added():
    scenario = build_scenario()
    world = scenario.actor.world
    projection = RoomSummaryProjection(world).attach()
    projection.summary(scenario.room_b, scenario.actor.epoch)  # room_b clean

    from bunnyland.core import ExitTo

    world.get_entity(scenario.room_b).add_relationship(ExitTo(direction="up"), scenario.room_a)
    await scenario.actor.tick(0.0)

    summary = projection.summary(scenario.room_b, scenario.actor.epoch)
    assert "up" in summary.visible_summary


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


def test_perceive_skips_invisible_contains_edges():
    scenario = build_scenario()
    world = scenario.actor.world
    hidden = spawn_entity(world, [IdentityComponent(name="ghost crate", kind="item")])
    # An explicitly invisible Contains edge must be skipped (perception line 75).
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT, visible=False), hidden.id
    )

    perception = perceive(world, world.get_entity(scenario.character))

    assert "ghost crate" not in {e.name for e in perception.entities}


def test_build_room_facts_names_identityless_object_something():
    scenario = build_scenario()
    world = scenario.actor.world
    # Object with no IdentityComponent -> _name falls back to "something" (line 119).
    add_object(scenario, scenario.room_a, [ContainerComponent(open=True)])

    facts = build_room_facts(world, scenario.room_a)

    assert any(obj.name == "something" for obj in facts.objects)


def test_perceive_hides_hidden_exits():
    scenario = build_scenario()
    world = scenario.actor.world
    secret_room = spawn_entity(world, [RoomComponent(title="Hidden Annex")])
    world.get_entity(scenario.room_a).add_relationship(
        ExitTo(direction="secret", hidden=True), secret_room.id
    )

    perception = perceive(world, world.get_entity(scenario.character))

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


def test_inactive_perception_component_perceives_nothing():
    scenario = build_scenario()
    world = scenario.actor.world
    char = world.get_entity(scenario.character)
    char.add_component(PerceptionComponent(active=False))

    perception = perceive(world, char)

    assert perception.can_perceive is False


def test_hidden_entity_is_not_visible_in_perception():
    scenario = build_scenario()
    world = scenario.actor.world
    add_object(
        scenario,
        scenario.room_a,
        [
            IdentityComponent(name="hidden cache", kind="item"),
            StealthComponent(visibility_level=0.05, hidden_threshold=0.1, hiding=True),
        ],
    )

    perception = perceive(world, world.get_entity(scenario.character))

    assert "hidden cache" not in {entity.name for entity in perception.entities}


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


def test_recent_context_records_inventory_and_lifecycle_fallbacks():
    scenario = build_scenario()
    recent = RecentContextProjection(scenario.actor.world, capacity=2)
    item = add_object(
        scenario,
        scenario.room_a,
        [IdentityComponent(name="silver spoon", kind="item")],
    )

    recent._on_event(
        ItemTakenEvent(
            **event_base(
                event_id="taken",
                actor_id=str(scenario.character),
                room_id=str(scenario.room_a),
            ),
            item_id=str(item.id),
            from_container_id=str(scenario.room_a),
        )
    )
    recent._on_event(
        ItemDroppedEvent(
            **event_base(
                event_id="dropped",
                actor_id=None,
                room_id=str(scenario.room_a),
            ),
            item_id="missing",
            room_id_dropped=str(scenario.room_a),
        )
    )
    assert recent.recent(scenario.room_a) == (
        "Juniper picked up silver spoon.",
        "someone dropped someone.",
    )

    recent._on_event(
        CharacterDownedEvent(
            **event_base(event_id="downed", actor_id=str(scenario.character)),
            cause="test",
        )
    )
    recent._on_event(
        CharacterDiedEvent(
            **event_base(
                event_id="died",
                actor_id="missing",
                room_id=str(scenario.room_a),
            ),
            cause="test",
        )
    )

    assert recent.recent("missing") == ()
    assert recent.recent(scenario.room_a) == ("Juniper collapsed.", "someone died.")


def test_recent_context_handles_unnamed_actors_and_roomless_lifecycle_events():
    scenario = build_scenario()
    world = scenario.actor.world
    recent = RecentContextProjection(world)

    # An entity that exists but has no IdentityComponent falls back to "someone" (65->67).
    nameless = spawn_entity(world, [CharacterComponent()])

    # A died event with no room and an actor that cannot be located resolves to no room,
    # so _append is called with None and stores nothing (76, 98->exit).
    recent._on_event(
        CharacterDiedEvent(
            **event_base(event_id="lost", actor_id=str(nameless.id), room_id=None),
            cause="test",
        )
    )
    # A downed event with a well-formed but non-existent actor id makes _room_of_actor
    # return None (76), so _append is skipped (70->exit).
    recent._on_event(
        CharacterDownedEvent(
            **event_base(event_id="lost-downed", actor_id="entity_999", room_id=None),
            cause="test",
        )
    )

    # An event type the projection does not special-case falls off the dispatch chain
    # without appending anything (98->exit).
    from bunnyland.core.events import SpeechToldEvent

    recent._on_event(
        SpeechToldEvent(
            event_id="aside",
            world_epoch=0,
            created_at=datetime.now(UTC),
            actor_id=str(scenario.character),
            room_id=str(scenario.room_a),
            target_ids=(str(nameless.id),),
            text="ignored",
        )
    )

    assert recent.recent(str(scenario.room_a)) == ()
    assert recent.recent(str(scenario.room_b)) == ()


def test_recent_context_records_eating_and_drinking():
    from bunnyland.foundation.needs.mechanics import DrinkConsumedEvent, FoodEatenEvent

    scenario = build_scenario()
    recent = RecentContextProjection(scenario.actor.world)
    bun = add_object(
        scenario, scenario.room_a, [IdentityComponent(name="steamed bun", kind="food")]
    )
    basin = add_object(
        scenario, scenario.room_a, [IdentityComponent(name="water basin", kind="fixture")]
    )

    recent._on_event(
        FoodEatenEvent(
            **event_base(
                event_id="ate",
                actor_id=str(scenario.character),
                room_id=str(scenario.room_a),
            ),
            item_id=str(bun.id),
            satiety=5.0,
        )
    )
    recent._on_event(
        DrinkConsumedEvent(
            **event_base(
                event_id="drank",
                actor_id=str(scenario.character),
                room_id=str(scenario.room_a),
            ),
            source_id=str(basin.id),
            hydration=3.0,
        )
    )

    assert recent.recent(scenario.room_a) == (
        "Juniper ate steamed bun.",
        "Juniper drank from water basin.",
    )
