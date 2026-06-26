"""End-to-end tests for the core command/tick spine."""

from __future__ import annotations

import random

import pytest
from conftest import build_scenario

from bunnyland.claims import (
    ClaimSecretRegistry,
    add_claim,
    character_has_claim,
    claim_matches,
    claimable_characters,
    claimed_character_for,
    controller_claim,
    current_controller,
    ensure_claim_secret,
    normalize_claimed_controllers_without_secrets,
    remove_claim,
    transfer_claim,
)
from bunnyland.core import (
    ActionPointsComponent,
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    ControlledBy,
    FocusPointsComponent,
    IdentityComponent,
    InitiativeComponent,
    Lane,
    OnInsufficientPoints,
    SuspendedComponent,
    WorldClockComponent,
    build_submitted_command,
    entity_name,
    entity_room_id,
    event_base,
    parse_entity_id,
    remove_from_container,
    room_id_for,
    spawn_entity,
)
from bunnyland.core.claim_timeout import (
    CLAIM_FALLBACK_LLM,
    CLAIM_FALLBACK_SUSPEND,
    CLAIM_TIMEOUT_MAX_SECONDS,
    CLAIM_TIMEOUT_MIN_SECONDS,
    apply_claim_timeout_settings,
    normalize_claim_fallback,
    normalize_claim_timeout,
    record_claim_activity,
)
from bunnyland.core.controllers import (
    BehaviorControllerComponent,
    ClaimedComponent,
    ClaimTimeoutComponent,
    DiscordControllerComponent,
    LLMControllerComponent,
    MCPControllerComponent,
    ScriptedControllerComponent,
    SuspendedControllerComponent,
    WebControllerComponent,
)
from bunnyland.core.ecs import get_or_none, reachable_ids
from bunnyland.core.events import (
    CommandExecutedEvent,
    CommandRejectedEvent,
    ControllerChangedEvent,
    EventBus,
    EventVisibility,
)
from bunnyland.core.systems import ClaimTimeoutSystem

HOUR = 3600.0


def move_command(scenario, *, generation=None, on_insufficient=OnInsufficientPoints.QUEUE):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation if generation is None else generation,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "north"},
        on_insufficient_points=on_insufficient,
    )


def collect(actor, event_type):
    seen = []
    actor.bus.subscribe(event_type, seen.append)
    return seen


def test_event_bus_unsubscribe_ignores_missing_handlers():
    bus = EventBus()
    seen = []

    bus.unsubscribe(CommandExecutedEvent, seen.append)
    bus.subscribe(CommandExecutedEvent, seen.append)
    bus.unsubscribe(CommandRejectedEvent, seen.append)
    bus.unsubscribe(CommandExecutedEvent, lambda event: None)
    bus.unsubscribe(CommandExecutedEvent, seen.append)

    assert bus._handlers[CommandExecutedEvent] == []


def test_get_or_none_and_nowait_submission_cover_absent_paths():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)

    assert get_or_none(character, IdentityComponent).name == "Juniper"
    assert get_or_none(character, SuspendedComponent) is None

    command = move_command(scenario)
    scenario.actor.submit_nowait(command)
    assert scenario.actor._inbox.get_nowait() is command


def test_event_base_defaults_visibility_only_when_requested():
    system_payload = event_base(7)
    public_payload = event_base(
        8, default_visibility=EventVisibility.PUBLIC, actor_id="entity_1"
    )

    assert system_payload["world_epoch"] == 7
    assert "visibility" not in system_payload
    assert public_payload["world_epoch"] == 8
    assert public_payload["visibility"] == "public"
    assert public_payload["actor_id"] == "entity_1"


def test_safe_entity_helpers_cover_missing_and_dangling_paths(monkeypatch):
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    loose = spawn_entity(world)

    assert entity_name(character) == "Juniper"
    assert entity_name(loose) == str(loose.id)
    assert entity_name(loose, "something") == "something"
    assert room_id_for(world, scenario.character) == str(scenario.room_a)
    assert room_id_for(world, parse_entity_id("entity_999999")) is None
    assert entity_room_id(character) == str(scenario.room_a)

    original_has_entity = world.has_entity

    def has_entity(entity_id):
        if entity_id == scenario.room_a:
            return False
        return original_has_entity(entity_id)

    monkeypatch.setattr(world, "has_entity", has_entity)

    # reachable_ids must skip a containing room whose entity no longer exists: the
    # character is still contained by room_a (container_of returns it), but has_entity
    # is patched False, so the room and its contents are dropped — only the character
    # (and any of its own existing inventory) remains reachable.
    reachable = reachable_ids(world, character)
    assert reachable == {character.id}
    assert scenario.room_a not in reachable

    remove_from_container(world, scenario.character)
    assert entity_room_id(character) == str(scenario.room_a)


# -- regeneration -----------------------------------------------------------------------


async def test_action_focus_regenerate_over_time():
    scenario = build_scenario(action_current=0.0, focus_current=0.0)
    char = scenario.actor.world.get_entity(scenario.character)

    await scenario.actor.tick(HOUR)  # +1 action, +0.5 focus
    assert char.get_component(ActionPointsComponent).current == pytest.approx(1.0)
    assert char.get_component(FocusPointsComponent).current == pytest.approx(0.5)


async def test_regen_caps_at_maximum():
    scenario = build_scenario(action_current=4.5, focus_current=2.9)
    char = scenario.actor.world.get_entity(scenario.character)

    await scenario.actor.tick(10 * HOUR)
    assert char.get_component(ActionPointsComponent).current == pytest.approx(5.0)
    assert char.get_component(FocusPointsComponent).current == pytest.approx(3.0)


async def test_world_clock_advances():
    scenario = build_scenario()
    await scenario.actor.tick(HOUR)
    clock = scenario.actor._clock_entity.get_component(WorldClockComponent)
    assert clock.game_time_seconds == int(HOUR)
    assert clock.tick_index == 1
    assert scenario.actor.epoch == int(HOUR)


async def test_claim_timeout_suspends_inactive_web_controller():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    scenario.actor.assign_controller(scenario.character, web.id)
    apply_claim_timeout_settings(
        web,
        now_unix=0,
        fallback_controller="suspend",
        timeout_seconds=300,
        reset_activity=True,
    )
    changed = collect(scenario.actor, ControllerChangedEvent)
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(default_timeout_seconds=1800, now=lambda: 301)
    )

    await scenario.actor.tick(0)

    _edge, controller_id = character.get_relationships(ControlledBy)[0]
    controller = scenario.actor.world.get_entity(controller_id)
    assert character.has_component(SuspendedComponent)
    assert controller.has_component(SuspendedControllerComponent)
    assert changed[-1].controller_kind == "suspended"


async def test_claim_timeout_can_fall_back_to_llm():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    scenario.actor.assign_controller(scenario.character, web.id)
    apply_claim_timeout_settings(
        web,
        now_unix=0,
        fallback_controller="llm",
        llm_model="claim-model",
        llm_provider="openrouter",
        timeout_seconds=300,
        reset_activity=True,
    )
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(default_timeout_seconds=1800, now=lambda: 301)
    )

    await scenario.actor.tick(0)

    _edge, controller_id = character.get_relationships(ControlledBy)[0]
    controller = scenario.actor.world.get_entity(controller_id)
    llm = controller.get_component(LLMControllerComponent)
    assert not character.has_component(SuspendedComponent)
    assert llm.model == "claim-model"
    assert llm.provider == "openrouter"


async def test_claim_timeout_can_fall_back_to_existing_controller_with_claim():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(SuspendedComponent(reason="afk"))
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    existing = spawn_entity(
        scenario.actor.world,
        [LLMControllerComponent(profile_name="idle", model="claim-model")],
    )
    scenario.actor.assign_controller(scenario.character, web.id)
    claim = add_claim(
        web,
        client_kind="web",
        client_id="client",
        character_id=str(scenario.character),
        claim_id="claim-1",
    )
    timeout = apply_claim_timeout_settings(
        web,
        now_unix=0,
        fallback_controller=str(existing.id),
        timeout_seconds=300,
        reset_activity=True,
    )
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(default_timeout_seconds=1800, now=lambda: 301)
    )

    await scenario.actor.tick(0)

    assert character.get_relationships(ControlledBy)[0][1] == existing.id
    assert not character.has_component(SuspendedComponent)
    assert controller_claim(existing) == claim
    assert existing.get_component(ClaimTimeoutComponent) == timeout
    assert not web.has_component(ClaimedComponent)
    assert not web.has_component(ClaimTimeoutComponent)


async def test_claim_timeout_ignores_unknown_existing_fallback_controller():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    unknown = spawn_entity(scenario.actor.world)
    scenario.actor.assign_controller(scenario.character, web.id)
    apply_claim_timeout_settings(
        web,
        now_unix=0,
        fallback_controller=str(unknown.id),
        timeout_seconds=300,
        reset_activity=True,
    )
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(default_timeout_seconds=1800, now=lambda: 301)
    )

    await scenario.actor.tick(0)

    _edge, controller_id = character.get_relationships(ControlledBy)[0]
    assert controller_id != unknown.id
    assert scenario.actor.world.get_entity(controller_id).has_component(
        SuspendedControllerComponent
    )


async def test_claim_timeout_skips_existing_fallback_claimed_by_another_client():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    unavailable = spawn_entity(
        scenario.actor.world,
        [LLMControllerComponent(profile_name="idle", model="claim-model")],
    )
    scenario.actor.assign_controller(scenario.character, web.id)
    claim = add_claim(
        web,
        client_kind="web",
        client_id="client",
        character_id=str(scenario.character),
        claim_id="claim-1",
    )
    other_claim = add_claim(
        unavailable,
        client_kind="web",
        client_id="other",
        character_id="other-character",
        claim_id="claim-2",
    )
    apply_claim_timeout_settings(
        web,
        now_unix=0,
        fallback_controller=str(unavailable.id),
        timeout_seconds=300,
        reset_activity=True,
    )
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(default_timeout_seconds=1800, now=lambda: 301)
    )

    await scenario.actor.tick(0)

    _edge, controller_id = character.get_relationships(ControlledBy)[0]
    controller = scenario.actor.world.get_entity(controller_id)
    assert controller.id != unavailable.id
    assert controller.has_component(SuspendedControllerComponent)
    assert controller_claim(controller) == claim
    assert controller_claim(unavailable) == other_claim


async def test_claim_timeout_llm_fallback_clears_suspended_component():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    scenario.actor.assign_controller(scenario.character, web.id)
    # Character is already suspended when the LLM fallback fires (line 180 path).
    character.add_component(SuspendedComponent(reason="afk"))
    apply_claim_timeout_settings(
        web,
        now_unix=0,
        fallback_controller="llm",
        timeout_seconds=300,
        reset_activity=True,
    )
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(default_timeout_seconds=1800, now=lambda: 301)
    )

    await scenario.actor.tick(0)

    assert not character.has_component(SuspendedComponent)


async def test_claim_timeout_noops_without_controller_kinds():
    scenario = build_scenario()
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    scenario.actor.assign_controller(scenario.character, web.id)
    apply_claim_timeout_settings(
        web,
        now_unix=0,
        fallback_controller="suspend",
        timeout_seconds=300,
        reset_activity=True,
    )
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(controller_kinds=(), now=lambda: 999999)
    )

    await scenario.actor.tick(0)

    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(SuspendedComponent)


async def test_claim_timeout_skips_dangling_unmatched_and_untracked_controllers(monkeypatch):
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    # A web controller of the wrong kind for a discord-only timeout (kind mismatch path).
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    scenario.actor.assign_controller(scenario.character, web.id)

    # Make the controller look dangling: has_entity reports False for the edge target
    # while the relationship still exists (line 153 continue path).
    original_has_entity = scenario.actor.world.has_entity

    def has_entity(entity_id):
        if entity_id == web.id:
            return False
        return original_has_entity(entity_id)

    monkeypatch.setattr(scenario.actor.world, "has_entity", has_entity)
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(controller_kinds=("discord",), now=lambda: 999999)
    )

    await scenario.actor.tick(0)

    assert not character.has_component(SuspendedComponent)


async def test_claim_timeout_skips_controller_of_unconfigured_kind():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    scenario.actor.assign_controller(scenario.character, web.id)
    apply_claim_timeout_settings(
        web,
        now_unix=0,
        fallback_controller="suspend",
        timeout_seconds=300,
        reset_activity=True,
    )
    # The web controller's kind is not in the configured discord-only set (line 157 skip).
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(controller_kinds=("discord",), now=lambda: 999999)
    )

    await scenario.actor.tick(0)

    assert not character.has_component(SuspendedComponent)


async def test_claim_timeout_skips_matching_controller_without_claim_component():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    scenario.actor.assign_controller(scenario.character, web.id)
    # Matching kind but no ClaimTimeoutComponent -> skipped (line 159).
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(controller_kinds=("web",), now=lambda: 999999)
    )

    await scenario.actor.tick(0)

    assert not character.has_component(SuspendedComponent)


async def test_claim_timeout_leaves_active_controller_untouched():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    scenario.actor.assign_controller(scenario.character, web.id)
    apply_claim_timeout_settings(
        web,
        now_unix=300,
        fallback_controller="suspend",
        timeout_seconds=300,
        reset_activity=True,
    )
    # now - last_active = 0 < timeout, so the claim has not expired (163->151 branch).
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(default_timeout_seconds=1800, now=lambda: 300)
    )

    await scenario.actor.tick(0)

    assert not character.has_component(SuspendedComponent)


async def test_action_focus_regen_handles_focus_only_entity():
    scenario = build_scenario()
    # Entity with only FocusPoints exercises the 96->103 skip branch.
    focus_only = spawn_entity(
        scenario.actor.world,
        [FocusPointsComponent(current=0.0, maximum=3.0, regen_per_hour=0.5)],
    )

    await scenario.actor.tick(HOUR)

    assert focus_only.get_component(FocusPointsComponent).current == pytest.approx(0.5)


def test_claim_timeout_controller_kind_classifies_every_controller():
    scenario = build_scenario()
    world = scenario.actor.world
    classify = ClaimTimeoutSystem._controller_kind

    discord = spawn_entity(
        world, [DiscordControllerComponent(discord_user_id=1, default_channel_id=2)]
    )
    web = spawn_entity(world, [WebControllerComponent(client_id="c")])
    mcp = spawn_entity(world, [MCPControllerComponent(client_id="a")])
    llm = spawn_entity(world, [LLMControllerComponent(profile_name="default", model="m")])
    behavior = spawn_entity(world, [BehaviorControllerComponent(behavior_name="b")])
    scripted = spawn_entity(world, [ScriptedControllerComponent(script_name="s")])
    suspended = spawn_entity(world, [SuspendedControllerComponent(reason="r")])
    unknown = spawn_entity(world)

    assert classify(discord) == "discord"
    assert classify(web) == "web"
    assert classify(mcp) == "mcp"
    assert classify(llm) == "llm"
    assert classify(behavior) == "behavioral"
    assert classify(scripted) == "scripted"
    assert classify(suspended) == "suspended"
    assert classify(unknown) == "unknown"


async def test_claim_timeout_uses_player_timeout_before_server_default():
    scenario = build_scenario()
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    scenario.actor.assign_controller(scenario.character, web.id)
    apply_claim_timeout_settings(
        web,
        now_unix=0,
        fallback_controller="suspend",
        timeout_seconds=300,
        reset_activity=True,
    )
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(default_timeout_seconds=3600, now=lambda: 301)
    )

    await scenario.actor.tick(0)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_component(SuspendedComponent)


def test_claim_timeout_normalizers_accept_aliases_and_controller_ids():
    assert normalize_claim_fallback(None) == CLAIM_FALLBACK_SUSPEND
    assert normalize_claim_fallback(" suspended ") == CLAIM_FALLBACK_SUSPEND
    assert normalize_claim_fallback("offline") == CLAIM_FALLBACK_SUSPEND
    assert normalize_claim_fallback("AI") == CLAIM_FALLBACK_LLM
    assert normalize_claim_fallback("client") == "client"
    assert normalize_claim_fallback("manual") == "manual"
    assert normalize_claim_timeout(CLAIM_TIMEOUT_MIN_SECONDS) == CLAIM_TIMEOUT_MIN_SECONDS
    assert normalize_claim_timeout(CLAIM_TIMEOUT_MAX_SECONDS) == CLAIM_TIMEOUT_MAX_SECONDS

    with pytest.raises(
        ValueError,
        match=(
            "timeout_seconds must be between "
            f"{CLAIM_TIMEOUT_MIN_SECONDS} and {CLAIM_TIMEOUT_MAX_SECONDS}"
        ),
    ):
        normalize_claim_timeout(CLAIM_TIMEOUT_MIN_SECONDS - 1)


def test_claim_timeout_settings_preserve_existing_values_and_record_activity():
    scenario = build_scenario()
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    first = apply_claim_timeout_settings(
        web,
        now_unix=100,
        fallback_controller="ai",
        fallback_reason=" idle ",
        llm_profile_name=" guide ",
        llm_model=" model ",
        llm_provider=" provider ",
        timeout_seconds=CLAIM_TIMEOUT_MIN_SECONDS,
        reset_activity=True,
    )

    second = apply_claim_timeout_settings(
        web,
        now_unix=200,
        fallback_controller=None,
        fallback_reason=" ",
        llm_profile_name=" ",
        llm_model=" ",
        llm_provider=" ",
        timeout_seconds=None,
        reset_activity=False,
    )
    untracked = spawn_entity(scenario.actor.world)
    record_claim_activity(untracked, now_unix=500)
    record_claim_activity(web, now_unix=300)
    updated = web.get_component(type(first))

    assert first.fallback_controller == CLAIM_FALLBACK_LLM
    assert second.fallback_reason == "idle"
    assert second.llm_profile_name == "guide"
    assert second.llm_model == "model"
    assert second.llm_provider == "provider"
    assert second.timeout_seconds == CLAIM_TIMEOUT_MIN_SECONDS
    assert second.claimed_at_unix == 100
    assert updated.last_command_unix == 300


def test_claim_secret_registry_and_claim_helpers_cover_security_paths():
    scenario = build_scenario()
    registry = ClaimSecretRegistry()
    character = scenario.actor.world.get_entity(scenario.character)
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id=" client ")])
    scenario.actor.assign_controller(scenario.character, web.id)

    claim = add_claim(
        web,
        client_kind=" WEB ",
        client_id=" client ",
        character_id=str(scenario.character),
        label=" player ",
        claim_id="claim-1",
        now_unix=123,
    )
    secret = registry.issue(claim.claim_id)

    assert registry.has_secret(claim.claim_id)
    assert registry.secret(claim.claim_id) == secret
    assert registry.validate(claim.claim_id, secret)
    assert not registry.validate(claim.claim_id, None)
    assert not registry.validate("missing", secret)
    assert claim_matches(claim, "web", "client")
    assert not claim_matches(claim, "web", "other")
    assert not claim_matches(claim, "mcp", "client")
    assert character_has_claim(scenario.actor, character)
    assert claimable_characters(scenario.actor, [character], allow_child_claims=True) == []
    loose = spawn_entity(scenario.actor.world, [CharacterComponent()])
    assert character_has_claim(scenario.actor, loose) is False
    assert claimed_character_for(
        scenario.actor,
        client_kind="WEB",
        client_id=" client ",
    ) == (character, web, character.get_relationships(ControlledBy)[0][0], claim)
    assert claimed_character_for(
        scenario.actor,
        client_kind="web",
        client_id="missing",
    ) is None
    ensure_claim_secret(registry, claim, claim_id="claim-1", claim_secret=secret)

    with pytest.raises(PermissionError, match="invalid claim id"):
        ensure_claim_secret(registry, claim, claim_id="claim-2", claim_secret=secret)
    with pytest.raises(PermissionError, match="invalid claim secret"):
        ensure_claim_secret(registry, claim, claim_id="claim-1", claim_secret="wrong")

    registry.clear()
    assert not registry.has_secret(claim.claim_id)
    kept = add_claim(
        spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="kept")]),
        client_kind="web",
        client_id="kept",
        character_id=str(scenario.character),
        claim_id="kept-claim",
    )
    registry.issue(kept.claim_id)
    normalize_claimed_controllers_without_secrets(scenario.actor, registry)
    assert not web.has_component(ClaimedComponent)
    assert claimed_character_for(
        scenario.actor,
        client_kind="web",
        client_id="kept",
    ) is None

    assert controller_claim(spawn_entity(scenario.actor.world)) is None


def test_claim_helpers_skip_dangling_controller_edges(monkeypatch):
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    original_has_entity = scenario.actor.world.has_entity

    def has_entity(entity_id):
        if entity_id == scenario.controller:
            return False
        return original_has_entity(entity_id)

    monkeypatch.setattr(scenario.actor.world, "has_entity", has_entity)

    assert current_controller(scenario.actor, character) is None
    assert character_has_claim(scenario.actor, character) is False


def test_claim_transfer_and_removal_cover_conflicts_and_timeouts():
    scenario = build_scenario()
    old = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="old")])
    target = spawn_entity(scenario.actor.world, [LLMControllerComponent("default", "m")])
    same_target = spawn_entity(
        scenario.actor.world,
        [SuspendedControllerComponent(reason="idle")],
    )
    conflict = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="other")])
    registry = ClaimSecretRegistry()

    assert transfer_claim(old, target) is None
    claim = add_claim(
        old,
        client_kind="web",
        client_id="old",
        character_id=str(scenario.character),
        claim_id="claim-1",
    )
    registry.issue(claim.claim_id)
    timeout = ClaimTimeoutComponent(fallback_controller="llm", timeout_seconds=300)
    old.add_component(timeout)
    same_target.add_component(claim)
    same_target.add_component(ClaimTimeoutComponent(fallback_controller="suspend"))
    add_claim(
        conflict,
        client_kind="web",
        client_id="other",
        character_id="other-character",
        claim_id="claim-2",
    )

    assert transfer_claim(old, old) == claim
    with pytest.raises(RuntimeError, match="target controller is already claimed"):
        transfer_claim(old, conflict)

    assert transfer_claim(old, same_target) == claim
    assert same_target.get_component(ClaimedComponent) == claim
    assert same_target.get_component(ClaimTimeoutComponent) == timeout
    plain_controller = spawn_entity(scenario.actor.world)
    no_registry = add_claim(
        plain_controller,
        client_kind="web",
        client_id="plain",
        character_id=str(scenario.character),
        claim_id="plain-claim",
    )
    assert remove_claim(old, registry) is None
    assert remove_claim(plain_controller) == no_registry
    assert remove_claim(same_target, registry) == claim
    assert not registry.has_secret(claim.claim_id)


# -- movement ---------------------------------------------------------------------------


async def test_move_transfers_containment_and_spends_action():
    scenario = build_scenario()
    char = scenario.actor.world.get_entity(scenario.character)
    assert scenario.character_room() == scenario.room_a

    await scenario.actor.submit(move_command(scenario))
    await scenario.actor.tick(HOUR)

    assert scenario.character_room() == scenario.room_b
    # started at 5.0, regen capped at 5.0, spent 1 -> 4.0
    assert char.get_component(ActionPointsComponent).current == pytest.approx(4.0)


async def test_move_with_no_matching_exit_is_rejected():
    scenario = build_scenario()
    rejects = collect(scenario.actor, CommandRejectedEvent)

    cmd = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "west"},  # no such exit
    )
    await scenario.actor.submit(cmd)
    await scenario.actor.tick(HOUR)

    assert scenario.character_room() == scenario.room_a
    assert any(r.reason == "no matching exit" for r in rejects)
    # points are not spent on a rejected command
    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(ActionPointsComponent).current == pytest.approx(5.0)


# -- controller generation --------------------------------------------------------------


async def test_stale_controller_generation_rejected():
    scenario = build_scenario()
    rejects = collect(scenario.actor, CommandRejectedEvent)

    stale = move_command(scenario, generation=scenario.generation)  # gen 0
    # A new controller takes over, bumping generation to 1 and flushing queues.
    new_controller = spawn_entity(scenario.actor.world)
    scenario.actor.assign_controller(scenario.character, new_controller.id)

    await scenario.actor.submit(stale)
    await scenario.actor.tick(HOUR)

    assert scenario.character_room() == scenario.room_a
    assert any(r.reason == "stale controller generation" for r in rejects)


# -- insufficient points: deny vs queue -------------------------------------------------


async def test_insufficient_points_deny_is_rejected_immediately():
    scenario = build_scenario(action_current=0.0)
    rejects = collect(scenario.actor, CommandRejectedEvent)

    await scenario.actor.submit(
        move_command(scenario, on_insufficient=OnInsufficientPoints.DENY)
    )
    await scenario.actor.tick(0.0)  # no regen

    assert scenario.character_room() == scenario.room_a
    assert any(r.reason == "insufficient points" for r in rejects)


async def test_insufficient_points_queue_waits_then_executes():
    scenario = build_scenario(action_current=0.0)
    executed = collect(scenario.actor, CommandExecutedEvent)

    await scenario.actor.submit(
        move_command(scenario, on_insufficient=OnInsufficientPoints.QUEUE)
    )
    # First tick: tiny regen, still cannot afford 1 action -> stays queued.
    await scenario.actor.tick(0.1)
    assert scenario.character_room() == scenario.room_a
    assert executed == []

    # Enough time passes to regen >= 1 action -> command runs.
    await scenario.actor.tick(HOUR)
    assert scenario.character_room() == scenario.room_b
    assert len(executed) == 1


# -- suspended characters ---------------------------------------------------------------


async def test_suspended_character_regenerates_but_cannot_act():
    scenario = build_scenario(action_current=2.0)
    no_op_controller = spawn_entity(scenario.actor.world)
    scenario.actor.suspend(scenario.character, no_op_controller.id, reason="offline")

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.has_component(SuspendedComponent)
    assert no_op_controller.has_component(SuspendedControllerComponent)

    rejects = collect(scenario.actor, CommandRejectedEvent)
    # Command built under the suspended controller's generation.
    generation = scenario.actor.current_generation(scenario.character, no_op_controller.id)
    cmd = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(no_op_controller.id),
        controller_generation=generation,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "north"},
    )
    await scenario.actor.submit(cmd)
    await scenario.actor.tick(HOUR)

    # Still regenerated (capped at 5), but did not move or spend.
    assert scenario.character_room() == scenario.room_a
    assert char.get_component(ActionPointsComponent).current == pytest.approx(3.0)
    assert any(r.reason == "character is suspended" for r in rejects)


# -- initiative -------------------------------------------------------------------------


async def test_initiative_orders_execution_high_score_first():
    # Two independent characters; the higher-initiative one should execute first.
    scenario = build_scenario(initiative=1.0)
    actor = scenario.actor

    # Second character in room_a with higher initiative and its own controller.
    other = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(species="bunny"),
            ActionPointsComponent(current=5.0, maximum=5.0, regen_per_hour=1.0),
            InitiativeComponent(score=9.0),
        ],
    )
    actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), other.id
    )
    other_controller = spawn_entity(actor.world)
    other_gen = actor.assign_controller(other.id, other_controller.id)

    order = []
    actor.bus.subscribe(CommandExecutedEvent, lambda e: order.append(e.actor_id))

    await actor.submit(move_command(scenario))  # initiative 1.0
    await actor.submit(
        build_submitted_command(
            character_id=str(other.id),
            controller_id=str(other_controller.id),
            controller_generation=other_gen,
            command_type="move",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload={"direction": "north"},
        )
    )
    await actor.tick(HOUR)

    assert order == [str(other.id), str(scenario.character)]


def test_initiative_tiebreak_is_randomized():
    # Pure unit check of the ordering helper with tied scores and seeded RNG.
    scenario = build_scenario()
    actor = scenario.actor
    actor._rng = random.Random(0)
    ids = ["entity_1", "entity_2", "entity_3"]
    # No entities exist for these ids -> all score 0.0, so order is purely random jitter.
    ordering = actor._initiative_order(ids)
    assert sorted(ordering) == sorted(ids)
