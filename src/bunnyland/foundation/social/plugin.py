"""Canonical Social plugin entrypoint."""

from bunnyland.foundation.social.mechanics import (
    GossipClaimComponent,
    KnowsGossip,
    ObligationComponent,
    ObligationCreditor,
    ObligationDebtor,
    ObligationResolvedEvent,
    ResolveObligationHandler,
    SocialBond,
    gossip_fragments,
    install_social,
    obligation_fragments,
    relationship_fragments,
)

from ...plugins.ids import (
    CORE_VERBS,
    SOCIAL,
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
from .actions import ACTION_DEFINITIONS


def _social_factory(actor) -> None:
    install_social(actor)


def _definition() -> Plugin:
    return Plugin(
        id=SOCIAL,
        name="Social Bonds",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(
            components=(GossipClaimComponent, ObligationComponent),
            edges=(SocialBond, KnowsGossip, ObligationDebtor, ObligationCreditor),
        ),
        commands=CommandContribution(
            action_definitions=ACTION_DEFINITIONS,
            action_handlers=(ResolveObligationHandler,),
            typed_events=(ObligationResolvedEvent,),
        ),
        runtime=RuntimeContribution(service_factories=(_social_factory,)),
        content=ContentContribution(
            persona_fragments=(relationship_fragments, gossip_fragments, obligation_fragments)
        ),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
