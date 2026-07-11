"""Canonical Persona plugin entrypoint."""

from bunnyland.core.generation import GenerationDelta, GenerationRequest
from bunnyland.foundation.persona.mechanics import (
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

GOALS_CAPABILITY = "bunnyland.persona.goals"
GOALS_CONTEXT = "bunnyland.persona.active_goals"


class PersonaGenerationEnricher:
    """Materialize goals requested through the public Persona generation capability."""

    capabilities = (GOALS_CAPABILITY,)

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        goals = tuple(request.context.get(GOALS_CONTEXT, ()))
        if request.entity_kind != "character" or not goals:
            return GenerationDelta()
        existing = next(
            (
                component
                for component in request.context.get("base_components", ())
                if isinstance(component, GoalComponent)
            ),
            None,
        )
        if existing is not None:
            return GenerationDelta()
        return GenerationDelta(
            components=(GoalComponent(active_goals=tuple(dict.fromkeys(goals))),)
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
        content=ContentContribution(
            persona_fragments=(persona_fragments,),
            generation_capabilities=(GOALS_CAPABILITY,),
            generation_enrichers=(PersonaGenerationEnricher(),),
        ),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = [
    "GOALS_CAPABILITY",
    "GOALS_CONTEXT",
    "PersonaGenerationEnricher",
    "bunnyland_plugins",
    "plugin",
]
