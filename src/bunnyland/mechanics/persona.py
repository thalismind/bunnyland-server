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

from ..prompts import ComponentPromptContext


@dataclass(frozen=True)
class PersonaProfileComponent(Component):
    """Stable roleplay profile fields that should survive prompt/model swaps."""

    voice: str = ""
    role: str = ""

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        lines: list[str] = []
        if self.voice:
            lines.append(f"Your voice: {self.voice}.")
        if self.role:
            lines.append(f"Your current role: {self.role}.")
        return tuple(lines)


@dataclass(frozen=True)
class TraitSetComponent(Component):
    traits: tuple[str, ...] = ()

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        if not self.traits:
            return ()
        traits = _join(self.traits)
        return (
            ctx.perspective.choose(
                first=f"I am {traits}.",
                second=f"You are {traits}.",
                third=f"They are {traits}.",
            ),
        )


@dataclass(frozen=True)
class PreferenceComponent(Component):
    likes: tuple[str, ...] = ()
    dislikes: tuple[str, ...] = ()

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        lines: list[str] = []
        if self.likes:
            likes = _join(self.likes)
            lines.append(
                ctx.perspective.choose(
                    first=f"I like {likes}.",
                    second=f"You like {likes}.",
                    third=f"They like {likes}.",
                )
            )
        if self.dislikes:
            dislikes = _join(self.dislikes)
            lines.append(
                ctx.perspective.choose(
                    first=f"I dislike {dislikes}.",
                    second=f"You dislike {dislikes}.",
                    third=f"They dislike {dislikes}.",
                )
            )
        return tuple(lines)


@dataclass(frozen=True)
class GoalComponent(Component):
    active_goals: tuple[str, ...] = ()

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        if not self.active_goals:
            return ()
        goals = _join(self.active_goals)
        return (
            ctx.perspective.choose(
                first=f"My goal: {goals}.",
                second=f"Your goal: {goals}.",
                third=f"Their goal: {goals}.",
            ),
        )


def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def persona_fragments(world: World, character: Entity) -> list[str]:
    """Foundation-prompt lines describing who the character is and what they want."""
    lines: list[str] = []
    ctx = ComponentPromptContext.for_entity(world, character)
    if character.has_component(PersonaProfileComponent):
        lines.extend(character.get_component(PersonaProfileComponent).prompt_fragments(ctx))
    if character.has_component(TraitSetComponent):
        lines.extend(character.get_component(TraitSetComponent).prompt_fragments(ctx))
    if character.has_component(PreferenceComponent):
        lines.extend(character.get_component(PreferenceComponent).prompt_fragments(ctx))
    if character.has_component(GoalComponent):
        lines.extend(character.get_component(GoalComponent).prompt_fragments(ctx))
    return lines


__all__ = [
    "GoalComponent",
    "PersonaProfileComponent",
    "PreferenceComponent",
    "TraitSetComponent",
    "persona_fragments",
]
