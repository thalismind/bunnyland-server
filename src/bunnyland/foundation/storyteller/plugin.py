"""Canonical Storyteller plugin entrypoint."""

from ...mechanics.storyteller import (
    IncidentBudgetComponent,
    IncidentComponent,
    IncidentGeneratedEvent,
    IncidentHistoryComponent,
    IncidentProposedEvent,
    IncidentResolvedEvent,
    IncidentSpawned,
    IncidentStartedEvent,
    ResolveIncidentHandler,
    StorytellerComponent,
    ThreatPointsComponent,
    default_incident_definitions,
    install_storyteller,
    storyteller_fragments,
)
from ...plugins.model import (
    CommandContribution,
    ContentContribution,
    DependencyContribution,
    EcsContribution,
    Plugin,
    PluginPlacement,
    RuntimeContribution,
)


def plugin() -> Plugin:
    return Plugin(
        id="bunnyland.storyteller",
        name="Storyteller",
        placement=PluginPlacement.FOUNDATION,
        dependencies=DependencyContribution(requires=("bunnyland.core_verbs",)),
        ecs=EcsContribution(
            components=(
                StorytellerComponent,
                IncidentBudgetComponent,
                ThreatPointsComponent,
                IncidentHistoryComponent,
                IncidentComponent,
            ),
            edges=(IncidentSpawned,),
        ),
        commands=CommandContribution(
            action_handlers=(ResolveIncidentHandler,),
            typed_events=(
                IncidentGeneratedEvent,
                IncidentProposedEvent,
                IncidentStartedEvent,
                IncidentResolvedEvent,
            ),
        ),
        runtime=RuntimeContribution(service_factories=(install_storyteller,)),
        content=ContentContribution(
            prompt_fragments=(storyteller_fragments,),
            incident_definitions=default_incident_definitions(),
        ),
    )


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
