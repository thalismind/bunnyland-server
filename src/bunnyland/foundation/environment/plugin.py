"""Canonical Environment plugin entrypoint."""

from ...mechanics.environment import (
    CalendarComponent,
    ExtinguishHandler,
    FireComponent,
    FireDamageEvent,
    FireExtinguishedEvent,
    FireSpreadEvent,
    FireStartedEvent,
    FlammableComponent,
    IgniteHandler,
    TimeOfDayComponent,
    WeatherComponent,
    environment_fragments,
    install_environment,
)
from ...plugins.ids import ENVIRONMENT
from ...plugins.model import (
    CommandContribution,
    ContentContribution,
    EcsContribution,
    Plugin,
    PluginPlacement,
    RuntimeContribution,
)
from .actions import ACTION_DEFINITIONS
from .generation import ALIASES, CAPABILITIES, GENERATION_ENRICHER


def _environment_factory(actor) -> None:
    install_environment(actor)


def _definition() -> Plugin:
    return Plugin(
        id=ENVIRONMENT,
        name="Environment",
        ecs=EcsContribution(
            components=(
                CalendarComponent,
                TimeOfDayComponent,
                WeatherComponent,
                FlammableComponent,
                FireComponent,
            )
        ),
        commands=CommandContribution(
            action_definitions=ACTION_DEFINITIONS,
            action_handlers=(IgniteHandler, ExtinguishHandler),
            typed_events=(
                FireStartedEvent,
                FireSpreadEvent,
                FireDamageEvent,
                FireExtinguishedEvent,
            ),
        ),
        runtime=RuntimeContribution(service_factories=(_environment_factory,)),
        content=ContentContribution(
            prompt_fragments=(environment_fragments,),
            generation_capabilities=CAPABILITIES,
            generation_aliases=ALIASES,
            generation_enrichers=(GENERATION_ENRICHER,),
        ),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
