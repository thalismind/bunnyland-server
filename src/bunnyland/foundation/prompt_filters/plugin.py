"""Canonical Prompt Filters plugin entrypoint."""

from ...plugins.ids import PROMPT_FILTERS
from ...plugins.model import ContentContribution, EcsContribution, Plugin, PluginPlacement
from .mechanics import (
    BUILTIN_PROMPT_FILTERS,
    CorruptedPromptFilterComponent,
    PromptFilterBinding,
    RecallPromptFilterComponent,
    RedactedPromptFilterComponent,
    StorytellerPromptFilterComponent,
)


def plugin() -> Plugin:
    return Plugin(
        id=PROMPT_FILTERS,
        name="Prompt Filters",
        placement=PluginPlacement.FOUNDATION,
        ecs=EcsContribution(
            components=(
                RedactedPromptFilterComponent,
                CorruptedPromptFilterComponent,
                RecallPromptFilterComponent,
                StorytellerPromptFilterComponent,
            ),
            edges=(PromptFilterBinding,),
        ),
        content=ContentContribution(prompt_filters=BUILTIN_PROMPT_FILTERS),
    )


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
