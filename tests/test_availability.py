"""Tests for coarse per-action availability and synchronous submit rejection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from conftest import build_scenario
from relics import Component, Edge

from bunnyland.core import (
    ActionArgument,
    ActionDefinition,
    ActionRequirement,
    CommandCost,
    ContainmentMode,
    Contains,
    DeadComponent,
    Lane,
    OnInsufficientPoints,
    SayHandler,
    SleepingComponent,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.availability import (
    affordable,
    evaluate_availability,
    lifecycle_block_reason,
    meets_requirement,
    target_group_for_argument,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.core.handlers import HandlerResult, ok
from bunnyland.mechanics.lifesim import SkillSetComponent


@dataclass(frozen=True)
class _Spellbook(Component):
    pass


@dataclass(frozen=True)
class _Anvil(Component):
    pass


@dataclass(frozen=True)
class _Knows(Edge):
    pass


def _definition(
    command_type: str = "demo",
    *,
    cost: CommandCost | None = None,
    arguments: dict[str, ActionArgument] | None = None,
    requirement: ActionRequirement | None = None,
) -> ActionDefinition:
    return ActionDefinition(
        command_type=command_type,
        arguments=arguments,
        cost=cost or CommandCost(action=1),
        requirement=requirement or ActionRequirement(),
    )


def _character(scenario):
    return scenario.actor.world.get_entity(scenario.character)


# -- evaluate_availability ------------------------------------------------------------


def test_available_when_affordable_and_unrestricted():
    scenario = build_scenario()
    result = evaluate_availability(
        scenario.actor, _character(scenario), _definition(), target_groups={}
    )

    assert result.available is True
    assert result.enough_action_points is True
    assert result.enough_focus_points is True
    assert result.has_required_target is True
    assert result.meets_requirements is True
    assert result.can_act is True
    assert result.reason == ""


def test_unavailable_when_not_enough_action_points():
    scenario = build_scenario(action_current=0.0)
    result = evaluate_availability(
        scenario.actor,
        _character(scenario),
        _definition(cost=CommandCost(action=2)),
        target_groups={},
    )

    assert result.enough_action_points is False
    assert result.available is False
    assert result.reason == "not enough action points"


def test_unavailable_when_not_enough_focus_points():
    scenario = build_scenario(focus_current=0.0)
    result = evaluate_availability(
        scenario.actor,
        _character(scenario),
        _definition(cost=CommandCost(focus=1)),
        target_groups={},
    )

    assert result.enough_focus_points is False
    assert result.available is False
    assert result.reason == "not enough focus points"


def test_required_target_tracks_candidate_lists():
    scenario = build_scenario()
    definition = _definition(
        arguments={"target_id": ActionArgument(kind="entity", required=True)},
    )
    # target_id maps to the generic "reachable" group.
    assert target_group_for_argument(definition, "target_id") == "reachable"

    empty = evaluate_availability(
        scenario.actor, _character(scenario), definition, target_groups={"reachable": []}
    )
    assert empty.has_required_target is False
    assert empty.available is False
    assert empty.reason == "no valid target available"

    present = evaluate_availability(
        scenario.actor,
        _character(scenario),
        definition,
        target_groups={"reachable": ["something"]},
    )
    assert present.has_required_target is True
    assert present.available is True


def test_requirement_met_via_character_component():
    scenario = build_scenario()
    character = _character(scenario)
    requirement = ActionRequirement(character_components=("_Spellbook",))

    unmet = evaluate_availability(
        scenario.actor, character, _definition(requirement=requirement), target_groups={}
    )
    assert unmet.meets_requirements is False
    assert unmet.reason == "missing a required skill or item"

    character.add_component(_Spellbook())
    met = evaluate_availability(
        scenario.actor, character, _definition(requirement=requirement), target_groups={}
    )
    assert met.meets_requirements is True


def test_requirement_met_via_character_edge():
    scenario = build_scenario()
    character = _character(scenario)
    requirement = ActionRequirement(character_edges=("_Knows",))

    assert (
        meets_requirement(scenario.actor.world, character, requirement) is False
    )

    character.add_relationship(_Knows(), scenario.room_b)
    assert meets_requirement(scenario.actor.world, character, requirement) is True


def test_requirement_met_via_reachable_component():
    scenario = build_scenario()
    character = _character(scenario)
    requirement = ActionRequirement(reachable_components=("_Anvil",))

    assert meets_requirement(scenario.actor.world, character, requirement) is False

    anvil = spawn_entity(scenario.actor.world, [_Anvil()])
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), anvil.id)
    assert meets_requirement(scenario.actor.world, character, requirement) is True


def test_can_act_reflects_lifecycle_gates():
    scenario = build_scenario()
    character = _character(scenario)
    character.add_component(DeadComponent(died_at_epoch=0, cause="test"))

    assert lifecycle_block_reason(character, "demo") == "character is dead"
    result = evaluate_availability(
        scenario.actor, character, _definition(), target_groups={}
    )
    assert result.can_act is False
    assert result.available is False
    assert result.reason == "character is dead"


def test_sleeping_character_can_still_wake():
    scenario = build_scenario()
    character = _character(scenario)
    character.add_component(SleepingComponent())

    assert lifecycle_block_reason(character, "look") == "character is asleep"
    assert lifecycle_block_reason(character, "wake") is None


def test_affordable_treats_missing_component_as_zero():
    scenario = build_scenario(action_current=1.0, focus_current=0.0)
    character = _character(scenario)
    enough_action, enough_focus = affordable(character, CommandCost(action=1, focus=1))
    assert enough_action is True
    assert enough_focus is False


# -- submit early rejection -----------------------------------------------------------


def _say_command(scenario, payload, **kwargs):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="say",
        cost=CommandCost(action=1, focus=1),
        lane=Lane.WORLD,
        payload=payload,
        **kwargs,
    )


def _capture_rejections(actor):
    rejected: list[CommandRejectedEvent] = []
    actor.bus.subscribe(CommandRejectedEvent, rejected.append)
    return rejected


def test_submit_rejects_missing_required_argument():
    scenario = build_scenario()
    scenario.actor.register_handler(SayHandler())
    rejected = _capture_rejections(scenario.actor)

    outcome = asyncio.run(scenario.actor.submit(_say_command(scenario, {})))

    assert outcome.accepted is False
    assert outcome.reason == "missing required argument: text"
    assert scenario.actor.pending_submissions() == []
    assert [event.reason for event in rejected] == ["missing required argument: text"]


def test_submit_accepts_valid_command():
    scenario = build_scenario()
    scenario.actor.register_handler(SayHandler())

    outcome = asyncio.run(
        scenario.actor.submit(_say_command(scenario, {"text": "hello"}))
    )

    assert outcome.accepted is True
    assert outcome.reason == ""
    assert len(scenario.actor.pending_submissions()) == 1


def test_submit_rejects_unknown_command_type():
    scenario = build_scenario()
    command = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="take",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"item_id": "x"},
    )

    outcome = asyncio.run(scenario.actor.submit(command))

    assert outcome.accepted is False
    assert outcome.reason == "no handler for take"


def test_submit_denies_unaffordable_only_under_deny_policy():
    scenario = build_scenario(action_current=0.0)
    scenario.actor.register_handler(SayHandler())

    denied = asyncio.run(
        scenario.actor.submit(
            _say_command(
                scenario,
                {"text": "hi"},
                on_insufficient_points=OnInsufficientPoints.DENY,
            )
        )
    )
    assert denied.accepted is False
    assert denied.reason == "insufficient points"

    queued = asyncio.run(
        scenario.actor.submit(
            _say_command(
                scenario,
                {"text": "hi"},
                on_insufficient_points=OnInsufficientPoints.QUEUE,
            )
        )
    )
    assert queued.accepted is True


def test_submit_rejects_when_character_cannot_act():
    scenario = build_scenario()
    scenario.actor.register_handler(SayHandler())
    _character(scenario).add_component(DeadComponent(died_at_epoch=0, cause="test"))

    outcome = asyncio.run(
        scenario.actor.submit(_say_command(scenario, {"text": "hi"}))
    )

    assert outcome.accepted is False
    assert outcome.reason == "character is dead"


def test_submit_rejects_unmet_capability_requirement():
    scenario = build_scenario()

    class _PickLockHandler:
        command_type = "pick-lock"

        def execute(self, ctx, command) -> HandlerResult:  # pragma: no cover - not run
            return ok()

    scenario.actor.register_handler(_PickLockHandler())

    def _pick(payload=None):
        return build_submitted_command(
            character_id=str(scenario.character),
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="pick-lock",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload=payload or {},
        )

    # The core "pick-lock" definition requires a SkillSetComponent.
    unmet = asyncio.run(scenario.actor.submit(_pick()))
    assert unmet.accepted is False
    assert unmet.reason == "missing a required skill or item"

    _character(scenario).add_component(SkillSetComponent(levels={"lockpicking": 1}))
    met = asyncio.run(scenario.actor.submit(_pick()))
    assert met.accepted is True
