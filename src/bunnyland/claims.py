"""Shared helpers for assigning external controllers to characters."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from relics import Component

from .core import CharacterComponent, ControlledBy, IdentityComponent
from .mechanics.lifesim import LifeStageComponent

CHILD_LIFE_STAGES = frozenset({"baby", "infant", "toddler", "child"})


def is_child_character(character) -> bool:
    if not character.has_component(LifeStageComponent):
        return False
    stage = character.get_component(LifeStageComponent).stage
    return stage.lower() in CHILD_LIFE_STAGES


def match_character_by_name(characters: Iterable[Any], character_name: str):
    lowered = character_name.lower()
    character_list = list(characters)
    exact = [
        character
        for character in character_list
        if character.get_component(IdentityComponent).name.lower() == lowered
    ]
    if exact:
        return exact[0]
    prefix = [
        character
        for character in character_list
        if character.get_component(IdentityComponent).name.lower().startswith(lowered)
    ]
    if len(prefix) == 1:
        return prefix[0]
    if len(prefix) > 1:
        names = ", ".join(character.get_component(IdentityComponent).name for character in prefix)
        raise RuntimeError(f"multiple characters match {character_name!r}: {names}")
    return None


def claimable_characters(characters: Iterable[Any], *, allow_child_claims: bool):
    from .core import SuspendedComponent

    return [
        character
        for character in characters
        if character.has_component(SuspendedComponent)
        and (allow_child_claims or not is_child_character(character))
    ]


def matching_controller(
    actor,
    controller_component_type: type[Component],
    matches_controller: Callable[[Component], bool],
):
    controllers = actor.world.query().with_all([controller_component_type])
    for controller in sorted(controllers.execute_entities(), key=lambda item: str(item.id)):
        if matches_controller(controller.get_component(controller_component_type)):
            return controller
    return None


def controlled_character(
    actor,
    controller_component_type: type[Component],
    matches_controller: Callable[[Component], bool],
):
    controller = matching_controller(actor, controller_component_type, matches_controller)
    if controller is not None:
        controller_id = controller.id
        characters = actor.world.query().with_all([CharacterComponent]).execute_entities()
        for character in characters:
            for edge, target in character.get_relationships(ControlledBy):
                if target == controller_id:
                    return character.id, controller_id, edge.generation
    return None


__all__ = [
    "CHILD_LIFE_STAGES",
    "claimable_characters",
    "controlled_character",
    "is_child_character",
    "match_character_by_name",
    "matching_controller",
]
