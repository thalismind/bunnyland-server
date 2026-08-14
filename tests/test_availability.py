"""Tests for coarse per-action availability and synchronous submit rejection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from conftest import build_scenario
from relics import Component, Edge

from bunnyland.core import (
    ActionArgument,
    ActionDefinition,
    ActionPointsComponent,
    ActionRequirement,
    CommandCost,
    ContainmentMode,
    Contains,
    DeadComponent,
    DownedComponent,
    Lane,
    MutationPlan,
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
from bunnyland.core.handlers import HandlerResult, planned
from bunnyland.plugins import PluginRegistry, bunnyland_plugins
from bunnyland.simpacks.lifesim.mechanics import SkillSetComponent


def _action_definition(command_type):
    return PluginRegistry(bunnyland_plugins()).actions[command_type][1]


@dataclass(frozen=True)
class _SpellbookComponent(Component):
    pass


@dataclass(frozen=True)
class _AnvilComponent(Component):
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


def test_pickpocket_uses_visible_held_items_instead_of_take_targets():
    definition = _definition(
        command_type="pickpocket",
        arguments={
            "target_id": ActionArgument(kind="entity", required=True),
            "item_id": ActionArgument(kind="entity", required=True),
        },
    )

    assert target_group_for_argument(definition, "target_id") == "reachable"
    assert target_group_for_argument(definition, "item_id") == "heldItems"


def test_conversation_arguments_use_participant_scoped_target_groups():
    start = _definition(
        command_type="start-conversation",
        arguments={"target_ids": ActionArgument(kind="entity", required=True)},
    )
    line = _definition(
        command_type="conversation-line",
        arguments={"conversation_id": ActionArgument(kind="entity", required=True)},
    )
    end = _definition(
        command_type="end-conversation",
        arguments={"conversation_id": ActionArgument(kind="entity", required=True)},
    )

    assert target_group_for_argument(start, "target_ids") == "characters"
    assert target_group_for_argument(line, "conversation_id") == "conversationTurns"
    assert target_group_for_argument(end, "conversation_id") == "activeConversations"


def test_requirement_met_via_character_component():
    scenario = build_scenario()
    character = _character(scenario)
    requirement = ActionRequirement(character_components=("_SpellbookComponent",))

    unmet = evaluate_availability(
        scenario.actor, character, _definition(requirement=requirement), target_groups={}
    )
    assert unmet.meets_requirements is False
    assert unmet.reason == "missing a required skill or item"

    character.add_component(_SpellbookComponent())
    met = evaluate_availability(
        scenario.actor, character, _definition(requirement=requirement), target_groups={}
    )
    assert met.meets_requirements is True


def test_requirement_met_via_character_edge():
    scenario = build_scenario()
    character = _character(scenario)
    requirement = ActionRequirement(character_edges=("_Knows",))

    assert meets_requirement(scenario.actor.world, character, requirement) is False

    character.add_relationship(_Knows(), scenario.room_b)
    assert meets_requirement(scenario.actor.world, character, requirement) is True


def test_requirement_met_via_reachable_component():
    scenario = build_scenario()
    character = _character(scenario)
    requirement = ActionRequirement(reachable_components=("_AnvilComponent",))

    assert meets_requirement(scenario.actor.world, character, requirement) is False

    anvil = spawn_entity(scenario.actor.world, [_AnvilComponent()])
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), anvil.id)
    assert meets_requirement(scenario.actor.world, character, requirement) is True


def test_reachable_requirement_false_when_no_entity_has_component():
    # A reachable entity exists (so the iteration runs and the character's own
    # id is skipped), but none of them carry the required component, so the
    # check falls through to ``return False``.
    scenario = build_scenario()
    character = _character(scenario)
    requirement = ActionRequirement(reachable_components=("_AnvilComponent",))

    # Spawn an _AnvilComponent somewhere unreachable so the component type is registered
    # (otherwise the check short-circuits before scanning reachable entities).
    spawn_entity(scenario.actor.world, [_AnvilComponent()])
    # A reachable bystander that does NOT carry the required component.
    bystander = spawn_entity(scenario.actor.world, [_SpellbookComponent()])
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), bystander.id)

    assert meets_requirement(scenario.actor.world, character, requirement) is False


def test_can_act_reflects_lifecycle_gates():
    scenario = build_scenario()
    character = _character(scenario)
    character.add_component(DeadComponent(died_at_epoch=0, cause="test"))

    assert lifecycle_block_reason(character, "demo") == "character is dead"
    result = evaluate_availability(scenario.actor, character, _definition(), target_groups={})
    assert result.can_act is False
    assert result.available is False
    assert result.reason == "character is dead"


def test_downed_character_cannot_act():
    scenario = build_scenario()
    character = _character(scenario)
    character.add_component(DownedComponent(downed_at_epoch=0, cause="test"))

    assert lifecycle_block_reason(character, "demo") == "character is downed"
    result = evaluate_availability(scenario.actor, character, _definition(), target_groups={})
    assert result.can_act is False
    assert result.reason == "character is downed"


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


def _move_command(scenario, **kwargs):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="move",
        payload={"direction": "north"},
        **kwargs,
    )


def _capture_rejections(actor):
    rejected: list[CommandRejectedEvent] = []
    actor.bus.subscribe(CommandRejectedEvent, rejected.append)
    return rejected


def test_submit_rejects_missing_required_argument():
    scenario = build_scenario()
    scenario.actor.register_handler(SayHandler())
    scenario.actor.register_action_definition(_action_definition("say"))
    rejected = _capture_rejections(scenario.actor)

    outcome = asyncio.run(scenario.actor.submit(_say_command(scenario, {})))

    assert outcome.accepted is False
    assert outcome.reason == "missing required argument: text"
    assert scenario.actor.pending_submissions() == []
    assert [event.reason for event in rejected] == ["missing required argument: text"]


def test_submit_accepts_valid_command():
    scenario = build_scenario()
    scenario.actor.register_handler(SayHandler())

    outcome = asyncio.run(scenario.actor.submit(_say_command(scenario, {"text": "hello"})))

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
    # `move` costs one action point by its definition; `say` is free, so affordability has to
    # be exercised with a verb the server actually charges for.
    scenario = build_scenario(action_current=0.0)

    denied = asyncio.run(
        scenario.actor.submit(
            _move_command(
                scenario,
                on_insufficient_points=OnInsufficientPoints.DENY,
            )
        )
    )
    assert denied.accepted is False
    assert denied.reason == "insufficient points"

    queued = asyncio.run(
        scenario.actor.submit(
            _move_command(
                scenario,
                on_insufficient_points=OnInsufficientPoints.QUEUE,
            )
        )
    )
    assert queued.accepted is True


def test_submit_rejects_when_character_cannot_act():
    scenario = build_scenario()
    scenario.actor.register_handler(SayHandler())
    _character(scenario).add_component(DeadComponent(died_at_epoch=0, cause="test"))

    outcome = asyncio.run(scenario.actor.submit(_say_command(scenario, {"text": "hi"})))

    assert outcome.accepted is False
    assert outcome.reason == "character is dead"


def test_submit_rejects_unmet_capability_requirement():
    scenario = build_scenario()

    class _PickLockHandler:
        command_type = "pick-lock"

        def execute(self, ctx, command) -> HandlerResult:  # pragma: no cover - not run
            return planned(MutationPlan())

    scenario.actor.register_handler(_PickLockHandler())
    scenario.actor.register_action_definition(_action_definition("pick-lock"))

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


# -- server-owned cost and lane ---------------------------------------------------------
#
# The submitted cost and lane arrive from the wire on every client-facing surface. Before
# they were server-owned, a caller could send cost 0 to act for free, or a negative cost to
# mint points outright (the spend is a subtraction), and could pick which lane serialised
# its command. These pin that shut.


def _submitted(scenario, command_type, payload=None, **kwargs):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        payload=payload if payload is not None else {"direction": "north"},
        **kwargs,
    )


def test_submitted_zero_cost_does_not_make_an_action_free():
    scenario = build_scenario()
    command = _submitted(scenario, "move", cost=CommandCost(action=0, focus=0))

    asyncio.run(scenario.actor.submit(command))

    # `move` costs one action point by definition, whatever the caller asked for.
    assert command.cost == CommandCost(action=1, focus=0)


def test_submitted_negative_cost_cannot_mint_points():
    scenario = build_scenario()
    before = _character(scenario).get_component(ActionPointsComponent).current
    command = _submitted(scenario, "move", cost=CommandCost(action=-1000, focus=-1000))

    asyncio.run(scenario.actor.submit(command))
    asyncio.run(scenario.actor.tick(3600))

    assert command.cost == CommandCost(action=1, focus=0)
    # Regen is capped at the pool maximum, so the balance can never exceed where it started.
    assert _character(scenario).get_component(ActionPointsComponent).current <= before


def test_submitted_lane_does_not_choose_the_queue():
    scenario = build_scenario()
    # `remember` is a focus-lane action; asking for the world lane must not move it.
    command = _submitted(scenario, "remember", lane=Lane.WORLD, payload={"query": "moss"})

    asyncio.run(scenario.actor.submit(command))

    assert command.lane is Lane.FOCUS


def test_confirm_command_expectations_accepts_agreement_and_silence():
    scenario = build_scenario()

    # Stating nothing is the normal path.
    scenario.actor.confirm_command_expectations("move")
    # Stating the definition's own values agrees.
    scenario.actor.confirm_command_expectations(
        "move", cost=CommandCost(action=1, focus=0), lane=Lane.WORLD
    )
    # An unregistered verb has nothing to disagree with; submission rejects it separately.
    scenario.actor.confirm_command_expectations("not-a-verb", cost=CommandCost(action=99))


def test_confirm_command_expectations_rejects_a_disagreeing_cost():
    scenario = build_scenario()

    try:
        scenario.actor.confirm_command_expectations("move", cost=CommandCost(action=0))
    except ValueError as exc:
        assert "cost mismatch for 'move'" in str(exc)
        assert "action=1" in str(exc)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("expected a cost mismatch")


def test_confirm_command_expectations_rejects_a_disagreeing_lane():
    scenario = build_scenario()

    try:
        scenario.actor.confirm_command_expectations("remember", lane=Lane.WORLD)
    except ValueError as exc:
        assert "lane mismatch for 'remember'" in str(exc)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("expected a lane mismatch")
