"""Selectable world generators (spec 21, 22).

A world generator is a named strategy for turning a seed into an instantiated world. They
are contributed by plugins (``ContentContribution.world_generators``) and chosen at runtime
by name, so a plugin can add a new generation strategy without touching the CLI.

Each generator is ``async generate(actor, seed, options) -> InstantiatedWorld``. The
builtins include ``empty`` (only the world clock), ``oneshot`` (one big proposal), and
``recursive`` (breadth-first graph). LLM generation uses a DM/world agent selected from
``options.llm``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .builder import StubWorldBuilder
from .defaults import DEFAULT_WORLDGEN_MODEL
from .instantiate import InstantiatedWorld, instantiate
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


async def empty_generator(
    actor: WorldActor, seed: str, options: GenOptions
) -> InstantiatedWorld:
    """Leave only the actor's default world clock in place."""

    del actor, seed, options
    return InstantiatedWorld()


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
    result = await instantiate(actor, builder.propose(seed))
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
    "WorldGenerator",
    "collect_generators",
    "oneshot_generator",
    "recursive_generator",
]
