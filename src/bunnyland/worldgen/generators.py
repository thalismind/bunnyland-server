"""Selectable world generators (spec 21, 22).

A world generator is a named strategy for turning a seed into an instantiated world. They
are contributed by plugins (``ContentContribution.world_generators``) and chosen at runtime
by name, so a plugin can add a new generation strategy without touching the CLI.

Each generator is ``async generate(actor, seed, options) -> InstantiatedWorld``. The two
builtins wrap the existing paths: ``oneshot`` (one big proposal) and ``recursive``
(breadth-first graph). Both pick a stub or Ollama builder from ``options.llm``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..llm_agents.agent import DEFAULT_MODEL
from .builder import StubWorldBuilder
from .instantiate import InstantiatedWorld, instantiate
from .recursive import RecursiveWorldGenerator
from .recursive_builder import StubRecursiveBuilder

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor


@dataclass(frozen=True)
class GenOptions:
    """Runtime knobs passed to a generator (LLM wiring + budgets)."""

    llm: bool = False
    model: str = DEFAULT_MODEL
    host: str | None = None
    api_key: str | None = None
    max_rooms: int = 6


GenerateFn = Callable[["WorldActor", str, GenOptions], Awaitable[InstantiatedWorld]]


@dataclass(frozen=True)
class WorldGenerator:
    """A named generation strategy contributed by a plugin."""

    name: str
    generate: GenerateFn
    description: str = ""


async def oneshot_generator(actor: WorldActor, seed: str, options: GenOptions) -> InstantiatedWorld:
    if options.llm:
        from .ollama_builder import OllamaWorldBuilder

        proposal = OllamaWorldBuilder(
            model=options.model, host=options.host, api_key=options.api_key
        ).propose(seed)
    else:
        proposal = StubWorldBuilder().propose(seed)
    return await instantiate(actor, proposal)


async def recursive_generator(
    actor: WorldActor, seed: str, options: GenOptions
) -> InstantiatedWorld:
    if options.llm:
        from .recursive_builder import OllamaRecursiveBuilder

        builder = OllamaRecursiveBuilder(
            model=options.model, host=options.host, api_key=options.api_key
        )
    else:
        builder = StubRecursiveBuilder()
    generator = RecursiveWorldGenerator(actor, builder, max_rooms=options.max_rooms)
    return await generator.generate(seed)


def collect_generators(plugins: Iterable) -> dict[str, WorldGenerator]:
    """Build a name -> generator registry from the enabled plugins' contributions."""
    registry: dict[str, WorldGenerator] = {}
    for plugin in plugins:
        for generator in plugin.content.world_generators:
            registry[generator.name] = generator
    return registry


__all__ = [
    "GenOptions",
    "GenerateFn",
    "WorldGenerator",
    "collect_generators",
    "oneshot_generator",
    "recursive_generator",
]
