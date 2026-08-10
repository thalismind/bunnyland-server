"""Canonical Bunnyland sandbox plugin entrypoint."""

from ..plugins.ids import CORE_VERBS, POLICY, WORLDGEN
from ..plugins.model import (
    CommandContribution,
    ContentContribution,
    DependencyContribution,
    EcsContribution,
    Plugin,
    PluginPlacement,
    PolicyContribution,
)
from ..worldgen.generators import WorldGenerator
from .actions import ACTION_DEFINITIONS
from .generation import CAPABILITIES, GENERATION_ENRICHER, sandbox_generator
from .mechanics import (
    AFTER_DARK_SCOPE,
    AcceptAfterDarkWarningHandler,
    AfterDarkConsentWithdrawnEvent,
    AfterDarkEntranceComponent,
    AfterDarkExitComponent,
    AfterDarkPassage,
    AfterDarkWarningAcceptedEvent,
    EnterAfterDarkHandler,
    LeaveAfterDarkHandler,
    WithdrawAfterDarkConsentHandler,
)

SANDBOX_PLUGIN_ID = "bunnyland.sandbox"

SANDBOX_GENERATOR = WorldGenerator(
    name="bunnyland-sandbox",
    generate=sandbox_generator,
    description=(
        "Crossroads, claimable New Arrivals, loaded-simpack regions, and an optional "
        "command-gated After Dark district."
    ),
    group="simpack sandbox",
)


def plugin() -> Plugin:
    return Plugin(
        id=SANDBOX_PLUGIN_ID,
        name="Bunnyland Sandbox",
        placement=PluginPlacement.ADDON,
        default_enabled=True,
        dependencies=DependencyContribution(
            requires=(CORE_VERBS, WORLDGEN, POLICY),
        ),
        ecs=EcsContribution(
            components=(AfterDarkEntranceComponent, AfterDarkExitComponent),
            edges=(AfterDarkPassage,),
        ),
        commands=CommandContribution(
            action_definitions=ACTION_DEFINITIONS,
            action_handlers=(
                AcceptAfterDarkWarningHandler,
                EnterAfterDarkHandler,
                LeaveAfterDarkHandler,
                WithdrawAfterDarkConsentHandler,
            ),
            typed_events=(
                AfterDarkWarningAcceptedEvent,
                AfterDarkConsentWithdrawnEvent,
            ),
        ),
        content=ContentContribution(
            world_generators=(SANDBOX_GENERATOR,),
            generation_capabilities=CAPABILITIES,
            generation_enrichers=(GENERATION_ENRICHER,),
        ),
        policy=PolicyContribution(boundary_tags=frozenset({AFTER_DARK_SCOPE})),
    )


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = [
    "SANDBOX_GENERATOR",
    "SANDBOX_PLUGIN_ID",
    "bunnyland_plugins",
    "plugin",
]
