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
    environment_fragments,
    install_environment,
)
from ..mechanics.mechanisms import install_mechanisms
from ..mechanics.needs import (
    HungerComponent,
    HungerSystem,
    ThirstComponent,
    ThirstSystem,
    need_fragments,
)
from ..mechanics.persona import (
    GoalComponent,
    PreferenceComponent,
    TraitSetComponent,
    persona_fragments,
)
from ..mechanics.policy import (
    CharacterBoundaryComponent,
    WorldPolicyComponent,
    install_policy,
)
from ..mechanics.social import SocialBond, install_social, relationship_fragments
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
POLICY = "bunnyland.policy"
PERSONA = "bunnyland.persona"


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
        content=ContentContribution(prompt_fragments=(need_fragments,)),
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
        content=ContentContribution(prompt_fragments=(environment_fragments,)),
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
        content=ContentContribution(prompt_fragments=(relationship_fragments,)),
    )


def _policy_factory(actor) -> None:
    install_policy(actor)


def policy_plugin() -> Plugin:
    return Plugin(
        id=POLICY,
        name="Policy & Boundaries",
        dependencies=(CORE_VERBS,),
        ecs=EcsContribution(components=(WorldPolicyComponent, CharacterBoundaryComponent)),
        runtime=RuntimeContribution(service_factories=(_policy_factory,)),
    )


def persona_plugin() -> Plugin:
    return Plugin(
        id=PERSONA,
        name="Persona",
        ecs=EcsContribution(
            components=(TraitSetComponent, PreferenceComponent, GoalComponent)
        ),
        content=ContentContribution(prompt_fragments=(persona_fragments,)),
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
        policy_plugin(),
        persona_plugin(),
    ]


__all__ = [
    "CORE_VERBS",
    "ENVIRONMENT",
    "LIFESIM",
    "MECHANISMS",
    "MEMORY",
    "PERSONA",
    "POLICY",
    "SOCIAL",
    "WORLDGEN",
    "bunnyland_plugins",
    "core_verbs_plugin",
    "environment_plugin",
    "lifesim_plugin",
    "mechanisms_plugin",
    "memory_plugin",
    "persona_plugin",
    "policy_plugin",
    "social_plugin",
    "worldgen_plugin",
]
