"""bunnyland command-line entrypoint.

``serve`` wires plugins onto a world actor, generates a world, and runs the game loop so
LLM-controlled characters act each tick. Offline (no ``--ollama-model``) it uses the
deterministic stub world and a waiting agent, so the loop is runnable without the ``llm``
extra; with a model it generates via Ollama and drives characters with a real agent.
"""

from __future__ import annotations

import argparse
import asyncio

from .core.world_actor import WorldActor
from .engine import GameLoop
from .llm_agents import ControllerDispatch, ScriptedAgent
from .plugins import apply_plugins, bunnyland_plugins, load_modules, resolve_order, select
from .prompts.builder import PromptBuilder
from .worldgen import StubWorldBuilder, instantiate

BUILTIN_MODULE = "bunnyland.plugins.builtin"


def build_actor(modules: list[str], enabled_ids: list[str] | None) -> tuple[WorldActor, list]:
    """Create an actor and apply builtin + requested plugins; return (actor, applied)."""
    plugins = list(bunnyland_plugins())
    plugins.extend(load_modules(modules))
    chosen = select(plugins, enabled_ids)
    actor = WorldActor()
    applied = apply_plugins(chosen, actor)
    return actor, applied


async def _serve(args) -> None:
    actor, applied = build_actor(args.module, args.plugin)
    print("Loaded plugins:")
    for plugin in resolve_order(applied):
        print(f"  - {plugin.id} ({plugin.name}) v{plugin.version}")

    if args.ollama_model:
        from .worldgen.ollama_builder import OllamaWorldBuilder

        proposal = OllamaWorldBuilder(model=args.ollama_model).propose(args.seed)
    else:
        proposal = StubWorldBuilder().propose(args.seed)
    result = await instantiate(actor, proposal)
    print(f"Generated world {args.seed!r}: {len(result.rooms)} rooms, "
          f"{len(result.characters)} characters.")

    if args.ollama_model:
        from .llm_agents import OllamaAgent

        agent = OllamaAgent(model=args.ollama_model)
    else:
        agent = ScriptedAgent([])  # offline: characters wait, the world still ticks
        print("No --ollama-model: characters will wait (offline demo).")

    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), agent)
    loop = GameLoop(actor, dispatch, tick_seconds=args.tick_seconds, time_scale=args.time_scale)
    max_ticks = args.ticks if args.ticks > 0 else None
    print(f"Running game loop ({'forever' if max_ticks is None else f'{max_ticks} ticks'})...")
    ticks = await loop.run(max_ticks=max_ticks)
    print(f"Stopped after {ticks} ticks at game epoch {actor.epoch}s.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bunnyland")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="generate a world and run the game loop")
    serve.add_argument("--module", action="append", default=[], help="import a plugin module")
    serve.add_argument("--plugin", action="append", default=None, help="enable a plugin id")
    serve.add_argument("--seed", default="a quiet marsh", help="world-generation seed")
    serve.add_argument(
        "--ollama-model", default=None, help="use this Ollama model (needs llm extra)"
    )
    serve.add_argument("--ticks", type=int, default=10, help="number of ticks (0 = run forever)")
    serve.add_argument("--tick-seconds", type=float, default=1.0, help="real seconds per tick")
    serve.add_argument(
        "--time-scale", type=float, default=3600.0, help="game seconds per real tick"
    )

    args = parser.parse_args(argv)
    if args.command != "serve":
        parser.print_help()
        return 0

    asyncio.run(_serve(args))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
