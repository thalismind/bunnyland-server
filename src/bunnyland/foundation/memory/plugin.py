"""Canonical Memory plugin entrypoint."""

from ...core.components import MemoryProfileComponent
from ...memory import install_memory
from ...plugins.ids import (
    CORE_VERBS,
    MEMORY,
    PROMPT_FILTERS,
)
from ...plugins.model import (
    CommandContribution,
    DependencyContribution,
    Plugin,
    PluginPlacement,
    RuntimeContribution,
)
from ...prompts import AutomaticPromptFilter
from ..prompt_filters.mechanics import RecallPromptFilterComponent
from .actions import ACTION_DEFINITIONS


def _memory_factory(actor) -> None:
    install_memory(actor)


def _automatic_recall_factory(actor) -> None:
    definition_id = f"{PROMPT_FILTERS}.recall"
    if (
        actor.plugins is None
        or definition_id not in actor.plugins.prompt_filters
    ):
        return

    def component():
        policy = actor.memory_recall_policy
        if policy is None or policy.limit == 0:
            return None
        return RecallPromptFilterComponent(
            limit=policy.limit,
            min_score=policy.min_score,
        )

    actor.register_automatic_prompt_filter(
        AutomaticPromptFilter(
            definition_id=definition_id,
            required_component=MemoryProfileComponent,
            component_factory=component,
        )
    )


def _definition() -> Plugin:
    return Plugin(
        id=MEMORY,
        name="Memory",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        commands=CommandContribution(action_definitions=ACTION_DEFINITIONS),
        runtime=RuntimeContribution(
            service_factories=(_memory_factory,),
            integration_factories=(_automatic_recall_factory,),
        ),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
