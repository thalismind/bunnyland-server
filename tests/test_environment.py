"""Tests for the time-of-day / day-night environment mechanic (spec 11.2, 11.13)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    DeadComponent,
    HealthComponent,
    IdentityComponent,
    Lane,
    LightComponent,
    PortableComponent,
    RoomComponent,
    SuspendedComponent,
    WorldActor,
    build_submitted_command,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.handlers import HandlerContext
from bunnyland.mechanics.environment import (
    CalendarComponent,
    ExtinguishHandler,
    FireComponent,
    FireConsequence,
    FireDamageEvent,
    FireExtinguishedEvent,
    FireSpreadEvent,
    FireStartedEvent,
    FlammableComponent,
    IgniteHandler,
    TimeOfDayChangedEvent,
    TimeOfDayComponent,
    WeatherChangedEvent,
    WeatherComponent,
    environment_fragments,
    install_environment,
    time_of_day,
    weather_for,
)
from bunnyland.prompts import ComponentPromptContext

HOUR = 3600.0
DAY = HOUR * 24


def _world():
    actor = WorldActor()
    install_environment(actor)
    return actor


def _cmd(scenario, command_type, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def test_time_of_day_derivation():
    assert time_of_day(0) == (1, 0, "night", "spring")
    assert time_of_day(int(8 * HOUR)) == (1, 8, "day", "spring")
    assert time_of_day(int(19 * HOUR)) == (1, 19, "dusk", "spring")
    # a day-and-a-bit later, at 02:00 on day 2
    assert time_of_day(int(DAY + 2 * HOUR)) == (2, 2, "night", "spring")
    # seasons advance every 28 days
    assert time_of_day(int(30 * DAY))[3] == "summer"


async def test_phase_change_emits_event_and_updates_singletons():
    actor = _world()
    events: list[TimeOfDayChangedEvent] = []
    actor.bus.subscribe(TimeOfDayChangedEvent, events.append)

    # Start of day -> night, then advance to mid-morning (day).
    await actor.tick(0.0)
    assert events[-1].phase == "night"
    clock = list(
        actor.world.query().with_all([TimeOfDayComponent]).execute_entities()
    )[0]
    assert clock.get_component(TimeOfDayComponent).phase == "night"

    await actor.tick(9 * HOUR)  # now 09:00 -> day
    assert clock.get_component(TimeOfDayComponent).phase == "day"
    assert events[-1].phase == "day"
    assert clock.get_component(CalendarComponent).hour == 9


async def test_phase_event_only_on_change():
    actor = _world()
    events: list[TimeOfDayChangedEvent] = []
    actor.bus.subscribe(TimeOfDayChangedEvent, events.append)

    await actor.tick(8 * HOUR)  # -> day
    await actor.tick(1 * HOUR)  # 09:00, still day: no new event
    assert [e.phase for e in events] == ["day"]


async def test_outdoor_light_follows_the_sky_indoor_does_not():
    actor = _world()
    world = actor.world
    outdoor = spawn_entity(
        world, [RoomComponent(title="Meadow", indoor=False), LightComponent(level=1.0)]
    )
    indoor = spawn_entity(
        world, [RoomComponent(title="Burrow", indoor=True), LightComponent(level=0.3)]
    )
    lamp = spawn_entity(
        world,
        [
            RoomComponent(title="Lamplit Cave", indoor=False),
            LightComponent(level=0.8, natural=False),
        ],
    )

    await actor.tick(0.0)  # midnight -> night
    assert outdoor.get_component(LightComponent).level == 0.05  # dark outside
    assert indoor.get_component(LightComponent).level == 0.3  # unchanged indoors
    assert lamp.get_component(LightComponent).level == 0.8  # artificial light unaffected

    await actor.tick(12 * HOUR)  # noon -> day
    assert outdoor.get_component(LightComponent).level == 1.0


async def test_environment_fragment_describes_the_time():
    actor = _world()
    await actor.tick(19 * HOUR)  # dusk on day 1
    fragments = environment_fragments(actor.world, character=None)
    assert fragments and "dusk" in fragments[0]
    assert "day 1" in fragments[0]


def test_fragment_is_empty_before_first_tick():
    actor = _world()  # consequence has not run yet
    assert environment_fragments(actor.world, character=None) == []


def test_environment_component_fragments_describe_clock_and_fire():
    actor = _world()
    clock = spawn_entity(
        actor.world,
        [
            CalendarComponent(day=3, season="spring"),
            TimeOfDayComponent(phase="dusk"),
            WeatherComponent(condition="rain", intensity=0.7),
        ],
    )
    room = spawn_entity(
        actor.world,
        [RoomComponent(title="Kitchen"), FireComponent(intensity=1.0)],
    )
    character = spawn_entity(actor.world, [CharacterComponent(), FireComponent(intensity=1.0)])

    clock_ctx = ComponentPromptContext.for_entity(actor.world, clock)
    room_ctx = ComponentPromptContext.for_entity(actor.world, room)
    character_ctx = ComponentPromptContext.for_entity(actor.world, character)

    assert clock.get_component(TimeOfDayComponent).prompt_fragments(clock_ctx) == (
        "It is rain dusk (day 3, spring).",
    )
    assert room.get_component(FireComponent).prompt_fragments(room_ctx) == (
        "There is a fire here.",
    )
    assert character.get_component(FireComponent).prompt_fragments(character_ctx) == (
        "You are on fire.",
    )


# -- weather ----------------------------------------------------------------------------


def test_weather_for_is_deterministic_and_day_one_is_clear():
    assert weather_for(1) == ("clear", 0.0)
    assert weather_for(5)[0] == "rain"
    assert weather_for(8) == weather_for(1)  # 7-day cycle


async def test_weather_dims_outdoor_daylight_on_a_rainy_day():
    actor = _world()
    meadow = spawn_entity(
        actor.world, [RoomComponent(title="Meadow", indoor=False), LightComponent(level=1.0)]
    )
    await actor.tick(4 * DAY + 12 * HOUR)  # noon on day 5 (rain)

    clock = list(actor.world.query().with_all([WeatherComponent]).execute_entities())[0]
    assert clock.get_component(WeatherComponent).condition == "rain"
    # noon daylight (1.0) dimmed by rain (0.5).
    assert meadow.get_component(LightComponent).level == 0.5


async def test_weather_change_emits_event_and_sets_singleton():
    actor = _world()
    events: list[WeatherChangedEvent] = []
    actor.bus.subscribe(WeatherChangedEvent, events.append)

    await actor.tick(12 * HOUR)  # day 1 -> clear
    assert events[-1].condition == "clear"
    await actor.tick(2 * DAY)  # day 3 -> cloudy
    assert events[-1].condition == "cloudy"


async def test_fragment_mentions_weather_when_not_clear():
    actor = _world()
    await actor.tick(4 * DAY + 19 * HOUR)  # dusk on day 5 (rain)
    fragment = environment_fragments(actor.world, character=None)[0]
    assert "rain" in fragment and "dusk" in fragment


# -- fire ------------------------------------------------------------------------------


async def test_fire_spreads_from_room_and_damages_character_health():
    scenario = build_scenario()
    install_environment(scenario.actor)
    scenario.actor.register_handler(IgniteHandler())
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(FlammableComponent(fuel=3.0))
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HealthComponent(current=20.0, maximum=20.0))
    blanket = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="dry blanket", kind="item"),
            PortableComponent(can_pick_up=True),
            FlammableComponent(fuel=2.0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), blanket.id)
    started: list[FireStartedEvent] = []
    spread: list[FireSpreadEvent] = []
    damage: list[FireDamageEvent] = []
    scenario.actor.bus.subscribe(FireStartedEvent, started.append)
    scenario.actor.bus.subscribe(FireSpreadEvent, spread.append)
    scenario.actor.bus.subscribe(FireDamageEvent, damage.append)

    await scenario.actor.submit(_cmd(scenario, "ignite", target_id=str(scenario.room_a)))
    await scenario.actor.tick(0.0)
    await scenario.actor.tick(HOUR)

    assert room.has_component(FireComponent)
    assert blanket.has_component(FireComponent)
    assert character.get_component(HealthComponent).current == 12.0
    assert started[0].target_id == str(scenario.room_a)
    assert spread[0].target_id == str(blanket.id)
    assert damage[0].health == 12.0
    assert "fire here" in " ".join(environment_fragments(scenario.actor.world, character))


async def test_extinguish_removes_fire_and_stops_damage():
    scenario = build_scenario()
    install_environment(scenario.actor)
    scenario.actor.register_handler(IgniteHandler())
    scenario.actor.register_handler(ExtinguishHandler())
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(FlammableComponent(fuel=3.0))
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HealthComponent(current=20.0, maximum=20.0))
    extinguished: list[FireExtinguishedEvent] = []
    scenario.actor.bus.subscribe(FireExtinguishedEvent, extinguished.append)

    await scenario.actor.submit(_cmd(scenario, "ignite", target_id=str(scenario.room_a)))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(_cmd(scenario, "extinguish", target_id=str(scenario.room_a)))
    await scenario.actor.tick(0.0)
    await scenario.actor.tick(HOUR)

    assert not room.has_component(FireComponent)
    assert character.get_component(HealthComponent).current == 20.0
    assert extinguished[0].target_id == str(scenario.room_a)


def test_ignite_and_extinguish_handlers_reject_invalid_state_directly():
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    unreachable = spawn_entity(
        scenario.actor.world,
        [RoomComponent(title="Far Field"), FlammableComponent(fuel=1.0)],
    )
    target = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="kindling", kind="item"), FlammableComponent(fuel=1.0)],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), target.id)

    ignite_cases = [
        (
            _cmd(scenario, "ignite", target_id=str(target.id), character_id="ignored"),
            "invalid character id",
            "not-an-id",
        ),
        (
            _cmd(scenario, "ignite", target_id=str(target.id), character_id="ignored"),
            "character does not exist",
            "entity_999999",
        ),
        (_cmd(scenario, "ignite", target_id="entity_999"), "target does not exist", None),
        (
            _cmd(scenario, "ignite", target_id=str(unreachable.id)),
            "target is not reachable",
            None,
        ),
        (
            _cmd(scenario, "ignite", target_id=str(scenario.character)),
            "target is not flammable",
            None,
        ),
        (
            _cmd(scenario, "ignite", target_id=str(target.id), intensity=0),
            "fire intensity must be positive",
            None,
        ),
    ]

    for command, reason, character_id in ignite_cases:
        if character_id is not None:
            command = build_submitted_command(
                character_id=character_id,
                controller_id=str(scenario.controller),
                controller_generation=scenario.generation,
                command_type=command.command_type,
                cost=CommandCost(action=1),
                lane=Lane.WORLD,
                payload=command.payload,
            )
        result = IgniteHandler().execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    result = IgniteHandler().execute(ctx, _cmd(scenario, "ignite", target_id=str(target.id)))
    assert result.ok is True
    assert target.has_component(FireComponent)
    result = IgniteHandler().execute(ctx, _cmd(scenario, "ignite", target_id=str(target.id)))
    assert result.ok is False
    assert result.reason == "target is already burning"

    extinguish_cases = [
        (
            _cmd(scenario, "extinguish", target_id=str(target.id)),
            "invalid character id",
            "not-an-id",
        ),
        (
            _cmd(scenario, "extinguish", target_id=str(target.id)),
            "character does not exist",
            "entity_999999",
        ),
        (_cmd(scenario, "extinguish", target_id="entity_999"), "target does not exist", None),
        (
            _cmd(scenario, "extinguish", target_id=str(unreachable.id)),
            "target is not reachable",
            None,
        ),
        (
            _cmd(scenario, "extinguish", target_id=str(scenario.character)),
            "target is not burning",
            None,
        ),
    ]
    for command, reason, character_id in extinguish_cases:
        if character_id is not None:
            command = build_submitted_command(
                character_id=character_id,
                controller_id=str(scenario.controller),
                controller_generation=scenario.generation,
                command_type=command.command_type,
                cost=CommandCost(action=1),
                lane=Lane.WORLD,
                payload=command.payload,
            )
        result = ExtinguishHandler().execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


def test_ignite_and_extinguish_default_to_current_room():
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(FlammableComponent(fuel=1.0))

    result = IgniteHandler().execute(ctx, _cmd(scenario, "ignite"))
    assert result.ok is True
    assert room.has_component(FireComponent)

    result = ExtinguishHandler().execute(ctx, _cmd(scenario, "extinguish"))
    assert result.ok is True
    assert not room.has_component(FireComponent)


def test_fire_consequence_covers_edge_damage_and_extinguish_paths():
    scenario = build_scenario()
    room = scenario.actor.world.get_entity(scenario.room_a)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HealthComponent(current=20.0, maximum=20.0))
    item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="burning coat", kind="item"),
            CharacterComponent(species="animated coat"),
            HealthComponent(current=10.0, maximum=10.0),
            FireComponent(intensity=0.0, fuel=0.05, last_updated_epoch=0),
        ],
    )
    dead = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ash", kind="character"),
            CharacterComponent(species="bunny"),
            HealthComponent(current=4.0, maximum=4.0),
            DeadComponent(died_at_epoch=0, cause="fire"),
        ],
    )
    suspended = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="paused", kind="character"),
            CharacterComponent(species="bunny"),
            HealthComponent(current=5.0, maximum=5.0),
            SuspendedComponent(reason="offline"),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), dead.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), suspended.id)
    room.add_component(FireComponent(intensity=1.0, fuel=0.05, last_updated_epoch=0))
    scenario.actor.world._relationships.setdefault(room.id, {}).setdefault(Contains, {})[
        parse_entity_id("entity_999")
    ] = Contains(mode=ContainmentMode.ROOM_CONTENT)

    assert FireConsequence().process(scenario.actor.world, 0) == []

    events = FireConsequence().process(scenario.actor.world, HOUR)

    assert not room.has_component(FireComponent)
    assert not item.has_component(FireComponent)
    assert character.get_component(HealthComponent).current == 12.0
    assert item.get_component(HealthComponent).current == 2.0
    assert dead.get_component(HealthComponent).current == 4.0
    assert suspended.get_component(HealthComponent).current == 5.0
    assert sum(isinstance(event, FireExtinguishedEvent) for event in events) == 2
    assert any(
        isinstance(event, FireDamageEvent) and event.target_id == str(item.id)
        for event in events
    )
