"""Behavior coverage for public event-focused media scene projection."""

from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import build_scenario
from relics import Entity, World

from bunnyland.core import (
    CharacterComponent,
    ContainmentMode,
    Contains,
    EventVisibility,
    Holding,
    IdentityComponent,
    Wearing,
    event_base,
    spawn_entity,
)
from bunnyland.core.components import (
    DeadComponent,
    DescriptionComponent,
    DoorComponent,
    DownedComponent,
    GenerationIntentComponent,
    LightComponent,
    LockableComponent,
    RestingComponent,
    RoomComponent,
    SleepingComponent,
    StealthComponent,
    SuspendedComponent,
    TemperatureComponent,
)
from bunnyland.core.ecs import replace_component
from bunnyland.core.events import ActorMovedEvent, CharacterAttackedEvent, DomainEvent
from bunnyland.foundation.environment.mechanics import TimeOfDayComponent, WeatherComponent
from bunnyland.imagegen.events import ImageGenerationCompletedEvent
from bunnyland.imagegen.scene_models import MediaFact, MediaFactRequest
from bunnyland.imagegen.scene_projection import MediaSceneProjection
from bunnyland.simpacks.toonsim.mechanics import (
    SpriteLayerComponent,
    SpritePositionComponent,
)


class _Facts:
    def facts_for(
        self,
        world: World,
        entity: Entity,
        request: MediaFactRequest,
    ) -> tuple[MediaFact, ...]:
        del world
        return (
            MediaFact(
                id=f"{request.role}:{entity.id}",
                category="visual",
                text=f"visual fact for {request.role}",
                entity_id=str(entity.id),
            ),
        )


class _BrokenFacts:
    def facts_for(
        self,
        world: World,
        entity: Entity,
        request: MediaFactRequest,
    ) -> tuple[MediaFact, ...]:
        del world, entity, request
        raise RuntimeError("broken media facts")


async def test_projection_captures_rich_public_scene_and_event_roles():
    scenario = build_scenario()
    actor = scenario.actor
    world = actor.world
    room = world.get_entity(scenario.room_a)
    character = world.get_entity(scenario.character)
    replace_component(
        room,
        replace(
            room.get_component(RoomComponent),
            indoor=True,
            biome="castle dungeon",
        ),
    )
    room.add_component(
        DescriptionComponent(
            short="stone gaol",
            long="wet stone walls and iron cells",
            appearance="gothic arches",
        )
    )
    room.add_component(LightComponent(level=0.2))
    room.add_component(TemperatureComponent(celsius=8))
    character.add_component(
        DescriptionComponent(short="rabbit guard", appearance="grey fur, red scarf")
    )
    character.add_component(
        GenerationIntentComponent(description="scar over one eye", tags=("scar",))
    )
    character.add_component(SpritePositionComponent(x=2, y=3))
    for component in (
        DeadComponent(died_at_epoch=1, cause="test"),
        DownedComponent(downed_at_epoch=1, cause="test"),
        SleepingComponent(),
        RestingComponent(),
        SuspendedComponent(),
    ):
        character.add_component(component)

    sword = spawn_entity(world, [IdentityComponent(name="Sword", kind="weapon")])
    cloak = spawn_entity(world, [IdentityComponent(name="Cloak", kind="clothing")])
    character.add_relationship(Holding(), sword.id)
    character.add_relationship(Wearing(), cloak.id)
    gate = spawn_entity(
        world,
        [
            IdentityComponent(name="Iron Gate", kind="door"),
            DoorComponent(open=False),
            LockableComponent(locked=True),
            SpritePositionComponent(x=5, y=1),
            SpriteLayerComponent(layer=9),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), gate.id)
    hidden = spawn_entity(
        world,
        [
            IdentityComponent(name="Hidden Rat", kind="character"),
            CharacterComponent(species="rat"),
            StealthComponent(hiding=True, visibility_level=0, hidden_threshold=0.1),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), hidden.id)
    background = spawn_entity(
        world,
        [
            IdentityComponent(name="Witness", kind="character"),
            CharacterComponent(),
            StealthComponent(hiding=False),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), background.id)
    invisible = spawn_entity(world, [IdentityComponent(name="Secret", kind="prop")])
    room.add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT, visible=False), invisible.id
    )
    nameless = spawn_entity(world, [])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), nameless.id)

    region = spawn_entity(world, [IdentityComponent(name="Black Keep", kind="region")])
    region.add_relationship(Contains(mode=ContainmentMode.REGION), room.id)
    clock = spawn_entity(
        world,
        [TimeOfDayComponent(phase="night"), WeatherComponent(condition="rain")],
    )
    del clock

    projection = MediaSceneProjection(
        actor,
        fact_providers=(_Facts(), _BrokenFacts()),
    )
    await actor.bus.publish(
        DomainEvent(
            **event_base(
                1,
                event_id="ambient",
                visibility=EventVisibility.ROOM,
                room_id=str(room.id),
            )
        )
    )
    stray = spawn_entity(world, [IdentityComponent(name="Stray", kind="prop")])
    await actor.bus.publish(
        DomainEvent(
            **event_base(
                1,
                event_id="stray",
                visibility=EventVisibility.PUBLIC,
                actor_id=str(stray.id),
            )
        )
    )
    await actor.bus.publish(
        DomainEvent(
            **event_base(
                1,
                event_id="private",
                visibility=EventVisibility.PRIVATE,
                room_id=str(room.id),
            )
        )
    )
    await actor.bus.publish(
        ImageGenerationCompletedEvent(
            **event_base(1, visibility=EventVisibility.ROOM, room_id=str(room.id)),
            entity_id=str(gate.id),
            purpose="event",
            url="/ignored.png",
        )
    )
    event = CharacterAttackedEvent(
        **event_base(
            2,
            event_id="attack",
            visibility=EventVisibility.ROOM,
            actor_id=str(character.id),
            room_id=str(room.id),
            target_ids=(str(gate.id), "missing-target"),
            causation_id="cause",
            correlation_id="correlation",
        ),
        target_id=str(gate.id),
        weapon_id=str(sword.id),
        damage=4.5,
    )
    await actor.bus.publish(event)

    selected = projection.select_event(room.id, event.event_id)
    assert selected is not None
    with pytest.raises(ValueError, match="not visible"):
        projection.select_event(scenario.room_b, event.event_id)
    with pytest.raises(ValueError, match="unknown or expired"):
        projection.select_event(room.id, "unknown")
    snapshot = projection.capture(viewer=character, room=room, primary=selected)

    assert snapshot.primary_event_id == "attack"
    assert snapshot.room.region == "Black Keep"
    assert snapshot.room.appearance == "gothic arches"
    assert snapshot.room.light
    assert snapshot.room.temperature
    assert snapshot.room.time_of_day == "night"
    assert snapshot.room.weather == "rain"
    assert snapshot.room.facts[0].text == "visual fact for room"
    assert [item.name for item in snapshot.characters] == ["Juniper", "Witness"]
    juniper = snapshot.characters[0]
    assert juniper.role == "primary_actor"
    assert juniper.states == ("dead", "collapsed", "sleeping", "resting", "inactive")
    assert juniper.held == ("Sword",)
    assert juniper.worn == ("Cloak",)
    assert juniper.position is not None and juniper.position.layer == 0
    assert "scar over one eye" in juniper.description
    iron_gate = next(item for item in snapshot.objects if item.name == "Iron Gate")
    assert iron_gate.role == "primary_target"
    assert iron_gate.states == ("closed", "locked")
    assert iron_gate.position is not None and iron_gate.position.layer == 9
    assert all(item.name not in {"Hidden Rat", "Secret"} for item in snapshot.characters)
    assert snapshot.events[-1].summary.startswith("Character Attacked by Juniper")
    assert "missing-target" in snapshot.events[-1].summary
    assert any(detail.startswith("damage: 4.5") for detail in snapshot.events[-1].details)


async def test_projection_tracks_move_rooms_and_latest_event_without_explicit_room():
    scenario = build_scenario()
    projection = MediaSceneProjection(scenario.actor, event_limit=2)
    moved = ActorMovedEvent(
        **event_base(
            1,
            event_id="move",
            visibility=EventVisibility.PUBLIC,
            actor_id=str(scenario.character),
        ),
        from_room_id=str(scenario.room_a),
        to_room_id=str(scenario.room_b),
        direction="north",
    )
    await scenario.actor.bus.publish(moved)
    assert projection.select_event(scenario.room_a) is not None
    assert projection.select_event(scenario.room_b) is not None
    assert projection.select_event(scenario.room_a).event.event_id == "move"
