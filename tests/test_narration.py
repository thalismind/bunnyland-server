from __future__ import annotations

import asyncio

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
from bunnyland.narration import (
    DEFAULT_VOICE,
    NarrationProjection,
    NarrationVoiceRegistry,
    SceneEvent,
    SceneInput,
    check_grounding,
    evaluate_narration_quality,
    render_scene,
)
from bunnyland.narration.projection import (
    _event_rooms,
    _event_salience,
    _event_summary,
    _event_visible_to,
    _name,
    _render_perceived_room_summary,
    _room_title,
)


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


def test_narration_salience_retains_important_events_and_compresses_routine_noise(
    scenario,
):
    world = scenario.actor.world
    routine_events = tuple(
        RoomLookedEvent(
            **event_base(
                4,
                visibility=EventVisibility.PRIVATE,
                actor_id=str(scenario.character),
                room_id=str(scenario.room_a),
                target_ids=(str(scenario.room_a),),
                room_title="Mosslit Burrow",
                summary=f"look {index}",
            )
        )
        for index in range(4)
    )
    important = SpeechSaidEvent(
        **event_base(
            4,
            visibility=EventVisibility.ROOM,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_a),
            text="The bridge is falling.",
        )
    )
    projection = NarrationProjection(world, max_scene_events=2)

    scene = projection.assemble(world.get_entity(scenario.character), (*routine_events, important))
    retained_ids = {event.event_id for event in scene.events}

    assert important.event_id in retained_ids
    assert len(scene.events) == 2
    assert len(scene.compressed_event_ids) == 3
    assert set(scene.compressed_event_ids).isdisjoint(retained_ids)
    assert scene.compression_notes == ("3 routine events compressed.",)
    assert any(fact.category == "compression" for fact in scene.facts)


def test_narration_voice_controls_style_without_changing_facts(scenario):
    world = scenario.actor.world
    event = SpeechSaidEvent(
        **event_base(
            5,
            visibility=EventVisibility.ROOM,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_a),
            text="The kettle is singing.",
        )
    )
    registry = NarrationVoiceRegistry()
    plain = NarrationProjection(world, voice=registry.get("plain"))
    cozy = NarrationProjection(world, voice=registry.for_tags(("warm",)))

    plain_scene = plain.assemble(world.get_entity(scenario.character), (event,))
    cozy_scene = cozy.assemble(world.get_entity(scenario.character), (event,))
    plain_facts = tuple(
        (fact.category, fact.text, fact.entity_id, fact.event_id)
        for fact in plain_scene.facts
    )
    cozy_facts = tuple(
        (fact.category, fact.text, fact.entity_id, fact.event_id)
        for fact in cozy_scene.facts
    )

    assert plain_facts == cozy_facts
    assert plain_scene.voice.name == "plain"
    assert cozy_scene.voice.name == "cozy"
    assert render_scene(plain_scene) != render_scene(cozy_scene)
    assert 'You said, "The kettle is singing."' in render_scene(cozy_scene)


def test_narration_quality_harness_reports_grounding_and_style_issues(scenario):
    world = scenario.actor.world
    hazel = spawn_entity(
        world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    pebble = spawn_entity(world, [IdentityComponent(name="smooth pebble", kind="item")])
    hidden = spawn_entity(
        world,
        [
            IdentityComponent(name="buried clue", kind="item"),
            StealthComponent(visibility_level=0.0, hidden_threshold=0.1, hiding=True),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hazel.id
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), pebble.id
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hidden.id
    )
    event = SpeechSaidEvent(
        **event_base(
            8,
            visibility=EventVisibility.ROOM,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_a),
            text="The bridge is falling.",
        )
    )
    projection = NarrationProjection(
        world,
        voice=NarrationVoiceRegistry().get("cozy"),
    )
    scene = projection.assemble(world.get_entity(scenario.character), (event,))

    issues = evaluate_narration_quality(
        scene,
        "Mosslit Burrow: You are alone. Nothing is visible. There are no exits. "
        "The buried clue shines.",
    )
    kinds = {issue.kind for issue in issues}

    assert "hidden-state-leak" in kinds
    assert "contradiction" in kinds
    assert "missing-high-salience-event" in kinds
    assert "style-drift" in kinds


def test_narration_quality_harness_accepts_grounded_voice_render(scenario):
    event = SpeechSaidEvent(
        **event_base(
            9,
            visibility=EventVisibility.ROOM,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_a),
            text="The kettle is singing.",
        )
    )
    projection = NarrationProjection(
        scenario.actor.world,
        voice=NarrationVoiceRegistry().get("cozy"),
    )
    scene = projection.assemble(
        scenario.actor.world.get_entity(scenario.character),
        (event,),
    )
    text = render_scene(scene)

    assert evaluate_narration_quality(scene, text) == ()


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


def test_narration_sync_mode_rejects_awaitable_renderer(scenario):
    class AwaitableText:
        def __await__(self):
            if False:
                yield None
            return "late"

    projection = NarrationProjection(
        scenario.actor.world,
        renderer=lambda _scene: AwaitableText(),
    )
    event = SpeechSaidEvent(
        **event_base(
            6,
            visibility=EventVisibility.ROOM,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_a),
            text="Hello.",
        )
    )
    projection._on_event(event)

    projection.after_tick(scenario.actor)

    assert projection.errors == ["async narration renderer requires non_blocking=True"]
    assert projection.latest(str(scenario.character)) is None


def test_narration_non_blocking_without_running_loop_uses_fallback_and_capacity(
    scenario,
):
    projection = NarrationProjection(
        scenario.actor.world,
        renderer=lambda _scene: "unavailable",
        non_blocking=True,
        capacity=1,
    )
    event = SpeechSaidEvent(
        **event_base(
            7,
            visibility=EventVisibility.ROOM,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_a),
            text="Hello.",
        )
    )
    scene = projection.assemble(scenario.actor.world.get_entity(scenario.character), (event,))

    projection._queue_delivery(str(scenario.character), 7, scene)
    projection._queue_delivery(str(scenario.character), 8, scene)

    narrations = projection.narrations(str(scenario.character))
    assert len(narrations) == 1
    assert narrations[0].epoch == 8
    assert 'You said, "Hello."' in narrations[0].text


def test_narration_voice_registry_falls_back_when_no_tag_matches():
    registry = NarrationVoiceRegistry()
    assert registry.for_tags(("unknown-style",)) is DEFAULT_VOICE


def test_name_and_room_title_fall_back_for_unknown_entities(scenario):
    world = scenario.actor.world
    # A spawned entity with no IdentityComponent / RoomComponent resolves to defaults.
    bare = spawn_entity(world, [CharacterComponent()])

    assert _name(world, None) == "someone"
    assert _name(world, "entity_99999") == "someone"
    assert _name(world, str(bare.id)) == "someone"
    assert _room_title(world, None) == "somewhere"
    assert _room_title(world, "entity_99999") == "somewhere"
    assert _room_title(world, str(bare.id)) == "somewhere"


def test_event_rooms_resolves_actor_room_and_handles_missing_locations(scenario):
    world = scenario.actor.world
    # Actor in a room but the event carries no room_id: room is taken from the actor.
    via_actor = CommandSubmittedEvent(
        **event_base(
            1,
            actor_id=str(scenario.character),
            command_id="cmd",
            command_type="wait",
        )
    )
    assert _event_rooms(world, via_actor) == (str(scenario.room_a),)

    # Actor exists but is in no room: nothing resolves (178->180).
    roomless = spawn_entity(world, [CharacterComponent()])
    no_room = CommandSubmittedEvent(
        **event_base(
            1,
            actor_id=str(roomless.id),
            command_id="cmd2",
            command_type="wait",
        )
    )
    assert _event_rooms(world, no_room) == ()

    # Actor id does not resolve to an entity (176->180).
    missing_actor = CommandSubmittedEvent(
        **event_base(
            1,
            actor_id="entity_99999",
            command_id="cmd3",
            command_type="wait",
        )
    )
    assert _event_rooms(world, missing_actor) == ()

    # No room_id and no actor_id at all (174->180).
    anonymous = CommandSubmittedEvent(
        **event_base(1, actor_id=None, command_id="cmd4", command_type="wait")
    )
    assert _event_rooms(world, anonymous) == ()


def test_event_salience_defaults_to_zero_for_unscored_events(scenario):
    event = CommandSubmittedEvent(
        **event_base(1, actor_id=str(scenario.character), command_id="c", command_type="wait")
    )
    assert _event_salience(event) == 0


def test_event_summary_describes_other_actors_movement_drop_and_third_party_tell(scenario):
    world = scenario.actor.world
    viewer = world.get_entity(scenario.character)
    hazel = spawn_entity(
        world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hazel.id
    )
    clover = spawn_entity(
        world,
        [IdentityComponent(name="Clover", kind="character"), CharacterComponent()],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), clover.id
    )
    pebble = spawn_entity(world, [IdentityComponent(name="smooth pebble", kind="item")])

    # Another actor leaving the viewer's room (227-230, the "left" branch).
    left = ActorMovedEvent(
        **event_base(
            1,
            actor_id=str(hazel.id),
            room_id=str(scenario.room_a),
            from_room_id=str(scenario.room_a),
            to_room_id=str(scenario.room_b),
            direction="north",
        )
    )
    assert _event_summary(world, viewer, left) == "Hazel left north."

    # Another actor arriving from elsewhere (231, the "arrived" branch).
    arrived = ActorMovedEvent(
        **event_base(
            1,
            actor_id=str(hazel.id),
            room_id=str(scenario.room_a),
            from_room_id=str(scenario.room_b),
            to_room_id=str(scenario.room_a),
            direction="south",
        )
    )
    assert _event_summary(world, viewer, arrived) == "Hazel arrived."

    # A tell between two other characters, overheard by the viewer (240).
    told = SpeechToldEvent(
        **event_base(
            1,
            visibility=EventVisibility.DIRECTED,
            actor_id=str(hazel.id),
            room_id=str(scenario.room_a),
            target_ids=(str(clover.id),),
            overhearer_ids=(str(scenario.character),),
            text="Meet me later.",
        )
    )
    assert _event_summary(world, viewer, told) == 'Hazel told Clover, "Meet me later."'

    # An item drop by another actor (244).
    dropped = ItemDroppedEvent(
        **event_base(
            1,
            actor_id=str(hazel.id),
            room_id=str(scenario.room_a),
            target_ids=(str(pebble.id),),
            item_id=str(pebble.id),
            room_id_dropped=str(scenario.room_a),
        )
    )
    assert _event_summary(world, viewer, dropped) == "Hazel dropped smooth pebble."


def test_render_perceived_room_summary_emits_bands_and_skips_empty_sections():
    with_bands = _render_perceived_room_summary(
        title="Mosslit Burrow",
        bands={"light": "dim", "temperature": "warm"},
        visible_characters=("Hazel",),
        visible_objects=(),
        exits=("north",),
    )
    assert "It is dim, warm." in with_bands
    assert "Here: Hazel." in with_bands
    assert "Exits: north." in with_bands
    assert "You see:" not in with_bands

    # No bands and no exits: those sections are skipped (371-372 not taken, 377->379).
    bare = _render_perceived_room_summary(
        title="Mosslit Burrow",
        bands={},
        visible_characters=(),
        visible_objects=("a pebble",),
        exits=(),
    )
    assert bare == "Mosslit Burrow\nYou see: a pebble."


def test_check_grounding_passes_when_scene_has_no_events():
    scene = SceneInput(
        viewer_id="entity_1",
        room_id="entity_2",
        location_title="Mosslit Burrow",
        room_summary="",
    )
    # No events and no hidden names: grounding has nothing to flag (280->290).
    assert check_grounding(scene, "anything at all") == ()


def test_render_scene_renders_event_summaries_without_clusters():
    scene = SceneInput(
        viewer_id="entity_1",
        room_id="entity_2",
        location_title="Mosslit Burrow",
        room_summary="",
        events=(
            SceneEvent(
                event_id="e1",
                event_type="SpeechSaidEvent",
                summary='You said, "Hi."',
                salience=80,
            ),
        ),
    )
    # clusters is empty, so the elif scene.events branch renders (350).
    assert render_scene(scene) == 'Mosslit Burrow: You said, "Hi."'


def test_compress_visible_events_returns_input_when_only_high_salience_overflow(scenario):
    world = scenario.actor.world
    # Three high-salience events over a budget of 2: there is no routine event to drop,
    # so the compressed bucket is empty and the full tuple is returned uncompressed (451).
    events = tuple(
        SpeechSaidEvent(
            **event_base(
                1,
                visibility=EventVisibility.ROOM,
                actor_id=str(scenario.character),
                room_id=str(scenario.room_a),
                text=f"line {index}",
            )
        )
        for index in range(3)
    )
    projection = NarrationProjection(world, max_scene_events=2)
    scene = projection.assemble(world.get_entity(scenario.character), events)
    assert scene.compressed_event_ids == ()
    assert scene.compression_notes == ()
    assert len(scene.events) == 3


def test_event_visible_to_includes_acting_viewer_outside_event_room(scenario):
    world = scenario.actor.world
    viewer = world.get_entity(scenario.character)  # located in room_a
    # A ROOM-visibility event tagged to room_b: the viewer is not in that room, but is the
    # actor, so it is still visible to them (line 216).
    event = SpeechSaidEvent(
        **event_base(
            1,
            visibility=EventVisibility.ROOM,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_b),
            text="An aside from afar.",
        )
    )
    assert _event_visible_to(world, viewer, event) is True


def test_after_tick_skips_viewers_with_no_visible_events(scenario):
    world = scenario.actor.world
    # A second character in a different room cannot see Juniper's room-scoped speech, so
    # after_tick skips them via the `continue` branch (line 617).
    rowan = spawn_entity(
        world,
        [IdentityComponent(name="Rowan", kind="character"), CharacterComponent()],
    )
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), rowan.id
    )
    projection = NarrationProjection(world)
    projection._on_event(
        SpeechSaidEvent(
            **event_base(
                1,
                visibility=EventVisibility.ROOM,
                actor_id=str(scenario.character),
                room_id=str(scenario.room_a),
                text="Only here.",
            )
        )
    )

    projection.after_tick(scenario.actor)

    assert projection.latest(str(scenario.character)) is not None
    assert projection.latest(str(rowan.id)) is None


def test_invisible_names_skips_entities_without_a_name(scenario):
    world = scenario.actor.world
    # An out-of-room entity carrying an IdentityComponent with an empty name is skipped
    # by the `if name:` guard (687->683).
    spawn_entity(world, [IdentityComponent(name="", kind="item")])
    named = spawn_entity(world, [IdentityComponent(name="Distant Bell", kind="item")])
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), named.id
    )

    projection = NarrationProjection(world)
    scene = projection.assemble(world.get_entity(scenario.character), ())

    assert "Distant Bell" in scene.invisible_names
    assert "" not in scene.invisible_names


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


async def test_narration_non_blocking_delivery_falls_back_on_timeout(scenario):
    scenario.actor.register_handler(SayHandler())
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_renderer(_scene):
        started.set()
        await release.wait()
        return "late text"

    projection = NarrationProjection(
        scenario.actor.world,
        renderer=slow_renderer,
        non_blocking=True,
        render_timeout_seconds=0.01,
    ).attach(scenario.actor)

    await scenario.actor.submit(_command(scenario, "say", {"text": "Hello."}))
    await scenario.actor.tick(0.0)

    assert projection.latest(str(scenario.character)) is None
    assert projection.pending_deliveries() == 1
    await asyncio.wait_for(started.wait(), timeout=1.0)
    await asyncio.sleep(0.05)
    narration = projection.latest(str(scenario.character))

    assert narration is not None
    assert 'You said, "Hello."' in narration.text
    assert projection.pending_deliveries() == 0
    assert projection.errors == ["narration render timed out"]
    release.set()


async def test_narration_non_blocking_delivery_uses_async_renderer(scenario):
    scenario.actor.register_handler(SayHandler())

    async def renderer(scene):
        return f"rendered {scene.location_title}"

    projection = NarrationProjection(
        scenario.actor.world,
        renderer=renderer,
        non_blocking=True,
    ).attach(scenario.actor)

    await scenario.actor.submit(_command(scenario, "say", {"text": "Hello."}))
    await scenario.actor.tick(0.0)
    await asyncio.sleep(0)

    narration = projection.latest(str(scenario.character))
    assert narration is not None
    assert narration.text == "rendered Mosslit Burrow"
    assert narration.source_event_ids


async def test_narration_non_blocking_delivery_accepts_sync_renderer(scenario):
    scenario.actor.register_handler(SayHandler())
    projection = NarrationProjection(
        scenario.actor.world,
        renderer=lambda scene: f"sync rendered {scene.location_title}",
        non_blocking=True,
    ).attach(scenario.actor)

    await scenario.actor.submit(_command(scenario, "say", {"text": "Hello."}))
    await scenario.actor.tick(0.0)
    await asyncio.sleep(0)

    narration = projection.latest(str(scenario.character))
    assert narration is not None
    assert narration.text == "sync rendered Mosslit Burrow"


async def test_narration_non_blocking_delivery_falls_back_on_renderer_error(scenario):
    scenario.actor.register_handler(SayHandler())

    def broken(_scene):
        raise RuntimeError("renderer down")

    projection = NarrationProjection(
        scenario.actor.world,
        renderer=broken,
        non_blocking=True,
    ).attach(scenario.actor)

    await scenario.actor.submit(_command(scenario, "say", {"text": "Hello."}))
    await scenario.actor.tick(0.0)
    await asyncio.sleep(0)

    narration = projection.latest(str(scenario.character))
    assert narration is not None
    assert 'You said, "Hello."' in narration.text
    assert projection.errors == ["renderer down"]


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
