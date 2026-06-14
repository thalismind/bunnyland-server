"""Tests for durable world history projection."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    ReadableComponent,
    WritableComponent,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import (
    CharacterDiedEvent,
    DomainEvent,
    ItemCraftedEvent,
    PhysicalWriteEvent,
    event_base,
)
from bunnyland.mechanics.history import (
    HistoryActor,
    HistoryTarget,
    WorldHistoryRecordComponent,
    history_fragments,
    record_world_history,
    world_history_records,
)
from bunnyland.persistence import WorldMeta, load_world, save_world
from bunnyland.plugins import apply_plugins, bunnyland_plugins, collect_prompt_fragments
from bunnyland.plugins.builtin import CORE_VERBS, HISTORY
from bunnyland.prompts import PromptBuilder

HOUR = 3600.0


def _plugins():
    return [plugin for plugin in bunnyland_plugins() if plugin.id in (CORE_VERBS, HISTORY)]


def _write_command(scenario, target_id, text: str):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="write",
        cost=CommandCost(action=1, focus=1),
        lane=Lane.WORLD,
        payload={"target_id": str(target_id), "text": text},
    )


async def test_physical_writing_creates_persisted_world_history_prompt(tmp_path):
    scenario = build_scenario()
    plugins = _plugins()
    apply_plugins(plugins, scenario.actor)
    world = scenario.actor.world
    paper = spawn_entity(
        world,
        [
            IdentityComponent(name="watch sign", kind="sign"),
            WritableComponent(),
            ReadableComponent(),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), paper.id
    )

    await scenario.actor.submit(
        _write_command(scenario, paper.id, "Juniper kept watch through the storm.")
    )
    await scenario.actor.tick(HOUR)

    records = world_history_records(world)
    assert len(records) == 1
    record_entity, record = records[0]
    assert record.tags == ("authored", "writing", "artifact")
    assert record.location_id == str(scenario.room_a)
    assert "Juniper wrote on watch sign" in record.summary
    assert record_entity.get_relationships(HistoryActor)[0][1] == scenario.character
    assert record_entity.get_relationships(HistoryTarget)[0][1] == paper.id

    ctx = PromptBuilder(
        world, fragment_providers=collect_prompt_fragments(plugins)
    ).build(scenario.character)
    assert any("Juniper kept watch through the storm" in line for line in ctx.conditions)

    path = tmp_path / "world.json"
    save_world(scenario.actor, path, meta=WorldMeta(seed="history"))
    loaded, _meta = load_world(path, plugins=plugins)

    loaded_records = world_history_records(loaded.world)
    assert len(loaded_records) == 1
    loaded_ctx = PromptBuilder(
        loaded.world, fragment_providers=collect_prompt_fragments(plugins)
    ).build(scenario.character)
    assert any("World history:" in line for line in loaded_ctx.conditions)
    assert any("source:" in line for line in loaded_ctx.conditions)


async def test_character_death_event_becomes_history_with_actor_and_target_edges():
    scenario = build_scenario()
    apply_plugins(_plugins(), scenario.actor)
    event = CharacterDiedEvent(
        **event_base(
            42,
            actor_id=str(scenario.character),
            target_ids=(str(scenario.character),),
            cause="a cave-in",
        )
    )

    await scenario.actor.bus.publish(event)

    record_entity, record = world_history_records(scenario.actor.world)[0]
    assert record.summary == "Juniper died from a cave-in."
    assert record.tags == ("death", "loss", "consequence")
    assert record.source_event_id == event.event_id
    assert record_entity.get_relationships(HistoryActor)[0][1] == scenario.character
    assert record_entity.get_relationships(HistoryTarget)[0][1] == scenario.character


async def test_history_reactor_handles_craft_fallback_and_non_notable_events():
    scenario = build_scenario()
    apply_plugins(_plugins(), scenario.actor)
    world = scenario.actor.world
    outputs = []
    for name in ("banner", "hook", "lamp", "map"):
        item = spawn_entity(world, [IdentityComponent(name=name, kind="item")])
        outputs.append(str(item.id))

    await scenario.actor.bus.publish(
        ItemCraftedEvent(
            **event_base(
                10,
                actor_id=str(scenario.character),
                target_ids=tuple(outputs),
                recipe_id="camp-kit",
                output_ids=tuple(outputs),
            )
        )
    )
    await scenario.actor.bus.publish(
        ItemCraftedEvent(
            **event_base(
                11,
                actor_id=None,
                recipe_id="empty",
                output_ids=(),
            )
        )
    )
    await scenario.actor.bus.publish(DomainEvent(**event_base(12)))

    summaries = [record.summary for _entity, record in world_history_records(world)]
    assert summaries == [
        "someone crafted 0 item from recipe empty.",
        "Juniper crafted banner, hook, lamp, and 1 more from recipe camp-kit.",
    ]
    assert world_history_records(world, tags={"missing"}) == []
    assert len(world_history_records(world, tags={"crafted"})) == 2


async def test_history_reactor_resolves_location_from_target_when_actor_is_missing():
    scenario = build_scenario()
    apply_plugins(_plugins(), scenario.actor)
    world = scenario.actor.world
    sign = spawn_entity(
        world,
        [IdentityComponent(name="long sign", kind="sign"), WritableComponent()],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), sign.id
    )

    await scenario.actor.bus.publish(
        PhysicalWriteEvent(
            **event_base(
                7,
                actor_id="entity_999",
                target_ids=(str(sign.id),),
                item_id=str(sign.id),
                text="word " * 40,
            )
        )
    )

    _record_entity, record = world_history_records(world)[0]
    assert record.location_id == str(scenario.room_a)
    assert record.summary.startswith('someone wrote on long sign: "word word')
    assert record.summary.endswith('..."')


def test_record_world_history_skips_empty_and_duplicate_sources():
    scenario = build_scenario()
    world = scenario.actor.world

    assert (
        record_world_history(
            world,
            summary="",
            source_event_id="event-a",
            event_type="Manual",
            created_at_epoch=1,
        )
        is None
    )
    assert (
        record_world_history(
            world,
            summary="No source should not persist.",
            source_event_id="",
            event_type="Manual",
            created_at_epoch=1,
        )
        is None
    )
    created = record_world_history(
        world,
        summary="Juniper mapped the tunnel. " * 20,
        source_event_id="event-a",
        event_type="Manual",
        created_at_epoch=1,
        actor_ids=("bad", "entity_999", str(scenario.character)),
        target_ids=("bad", "entity_999", str(scenario.room_a)),
        tags=("mapped", "mapped", ""),
        salience=-1.0,
    )
    duplicate = record_world_history(
        world,
        summary="Juniper mapped it again.",
        source_event_id="event-a",
        event_type="Manual",
        created_at_epoch=2,
    )

    assert created is not None
    assert duplicate is None
    record = created.get_component(WorldHistoryRecordComponent)
    assert record.summary.endswith("...")
    assert record.tags == ("mapped",)
    assert record.salience == 0.0
    assert created.get_relationships(HistoryActor)[0][1] == scenario.character
    assert created.get_relationships(HistoryTarget)[0][1] == scenario.room_a


def test_history_fragments_only_show_relevant_records():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    record_world_history(
        world,
        summary="Juniper mapped this burrow.",
        source_event_id="near",
        event_type="Manual",
        created_at_epoch=1,
        location_id=str(scenario.room_a),
    )
    record_world_history(
        world,
        summary="A far tunnel collapsed.",
        source_event_id="far",
        event_type="Manual",
        created_at_epoch=2,
        location_id=str(scenario.room_b),
    )
    record_world_history(
        world,
        summary="Juniper is remembered elsewhere.",
        source_event_id="actor",
        event_type="Manual",
        created_at_epoch=29,
        location_id=str(scenario.room_b),
        actor_ids=(str(scenario.character),),
    )
    token = spawn_entity(world, [IdentityComponent(name="visible token", kind="item")])
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), token.id)
    record_world_history(
        world,
        summary="The visible token was blessed elsewhere.",
        source_event_id="target",
        event_type="Manual",
        created_at_epoch=30,
        location_id=str(scenario.room_b),
        target_ids=(str(token.id),),
    )
    for index in range(6):
        record_world_history(
            world,
            summary=f"Room deed {index}.",
            source_event_id=f"near-{index}",
            event_type="Manual",
            created_at_epoch=10 + index,
            location_id=str(scenario.room_a),
        )

    fragments = history_fragments(world, character)

    assert len(fragments) == 5
    assert any("Room deed 5." in fragment for fragment in fragments)
    assert any("source:target" in fragment for fragment in fragments)
