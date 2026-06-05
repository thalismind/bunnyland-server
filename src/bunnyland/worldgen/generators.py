"""Selectable world generators (spec 21, 22).

A world generator is a named strategy for turning a seed into an instantiated world. They
are contributed by plugins (``ContentContribution.world_generators``) and chosen at runtime
by name, so a plugin can add a new generation strategy without touching the CLI.

Each generator is ``async generate(actor, seed, options) -> InstantiatedWorld``. The
builtins include ``empty`` (only the world clock), seasonal deterministic demos,
``waiting-room`` (one static room), ``oneshot`` (one big proposal), and ``recursive``
(breadth-first graph). LLM generation uses a DM/world agent selected from ``options.llm``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .builder import StubWorldBuilder
from .defaults import DEFAULT_WORLDGEN_MODEL
from .instantiate import InstantiatedWorld, instantiate
from .proposal import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal
from .recursive import RecursiveWorldGenerator
from .recursive_builder import StubWorldAgent

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor


@dataclass(frozen=True)
class GenOptions:
    """Runtime knobs passed to a generator (LLM wiring + budgets)."""

    llm: bool = False
    provider: str = "ollama"
    model: str = DEFAULT_WORLDGEN_MODEL
    host: str | None = None
    api_key: str | None = None
    server_url: str | None = None
    max_rooms: int = 6


GenerateFn = Callable[["WorldActor", str, GenOptions], Awaitable[InstantiatedWorld]]


@dataclass(frozen=True)
class WorldGenerator:
    """A named generation strategy contributed by a plugin."""

    name: str
    generate: GenerateFn
    description: str = ""
    uses_seed: bool = True


async def empty_generator(
    actor: WorldActor, seed: str, options: GenOptions
) -> InstantiatedWorld:
    """Leave only the actor's default world clock in place."""

    del actor, seed, options
    return InstantiatedWorld()


async def waiting_room_generator(
    actor: WorldActor, seed: str, options: GenOptions
) -> InstantiatedWorld:
    """Generate a single bright white room with one red chair."""

    del options
    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="waiting_room",
                title="Waiting Room",
                biome="white-room",
                indoor=True,
                light=1.0,
                celsius=20.0,
            )
        ],
        objects=[
            ObjectSpec(
                key="red_chair",
                room_key="waiting_room",
                name="a red chair",
                kind="chair",
                portable=False,
            )
        ],
    )
    return await instantiate(actor, proposal)


async def halloween_generator(
    actor: WorldActor, seed: str, options: GenOptions
) -> InstantiatedWorld:
    """Generate a small haunted autumn demo world."""

    del options
    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="porch",
                title="Pumpkin-Lit Porch",
                biome="autumn",
                indoor=False,
                light=0.45,
                celsius=9.0,
            ),
            RoomSpec(
                key="foyer",
                title="Candlelit Foyer",
                biome="haunted-house",
                indoor=True,
                light=0.25,
                celsius=13.0,
            ),
            RoomSpec(
                key="cellar",
                title="Cobweb Cellar",
                biome="cellar",
                indoor=True,
                light=0.1,
                celsius=7.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="porch", direction="in", to_key="foyer"),
            ExitSpec(from_key="foyer", direction="out", to_key="porch"),
            ExitSpec(from_key="foyer", direction="down", to_key="cellar"),
            ExitSpec(from_key="cellar", direction="up", to_key="foyer"),
        ],
        objects=[
            ObjectSpec(
                key="candy_bowl",
                room_key="porch",
                name="a bowl of wrapped candy",
                kind="food",
                nutrition=2.0,
                satiety=8.0,
                portable=False,
            ),
            ObjectSpec(
                key="lantern",
                room_key="foyer",
                name="a brass lantern",
                kind="item",
                portable=True,
            ),
            ObjectSpec(
                key="spell_note",
                room_key="cellar",
                name="a brittle handwritten note",
                kind="paper",
                writable=True,
            ),
            ObjectSpec(
                key="rain_barrel",
                room_key="porch",
                name="a rain barrel under the eaves",
                kind="water",
                portable=False,
                hydration=18.0,
            ),
        ],
        characters=[
            CharacterSpec(
                key="caretaker",
                name="Marlow",
                room_key="porch",
                controller="suspended",
                traits=("curious", "watchful"),
                goals=("find the cellar note",),
            ),
            CharacterSpec(
                key="host",
                name="October",
                room_key="foyer",
                controller="llm",
                llm_profile="haunted-host",
                traits=("dramatic",),
                goals=("keep the candles lit",),
            ),
        ],
    )
    return await instantiate(actor, proposal)


async def holiday_generator(
    actor: WorldActor, seed: str, options: GenOptions
) -> InstantiatedWorld:
    """Generate a compact snowy holiday demo world."""

    del options
    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="snowfield",
                title="North Pole Snowfield",
                biome="tundra",
                indoor=False,
                light=0.85,
                celsius=-8.0,
            ),
            RoomSpec(
                key="workshop",
                title="Toy Workshop",
                biome="workshop",
                indoor=True,
                light=0.75,
                celsius=21.0,
            ),
            RoomSpec(
                key="stable",
                title="Lantern Stable",
                biome="stable",
                indoor=True,
                light=0.55,
                celsius=4.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="snowfield", direction="in", to_key="workshop"),
            ExitSpec(from_key="workshop", direction="out", to_key="snowfield"),
            ExitSpec(from_key="workshop", direction="east", to_key="stable"),
            ExitSpec(from_key="stable", direction="west", to_key="workshop"),
        ],
        objects=[
            ObjectSpec(
                key="cocoa",
                room_key="workshop",
                name="a pot of hot cocoa",
                kind="water",
                portable=False,
                hydration=20.0,
            ),
            ObjectSpec(
                key="gingerbread",
                room_key="workshop",
                name="a tray of gingerbread cookies",
                kind="food",
                nutrition=3.0,
                satiety=12.0,
                portable=False,
            ),
            ObjectSpec(
                key="gift_box",
                room_key="stable",
                name="a ribboned gift box",
                kind="container",
                portable=True,
                open=True,
            ),
            ObjectSpec(
                key="silver_bell",
                room_key="snowfield",
                name="a silver sleigh bell",
                kind="item",
                portable=True,
            ),
        ],
        characters=[
            CharacterSpec(
                key="helper",
                name="Pip",
                room_key="workshop",
                controller="suspended",
                traits=("cheerful", "busy"),
                goals=("deliver the silver bell",),
            ),
            CharacterSpec(
                key="foreman",
                name="Marta",
                room_key="stable",
                controller="llm",
                llm_profile="workshop-foreman",
                traits=("practical",),
                goals=("finish the holiday route",),
            ),
        ],
    )
    return await instantiate(actor, proposal)


async def oneshot_generator(actor: WorldActor, seed: str, options: GenOptions) -> InstantiatedWorld:
    if options.llm:
        if options.provider != "ollama":
            raise RuntimeError(
                "OpenRouter world generation uses the recursive generator; "
                "rerun with --generator recursive"
            )
        from .ollama_builder import OllamaWorldBuilder

        builder = OllamaWorldBuilder(
            model=options.model, host=options.host, api_key=options.api_key
        )
    else:
        builder = StubWorldBuilder()
    proposal = await asyncio.to_thread(builder.propose, seed)
    result = await instantiate(actor, proposal)
    result.prompt = builder.system_prompt  # literal DM system prompt, for provenance
    return result


async def recursive_generator(
    actor: WorldActor, seed: str, options: GenOptions
) -> InstantiatedWorld:
    if options.llm:
        if options.provider == "openrouter":
            from .recursive_builder import OpenRouterWorldAgent

            builder = OpenRouterWorldAgent(
                model=options.model, api_key=options.api_key, server_url=options.server_url
            )
        else:
            from .recursive_builder import OllamaWorldAgent

            builder = OllamaWorldAgent(
                model=options.model, host=options.host, api_key=options.api_key
            )
    else:
        builder = StubWorldAgent()
    generator = RecursiveWorldGenerator(actor, builder, max_rooms=options.max_rooms)
    result = await generator.generate(seed)
    result.prompt = builder.system_prompt  # literal DM system prompt, for provenance
    return result


def collect_generators(plugins: Iterable) -> dict[str, WorldGenerator]:
    """Build a name -> generator registry from the enabled plugins' contributions."""
    registry: dict[str, WorldGenerator] = {}
    for plugin in plugins:
        for generator in plugin.content.world_generators:
            registry[generator.name] = generator
    return registry


__all__ = [
    "GenOptions",
    "DEFAULT_WORLDGEN_MODEL",
    "empty_generator",
    "GenerateFn",
    "halloween_generator",
    "holiday_generator",
    "WorldGenerator",
    "collect_generators",
    "oneshot_generator",
    "recursive_generator",
    "waiting_room_generator",
]
