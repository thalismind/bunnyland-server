"""Canonical Persona plugin entrypoint."""

from ...mechanics.persona import (
    GoalComponent,
    PersonaProfileComponent,
    PreferenceComponent,
    TraitSetComponent,
    persona_fragments,
)
from ...plugins.ids import PERSONA
from ...plugins.model import (
    ContentContribution,
    EcsContribution,
    Plugin,
    PluginPlacement,
)


def _definition() -> Plugin:
    return Plugin(
        id=PERSONA,
        name="Persona",
        ecs=EcsContribution(
            components=(
                PersonaProfileComponent,
                TraitSetComponent,
                PreferenceComponent,
                GoalComponent,
            )
        ),
        content=ContentContribution(persona_fragments=(persona_fragments,)),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
