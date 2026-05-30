"""Character persona: traits, preferences, and goals (spec 11.12).

These are descriptive, not mechanical — they give a character personality and direction that
the LLM roleplays. They surface in the foundation prompt via ``persona_fragments`` (the same
fragment pipeline needs/weather/relationships use). Worldgen may set them; admins and plugins
can too. Empty components contribute nothing, so the feature is inert until populated.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic.dataclasses import dataclass
from relics import Component, Entity, World


@dataclass(frozen=True)
class TraitSetComponent(Component):
    traits: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreferenceComponent(Component):
    likes: tuple[str, ...] = ()
    dislikes: tuple[str, ...] = ()


@dataclass(frozen=True)
class GoalComponent(Component):
    active_goals: tuple[str, ...] = ()


def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def persona_fragments(world: World, character: Entity) -> list[str]:
    """Foundation-prompt lines describing who the character is and what they want."""
    del world
    lines: list[str] = []
    if character.has_component(TraitSetComponent):
        traits = character.get_component(TraitSetComponent).traits
        if traits:
            lines.append(f"You are {_join(traits)}.")
    if character.has_component(PreferenceComponent):
        preference = character.get_component(PreferenceComponent)
        if preference.likes:
            lines.append(f"You like {_join(preference.likes)}.")
        if preference.dislikes:
            lines.append(f"You dislike {_join(preference.dislikes)}.")
    if character.has_component(GoalComponent):
        goals = character.get_component(GoalComponent).active_goals
        if goals:
            lines.append(f"Your goal: {_join(goals)}.")
    return lines


__all__ = [
    "GoalComponent",
    "PreferenceComponent",
    "TraitSetComponent",
    "persona_fragments",
]
