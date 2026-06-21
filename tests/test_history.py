"""Tests for durable world history projection."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    EntityInspectedEvent,
    IdentityComponent,
    Lane,
    ReadableComponent,
    WritableComponent,
    build_submitted_command,
    parse_entity_id,
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
    CreatedBy,
    CreatorSignatureComponent,
    DeathConsequenceComponent,
    DeathOf,
    DeedReputationComponent,
    HistoryActor,
    HistoryTarget,
    MarkOn,
    PhysicalMarkComponent,
    WorldHistoryRecordComponent,
    apply_deed_reputation,
    creator_fragments,
    creator_signature_for_event,
    death_consequence_for_event,
    death_consequence_fragments,
    deed_reputation_fragments,
    history_fragments,
    mark_fragments,
    marks_on,
    physical_mark_for_event,
    record_creator_signature,
    record_death_consequence,
    record_physical_mark,
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


def _inspect_command(scenario, target_id):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="inspect",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"target_id": str(target_id)},
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
    mark_entity, mark = marks_on(world, paper.id)[0]
    assert mark.text == "Juniper kept watch through the storm."
    assert mark.author_id == str(scenario.character)
    assert mark_entity.get_component(PhysicalMarkComponent) == mark
    assert mark_entity.get_relationships(MarkOn)[0][1] == paper.id
    assert physical_mark_for_event(world, mark.source_event_id) == mark_entity
    signature = mark_entity.get_component(CreatorSignatureComponent)
    assert signature.creator_id == str(scenario.character)
    assert signature.circumstance == "writing on watch sign"
    assert mark_entity.get_relationships(CreatedBy)[0][1] == scenario.character
    deed_reputation = world.get_entity(scenario.character).get_component(
        DeedReputationComponent
    )
    assert deed_reputation.scores["writing"] == 0.7
    assert deed_reputation.scores["authored"] == 0.7
    assert deed_reputation.known_for == (record.summary,)

    ctx = PromptBuilder(
        world, fragment_providers=collect_prompt_fragments(plugins)
    ).build(scenario.character)
    assert any("Juniper kept watch through the storm" in line for line in ctx.conditions)
    assert any("watch sign bears writing by Juniper" in line for line in ctx.conditions)
    assert any("Deed reputation writing: 0.7." in line for line in ctx.conditions)

    path = tmp_path / "world.json"
    save_world(scenario.actor, path, meta=WorldMeta(seed="history"))
    loaded, _meta = load_world(path, plugins=plugins)

    loaded_records = world_history_records(loaded.world)
    assert len(loaded_records) == 1
    loaded_marks = marks_on(loaded.world, paper.id)
    assert len(loaded_marks) == 1
    assert loaded_marks[0][1].text == "Juniper kept watch through the storm."
    assert loaded_marks[0][0].get_component(CreatorSignatureComponent).circumstance == (
        "writing on watch sign"
    )
    loaded_ctx = PromptBuilder(
        loaded.world, fragment_providers=collect_prompt_fragments(plugins)
    ).build(scenario.character)
    assert any("World history:" in line for line in loaded_ctx.conditions)
    assert any("source:" in line for line in loaded_ctx.conditions)
    assert any("watch sign bears writing by Juniper" in line for line in loaded_ctx.conditions)

    inspected: list[EntityInspectedEvent] = []
    loaded.bus.subscribe(EntityInspectedEvent, inspected.append)
    await loaded.submit(_inspect_command(scenario, paper.id))
    await loaded.tick(HOUR)

    assert inspected[0].text == "Juniper kept watch through the storm."


async def test_character_death_event_becomes_history_and_visible_consequence(tmp_path):
    scenario = build_scenario()
    plugins = _plugins()
    apply_plugins(plugins, scenario.actor)
    event = CharacterDiedEvent(
        **event_base(
            42,
            actor_id=str(scenario.character),
            target_ids=(str(scenario.character),),
            cause="a cave-in",
        )
    )

    await scenario.actor.bus.publish(event)

    consequence_entity = death_consequence_for_event(scenario.actor.world, event.event_id)
    assert consequence_entity is not None
    consequence = consequence_entity.get_component(DeathConsequenceComponent)
    assert consequence.summary == "Juniper died from a cave-in."
    assert consequence.location_id == str(scenario.room_a)
    assert consequence_entity.get_relationships(DeathOf)[0][1] == scenario.character

    record_entity, record = world_history_records(scenario.actor.world)[0]
    assert record.summary == "Juniper died from a cave-in."
    assert record.tags == ("death", "loss", "consequence")
    assert record.source_event_id == event.event_id
    assert record_entity.get_relationships(HistoryActor)[0][1] == scenario.character
    assert record_entity.get_relationships(HistoryTarget)[0][1] == scenario.character
    ctx = PromptBuilder(
        scenario.actor.world, fragment_providers=collect_prompt_fragments(plugins)
    ).build(scenario.character)
    assert any(
        "Death consequence: Juniper died from a cave-in." in line
        for line in ctx.conditions
    )

    path = tmp_path / "world.json"
    save_world(scenario.actor, path, meta=WorldMeta(seed="death-consequence"))
    loaded, _meta = load_world(path, plugins=plugins)
    loaded_consequence = death_consequence_for_event(loaded.world, event.event_id)
    assert loaded_consequence is not None
    assert loaded_consequence.get_component(DeathConsequenceComponent).summary == (
        "Juniper died from a cave-in."
    )
    loaded_ctx = PromptBuilder(
        loaded.world, fragment_providers=collect_prompt_fragments(plugins)
    ).build(scenario.character)
    assert any(
        "Death consequence: Juniper died from a cave-in." in line
        for line in loaded_ctx.conditions
    )


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
    first_output = world.get_entity(parse_entity_id(outputs[0]))
    signature = first_output.get_component(CreatorSignatureComponent)
    assert signature.creator_id == str(scenario.character)
    assert signature.circumstance == "crafting recipe camp-kit"
    assert first_output.get_relationships(CreatedBy)[0][1] == scenario.character
    signed = creator_signature_for_event(world, signature.source_event_id)
    assert signed is not None
    assert str(signed.id) in outputs
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


async def test_history_reactor_ignores_duplicate_source_event():
    scenario = build_scenario()
    apply_plugins(_plugins(), scenario.actor)
    world = scenario.actor.world
    payload = event_base(
        9,
        event_id="fixed-death-event",
        actor_id=str(scenario.character),
        target_ids=(str(scenario.character),),
        cause="a rockfall",
    )

    await scenario.actor.bus.publish(CharacterDiedEvent(**payload))
    # Re-emitting the same source event id must not create a second record (577).
    await scenario.actor.bus.publish(CharacterDiedEvent(**payload))

    records = world_history_records(world)
    assert len(records) == 1
    assert records[0][1].source_event_id == "fixed-death-event"


async def test_history_reactor_leaves_location_blank_when_nothing_is_roomed():
    scenario = build_scenario()
    apply_plugins(_plugins(), scenario.actor)
    world = scenario.actor.world
    # Roomless actor (693->695), a missing target id (697->695), and a roomless
    # target (699->695): _location_for_event_actor exhausts every branch to "".
    world.get_entity(scenario.room_a).remove_relationship(Contains, scenario.character)
    roomless_target = spawn_entity(
        world, [IdentityComponent(name="drifting husk", kind="character")]
    )

    await scenario.actor.bus.publish(
        CharacterDiedEvent(
            **event_base(
                8,
                actor_id=str(scenario.character),
                target_ids=("entity_999", str(roomless_target.id)),
                cause="the void",
            )
        )
    )

    _entity, record = world_history_records(world)[0]
    assert record.location_id == ""
    assert record.summary == "Juniper died from the void."


def test_deed_reputation_fragments_empty_without_component():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)

    assert deed_reputation_fragments(scenario.actor.world, character) == []


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


def test_record_physical_mark_skips_invalid_empty_and_duplicate_sources():
    scenario = build_scenario()
    world = scenario.actor.world

    assert (
        record_physical_mark(
            world,
            target_id="not-an-id",
            text="x",
            source_event_id="mark-a",
            created_at_epoch=1,
        )
        is None
    )
    assert (
        record_physical_mark(
            world,
            target_id=str(scenario.room_a),
            text="",
            source_event_id="mark-a",
            created_at_epoch=1,
        )
        is None
    )
    assert (
        record_physical_mark(
            world,
            target_id=str(scenario.room_a),
            text="x",
            source_event_id="",
            created_at_epoch=1,
        )
        is None
    )
    created = record_physical_mark(
        world,
        target_id=str(scenario.room_a),
        text="  old chalk   line ",
        source_event_id="mark-a",
        created_at_epoch=1,
        mark_type="carving",
        author_id=str(scenario.character),
    )
    duplicate = record_physical_mark(
        world,
        target_id=str(scenario.room_a),
        text="another line",
        source_event_id="mark-a",
        created_at_epoch=2,
    )

    assert created is not None
    assert duplicate is None
    assert marks_on(world, scenario.room_a)[0][1].text == "old chalk line"


def test_record_creator_signature_skips_invalid_and_duplicate_sources():
    scenario = build_scenario()
    world = scenario.actor.world
    artifact = spawn_entity(world, [IdentityComponent(name="carved hook", kind="item")])

    assert (
        record_creator_signature(
            world,
            artifact_id="not-an-id",
            creator_id=str(scenario.character),
            source_event_id="sig-a",
            created_at_epoch=1,
        )
        is False
    )
    assert (
        record_creator_signature(
            world,
            artifact_id=str(artifact.id),
            creator_id=str(scenario.character),
            source_event_id="",
            created_at_epoch=1,
        )
        is False
    )
    created = record_creator_signature(
        world,
        artifact_id=str(artifact.id),
        creator_id=str(scenario.character),
        source_event_id="sig-a",
        created_at_epoch=1,
        circumstance="  carving moon bone  ",
    )
    duplicate = record_creator_signature(
        world,
        artifact_id=str(artifact.id),
        creator_id=str(scenario.character),
        source_event_id="sig-a",
        created_at_epoch=2,
        circumstance="different",
    )

    assert created is True
    assert duplicate is False
    signature = artifact.get_component(CreatorSignatureComponent)
    assert signature.circumstance == "carving moon bone"
    assert artifact.get_relationships(CreatedBy)[0][1] == scenario.character
    assert creator_signature_for_event(world, "missing") is None
    assert (
        record_creator_signature(
            world,
            artifact_id="entity_999",
            creator_id=str(scenario.character),
            source_event_id="sig-missing",
            created_at_epoch=3,
        )
        is False
    )
    updated = record_creator_signature(
        world,
        artifact_id=str(artifact.id),
        creator_id="entity_999",
        source_event_id="sig-b",
        created_at_epoch=4,
    )
    assert updated is True
    assert artifact.get_component(CreatorSignatureComponent).source_event_id == "sig-b"


def test_record_death_consequence_skips_invalid_empty_and_duplicate_sources():
    scenario = build_scenario()
    world = scenario.actor.world

    assert (
        record_death_consequence(
            world,
            character_id="not-an-id",
            cause="a cave-in",
            source_event_id="death-a",
            created_at_epoch=1,
        )
        is None
    )
    assert (
        record_death_consequence(
            world,
            character_id=str(scenario.character),
            cause="a cave-in",
            source_event_id="",
            created_at_epoch=1,
        )
        is None
    )
    created = record_death_consequence(
        world,
        character_id=str(scenario.character),
        cause="  a cave-in  ",
        source_event_id="death-a",
        created_at_epoch=1,
        location_id=str(scenario.room_a),
    )
    duplicate = record_death_consequence(
        world,
        character_id=str(scenario.character),
        cause="different",
        source_event_id="death-a",
        created_at_epoch=2,
    )

    assert created is not None
    assert duplicate is None
    consequence = created.get_component(DeathConsequenceComponent)
    assert consequence.cause == "a cave-in"
    assert consequence.summary == "Juniper died from a cave-in."
    assert created.get_relationships(DeathOf)[0][1] == scenario.character
    assert death_consequence_for_event(world, "missing") is None


def test_apply_deed_reputation_accumulates_tags_and_skips_duplicates():
    scenario = build_scenario()
    world = scenario.actor.world

    assert (
        apply_deed_reputation(
            world,
            actor_id="not-an-id",
            deed_id="deed-a",
            summary="nope",
            tags=("crafted",),
            score=1.0,
        )
        is False
    )
    assert (
        apply_deed_reputation(
            world,
            actor_id=str(scenario.character),
            deed_id="",
            summary="nope",
            tags=("crafted",),
            score=1.0,
        )
        is False
    )
    first = apply_deed_reputation(
        world,
        actor_id=str(scenario.character),
        deed_id="deed-a",
        summary="crafted a camp kit",
        tags=("crafted", "artifact", ""),
        score=0.8,
    )
    duplicate = apply_deed_reputation(
        world,
        actor_id=str(scenario.character),
        deed_id="deed-a",
        summary="crafted a camp kit again",
        tags=("crafted",),
        score=0.8,
    )
    second = apply_deed_reputation(
        world,
        actor_id=str(scenario.character),
        deed_id="deed-b",
        summary="crafted a bridge brace",
        tags=("crafted",),
        score=0.4,
    )

    assert first is True
    assert duplicate is False
    assert second is True
    reputation = world.get_entity(scenario.character).get_component(DeedReputationComponent)
    assert reputation.scores == {"crafted": 1.2, "artifact": 0.8}
    assert reputation.deed_ids == ("deed-a", "deed-b")
    assert deed_reputation_fragments(world, world.get_entity(scenario.character)) == [
        "Deed reputation artifact: 0.8.",
        "Deed reputation crafted: 1.2.",
        "Known deed: crafted a camp kit.",
        "Known deed: crafted a bridge brace.",
    ]


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


def test_history_fragments_can_filter_all_records_as_irrelevant():
    scenario = build_scenario()
    world = scenario.actor.world
    record_world_history(
        world,
        summary="A far tunnel collapsed.",
        source_event_id="far-only",
        event_type="Manual",
        created_at_epoch=1,
        location_id=str(scenario.room_b),
    )

    assert history_fragments(world, world.get_entity(scenario.character)) == []


def test_history_fragments_skip_records_with_other_actors_and_targets():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    other_character = spawn_entity(
        world, [IdentityComponent(name="Bramble", kind="character")]
    )
    far_target = spawn_entity(
        world, [IdentityComponent(name="distant relic", kind="item")]
    )
    # Far record whose only actor/target are someone else and an unreachable item:
    # both relevance loops iterate fully without matching (653->652, 656->655).
    record_world_history(
        world,
        summary="Bramble blessed a distant relic.",
        source_event_id="other-only",
        event_type="Manual",
        created_at_epoch=1,
        location_id=str(scenario.room_b),
        actor_ids=(str(other_character.id),),
        target_ids=(str(far_target.id),),
    )

    assert history_fragments(world, character) == []


def test_mark_fragments_show_reachable_marks_with_limit():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    sign = spawn_entity(world, [IdentityComponent(name="notice board", kind="sign")])
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), sign.id
    )
    far_sign = spawn_entity(world, [IdentityComponent(name="far sign", kind="sign")])
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), far_sign.id
    )
    for index in range(6):
        record_physical_mark(
            world,
            target_id=str(sign.id),
            text=f"line {index}",
            source_event_id=f"mark-{index}",
            created_at_epoch=index,
            author_id=str(scenario.character),
        )
    record_physical_mark(
        world,
        target_id=str(far_sign.id),
        text="too far",
        source_event_id="far-mark",
        created_at_epoch=20,
        author_id=str(scenario.character),
    )

    fragments = mark_fragments(world, character)

    assert len(fragments) == 5
    assert all("notice board bears writing by Juniper" in fragment for fragment in fragments)
    assert not any("too far" in fragment for fragment in fragments)


def test_mark_fragments_use_anonymous_author_without_author_id():
    scenario = build_scenario()
    world = scenario.actor.world
    sign = spawn_entity(world, [IdentityComponent(name="notice board", kind="sign")])
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), sign.id
    )
    record_physical_mark(
        world,
        target_id=str(sign.id),
        text="anonymous line",
        source_event_id="anon-mark",
        created_at_epoch=1,
    )

    assert mark_fragments(world, world.get_entity(scenario.character)) == [
        (
            f"notice board bears writing by someone: anonymous line "
            f"[mark:{marks_on(world, sign.id)[0][0].id} source:anon-mark]"
        )
    ]


def test_creator_fragments_show_reachable_artifacts_with_limit():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    far_artifact = spawn_entity(world, [IdentityComponent(name="far hook", kind="item")])
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), far_artifact.id
    )
    record_creator_signature(
        world,
        artifact_id=str(far_artifact.id),
        creator_id=str(scenario.character),
        source_event_id="far-sig",
        created_at_epoch=20,
        circumstance="crafting far recipe",
    )
    for index in range(6):
        artifact = spawn_entity(
            world, [IdentityComponent(name=f"visible hook {index}", kind="item")]
        )
        world.get_entity(scenario.room_a).add_relationship(
            Contains(mode=ContainmentMode.ROOM_CONTENT), artifact.id
        )
        record_creator_signature(
            world,
            artifact_id=str(artifact.id),
            creator_id=str(scenario.character),
            source_event_id=f"sig-{index}",
            created_at_epoch=index,
            circumstance=f"crafting recipe {index}",
        )

    fragments = creator_fragments(world, character)

    assert len(fragments) == 5
    assert all("was made by Juniper while crafting recipe" in line for line in fragments)
    assert not any("far hook" in line for line in fragments)


def test_creator_fragments_use_anonymous_creator_without_circumstance():
    scenario = build_scenario()
    world = scenario.actor.world
    artifact = spawn_entity(world, [IdentityComponent(name="plain hook", kind="item")])
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), artifact.id
    )
    record_creator_signature(
        world,
        artifact_id=str(artifact.id),
        creator_id="",
        source_event_id="anon-sig",
        created_at_epoch=1,
    )

    assert creator_fragments(world, world.get_entity(scenario.character)) == [
        f"plain hook was made by someone. [signature:{artifact.id} source:anon-sig]"
    ]


def test_death_consequence_fragments_show_relevant_deaths_with_limit():
    scenario = build_scenario()
    world = scenario.actor.world
    for index in range(6):
        record_death_consequence(
            world,
            character_id=str(scenario.character),
            cause=f"cause {index}",
            source_event_id=f"death-{index}",
            created_at_epoch=index,
            location_id=str(scenario.room_a),
        )
    far_character = spawn_entity(
        world, [IdentityComponent(name="Farley", kind="character")]
    )
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), far_character.id
    )
    record_death_consequence(
        world,
        character_id=str(far_character.id),
        cause="far trouble",
        source_event_id="far-death",
        created_at_epoch=20,
        location_id=str(scenario.room_b),
    )

    fragments = death_consequence_fragments(world, world.get_entity(scenario.character))

    assert len(fragments) == 5
    assert fragments[0].startswith("Death consequence: Juniper died from cause 5.")
    assert not any("Farley" in fragment for fragment in fragments)


async def test_write_event_with_missing_target_records_history_without_mark():
    scenario = build_scenario()
    apply_plugins(_plugins(), scenario.actor)

    await scenario.actor.bus.publish(
        PhysicalWriteEvent(
            **event_base(
                5,
                actor_id=str(scenario.character),
                target_ids=("entity_999",),
                item_id="entity_999",
                text="lost text",
            )
        )
    )

    assert marks_on(scenario.actor.world, scenario.room_a) == []
    assert world_history_records(scenario.actor.world)[0][1].summary == (
        'Juniper wrote on someone: "lost text"'
    )
