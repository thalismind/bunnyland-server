from __future__ import annotations

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    MoveHandler,
    SayHandler,
    StealthComponent,
    build_submitted_command,
    container_of,
    spawn_entity,
)
from bunnyland.core.events import (
    ActorMovedEvent,
    CharacterDiedEvent,
    CharacterDownedEvent,
    CommandExecutedEvent,
    CommandQueuedEvent,
    CommandSubmittedEvent,
    EntityInspectedEvent,
    EventVisibility,
    ItemDroppedEvent,
    ItemPutEvent,
    ItemTakenEvent,
    RoomLookedEvent,
    SpeechSaidEvent,
    SpeechToldEvent,
    event_base,
)
from bunnyland.narration import NarrationProjection, SceneInput, check_grounding, render_scene


def _command(scenario, command_type: str, payload=None):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(),
        lane=Lane.WORLD,
        payload=payload or {},
    )


def test_narration_assembles_visible_pov_and_omits_hidden_or_remote_state(scenario):
    world = scenario.actor.world
    hazel = spawn_entity(
        world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hazel.id
    )
    rowan = spawn_entity(
        world,
        [IdentityComponent(name="Rowan", kind="character"), CharacterComponent()],
    )
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), rowan.id
    )
    hidden = spawn_entity(
        world,
        [
            IdentityComponent(name="silver secret", kind="item"),
            StealthComponent(visibility_level=0.0, hidden_threshold=0.1, hiding=True),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hidden.id
    )
    remote_item = spawn_entity(world, [IdentityComponent(name="distant bell", kind="item")])
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), remote_item.id
    )
    projection = NarrationProjection(world)
    visible_event = SpeechSaidEvent(
        **event_base(
            1,
            visibility=EventVisibility.ROOM,
            actor_id=str(hazel.id),
            room_id=str(scenario.room_a),
            text="Juniper, watch the moss.",
        )
    )
    remote_event = ItemDroppedEvent(
        **event_base(
            1,
            actor_id=str(rowan.id),
            room_id=str(scenario.room_b),
            target_ids=(str(remote_item.id),),
            item_id=str(remote_item.id),
            room_id_dropped=str(scenario.room_b),
        )
    )

    scene = projection.assemble(
        world.get_entity(scenario.character), (visible_event, remote_event)
    )
    text = projection.renderer(scene)

    assert scene.visible_characters == ("Hazel",)
    assert "silver secret" not in scene.visible_objects
    assert [event.summary for event in scene.events] == [
        'Hazel said, "Juniper, watch the moss."'
    ]
    assert remote_event.event_id in scene.omitted_event_ids
    assert "distant bell" not in text
    assert "silver secret" not in text
    assert check_grounding(scene, text) == ()


def test_narration_renders_supported_event_shapes_and_grounding_issues(scenario):
    world = scenario.actor.world
    hazel = spawn_entity(
        world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hazel.id
    )
    basket = spawn_entity(world, [IdentityComponent(name="woven basket", kind="container")])
    pebble = spawn_entity(world, [IdentityComponent(name="smooth pebble", kind="item")])
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), basket.id
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), pebble.id
    )
    hidden = spawn_entity(
        world,
        [
            IdentityComponent(name="silver secret", kind="item"),
            StealthComponent(visibility_level=0.0, hidden_threshold=0.1, hiding=True),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hidden.id
    )
    projection = NarrationProjection(world)
    events = (
        SpeechToldEvent(
            **event_base(
                1,
                visibility=EventVisibility.DIRECTED,
                actor_id=str(scenario.character),
                room_id=str(scenario.room_a),
                target_ids=(str(hazel.id),),
                text="Keep this quiet.",
            )
        ),
        ItemTakenEvent(
            **event_base(
                1,
                actor_id=str(hazel.id),
                room_id=str(scenario.room_a),
                target_ids=(str(pebble.id),),
                item_id=str(pebble.id),
                from_container_id=str(scenario.room_a),
            )
        ),
        ItemPutEvent(
            **event_base(
                1,
                actor_id=str(hazel.id),
                room_id=str(scenario.room_a),
                target_ids=(str(pebble.id),),
                item_id=str(pebble.id),
                to_container_id=str(basket.id),
            )
        ),
        CharacterDownedEvent(
            **event_base(1, actor_id=str(hazel.id), room_id=str(scenario.room_a), cause="trip")
        ),
        CharacterDiedEvent(
            **event_base(1, actor_id=str(hazel.id), room_id=str(scenario.room_a), cause="test")
        ),
        RoomLookedEvent(
            **event_base(
                1,
                visibility=EventVisibility.PRIVATE,
                actor_id=str(scenario.character),
                room_id=str(scenario.room_a),
                target_ids=(str(scenario.room_a),),
                room_title="Mosslit Burrow",
                summary="Mosslit Burrow",
            )
        ),
        EntityInspectedEvent(
            **event_base(
                1,
                visibility=EventVisibility.PRIVATE,
                actor_id=str(scenario.character),
                target_ids=(str(basket.id),),
                entity_id=str(basket.id),
                name="woven basket",
                kind="container",
            )
        ),
        CommandSubmittedEvent(
            **event_base(
                1,
                actor_id=str(scenario.character),
                command_id="cmd",
                command_type="wait",
            )
        ),
    )

    juniper_scene = projection.assemble(world.get_entity(scenario.character), events)
    hazel_scene = projection.assemble(world.get_entity(hazel.id), events)
    juniper_summaries = {event.summary for event in juniper_scene.events}
    hazel_summaries = {event.summary for event in hazel_scene.events}

    assert 'You told Hazel, "Keep this quiet."' in juniper_summaries
    assert "Hazel picked up smooth pebble." in juniper_summaries
    assert "Hazel put smooth pebble away." in juniper_summaries
    assert "Hazel collapsed." in juniper_summaries
    assert "Hazel died." in juniper_summaries
    assert "You looked around." in juniper_summaries
    assert "You inspected woven basket." in juniper_summaries
    assert events[-1].event_id in juniper_scene.omitted_event_ids
    assert 'Juniper told you, "Keep this quiet."' in hazel_summaries

    hidden_issue = check_grounding(juniper_scene, "The silver secret is here.")
    assert hidden_issue[0].kind == "hidden-state-leak"
    empty = SceneInput(
        viewer_id=str(scenario.character),
        room_id=str(scenario.room_a),
        location_title="Mosslit Burrow",
        room_summary="",
    )
    assert render_scene(empty) == "Mosslit Burrow: Nothing notable changes."


def test_narration_programmatic_facts_are_viewer_scoped_for_same_tick(scenario):
    world = scenario.actor.world
    hazel = spawn_entity(
        world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hazel.id
    )
    lantern = spawn_entity(world, [IdentityComponent(name="moss lantern", kind="item")])
    map_item = spawn_entity(world, [IdentityComponent(name="tunnel map", kind="item")])
    hidden = spawn_entity(
        world,
        [
            IdentityComponent(name="buried clue", kind="item"),
            StealthComponent(visibility_level=0.0, hidden_threshold=0.1, hiding=True),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), lantern.id
    )
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), map_item.id
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hidden.id
    )
    events = (
        SpeechSaidEvent(
            **event_base(
                2,
                visibility=EventVisibility.ROOM,
                actor_id=str(scenario.character),
                room_id=str(scenario.room_a),
                text="I can see the lantern.",
            )
        ),
        SpeechSaidEvent(
            **event_base(
                2,
                visibility=EventVisibility.ROOM,
                actor_id=str(hazel.id),
                room_id=str(scenario.room_b),
                text="I can see the map.",
            )
        ),
    )
    projection = NarrationProjection(world)

    juniper_scene = projection.assemble(world.get_entity(scenario.character), events)
    hazel_scene = projection.assemble(world.get_entity(hazel.id), events)
    juniper_facts = {fact.text for fact in juniper_scene.facts}
    hazel_facts = {fact.text for fact in hazel_scene.facts}

    assert "Location: Mosslit Burrow." in juniper_facts
    assert "Visible object: moss lantern." in juniper_facts
    assert 'You said, "I can see the lantern."' in juniper_facts
    assert "Location: North Tunnel." in hazel_facts
    assert "Visible object: tunnel map." in hazel_facts
    assert 'You said, "I can see the map."' in hazel_facts
    assert not any("tunnel map" in fact for fact in juniper_facts)
    assert not any("moss lantern" in fact for fact in hazel_facts)
    assert not any("buried clue" in fact for fact in juniper_facts | hazel_facts)
    assert juniper_facts != hazel_facts


def test_narration_clusters_visible_events_and_omits_command_lifecycle(scenario):
    world = scenario.actor.world
    pebble = spawn_entity(world, [IdentityComponent(name="smooth pebble", kind="item")])
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), pebble.id
    )
    lifecycle_events = (
        CommandSubmittedEvent(
            **event_base(
                3,
                actor_id=str(scenario.character),
                command_id="cmd-move",
                command_type="move",
            )
        ),
        CommandQueuedEvent(
            **event_base(
                3,
                actor_id=str(scenario.character),
                command_id="cmd-move",
                command_type="move",
                lane="world",
            )
        ),
        CommandExecutedEvent(
            **event_base(
                3,
                actor_id=str(scenario.character),
                command_id="cmd-move",
                command_type="move",
            )
        ),
    )
    visible_events = (
        SpeechSaidEvent(
            **event_base(
                3,
                visibility=EventVisibility.ROOM,
                actor_id=str(scenario.character),
                room_id=str(scenario.room_a),
                text="I found a pebble.",
            )
        ),
        ItemTakenEvent(
            **event_base(
                3,
                actor_id=str(scenario.character),
                room_id=str(scenario.room_a),
                target_ids=(str(pebble.id),),
                item_id=str(pebble.id),
                from_container_id=str(scenario.room_a),
            )
        ),
    )
    move_event = ActorMovedEvent(
        **event_base(
            3,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_b),
            from_room_id=str(scenario.room_a),
            to_room_id=str(scenario.room_b),
            direction="north",
        )
    )
    projection = NarrationProjection(world)

    scene = projection.assemble(
        world.get_entity(scenario.character),
        (*lifecycle_events, *visible_events, move_event),
    )

    assert set(scene.omitted_event_ids) >= {event.event_id for event in lifecycle_events}
    assert {event.event_id for event in scene.events} == {
        event.event_id for event in (*visible_events, move_event)
    }
    same_room_cluster = next(
        cluster for cluster in scene.clusters if visible_events[0].event_id in cluster.event_ids
    )
    assert same_room_cluster.event_ids == tuple(event.event_id for event in visible_events)
    assert same_room_cluster.summaries == (
        'You said, "I found a pebble."',
        "You picked up smooth pebble.",
    )


def test_narration_handles_no_pending_events_and_orphan_viewer(scenario):
    world = scenario.actor.world
    projection = NarrationProjection(world)
    orphan = spawn_entity(
        world,
        [IdentityComponent(name="Orphan", kind="character"), CharacterComponent()],
    )

    projection.after_tick(scenario.actor)
    scene = projection.assemble(world.get_entity(orphan.id), ())

    assert projection.latest(str(scenario.character)) is None
    assert scene.room_id is None
    assert scene.location_title == "nowhere"


async def test_narration_after_tick_records_presentation_without_mutating_world(scenario):
    scenario.actor.register_handler(MoveHandler())
    projection = NarrationProjection(scenario.actor.world).attach(scenario.actor)
    before_room = scenario.character_room()

    await scenario.actor.submit(_command(scenario, "move", {"direction": "north"}))
    await scenario.actor.tick(0.0)

    narration = projection.latest(str(scenario.character))
    assert before_room == scenario.room_a
    assert container_of(scenario.actor.world.get_entity(scenario.character)) == scenario.room_b
    assert narration is not None
    assert "You moved north to North Tunnel." in narration.text
    assert narration.source_event_ids
    assert narration.scene.room_id == str(scenario.room_b)


def test_narration_renderer_failure_is_isolated_from_world_state(scenario):
    def broken(_scene):
        raise RuntimeError("renderer down")

    projection = NarrationProjection(scenario.actor.world, renderer=broken).attach(scenario.actor)
    event = SpeechSaidEvent(
        **event_base(
            1,
            visibility=EventVisibility.ROOM,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_a),
            text="hello",
        )
    )
    projection._on_event(event)

    projection.after_tick(scenario.actor)

    assert projection.errors == ["renderer down"]
    assert projection.latest(str(scenario.character)) is None
    assert scenario.character_room() == scenario.room_a


async def test_narration_e2e_uses_command_events_and_current_projection(scenario):
    scenario.actor.register_handler(SayHandler())
    projection = NarrationProjection(scenario.actor.world).attach(scenario.actor)

    await scenario.actor.submit(_command(scenario, "say", {"text": "The moss is bright."}))
    await scenario.actor.tick(0.0)

    narration = projection.latest(str(scenario.character))
    assert narration is not None
    assert 'You said, "The moss is bright."' in narration.text
    assert narration.scene.location_title == "Mosslit Burrow"
    assert narration.scene.exits == ("north",)
