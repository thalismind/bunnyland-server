"""Tests for policy & boundaries: the allow/deny gate (spec 20)."""

from __future__ import annotations

import pytest
from conftest import build_scenario
from pydantic import TypeAdapter

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    TellHandler,
    WorldActor,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent, SpeechToldEvent
from bunnyland.foundation.policy.mechanics import (
    BoundaryTag,
    CharacterBoundaryComponent,
    WorldPolicyComponent,
    activate_boundary_tags,
    boundary_fragments,
    evaluate,
    flirt_classifier,
    install_policy,
)

HOUR = 3600.0
FLIRTING = BoundaryTag.FLIRTING
ADULT_SEXUAL = BoundaryTag.ADULT_SEXUAL


def _two_characters(actor, *, a_boundary=None, b_boundary=None):
    a = spawn_entity(actor.world, [IdentityComponent(name="A", kind="character")])
    b = spawn_entity(actor.world, [IdentityComponent(name="B", kind="character")])
    if a_boundary is not None:
        a.add_component(a_boundary)
    if b_boundary is not None:
        b.add_component(b_boundary)
    return str(a.id), str(b.id)


# -- evaluate() ------------------------------------------------------------------------


def test_world_enabled_tag_is_allowed_without_denials():
    actor = WorldActor()
    install_policy(actor)  # FLIRTING enabled by default
    a, b = _two_characters(actor)
    assert evaluate(actor.world, FLIRTING, [a, b]) == (True, None)


def test_denied_always_wins_even_when_world_enables():
    actor = WorldActor()
    install_policy(actor)  # FLIRTING enabled
    a, b = _two_characters(
        actor, b_boundary=CharacterBoundaryComponent(denied=frozenset({FLIRTING}))
    )
    allowed, reason = evaluate(actor.world, FLIRTING, [a, b])
    assert allowed is False
    assert "consented" in reason


def test_world_disabled_blocks_even_with_opt_in():
    actor = WorldActor()
    install_policy(actor, enabled=frozenset(), disabled=frozenset({FLIRTING}))
    a, b = _two_characters(
        actor,
        a_boundary=CharacterBoundaryComponent(allowed=frozenset({FLIRTING})),
        b_boundary=CharacterBoundaryComponent(allowed=frozenset({FLIRTING})),
    )
    allowed, reason = evaluate(actor.world, FLIRTING, [a, b])
    assert allowed is False
    assert "disabled" in reason


def test_mutual_opt_in_allows_a_tag_the_world_did_not_enable():
    actor = WorldActor()
    install_policy(actor, enabled=frozenset())  # nothing enabled globally
    opted = CharacterBoundaryComponent(allowed=frozenset({FLIRTING}))
    a, b = _two_characters(actor, a_boundary=opted, b_boundary=opted)
    assert evaluate(actor.world, FLIRTING, [a, b])[0] is True

    # but if only one opts in, it stays blocked
    c, _d = _two_characters(actor, a_boundary=opted)
    assert evaluate(actor.world, FLIRTING, [c, _d])[0] is False


def test_unenabled_tag_with_no_opt_in_is_denied():
    actor = WorldActor()
    install_policy(actor)
    a, b = _two_characters(actor)
    assert evaluate(actor.world, BoundaryTag.PVP, [a, b])[0] is False


def test_adult_parent_enable_and_allow_do_not_grant_child_scope():
    actor = WorldActor()
    install_policy(actor, enabled=frozenset({BoundaryTag.ADULT}))
    parent_only = CharacterBoundaryComponent(allowed=frozenset({BoundaryTag.ADULT}))
    a, b = _two_characters(actor, a_boundary=parent_only, b_boundary=parent_only)

    assert evaluate(actor.world, ADULT_SEXUAL, [a, b]) == (
        False,
        "adult:sexual is not enabled here",
    )


def test_exact_adult_child_enable_or_mutual_opt_in_grants_scope():
    enabled_actor = WorldActor()
    install_policy(enabled_actor, enabled=frozenset({ADULT_SEXUAL}))
    a, b = _two_characters(enabled_actor)
    assert evaluate(enabled_actor.world, ADULT_SEXUAL, [a, b]) == (True, None)

    opted_actor = WorldActor()
    install_policy(opted_actor, enabled=frozenset())
    exact = CharacterBoundaryComponent(allowed=frozenset({ADULT_SEXUAL}))
    c, d = _two_characters(opted_actor, a_boundary=exact, b_boundary=exact)
    assert evaluate(opted_actor.world, ADULT_SEXUAL, [c, d]) == (True, None)


def test_adult_parent_or_exact_denial_blocks_child_but_unrelated_denial_does_not():
    for denied in (BoundaryTag.ADULT, ADULT_SEXUAL):
        actor = WorldActor()
        install_policy(actor, enabled=frozenset({ADULT_SEXUAL}))
        a, b = _two_characters(
            actor,
            b_boundary=CharacterBoundaryComponent(denied=frozenset({denied})),
        )
        assert evaluate(actor.world, ADULT_SEXUAL, [a, b])[0] is False

    actor = WorldActor()
    install_policy(actor, enabled=frozenset({ADULT_SEXUAL}))
    a, b = _two_characters(
        actor,
        b_boundary=CharacterBoundaryComponent(denied=frozenset({BoundaryTag.ADULT_BONDAGE})),
    )
    assert evaluate(actor.world, ADULT_SEXUAL, [a, b]) == (True, None)


def test_world_adult_parent_or_exact_disable_blocks_child():
    for disabled in (BoundaryTag.ADULT, ADULT_SEXUAL):
        actor = WorldActor()
        install_policy(
            actor,
            enabled=frozenset({ADULT_SEXUAL}),
            disabled=frozenset({disabled}),
        )
        a, b = _two_characters(actor)
        assert evaluate(actor.world, ADULT_SEXUAL, [a, b])[0] is False


def test_plugin_boundary_scopes_are_validated_and_activated():
    actor = WorldActor()
    install_policy(actor, enabled=frozenset({"adult:custom"}))
    a, b = _two_characters(actor)
    assert evaluate(actor.world, "adult:custom", [a, b]) == (
        False,
        "adult:custom is not available here",
    )

    activate_boundary_tags(actor.world, {"adult:custom"})

    assert evaluate(actor.world, "adult:custom", [a, b]) == (True, None)


def test_boundary_components_reject_malformed_string_scopes():
    with pytest.raises(ValueError, match="boundary scopes"):
        CharacterBoundaryComponent(allowed=frozenset({"Adult:Invalid"}))

    with pytest.raises(ValueError, match="boundary scopes"):
        CharacterBoundaryComponent(allowed=frozenset({"a" * 65}))


def test_old_enum_only_policy_payload_loads_with_core_scope_defaults():
    loaded = TypeAdapter(WorldPolicyComponent).validate_python(
        {"enabled": ["flirting"], "disabled": ["pvp"]}
    )
    assert loaded.enabled == frozenset({"flirting"})
    assert BoundaryTag.ADULT_SEXUAL in loaded.available


def test_activating_no_scopes_or_without_policy_is_a_noop():
    actor = WorldActor()
    activate_boundary_tags(actor.world, {"adult:custom"})
    activate_boundary_tags(actor.world, set())


def test_unknown_participant_id_is_treated_as_unconsented():
    actor = WorldActor()
    install_policy(actor, enabled=frozenset())  # nothing globally enabled
    # an unparseable / missing id yields (raw_id, None) so it cannot opt in (line 70)
    assert evaluate(actor.world, FLIRTING, ["not-an-id"])[0] is False


def test_evaluate_without_any_world_policy_denies_unenabled_tag():
    actor = WorldActor()  # no install_policy -> no WorldPolicyComponent (line 64)
    a = spawn_entity(actor.world, [IdentityComponent(name="A", kind="character")])
    assert evaluate(actor.world, FLIRTING, [str(a.id)])[0] is False


def test_boundary_fragments_empty_when_nothing_configured():
    actor = WorldActor()
    install_policy(actor, enabled=frozenset(), disabled=frozenset())
    plain = spawn_entity(actor.world, [IdentityComponent(name="P", kind="character")])
    assert boundary_fragments(actor.world, plain) == []


def test_boundary_fragments_with_empty_character_boundary_adds_no_lines():
    actor = WorldActor()
    install_policy(actor, enabled=frozenset(), disabled=frozenset())
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="C", kind="character"),
            CharacterBoundaryComponent(),  # neither allowed nor denied (120->123, 123->126)
        ],
    )
    assert boundary_fragments(actor.world, character) == []


def test_flirt_classifier_ignores_non_speech_commands():
    command = build_submitted_command(
        character_id="entity_1",
        controller_id="entity_1",
        controller_generation=0,
        command_type="move",  # not say/tell (line 132)
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"intent": "flirt"},
    )
    assert flirt_classifier(command) is None


def test_boundary_fragments_describe_world_and_character_boundaries():
    actor = WorldActor()
    install_policy(
        actor,
        enabled=frozenset({FLIRTING}),
        disabled=frozenset({BoundaryTag.PVP}),
    )
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="C", kind="character"),
            CharacterBoundaryComponent(
                allowed=frozenset({BoundaryTag.ROMANCE}),
                denied=frozenset({BoundaryTag.THEFT}),
            ),
        ],
    )
    lines = boundary_fragments(actor.world, character)
    assert "World boundaries enabled: flirting." in lines
    assert "World boundaries disabled: pvp." in lines  # 116-117
    assert "Your allowed boundaries: romance." in lines  # 121-122
    assert "Your denied boundaries: theft." in lines  # 123->126


def test_flirt_classifier_without_target_uses_speaker_only():
    actor = WorldActor()
    speaker = spawn_entity(actor.world, [IdentityComponent(name="S", kind="character")])
    command = build_submitted_command(
        character_id=str(speaker.id),
        controller_id=str(speaker.id),
        controller_generation=0,
        command_type="say",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"intent": "flirt"},  # no target_id (137->139)
    )
    tag, participants = flirt_classifier(command)
    assert tag is FLIRTING
    assert participants == [str(speaker.id)]


def test_install_policy_keeps_existing_world_policy():
    actor = WorldActor()
    target = spawn_entity(
        actor.world,
        [WorldPolicyComponent(enabled=frozenset({BoundaryTag.ROMANCE}))],
    )
    install_policy(actor, enabled=frozenset({FLIRTING}))  # 173->178: skip spawning
    # the pre-existing policy is left untouched
    assert target.get_component(WorldPolicyComponent).enabled == frozenset({BoundaryTag.ROMANCE})


# -- gate in the command pipeline ------------------------------------------------------


def _flirt_tell(scenario, target_id):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="tell",
        cost=CommandCost(action=1, focus=1),
        lane=Lane.WORLD,
        payload={"target_id": str(target_id), "text": "hey, you're cute", "intent": "flirt"},
    )


def _present_listener(scenario, *, boundary=None):
    components = [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()]
    if boundary is not None:
        components.append(boundary)
    hazel = spawn_entity(scenario.actor.world, components)
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hazel.id
    )
    return hazel.id


async def test_flirt_tell_blocked_when_target_denies():
    scenario = build_scenario()
    scenario.actor.register_handler(TellHandler())
    install_policy(scenario.actor)
    hazel = _present_listener(
        scenario, boundary=CharacterBoundaryComponent(denied=frozenset({FLIRTING}))
    )
    rejects: list[CommandRejectedEvent] = []
    told: list[SpeechToldEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)
    scenario.actor.bus.subscribe(SpeechToldEvent, told.append)

    await scenario.actor.submit(_flirt_tell(scenario, hazel))
    await scenario.actor.tick(HOUR)

    assert told == []  # never delivered
    assert any("consented" in r.reason for r in rejects)


async def test_flirt_tell_allowed_when_enabled_and_not_denied():
    scenario = build_scenario()
    scenario.actor.register_handler(TellHandler())
    install_policy(scenario.actor)  # FLIRTING enabled
    hazel = _present_listener(scenario)  # no boundary -> not denied
    told: list[SpeechToldEvent] = []
    scenario.actor.bus.subscribe(SpeechToldEvent, told.append)

    await scenario.actor.submit(_flirt_tell(scenario, hazel))
    await scenario.actor.tick(HOUR)

    assert len(told) == 1


async def test_non_flirt_speech_is_never_gated():
    scenario = build_scenario()
    scenario.actor.register_handler(TellHandler())
    install_policy(scenario.actor, enabled=frozenset())  # flirting NOT enabled
    hazel = _present_listener(scenario)
    told: list[SpeechToldEvent] = []
    scenario.actor.bus.subscribe(SpeechToldEvent, told.append)

    plain = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="tell",
        cost=CommandCost(action=1, focus=1),
        lane=Lane.WORLD,
        payload={"target_id": str(hazel), "text": "good morning", "intent": "neutral"},
    )
    await scenario.actor.submit(plain)
    await scenario.actor.tick(HOUR)

    assert len(told) == 1  # ungated despite flirting being disabled
