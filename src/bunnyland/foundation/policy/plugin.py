"""Canonical Policy plugin entrypoint."""

from bunnyland.foundation.policy.mechanics import (
    BoundaryTag,
    CharacterBoundaryComponent,
    WorldPolicyComponent,
    boundary_fragments,
    install_policy,
)

from ...plugins.ids import (
    CORE_VERBS,
    POLICY,
)
from ...plugins.model import (
    ContentContribution,
    DependencyContribution,
    EcsContribution,
    Plugin,
    PluginPlacement,
    PolicyContribution,
    RuntimeContribution,
)


def _policy_factory(actor) -> None:
    install_policy(actor)


def _definition() -> Plugin:
    return Plugin(
        id=POLICY,
        name="Policy & Boundaries",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(components=(WorldPolicyComponent, CharacterBoundaryComponent)),
        runtime=RuntimeContribution(service_factories=(_policy_factory,)),
        content=ContentContribution(persona_fragments=(boundary_fragments,)),
        policy=PolicyContribution(boundary_tags=frozenset(BoundaryTag)),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
