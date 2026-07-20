"""Coarse, cheap per-action availability checks shared by the projection and submit.

The character projection uses this to tell clients which actions a character can take
right now (enough points, a valid target, and a met capability requirement). The submit
path reuses the same helpers to reject obviously-invalid commands synchronously instead
of queuing them to fail at the next tick.

This layer is intentionally argument-agnostic and cheap (O(1) component/edge lookups via
the Relics registries, plus the already room+inventory-scoped reachable set). Fine-grained,
argument-specific gates -- e.g. "skill level high enough for *this* spell" -- stay inside
the handler, which remains the source of truth at execution time.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from relics import Entity, World

from .actions import ActionDefinition, ActionRequirement
from .commands import CommandCost
from .components import (
    ActionPointsComponent,
    DeadComponent,
    DownedComponent,
    FocusPointsComponent,
    SleepingComponent,
    SuspendedComponent,
)
from .ecs import reachable_ids
from .handlers.lifecycle import WakeHandler

if TYPE_CHECKING:
    from .world_actor import WorldActor


@dataclass(frozen=True)
class AvailabilityResult:
    """Per-action availability for one character, as surfaced in the projection."""

    available: bool
    enough_action_points: bool
    enough_focus_points: bool
    has_required_target: bool
    meets_requirements: bool
    can_act: bool
    reason: str = ""


def affordable(character: Entity, cost: CommandCost) -> tuple[bool, bool]:
    """Return ``(enough_action_points, enough_focus_points)`` for a cost.

    A missing points component counts as zero available, so a character with no points
    component can still afford a free action.
    """

    action_have = (
        character.get_component(ActionPointsComponent).current
        if character.has_component(ActionPointsComponent)
        else 0.0
    )
    focus_have = (
        character.get_component(FocusPointsComponent).current
        if character.has_component(FocusPointsComponent)
        else 0.0
    )
    return action_have >= cost.action, focus_have >= cost.focus


def lifecycle_block_reason(character: Entity, command_type: str) -> str | None:
    """Why a character cannot act at all right now, or ``None`` if it can.

    Mirrors the character-level gates in ``WorldActor._attempt`` (dead/suspended/downed,
    and asleep for everything but waking).
    """

    if character.has_component(DeadComponent):
        return "character is dead"
    if character.has_component(SuspendedComponent):
        return "character is suspended"
    if character.has_component(DownedComponent):
        return "character is downed"
    if character.has_component(SleepingComponent) and command_type != WakeHandler.command_type:
        return "character is asleep"
    return None


def _has_any_component(world: World, character: Entity, names: Sequence[str]) -> bool:
    for name in names:
        component_type = world._component_types.get(name)
        if component_type is not None and character.has_component(component_type):
            return True
    return False


def _has_any_edge(world: World, character: Entity, names: Sequence[str]) -> bool:
    for name in names:
        edge_type = world._edge_types.get(name)
        if edge_type is not None and character.get_relationships(edge_type):
            return True
    return False


def _reachable_has_any_component(world: World, character: Entity, names: Sequence[str]) -> bool:
    types = [world._component_types.get(name) for name in names]
    types = [component_type for component_type in types if component_type is not None]
    if not types:
        return False
    for reachable_id in reachable_ids(world, character):
        if reachable_id == character.id or not world.has_entity(reachable_id):
            continue
        entity = world.get_entity(reachable_id)
        if any(entity.has_component(component_type) for component_type in types):
            return True
    return False


def meets_requirement(world: World, character: Entity, requirement: ActionRequirement) -> bool:
    """Coarse any-of capability gate. Empty requirement always passes.

    Requirement names are resolved against the world's component/edge registries; an
    unknown name resolves to nothing and so fails closed (a catalogue test guards typos).
    """

    if requirement.is_empty:
        return True
    return (
        _has_any_component(world, character, requirement.character_components)
        or _has_any_edge(world, character, requirement.character_edges)
        or _reachable_has_any_component(world, character, requirement.reachable_components)
    )


def target_group_for_argument(definition: ActionDefinition, key: str) -> str | None:
    """Map a command argument to the projection target group that lists its candidates."""

    if key == "exit_id":
        return "exits"
    if key == "target_id" and definition.command_type == "tell":
        return "characters"
    if key == "item_id":
        if definition.command_type == "pickpocket":
            return "heldItems"
        return "inventory" if definition.command_type in {"drop", "put"} else "reachableItems"
    if key == "source_id":
        return "reachableItems"
    if key == "target_container_id":
        return "reachableItems"
    argument = (definition.arguments or {}).get(key)
    if argument is not None and argument.kind == "entity":
        return "reachable"
    return None


def _has_required_target(
    definition: ActionDefinition, target_groups: Mapping[str, Sequence[Any]]
) -> bool:
    """Whether every required entity argument has at least one candidate in the room."""

    for key, argument in (definition.arguments or {}).items():
        if argument.kind != "entity" or not argument.required:
            continue
        group = target_group_for_argument(definition, key)
        candidates = target_groups.get(group, ()) if group else ()
        if not candidates:
            return False
    return True


def evaluate_availability(
    actor: WorldActor,
    character: Entity,
    definition: ActionDefinition,
    *,
    target_groups: Mapping[str, Sequence[Any]] | None = None,
) -> AvailabilityResult:
    """Coarse availability of one action for one character, for the projection.

    ``target_groups`` is the precomputed candidate lists from the character projection;
    when omitted, target availability is not evaluated (treated as satisfied).
    """

    world = actor.world
    enough_action, enough_focus = affordable(character, definition.cost)
    meets = meets_requirement(world, character, definition.requirement)
    has_target = True if target_groups is None else _has_required_target(definition, target_groups)
    can_act = lifecycle_block_reason(character, definition.command_type) is None
    available = can_act and meets and has_target and enough_action and enough_focus

    reason = ""
    if not available:
        if not can_act:
            reason = (
                lifecycle_block_reason(character, definition.command_type) or "character cannot act"
            )
        elif not meets:
            reason = "missing a required skill or item"
        elif not has_target:
            reason = "no valid target available"
        elif not enough_action:
            reason = "not enough action points"
        else:
            reason = "not enough focus points"

    return AvailabilityResult(
        available=available,
        enough_action_points=enough_action,
        enough_focus_points=enough_focus,
        has_required_target=has_target,
        meets_requirements=meets,
        can_act=can_act,
        reason=reason,
    )


__all__ = [
    "AvailabilityResult",
    "affordable",
    "evaluate_availability",
    "lifecycle_block_reason",
    "meets_requirement",
    "target_group_for_argument",
]
