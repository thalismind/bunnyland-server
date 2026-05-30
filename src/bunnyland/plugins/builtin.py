"""Builtin bunnyland plugins (spec 21.4): core verbs, lifesim, memory.

This module is a plugin source: ``bunnyland_plugins()`` returns the plugins it declares,
exactly as a third-party module would. The world actor still provides the always-on
spine (clock, Action/Focus regen, downed/death); these plugins add the optional verb
surface and mechanics so disabling one removes its components/systems/verbs.
"""

from __future__ import annotations

from ..core.handlers import (
    MoveHandler,
    PutHandler,
    SayHandler,
    SleepHandler,
    TakeHandler,
    TellHandler,
    UseHandler,
    WaitHandler,
    WakeHandler,
    WriteHandler,
)
from ..mechanics.affect import AffectAggregation, AffectReactor
from ..mechanics.consumables import ConsumableComponent, DrinkableComponent, FoodComponent
from ..mechanics.eat_drink import DrinkHandler, EatHandler
from ..mechanics.environment import (
    CalendarComponent,
    TimeOfDayComponent,
    WeatherComponent,
    install_environment,
)
from ..mechanics.mechanisms import install_mechanisms
from ..mechanics.needs import (
    HungerComponent,
    HungerSystem,
    ThirstComponent,
    ThirstSystem,
)
from ..mechanics.social import SocialBond, install_social
from ..memory import install_memory
from ..worldgen.generators import WorldGenerator, oneshot_generator, recursive_generator
from .model import (
    CommandContribution,
    ContentContribution,
    EcsContribution,
    Plugin,
    RuntimeContribution,
)

CORE_VERBS = "bunnyland.core_verbs"
LIFESIM = "bunnyland.lifesim"
MEMORY = "bunnyland.memory"
WORLDGEN = "bunnyland.worldgen"
ENVIRONMENT = "bunnyland.environment"
MECHANISMS = "bunnyland.mechanisms"
SOCIAL = "bunnyland.social"


def _install_affect(actor) -> None:
    reactor = AffectReactor(actor.world)
    reactor.subscribe(actor.bus)
    actor.register_consequence(AffectAggregation())


def core_verbs_plugin() -> Plugin:
    return Plugin(
        id=CORE_VERBS,
        name="Core Verbs",
        commands=CommandContribution(
            action_handlers=(
                MoveHandler,
                TakeHandler,
                PutHandler,
                UseHandler,
                WriteHandler,
                SleepHandler,
                WakeHandler,
                WaitHandler,
                SayHandler,
                TellHandler,
            )
        ),
    )


def lifesim_plugin() -> Plugin:
    return Plugin(
        id=LIFESIM,
        name="Life Sim",
        dependencies=(CORE_VERBS,),
        ecs=EcsContribution(
            components=(
                HungerComponent,
                ThirstComponent,
                FoodComponent,
                DrinkableComponent,
                ConsumableComponent,
            ),
            systems=(HungerSystem, ThirstSystem),
        ),
        commands=CommandContribution(action_handlers=(EatHandler, DrinkHandler)),
        runtime=RuntimeContribution(service_factories=(_install_affect,)),
    )


def memory_plugin() -> Plugin:
    return Plugin(
        id=MEMORY,
        name="Memory",
        dependencies=(CORE_VERBS,),
        runtime=RuntimeContribution(service_factories=(_memory_factory,)),
    )


def _memory_factory(actor) -> None:
    install_memory(actor)


def _environment_factory(actor) -> None:
    install_environment(actor)


def environment_plugin() -> Plugin:
    return Plugin(
        id=ENVIRONMENT,
        name="Environment",
        ecs=EcsContribution(
            components=(CalendarComponent, TimeOfDayComponent, WeatherComponent)
        ),
        runtime=RuntimeContribution(service_factories=(_environment_factory,)),
    )


def _mechanisms_factory(actor) -> None:
    install_mechanisms(actor)


def mechanisms_plugin() -> Plugin:
    return Plugin(
        id=MECHANISMS,
        name="Mechanisms",
        dependencies=(CORE_VERBS,),
        runtime=RuntimeContribution(service_factories=(_mechanisms_factory,)),
    )


def _social_factory(actor) -> None:
    install_social(actor)


def social_plugin() -> Plugin:
    return Plugin(
        id=SOCIAL,
        name="Social Bonds",
        dependencies=(CORE_VERBS,),
        ecs=EcsContribution(edges=(SocialBond,)),
        runtime=RuntimeContribution(service_factories=(_social_factory,)),
    )


def worldgen_plugin() -> Plugin:
    return Plugin(
        id=WORLDGEN,
        name="World Generators",
        content=ContentContribution(
            world_generators=(
                WorldGenerator(
                    "oneshot", oneshot_generator, "single LLM proposal, instantiated at once"
                ),
                WorldGenerator(
                    "recursive", recursive_generator, "breadth-first graph, grown room-by-room"
                ),
            )
        ),
    )


def bunnyland_plugins() -> list[Plugin]:
    return [
        core_verbs_plugin(),
        lifesim_plugin(),
        memory_plugin(),
        worldgen_plugin(),
        environment_plugin(),
        mechanisms_plugin(),
        social_plugin(),
    ]


__all__ = [
    "CORE_VERBS",
    "ENVIRONMENT",
    "LIFESIM",
    "MECHANISMS",
    "MEMORY",
    "SOCIAL",
    "WORLDGEN",
    "bunnyland_plugins",
    "core_verbs_plugin",
    "environment_plugin",
    "lifesim_plugin",
    "mechanisms_plugin",
    "memory_plugin",
    "social_plugin",
    "worldgen_plugin",
]
