"""End-to-end checks for core simulation mechanics."""

from __future__ import annotations

import pytest
from conftest import build_scenario

from bunnyland.core import (
    ActionPointsComponent,
    AttentionComponent,
    BleedingComponent,
    BodyPlanComponent,
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    EncumbranceComponent,
    HasInjury,
    HealthComponent,
    HearingComponent,
    IdentityComponent,
    Lane,
    NoiseComponent,
    PainComponent,
    PerceptionComponent,
    StealthComponent,
    StimulusComponent,
    WeightComponent,
    build_submitted_command,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.events import (
    AttentionShiftedEvent,
    EncumbranceChangedEvent,
    EntitySeenEvent,
    InjuryAddedEvent,
    NoiseHeardEvent,
)
from bunnyland.mechanics.barbariansim import AttackHandler

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


async def test_fight_creates_injury_and_bleeding_reduces_health():
    scenario = build_scenario()
    scenario.actor.register_handler(AttackHandler())
    attacker = scenario.actor.world.get_entity(scenario.character)
    attacker.add_component(HealthComponent(current=20.0, maximum=20.0))
    target = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(),
            ActionPointsComponent(current=5.0, maximum=5.0),
            HealthComponent(current=20.0, maximum=20.0),
            BodyPlanComponent(parts=("torso",), vital_parts=("torso",)),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), target.id
    )
    injuries = collect(scenario.actor, InjuryAddedEvent)

    await scenario.actor.submit(
        build_submitted_command(
            character_id=str(scenario.character),
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="attack",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload={"target_id": str(target.id)},
        )
    )
    await scenario.actor.tick(HOUR)

    target_health = target.get_component(HealthComponent)
    assert target_health.current == pytest.approx(15.0)
    assert target.has_component(PainComponent)
    assert target.get_component(PainComponent).current == pytest.approx(5.0)
    assert target.has_component(BleedingComponent)
    assert target.get_component(BleedingComponent).rate == pytest.approx(0.5)
    assert len(target.get_relationships(HasInjury)) == 1
    assert injuries[-1].body_part == "torso"

    await scenario.actor.tick(HOUR)

    assert target.get_component(HealthComponent).current == pytest.approx(14.5)
    assert target.get_component(BleedingComponent).accumulated_loss == pytest.approx(0.5)


async def test_room_perception_tracks_visible_entities_and_skips_hidden():
    scenario = build_scenario()
    visible_item = spawn_entity(
        scenario.actor.world, [IdentityComponent(name="brass bell", kind="item")]
    )
    hidden_item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="hidden cache", kind="item"),
            StealthComponent(visibility_level=0.05, hidden_threshold=0.1, hiding=True),
        ],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), visible_item.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), hidden_item.id)
    seen = collect(scenario.actor, EntitySeenEvent)

    await scenario.actor.tick(HOUR)

    perception = scenario.actor.world.get_entity(scenario.character).get_component(
        PerceptionComponent
    )
    assert str(visible_item.id) in perception.visible_entities
    assert str(hidden_item.id) not in perception.visible_entities
    assert any(event.entity_id == str(visible_item.id) for event in seen)


async def test_listener_hears_character_move_when_noise_meets_sensitivity():
    scenario = build_scenario()
    listener = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(),
            HearingComponent(sensitivity=0.5),
        ],
    )
    hard_of_hearing = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(),
            HearingComponent(sensitivity=2.0),
        ],
    )
    room_b = scenario.actor.world.get_entity(scenario.room_b)
    room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), listener.id)
    room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), hard_of_hearing.id)
    heard = collect(scenario.actor, NoiseHeardEvent)

    await scenario.actor.submit(
        build_submitted_command(
            character_id=str(scenario.character),
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="move",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload={"direction": "north", "noise": 1.0},
        )
    )
    await scenario.actor.tick(HOUR)

    listener_perception = listener.get_component(PerceptionComponent)
    quiet_perception = hard_of_hearing.get_component(PerceptionComponent)
    assert len(listener_perception.audible_entities) == 1
    assert quiet_perception.audible_entities == frozenset()
    noise_id = next(iter(listener_perception.audible_entities))
    parsed_noise_id = parse_entity_id(noise_id)
    assert parsed_noise_id is not None
    noise = scenario.actor.world.get_entity(parsed_noise_id)
    assert noise.get_component(NoiseComponent).source_entity_id == str(scenario.character)
    assert any(event.noise_id == noise_id and event.actor_id == str(listener.id) for event in heard)


async def test_stimulus_shifts_attention_then_decays_after_expiration():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(AttentionComponent(decay_rate=0.5))
    source = spawn_entity(
        scenario.actor.world, [IdentityComponent(name="silver chime", kind="item")]
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), source.id
    )
    spawn_entity(
        scenario.actor.world,
        [
            StimulusComponent(
                stimulus_type="sound",
                source_entity_id=str(source.id),
                room_id=str(scenario.room_a),
                intensity=1.0,
                created_at_epoch=0,
                expires_at_epoch=int(HOUR),
                text="a clear chime",
            )
        ],
    )
    shifts = collect(scenario.actor, AttentionShiftedEvent)

    await scenario.actor.tick(HOUR)

    attention = character.get_component(AttentionComponent)
    assert attention.focus_entity_id == str(source.id)
    assert attention.score == pytest.approx(1.0)
    assert any(event.focus_entity_id == str(source.id) for event in shifts)

    await scenario.actor.tick(HOUR)

    attention = character.get_component(AttentionComponent)
    assert attention.focus_entity_id == str(source.id)
    assert attention.score == pytest.approx(0.5)
