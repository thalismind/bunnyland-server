"""Canonical shared Factions plugin entrypoint."""

from ...plugins.ids import CORE_VERBS, FACTIONS
from ...plugins.model import (
    CommandContribution,
    ContentContribution,
    DependencyContribution,
    EcsContribution,
    Plugin,
    PluginPlacement,
)
from .actions import ACTION_DEFINITIONS
from .generation import CAPABILITIES, GENERATION_ENRICHER
from .mechanics import (
    FactionComponent,
    FactionDisposition,
    FactionJoinedEvent,
    FactionLeftEvent,
    HasStandingWithFaction,
    JoinFactionHandler,
    LeaveFactionHandler,
    MemberOfFaction,
    faction_fragments,
)


def _definition() -> Plugin:
    return Plugin(
        id=FACTIONS,
        name="Factions",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(
            components=(FactionComponent,),
            edges=(MemberOfFaction, HasStandingWithFaction, FactionDisposition),
        ),
        commands=CommandContribution(
            action_definitions=ACTION_DEFINITIONS,
            action_handlers=(JoinFactionHandler, LeaveFactionHandler),
            typed_events=(FactionJoinedEvent, FactionLeftEvent),
        ),
        content=ContentContribution(
            prompt_fragments=(faction_fragments,),
            generation_capabilities=CAPABILITIES,
            generation_enrichers=(GENERATION_ENRICHER,),
        ),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
