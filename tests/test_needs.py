"""Tests for hunger/thirst rise and eat/drink relief."""

from __future__ import annotations

import pytest
from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    SleepingComponent,
    build_submitted_command,
    container_of,
    spawn_entity,
)
from bunnyland.core.handlers.base import HandlerContext
from bunnyland.foundation.consumables.actions import DrinkHandler, EatHandler, _consume_one_use
from bunnyland.foundation.consumables.components import (
    ConsumableComponent,
    DrinkableComponent,
    FoodComponent,
)
from bunnyland.foundation.meters.mechanics import Meter
from bunnyland.foundation.needs.mechanics import (
    BatheHandler,
    ComfortNeedComponent,
    FatigueComponent,
    FunNeedComponent,
    HungerComponent,
    HygieneComponent,
    NeedAffordanceComponent,
    PrivacyNeedComponent,
    SafetyNeedComponent,
    SocialNeedComponent,
    ThirstComponent,
    hunger_band,
    install_needs,
    need_fragments,
    recover_daily_need,
    thirst_band,
)
from bunnyland.prompts import ComponentPromptContext, PromptPerspective

HOUR = 3600.0


def needs_scenario(*, hunger=0.0, thirst=0.0):
    scenario = build_scenario()
    install_needs(scenario.actor)
    char = scenario.actor.world.get_entity(scenario.character)
    char.add_component(HungerComponent(meter=Meter(value=hunger), metabolism=2.0))
    char.add_component(ThirstComponent(meter=Meter(value=thirst), hydration_loss_rate=3.0))
    return scenario


def daily_needs_scenario():
    scenario = needs_scenario()
    char = scenario.actor.world.get_entity(scenario.character)
    char.add_component(FatigueComponent(meter=Meter(value=20.0), fatigue_rate=2.0))
    char.add_component(HygieneComponent(meter=Meter(value=60.0), decay_rate=2.0))
    char.add_component(ComfortNeedComponent(meter=Meter(value=60.0), decay_rate=2.0))
    char.add_component(FunNeedComponent(meter=Meter(value=60.0), decay_rate=2.0))
    char.add_component(SocialNeedComponent(meter=Meter(value=60.0), decay_rate=2.0))
    char.add_component(PrivacyNeedComponent(meter=Meter(value=60.0), decay_rate=2.0))
    char.add_component(SafetyNeedComponent(meter=Meter(value=60.0), decay_rate=2.0))
    return scenario


def verb(scenario, command_type, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def give_item(scenario, components, *, in_inventory=True):
    item = spawn_entity(scenario.actor.world, components)
    holder = scenario.character if in_inventory else scenario.room_a
    mode = ContainmentMode.INVENTORY if in_inventory else ContainmentMode.ROOM_CONTENT
    scenario.actor.world.get_entity(holder).add_relationship(Contains(mode=mode), item.id)
    return item.id


def handler_context(scenario):
    return HandlerContext(scenario.actor.world, scenario.actor.epoch)


def execute_eat(scenario, item_id, *, character_id=None):
    command = verb(scenario, "eat", item_id=str(item_id))
    if character_id is not None:
        command = build_submitted_command(
            character_id=character_id,
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="eat",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload=command.payload,
        )
    return EatHandler().execute(handler_context(scenario), command)


def execute_drink(scenario, source_id, *, character_id=None):
    command = verb(scenario, "drink", source_id=str(source_id))
    if character_id is not None:
        command = build_submitted_command(
            character_id=character_id,
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="drink",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload=command.payload,
        )
    return DrinkHandler().execute(handler_context(scenario), command)


# -- rise over time ---------------------------------------------------------------------


def test_hunger_and_thirst_bands_track_meter_severity():
    scenario = needs_scenario(hunger=95.0, thirst=10.0)
    char = scenario.actor.world.get_entity(scenario.character)

    assert hunger_band(char) == "crisis"
    assert thirst_band(char) == "calm"


def test_recover_daily_need_without_timestamp_field_leaves_epoch_unchanged():
    scenario = needs_scenario()
    char = scenario.actor.world.get_entity(scenario.character)
    char.add_component(SocialNeedComponent(meter=Meter(value=60.0), last_social_epoch=7))

    updated = recover_daily_need(char, SocialNeedComponent, 25.0, epoch=99)

    # timestamp_field is None: the meter drops but the stored epoch is untouched (353->355).
    assert updated.meter.value == pytest.approx(35.0)
    assert updated.last_social_epoch == 7
    assert char.get_component(SocialNeedComponent).meter.value == pytest.approx(35.0)


async def test_hunger_and_thirst_rise_independently():
    scenario = needs_scenario()
    char = scenario.actor.world.get_entity(scenario.character)

    await scenario.actor.tick(HOUR)
    # hunger += metabolism(2.0)*1h; thirst += loss(3.0)*1h
    assert char.get_component(HungerComponent).meter.value == pytest.approx(2.0)
    assert char.get_component(ThirstComponent).meter.value == pytest.approx(3.0)


async def test_daily_needs_decay_and_fatigue_recovers_while_sleeping():
    scenario = daily_needs_scenario()
    char = scenario.actor.world.get_entity(scenario.character)

    await scenario.actor.tick(HOUR)

    assert char.get_component(FatigueComponent).meter.value == pytest.approx(22.0)
    assert char.get_component(HygieneComponent).meter.value == pytest.approx(62.0)
    assert char.get_component(ComfortNeedComponent).meter.value == pytest.approx(62.0)
    assert char.get_component(FunNeedComponent).meter.value == pytest.approx(62.0)
    assert char.get_component(SocialNeedComponent).meter.value == pytest.approx(62.0)
    assert char.get_component(PrivacyNeedComponent).meter.value == pytest.approx(62.0)
    assert char.get_component(SafetyNeedComponent).meter.value == pytest.approx(62.0)

    char.add_component(SleepingComponent(started_at_epoch=scenario.actor.epoch))
    await scenario.actor.tick(HOUR)

    assert char.get_component(FatigueComponent).meter.value < 22.0


async def test_daily_need_recovery_verbs_use_reachable_affordances_and_prompt_fragments():
    scenario = daily_needs_scenario()
    basin = give_item(
        scenario,
        [
            IdentityComponent(name="bath basin", kind="fixture"),
            NeedAffordanceComponent(recoveries={"hygiene": 10.0}),
        ],
        in_inventory=False,
    )
    chair = give_item(
        scenario,
        [
            IdentityComponent(name="soft chair", kind="furniture"),
            NeedAffordanceComponent(recoveries={"comfort": 5.0}),
        ],
        in_inventory=False,
    )

    await scenario.actor.submit(verb(scenario, "bathe", target_id=str(basin)))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(verb(scenario, "relax", target_id=str(chair)))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(verb(scenario, "play"))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(verb(scenario, "seek-privacy"))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(verb(scenario, "seek-safety"))
    await scenario.actor.tick(0.0)

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(HygieneComponent).meter.value == pytest.approx(15.0)
    assert char.get_component(ComfortNeedComponent).meter.value == pytest.approx(30.0)
    assert char.get_component(FunNeedComponent).meter.value == pytest.approx(35.0)
    assert char.get_component(PrivacyNeedComponent).meter.value == pytest.approx(30.0)
    assert char.get_component(SafetyNeedComponent).meter.value == pytest.approx(30.0)
    assert any(
        "company" in fact.text
        for fact in need_fragments(scenario.actor.world, char, detail_cutoff=30)
    )


def test_daily_need_recovery_handler_rejects_invalid_missing_and_unreachable_targets():
    scenario = build_scenario()
    ctx = handler_context(scenario)
    char = scenario.actor.world.get_entity(scenario.character)
    distant_basin = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant basin", kind="fixture"),
            NeedAffordanceComponent(recoveries={"hygiene": 10.0}),
        ],
    )

    invalid_command = build_submitted_command(
        character_id="not-an-id",
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="bathe",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={},
    )
    assert BatheHandler().execute(ctx, invalid_command).reason == "invalid character id"
    missing_command = build_submitted_command(
        character_id="entity_999",
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="bathe",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={},
    )
    assert BatheHandler().execute(ctx, missing_command).reason == "character does not exist"
    assert BatheHandler().execute(ctx, verb(scenario, "bathe")).reason == (
        "character has no hygiene need"
    )

    char.add_component(HygieneComponent(meter=Meter(value=40.0)))
    missing_target = BatheHandler().execute(
        ctx,
        verb(scenario, "bathe", target_id="entity_999"),
    )
    assert missing_target.ok is False
    assert missing_target.reason == "target does not exist"
    result = BatheHandler().execute(
        ctx,
        verb(scenario, "bathe", target_id=str(distant_basin.id)),
    )
    assert result.ok is False
    assert result.reason == "target is not reachable"


def test_need_fragments_include_hunger_and_thirst_pressure():
    scenario = build_scenario()
    char = scenario.actor.world.get_entity(scenario.character)
    char.add_component(HungerComponent(meter=Meter(value=95.0)))
    char.add_component(ThirstComponent(meter=Meter(value=95.0)))

    fragments = need_fragments(scenario.actor.world, char)

    assert any("starving" in fact.text.lower() for fact in fragments)
    assert any("dehydrated" in fact.text.lower() for fact in fragments)


def test_need_component_fragments_preserve_thresholds_and_support_perspective():
    scenario = build_scenario()
    char = scenario.actor.world.get_entity(scenario.character)
    first = ComponentPromptContext.for_entity(
        scenario.actor.world,
        char,
        perspective=PromptPerspective(viewer=char, perspective="first-person"),
    )
    third = ComponentPromptContext.for_entity(
        scenario.actor.world,
        char,
        perspective=PromptPerspective(viewer=char, perspective="third-person"),
    )

    assert HungerComponent(meter=Meter(value=10.0)).prompt_fragments(first) == ()
    hunger = HungerComponent(meter=Meter(value=95.0)).prompt_fragments(first)
    assert [(fact.key, fact.text, fact.detail) for fact in hunger] == [
        ("needs.hunger", "I am starving and feel weak.", 0)
    ]
    thirst = ThirstComponent(meter=Meter(value=75.0)).prompt_fragments(third)
    assert [(fact.text, fact.detail) for fact in thirst] == [
        ("They are thirsty; they should find clean water soon.", 10)
    ]
    fatigue = FatigueComponent(meter=Meter(value=40.0)).prompt_fragments(first)
    assert fatigue == ()

    detailed = ComponentPromptContext.for_entity(
        scenario.actor.world,
        char,
        perspective=PromptPerspective(viewer=char, perspective="first-person"),
        detail_cutoff=30,
    )
    calm = HungerComponent(meter=Meter(value=10.0)).prompt_fragments(detailed)
    assert [(fact.key, fact.text, fact.detail) for fact in calm] == [
        ("needs.hunger", "I am not hungry.", 30)
    ]
    warning = FatigueComponent(meter=Meter(value=40.0)).prompt_fragments(detailed)
    assert [(fact.text, fact.detail) for fact in warning] == [("I am getting tired.", 20)]

    observer = spawn_entity(scenario.actor.world)
    observed_detail = ComponentPromptContext.for_entity(
        scenario.actor.world,
        char,
        perspective=PromptPerspective(viewer=observer, perspective="third-person"),
        detail_cutoff=30,
    )
    assert FatigueComponent(meter=Meter(value=95.0)).prompt_fragments(observed_detail) == ()
    assert HungerComponent(meter=Meter(value=10.0)).prompt_fragments(observed_detail) == ()


async def test_suspended_character_does_not_get_hungry():
    scenario = needs_scenario()
    no_op = spawn_entity(scenario.actor.world)
    scenario.actor.suspend(scenario.character, no_op.id)

    await scenario.actor.tick(10 * HOUR)
    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(HungerComponent).meter.value == pytest.approx(0.0)
    assert char.get_component(ThirstComponent).meter.value == pytest.approx(0.0)


# -- eat --------------------------------------------------------------------------------


async def test_eat_reduces_hunger_and_consumes_item():
    scenario = needs_scenario(hunger=50.0)
    berry = give_item(
        scenario,
        [
            IdentityComponent(name="berry", kind="item"),
            FoodComponent(nutrition=5.0, satiety=20.0),
            ConsumableComponent(current_uses=1, max_uses=1),
        ],
    )

    await scenario.actor.submit(verb(scenario, "eat", item_id=str(berry)))
    await scenario.actor.tick(0.0)  # no rise this tick

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(HungerComponent).meter.value == pytest.approx(30.0)
    assert not scenario.actor.world.has_entity(berry)  # single-use item consumed


async def test_eat_non_food_is_rejected():
    scenario = needs_scenario(hunger=50.0)
    rock = give_item(scenario, [IdentityComponent(name="rock", kind="item")])

    await scenario.actor.submit(verb(scenario, "eat", item_id=str(rock)))
    await scenario.actor.tick(0.0)

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(HungerComponent).meter.value == pytest.approx(50.0)
    assert scenario.actor.world.has_entity(rock)


def test_eat_rejects_invalid_missing_unable_and_unreachable_food():
    scenario = needs_scenario(hunger=50.0)
    berry = give_item(
        scenario,
        [IdentityComponent(name="berry", kind="item"), FoodComponent(nutrition=5.0, satiety=10.0)],
    )
    far_berry = give_item(
        scenario,
        [
            IdentityComponent(name="far berry", kind="item"),
            FoodComponent(nutrition=5.0, satiety=10.0),
        ],
        in_inventory=False,
    )
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(Contains, far_berry)
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        far_berry,
    )

    assert execute_eat(scenario, berry, character_id="not-an-id").reason == (
        "invalid or missing item"
    )
    assert execute_eat(scenario, "entity_999").reason == "invalid or missing item"

    character = scenario.actor.world.get_entity(scenario.character)
    character.remove_component(HungerComponent)
    assert execute_eat(scenario, berry).reason == "character cannot eat"

    character.add_component(HungerComponent(meter=Meter(value=50.0)))
    assert execute_eat(scenario, far_berry).reason == "food is not reachable"


def test_eat_rejects_detached_food_as_unreachable():
    scenario = needs_scenario(hunger=50.0)
    berry = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="loose berry", kind="item"),
            FoodComponent(nutrition=5.0, satiety=10.0),
        ],
    )

    assert execute_eat(scenario, berry.id).reason == "food is not reachable"


def test_eat_decrements_multi_use_food_without_destroying_it():
    scenario = needs_scenario(hunger=50.0)
    berry = give_item(
        scenario,
        [
            IdentityComponent(name="berry", kind="item"),
            FoodComponent(nutrition=5.0, satiety=10.0),
            ConsumableComponent(current_uses=2, max_uses=2),
        ],
    )

    result = execute_eat(scenario, berry)

    assert result.ok is True
    assert scenario.actor.world.has_entity(berry)
    item = scenario.actor.world.get_entity(berry)
    assert item.get_component(ConsumableComponent).current_uses == 1
    assert container_of(item) == scenario.character


# -- drink ------------------------------------------------------------------------------


async def test_drink_reduces_thirst_from_renewable_source():
    scenario = needs_scenario(thirst=60.0)
    # A basin in the room: drinkable but not consumable -> renewable.
    basin = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="basin", kind="furniture"), DrinkableComponent(hydration=25.0)],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), basin.id
    )

    await scenario.actor.submit(verb(scenario, "drink", source_id=str(basin.id)))
    await scenario.actor.tick(0.0)

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(ThirstComponent).meter.value == pytest.approx(35.0)
    assert scenario.actor.world.has_entity(basin.id)  # renewable, not consumed


async def test_drink_meter_clamps_at_minimum():
    scenario = needs_scenario(thirst=10.0)
    cup = give_item(
        scenario,
        [IdentityComponent(name="cup", kind="item"), DrinkableComponent(hydration=50.0)],
    )

    await scenario.actor.submit(verb(scenario, "drink", source_id=str(cup)))
    await scenario.actor.tick(0.0)

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(ThirstComponent).meter.value == pytest.approx(0.0)


def test_drink_rejects_invalid_missing_unable_and_unreachable_source():
    scenario = needs_scenario(thirst=50.0)
    cup = give_item(
        scenario,
        [IdentityComponent(name="cup", kind="item"), DrinkableComponent(hydration=10.0)],
    )
    rock = give_item(scenario, [IdentityComponent(name="rock", kind="item")])
    far_cup = give_item(
        scenario,
        [IdentityComponent(name="far cup", kind="item"), DrinkableComponent(hydration=10.0)],
        in_inventory=False,
    )
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(Contains, far_cup)
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        far_cup,
    )

    assert execute_drink(scenario, cup, character_id="not-an-id").reason == (
        "invalid or missing source"
    )
    assert execute_drink(scenario, "entity_999").reason == "invalid or missing source"
    assert execute_drink(scenario, rock).reason == "source is not drinkable"

    character = scenario.actor.world.get_entity(scenario.character)
    character.remove_component(ThirstComponent)
    assert execute_drink(scenario, cup).reason == "character cannot drink"

    character.add_component(ThirstComponent(meter=Meter(value=50.0)))
    assert execute_drink(scenario, far_cup).reason == "source is not reachable"


def test_consume_one_use_destroys_detached_spent_item():
    scenario = needs_scenario()
    item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="vanishing wafer", kind="item"),
            ConsumableComponent(current_uses=1, max_uses=1),
        ],
    )

    _consume_one_use(handler_context(scenario), item)

    assert not scenario.actor.world.has_entity(item.id)
