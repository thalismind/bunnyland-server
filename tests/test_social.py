"""Tests for social bonds: speech grows relationships, surfaced in the prompt (spec 11.15)."""

from __future__ import annotations

from datetime import UTC, datetime

from conftest import build_scenario, execute_handler

from bunnyland.core import (
    AffectComponent,
    AffectVector,
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    SayHandler,
    build_submitted_command,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.events import ConversationLineEvent, EventVisibility, SpeechToldEvent
from bunnyland.core.handlers import HandlerContext
from bunnyland.foundation.meters.mechanics import Meter
from bunnyland.foundation.needs.mechanics import SocialNeedComponent
from bunnyland.foundation.social.mechanics import (
    GossipClaimComponent,
    GossipReactor,
    KnowsGossip,
    ObligationComponent,
    ObligationCreditor,
    ObligationDebtor,
    ObligationReactor,
    ObligationResolvedEvent,
    RelationshipReactor,
    ResolveObligationHandler,
    SocialBond,
    adjust_bond,
    bond_between,
    create_gossip_claim,
    create_obligation,
    gossip_fragments,
    install_social,
    interpret_speech_for_listener,
    known_gossip,
    learn_gossip,
    obligation_for_source,
    obligation_fragments,
    obligations_for,
    relationship_fragments,
)
from bunnyland.foundation.social.queries import SOCIAL_PERSPECTIVE_QUERIES
from bunnyland.persistence import WorldMeta, load_world, save_world
from bunnyland.plugins import PluginRegistry, bunnyland_plugins
from bunnyland.prompts import ComponentPromptContext, PromptPerspective

HOUR = 3600.0


def test_social_perspective_questions_are_typed_claim_scoped_graph_results():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    world.get_entity(scenario.character).add_relationship(
        SocialBond(affinity=0.4, trust=0.7, familiarity=0.8), hazel
    )
    obligation = create_obligation(
        world,
        kind="promise",
        text="Bring the lantern",
        debtor_id=scenario.character,
        creditor_id=hazel,
        due_epoch=42,
    )
    for definition in SOCIAL_PERSPECTIVE_QUERIES:
        scenario.actor.perspective_queries.register(definition, owner="bunnyland.social")

    connections = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "social_connections",
        {},
        actor_id=str(scenario.character),
    )
    obligations = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "open_obligations",
        {},
        actor_id=str(scenario.character),
    )

    assert connections.owner == "bunnyland.social"
    assert connections.visibility == "claim"
    assert connections.result == [
        {
            "character": {"id": str(hazel), "name": "Hazel", "kind": "character"},
            "bond": {
                "affinity": 0.4,
                "trust": 0.7,
                "fear": 0.0,
                "resentment": 0.0,
                "familiarity": 0.8,
            },
        }
    ]
    assert obligations.result == [
        {
            "obligation": {
                "id": str(obligation.id),
                "name": "Promise from Juniper to Hazel",
                "kind": "obligation",
            },
            "role": "debtor",
            "counterparty": {"id": str(hazel), "name": "Hazel", "kind": "character"},
            "debtor": {
                "id": str(scenario.character),
                "name": "Juniper",
                "kind": "character",
            },
            "creditor": {"id": str(hazel), "name": "Hazel", "kind": "character"},
            "text": "Bring the lantern",
            "kind": "promise",
            "due_epoch": 42,
        }
    ]
    assert "components" not in str(connections.result)
    assert "relationships" not in str(obligations.result)


def _scenario_with_listener():
    scenario = build_scenario()
    scenario.actor.register_handler(SayHandler())
    install_social(scenario.actor)
    hazel = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hazel.id
    )
    return scenario, hazel.id


def _say(scenario, text, intent):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="say",
        cost=CommandCost(action=1, focus=1),
        lane=Lane.WORLD,
        payload={"text": text, "intent": intent},
    )


async def test_saying_builds_familiarity_both_ways():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    juniper = scenario.character

    await scenario.actor.submit(_say(scenario, "Hello there.", "neutral"))
    await scenario.actor.tick(HOUR)

    assert bond_between(world, juniper, hazel).familiarity > 0
    assert bond_between(world, hazel, juniper).familiarity > 0


async def test_speech_satisfies_social_need_for_speaker_and_listener():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    speaker = world.get_entity(scenario.character)
    listener = world.get_entity(hazel)
    speaker.add_component(SocialNeedComponent(meter=Meter(value=50.0)))
    listener.add_component(SocialNeedComponent(meter=Meter(value=50.0)))

    await scenario.actor.submit(_say(scenario, "Hello there.", "neutral"))
    await scenario.actor.tick(HOUR)

    assert speaker.get_component(SocialNeedComponent).meter.value < 50.0
    assert listener.get_component(SocialNeedComponent).meter.value < 50.0


async def test_praise_warms_the_bond_and_threat_frightens_the_listener():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    juniper = scenario.character

    await scenario.actor.submit(_say(scenario, "You are wonderful.", "praise"))
    await scenario.actor.tick(HOUR)
    assert bond_between(world, juniper, hazel).affinity > 0
    assert bond_between(world, hazel, juniper).affinity > 0

    await scenario.actor.submit(_say(scenario, "I will get you.", "threat"))
    await scenario.actor.tick(HOUR)
    # The listener now fears the speaker.
    assert bond_between(world, hazel, juniper).fear > 0


async def test_speech_interpretation_depends_on_listener_mood_and_relationship():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    juniper = scenario.character
    clover = spawn_entity(
        world,
        [
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(),
            AffectComponent(current=AffectVector(anger=10.0), labels=("angry",)),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), clover.id
    )
    adjust_bond(world, clover.id, juniper, {"resentment": 0.6})

    await scenario.actor.submit(_say(scenario, "That was excellent work.", "praise"))
    await scenario.actor.tick(HOUR)

    warm = bond_between(world, hazel, juniper)
    hostile = bond_between(world, clover.id, juniper)
    assert warm.affinity > 0
    assert hostile.resentment > 0.6
    assert hostile.affinity < 0


def test_interpret_speech_can_soften_a_trusted_threat():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    adjust_bond(world, hazel, scenario.character, {"trust": 0.6})

    interpretation = interpret_speech_for_listener(
        world,
        scenario.character,
        hazel,
        "threat",
    )

    assert interpretation.base_interpretation == "threat"
    assert interpretation.final_interpretation == "joke"
    assert interpretation.relationship_tags == ("trusting",)


def test_interpret_speech_handles_missing_listener_and_suspicious_apology():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    wary = world.get_entity(hazel)
    wary.add_component(AffectComponent(current=AffectVector(fear=10.0, stress=10.0), labels=()))
    adjust_bond(world, hazel, scenario.character, {"resentment": 0.6})

    missing_interpretation = interpret_speech_for_listener(
        world,
        scenario.character,
        parse_entity_id("entity_999"),
        "praise",
    )
    apology = interpret_speech_for_listener(
        world,
        scenario.character,
        hazel,
        "apology",
    )

    assert missing_interpretation.final_interpretation == "praise"
    assert apology.final_interpretation == "neutral"
    assert apology.relationship_tags == ("hostile",)
    assert "afraid" in apology.mood_tags
    assert "tense" in apology.mood_tags


async def test_repeated_speech_accumulates_familiarity():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    juniper = scenario.character

    await scenario.actor.submit(_say(scenario, "One.", "neutral"))
    await scenario.actor.tick(HOUR)
    first = bond_between(world, juniper, hazel).familiarity

    await scenario.actor.submit(_say(scenario, "Two.", "neutral"))
    await scenario.actor.tick(HOUR)
    second = bond_between(world, juniper, hazel).familiarity

    assert second > first  # the edge updates in place, not resets


def test_adjust_bond_creates_clamps_and_accumulates():
    scenario = build_scenario()
    world = scenario.actor.world
    a, b = scenario.character, scenario.room_b  # any two entities suffice for the edge

    adjust_bond(world, a, b, {"affinity": 0.6})
    adjust_bond(world, a, b, {"affinity": 0.9})  # 1.5 -> clamps to 1.0
    bond = bond_between(world, a, b)
    assert bond.affinity == 1.0
    adjust_bond(world, a, b, {"fear": -5.0})  # clamps to -1.0
    assert bond_between(world, a, b).fear == -1.0


def test_relationship_fragment_describes_strong_bonds():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    juniper = world.get_entity(scenario.character)

    adjust_bond(world, scenario.character, hazel, {"affinity": 0.5})
    fragments = relationship_fragments(world, juniper)
    assert any("fond of Hazel" in line for line in fragments)

    adjust_bond(world, scenario.character, hazel, {"fear": 0.6})  # fear dominates
    assert any("fear Hazel" in line for line in relationship_fragments(world, juniper))


def test_social_bond_prompt_fragments_use_context_target_and_perspective():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    target = spawn_entity(
        world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    first = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(viewer=character, perspective="first-person"),
        target=target,
    )
    third = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(viewer=character, perspective="third-person"),
        target=target,
    )
    observer = spawn_entity(world, [CharacterComponent()])
    observer_ctx = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(viewer=observer),
        target=target,
    )

    assert SocialBond(affinity=0.5).prompt_fragments(first) == ("I am fond of Hazel.",)
    assert SocialBond(familiarity=0.5).prompt_fragments(third) == ("They know Hazel.",)
    assert SocialBond(affinity=0.5).prompt_fragments(observer_ctx) == ()
    assert SocialBond(affinity=0.1).prompt_fragments(first) == ()


def test_relationship_fragments_cover_negative_and_familiar_bonds():
    scenario = build_scenario()
    world = scenario.actor.world
    juniper = world.get_entity(scenario.character)
    rival = spawn_entity(
        world,
        [IdentityComponent(name="Rival", kind="character"), CharacterComponent()],
    )
    acquaintance = spawn_entity(
        world,
        [IdentityComponent(name="Acquaintance", kind="character"), CharacterComponent()],
    )
    mystery = spawn_entity(world, [CharacterComponent()])

    adjust_bond(world, scenario.character, rival.id, {"resentment": 0.4})
    adjust_bond(world, scenario.character, acquaintance.id, {"familiarity": 0.4})
    adjust_bond(world, scenario.character, mystery.id, {"affinity": -0.4})

    fragments = relationship_fragments(world, juniper)

    assert any("resent Rival" in line for line in fragments)
    assert any("know Acquaintance" in line for line in fragments)
    assert any("dislike someone" in line for line in fragments)


def test_relationship_fragments_skip_dangling_targets():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    target = spawn_entity(world, [CharacterComponent()])
    character.add_relationship(SocialBond(familiarity=0.5), target.id)
    world.remove(target.id)

    assert relationship_fragments(world, character) == []


def test_relationship_reactor_handles_tell_events_and_ignores_invalid_targets():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    speaker = world.get_entity(scenario.character)
    listener = world.get_entity(hazel)
    speaker.add_component(SocialNeedComponent(meter=Meter(value=40.0)))
    listener.add_component(SocialNeedComponent(meter=Meter(value=40.0)))
    reactor = RelationshipReactor(world)

    reactor._on_speech(
        SpeechToldEvent(
            event_id="missing-speaker",
            world_epoch=0,
            created_at="2026-01-01T00:00:00Z",
            visibility=EventVisibility.PRIVATE,
            actor_id="entity_999",
            target_ids=(str(hazel),),
            text="hello",
        )
    )
    reactor._on_speech(
        SpeechToldEvent(
            event_id="tell",
            world_epoch=1,
            created_at="2026-01-01T00:00:00Z",
            visibility=EventVisibility.PRIVATE,
            actor_id=str(scenario.character),
            target_ids=("not-an-id", str(scenario.character), str(hazel)),
            text="hello",
            final_interpretation="apology",
        )
    )

    assert speaker.get_component(SocialNeedComponent).meter.value < 40.0
    assert listener.get_component(SocialNeedComponent).meter.value < 40.0
    assert bond_between(world, scenario.character, hazel).familiarity > 0


async def test_promise_speech_creates_persisted_obligation_prompt(tmp_path):
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world

    await scenario.actor.submit(_say(scenario, "I promise I will repair the latch.", "promise"))
    await scenario.actor.tick(HOUR)

    obligations = obligations_for(world, scenario.character)
    assert len(obligations) == 1
    obligation_entity, obligation = obligations[0]
    assert obligation.kind == "promise"
    assert obligation.text == "I promise I will repair the latch."
    assert obligation.status == "open"
    assert obligation_entity.get_relationships(ObligationDebtor)[0][1] == scenario.character
    assert obligation_entity.get_relationships(ObligationCreditor)[0][1] == hazel
    assert (
        obligation_for_source(world, obligation.source_event_id, scenario.character, hazel)
        == obligation_entity
    )
    assert any(
        "You owe Hazel" in line
        for line in obligation_fragments(world, world.get_entity(scenario.character))
    )
    assert any(
        "Juniper owes you" in line for line in obligation_fragments(world, world.get_entity(hazel))
    )

    path = tmp_path / "world.json"
    save_world(scenario.actor, path, meta=WorldMeta(seed="obligation"))
    loaded, _meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))
    loaded_obligations = obligations_for(loaded.world, scenario.character)
    assert len(loaded_obligations) == 1
    assert loaded_obligations[0][1].text == "I promise I will repair the latch."


def test_obligation_creation_handles_request_dedupe_and_invalid_inputs():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    request = create_obligation(
        world,
        kind="request",
        text="  bring water   ",
        debtor_id=hazel,
        creditor_id=scenario.character,
        source_event_id="request-1",
        created_at_epoch=10,
    )
    duplicate = create_obligation(
        world,
        kind="request",
        text="bring water again",
        debtor_id=hazel,
        creditor_id=scenario.character,
        source_event_id="request-1",
        created_at_epoch=11,
    )

    assert request is not None
    assert duplicate is None
    assert request.get_component(ObligationComponent).text == "bring water"
    assert obligations_for(world, hazel)[0][0] == request
    assert obligations_for(world, parse_entity_id("entity_999")) == []
    assert (
        create_obligation(
            world,
            kind="neutral",
            text="nothing",
            debtor_id=hazel,
            creditor_id=scenario.character,
        )
        is None
    )
    assert (
        create_obligation(
            world,
            kind="promise",
            text=" ",
            debtor_id=hazel,
            creditor_id=scenario.character,
        )
        is None
    )
    missing_id = parse_entity_id("entity_999")
    assert missing_id is not None
    assert (
        create_obligation(
            world,
            kind="promise",
            text="missing debtor",
            debtor_id=missing_id,
            creditor_id=scenario.character,
        )
        is None
    )
    assert obligation_for_source(world, "different-source", hazel, scenario.character) is None
    assert obligation_for_source(world, "request-1", scenario.character, hazel) is None


def test_obligation_reactor_handles_request_and_ignores_invalid_speech():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    obligation_reactor = ObligationReactor(world)
    obligation_reactor._on_speech(
        SpeechToldEvent(
            event_id="neutral",
            world_epoch=1,
            created_at=datetime.now(UTC),
            visibility=EventVisibility.PRIVATE,
            actor_id=str(scenario.character),
            target_ids=(str(hazel),),
            text="hello",
            final_interpretation="neutral",
        )
    )
    obligation_reactor._on_speech(
        SpeechToldEvent(
            event_id="missing-speaker",
            world_epoch=2,
            created_at=datetime.now(UTC),
            visibility=EventVisibility.PRIVATE,
            actor_id="entity_999",
            target_ids=(str(hazel),),
            text="please bring water",
            final_interpretation="request",
        )
    )
    obligation_reactor._on_speech(
        SpeechToldEvent(
            event_id="request",
            world_epoch=3,
            created_at=datetime.now(UTC),
            visibility=EventVisibility.PRIVATE,
            actor_id=str(scenario.character),
            target_ids=("not-an-id", str(scenario.character), "entity_999", str(hazel)),
            text="please bring water",
            final_interpretation="request",
        )
    )

    obligations = obligations_for(world, hazel)

    assert len(obligations) == 1
    obligation_entity, obligation = obligations[0]
    assert obligation.kind == "request"
    assert obligation_entity.get_relationships(ObligationDebtor)[0][1] == hazel
    assert obligation_entity.get_relationships(ObligationCreditor)[0][1] == scenario.character


def test_obligation_reactor_deduplicates_repeated_open_request_intents():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    obligation_reactor = ObligationReactor(world)

    for event_number in range(100):
        obligation_reactor._on_speech(
            SpeechToldEvent(
                event_id=f"repeated-request-{event_number}",
                world_epoch=event_number,
                created_at=datetime.now(UTC),
                visibility=EventVisibility.PRIVATE,
                actor_id=str(scenario.character),
                target_ids=(str(hazel),),
                text="please   bring water",
                final_interpretation="request",
            )
        )

    obligations = obligations_for(world, hazel)

    assert len(obligations) == 1
    obligation_entity, obligation = obligations[0]
    assert obligation.text == "please bring water"
    assert obligation.source_event_id == "repeated-request-0"
    assert obligation_entity.get_relationships(ObligationDebtor)[0][1] == hazel
    assert obligation_entity.get_relationships(ObligationCreditor)[0][1] == scenario.character


def test_resolve_obligation_updates_status_and_social_consequence():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    obligation = create_obligation(
        world,
        kind="promise",
        text="repair the latch",
        debtor_id=scenario.character,
        creditor_id=hazel,
        source_event_id="promise-1",
        created_at_epoch=1,
    )
    assert obligation is not None
    ctx = HandlerContext(world, HOUR)
    command = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="resolve-obligation",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={
            "obligation_id": str(obligation.id),
            "status": "fulfilled",
            "note": "fixed before dusk",
        },
    )

    result = execute_handler(ResolveObligationHandler(), ctx, command)

    assert result.ok is True
    event = result.events[0]
    assert isinstance(event, ObligationResolvedEvent)
    assert event.status == "fulfilled"
    component = obligation.get_component(ObligationComponent)
    assert component.status == "fulfilled"
    assert component.resolution_note == "fixed before dusk"
    assert obligations_for(world, scenario.character) == []
    assert obligations_for(world, scenario.character, include_resolved=True)[0][0] == obligation
    assert bond_between(world, hazel, scenario.character).trust > 0


def test_resolve_obligation_rejections_and_failed_consequence():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    outsider = spawn_entity(
        world, [IdentityComponent(name="Outsider", kind="character"), CharacterComponent()]
    )
    wrong_kind = spawn_entity(world, [IdentityComponent(name="token", kind="item")])
    obligation = create_obligation(
        world,
        kind="promise",
        text="repair the latch",
        debtor_id=scenario.character,
        creditor_id=hazel,
        source_event_id="promise-2",
        created_at_epoch=1,
    )
    assert obligation is not None
    ctx = HandlerContext(world, HOUR)

    def command(character_id, obligation_id, status="failed"):
        return build_submitted_command(
            character_id=str(character_id),
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="resolve-obligation",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload={"obligation_id": str(obligation_id), "status": status},
        )

    cases = [
        (command("not-an-id", obligation.id), "invalid character or obligation id"),
        (command(scenario.character, "entity_999"), "obligation does not exist"),
        (command(scenario.character, wrong_kind.id), "target is not an obligation"),
        (command(outsider.id, obligation.id), "character is not party to obligation"),
        (command(scenario.character, obligation.id, "unknown"), "invalid obligation status"),
    ]
    for submitted, reason in cases:
        result = execute_handler(ResolveObligationHandler(), ctx, submitted)
        assert result.ok is False
        assert result.reason == reason

    failed = execute_handler(
        ResolveObligationHandler(), ctx, command(scenario.character, obligation.id)
    )
    assert failed.ok is True
    assert bond_between(world, hazel, scenario.character).resentment > 0
    second = execute_handler(
        ResolveObligationHandler(), ctx, command(scenario.character, obligation.id)
    )
    assert second.ok is False
    assert second.reason == "obligation is already resolved"


def test_no_fragment_for_a_faint_bond():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    adjust_bond(world, scenario.character, hazel, {"familiarity": 0.1})  # below threshold
    assert relationship_fragments(world, world.get_entity(scenario.character)) == []


def test_social_bond_defaults_are_neutral():
    assert SocialBond().affinity == 0.0
    assert SocialBond().familiarity == 0.0


def test_conversation_line_creates_structured_gossip_claim_for_participants():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    reactor = GossipReactor(world)

    reactor._on_conversation_line(
        ConversationLineEvent(
            event_id="line-1",
            world_epoch=10,
            created_at=datetime.now(UTC),
            visibility=EventVisibility.ROOM,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_a),
            target_ids=(str(hazel),),
            conversation_id="conversation_1",
            speaker_id=str(scenario.character),
            text="The east gate is unlatched.",
            turn_index=0,
            final_interpretation="inform",
        )
    )

    hazel_claims = known_gossip(world, hazel)
    juniper_claims = known_gossip(world, scenario.character)

    assert len(hazel_claims) == 1
    assert juniper_claims[0][0].id == hazel_claims[0][0].id
    claim, edge = hazel_claims[0]
    component = claim.get_component(GossipClaimComponent)
    assert component.subject_id == str(scenario.character)
    assert component.source_event_id == "line-1"
    assert "Juniper said in conversation conversation_1" in component.text
    assert "east gate is unlatched" in component.text
    assert edge == KnowsGossip(
        confidence=1.0,
        learned_from_id=str(scenario.character),
        learned_at_epoch=10,
    )
    juniper_fragments = gossip_fragments(world, world.get_entity(scenario.character))
    assert any("You know:" in line for line in juniper_fragments)


def test_gossip_relay_teaches_absent_character_attributed_degraded_claim():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    clover = spawn_entity(
        world,
        [IdentityComponent(name="Clover", kind="character"), CharacterComponent()],
    )
    reactor = GossipReactor(world)

    reactor._on_conversation_line(
        ConversationLineEvent(
            event_id="line-2",
            world_epoch=20,
            created_at=datetime.now(UTC),
            visibility=EventVisibility.ROOM,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_a),
            target_ids=(str(hazel),),
            conversation_id="conversation_2",
            speaker_id=str(scenario.character),
            text="The baker hid the ledger under the millstone.",
            turn_index=0,
            final_interpretation="inform",
        )
    )
    assert known_gossip(world, clover.id) == []

    adjust_bond(world, clover.id, hazel, {"trust": 0.4, "familiarity": 0.4})
    reactor._on_speech(
        SpeechToldEvent(
            event_id="gossip-1",
            world_epoch=25,
            created_at=datetime.now(UTC),
            visibility=EventVisibility.PRIVATE,
            actor_id=str(hazel),
            room_id=str(scenario.room_a),
            target_ids=(str(clover.id),),
            text="You should know what Juniper said.",
            final_interpretation="gossip",
        )
    )

    learned = known_gossip(world, clover.id)
    assert len(learned) == 1
    claim, edge = learned[0]
    assert "baker hid the ledger" in claim.get_component(GossipClaimComponent).text
    assert edge.learned_from_id == str(hazel)
    assert edge.hops == 1
    assert 0.0 < edge.confidence < 1.0
    fragments = gossip_fragments(world, world.get_entity(clover.id))
    assert any("You heard from Hazel:" in fragment for fragment in fragments)
    assert any("confidence 0." in fragment for fragment in fragments)


def test_gossip_helpers_ignore_invalid_and_weaker_claims():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    claim = create_gossip_claim(world, text="Hazel found a brass key.")
    not_claim = spawn_entity(world, [IdentityComponent(name="rumor shell", kind="note")])
    dangling = spawn_entity(world, [IdentityComponent(name="old rumor", kind="note")])
    world.get_entity(hazel).add_relationship(KnowsGossip(confidence=0.4), not_claim.id)
    world.get_entity(hazel).add_relationship(KnowsGossip(confidence=0.3), dangling.id)
    world.remove(dangling.id)

    assert known_gossip(world, parse_entity_id("entity_999")) == []
    assert known_gossip(world, hazel) == []
    assert not learn_gossip(world, parse_entity_id("entity_999"), claim.id)
    assert not learn_gossip(world, hazel, parse_entity_id("entity_999"))
    assert not learn_gossip(world, hazel, not_claim.id)
    assert learn_gossip(world, hazel, claim.id, confidence=0.8, hops=1)
    assert not learn_gossip(world, hazel, claim.id, confidence=0.7, hops=2)
    assert learn_gossip(world, hazel, claim.id, confidence=0.9, hops=1)
    assert known_gossip(world, hazel)[0][1].confidence == 0.9


def test_gossip_reactor_ignores_invalid_sources_targets_and_known_claims():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    reactor = GossipReactor(world)

    reactor._on_conversation_line(
        ConversationLineEvent(
            event_id="bad-line",
            world_epoch=30,
            created_at=datetime.now(UTC),
            visibility=EventVisibility.ROOM,
            actor_id="entity_999",
            target_ids=(str(hazel),),
            conversation_id="conversation_3",
            speaker_id="entity_999",
            text="Nobody hears this.",
            turn_index=0,
        )
    )
    assert known_gossip(world, hazel) == []

    claim = create_gossip_claim(world, text="Juniper saw the lantern go out.")
    assert learn_gossip(world, scenario.character, claim.id, confidence=1.0)
    assert learn_gossip(world, hazel, claim.id, confidence=0.6)
    reactor._on_speech(
        SpeechToldEvent(
            event_id="no-claims",
            world_epoch=31,
            created_at=datetime.now(UTC),
            visibility=EventVisibility.PRIVATE,
            actor_id=str(hazel),
            target_ids=("not-an-id", str(scenario.character), str(hazel)),
            text="Rumor has it.",
            final_interpretation="gossip",
        )
    )
    reactor._on_speech(
        SpeechToldEvent(
            event_id="missing-speaker",
            world_epoch=32,
            created_at=datetime.now(UTC),
            visibility=EventVisibility.PRIVATE,
            actor_id="entity_999",
            target_ids=(str(hazel),),
            text="Rumor has it.",
            final_interpretation="gossip",
        )
    )

    assert len(known_gossip(world, hazel)) == 1


def test_social_bond_first_person_fragment_needs_a_target():
    # A first-person bond fragment with no target entity surfaces nothing (it has no name to
    # speak about), even when the bond itself is strong enough to describe.
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    no_target = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(viewer=character, perspective="first-person"),
        target=None,
    )
    assert SocialBond(affinity=0.5).prompt_fragments(no_target) == ()


def test_obligation_for_source_skips_matching_debtor_with_other_creditor():
    # An obligation whose debtor matches but whose creditor differs is not the one we asked
    # for: the lookup keeps scanning and ultimately finds nothing.
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    other = spawn_entity(
        world, [IdentityComponent(name="Other", kind="character"), CharacterComponent()]
    )
    obligation = create_obligation(
        world,
        kind="promise",
        text="mind the gate",
        debtor_id=scenario.character,
        creditor_id=hazel,
        source_event_id="src-mismatch",
        created_at_epoch=1,
    )
    assert obligation is not None
    # Same source and debtor, but a creditor that is not party to the obligation.
    assert obligation_for_source(world, "src-mismatch", scenario.character, other.id) is None


def test_obligations_for_skips_obligations_without_the_character():
    # An obligation between two other characters is not returned when querying a third.
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    bystander = spawn_entity(
        world, [IdentityComponent(name="Bystander", kind="character"), CharacterComponent()]
    )
    obligation = create_obligation(
        world,
        kind="promise",
        text="mind the gate",
        debtor_id=scenario.character,
        creditor_id=hazel,
        source_event_id="src-bystander",
        created_at_epoch=1,
    )
    assert obligation is not None
    assert obligations_for(world, bystander.id) == []


def test_obligations_for_orders_tied_epochs_without_entity_id_comparison():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    first = create_obligation(
        world,
        kind="promise",
        text="first promise",
        debtor_id=scenario.character,
        creditor_id=hazel,
        source_event_id="src-first",
        created_at_epoch=1,
    )
    second = create_obligation(
        world,
        kind="promise",
        text="second promise",
        debtor_id=scenario.character,
        creditor_id=hazel,
        source_event_id="src-second",
        created_at_epoch=1,
    )

    assert first is not None
    assert second is not None
    assert {entity for entity, _component in obligations_for(world, scenario.character)} == {
        first,
        second,
    }


def test_conversation_line_skips_invalid_targets():
    # Unparseable, self, and missing targets are all skipped; only the valid listener learns.
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    reactor = GossipReactor(world)

    reactor._on_conversation_line(
        ConversationLineEvent(
            event_id="line-targets",
            world_epoch=10,
            created_at=datetime.now(UTC),
            visibility=EventVisibility.ROOM,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_a),
            target_ids=("not-an-id", str(scenario.character), "entity_999", str(hazel)),
            conversation_id="conversation_targets",
            speaker_id=str(scenario.character),
            text="The east gate is unlatched.",
            turn_index=0,
            final_interpretation="inform",
        )
    )

    assert len(known_gossip(world, hazel)) == 1


def test_gossip_speech_with_no_known_claims_relays_nothing():
    # A speaker who knows no gossip cannot relay any, even with a valid listener.
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    reactor = GossipReactor(world)

    reactor._on_speech(
        SpeechToldEvent(
            event_id="empty-gossip",
            world_epoch=5,
            created_at=datetime.now(UTC),
            visibility=EventVisibility.PRIVATE,
            actor_id=str(scenario.character),
            target_ids=(str(hazel),),
            text="Rumor has it.",
            final_interpretation="gossip",
        )
    )

    assert known_gossip(world, hazel) == []


def test_resolve_obligation_cancel_leaves_bond_unchanged():
    # A cancelled obligation resolves without warming or souring the bond between parties.
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    obligation = create_obligation(
        world,
        kind="promise",
        text="repair the latch",
        debtor_id=scenario.character,
        creditor_id=hazel,
        source_event_id="promise-cancel",
        created_at_epoch=1,
    )
    assert obligation is not None
    ctx = HandlerContext(world, HOUR)
    command = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="resolve-obligation",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"obligation_id": str(obligation.id), "status": "canceled"},
    )

    result = execute_handler(ResolveObligationHandler(), ctx, command)

    assert result.ok is True
    assert obligation.get_component(ObligationComponent).status == "canceled"
    # No bond is created as a consequence of a cancellation.
    assert bond_between(world, hazel, scenario.character) is None
