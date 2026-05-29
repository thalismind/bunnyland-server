"""bunnyland command-line entrypoint.

``serve`` wires plugins onto a world actor, generates a world, and runs the game loop so
LLM-controlled characters act each tick. By default (no ``--llm``) it uses the
deterministic stub world and a waiting agent, so the loop is runnable without the ``llm``
extra; with ``--llm`` it generates via Ollama and drives characters with a real agent,
reading the API key from ``OLLAMA_CLOUD_API_KEY`` (loaded from ``.env`` if present).
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from .core.world_actor import WorldActor
from .engine import GameLoop
from .llm_agents import DEFAULT_MODEL, ControllerDispatch, ScriptedAgent
from .plugins import apply_plugins, bunnyland_plugins, load_modules, resolve_order, select
from .prompts.builder import PromptBuilder
from .worldgen import StubWorldBuilder, instantiate

BUILTIN_MODULE = "bunnyland.plugins.builtin"
#: Ollama Cloud endpoint; the API key authenticates against it.
OLLAMA_CLOUD_HOST = "https://ollama.com"


def load_dotenv(path: str | Path = ".env") -> None:
    """Load simple ``KEY=value`` lines from ``.env`` into ``os.environ`` (no overrides)."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def build_actor(modules: list[str], enabled_ids: list[str] | None) -> tuple[WorldActor, list]:
    """Create an actor and apply builtin + requested plugins; return (actor, applied)."""
    plugins = list(bunnyland_plugins())
    plugins.extend(load_modules(modules))
    chosen = select(plugins, enabled_ids)
    actor = WorldActor()
    applied = apply_plugins(chosen, actor)
    return actor, applied


async def _generate_world(actor, args, *, host, api_key):
    """Generate a world via the recursive BFS path or the one-shot proposal path."""
    if args.recursive:
        if args.llm:
            from .worldgen import OllamaRecursiveBuilder

            builder = OllamaRecursiveBuilder(model=args.ollama_model, host=host, api_key=api_key)
        else:
            from .worldgen import StubRecursiveBuilder

            builder = StubRecursiveBuilder()
        from .worldgen import RecursiveWorldGenerator

        generator = RecursiveWorldGenerator(actor, builder, max_rooms=args.max_rooms)
        return await generator.generate(args.seed)

    if args.llm:
        from .worldgen.ollama_builder import OllamaWorldBuilder

        proposal = OllamaWorldBuilder(
            model=args.ollama_model, host=host, api_key=api_key
        ).propose(args.seed)
    else:
        proposal = StubWorldBuilder().propose(args.seed)
    return await instantiate(actor, proposal)


async def _serve(args) -> None:
    actor, applied = build_actor(args.module, args.plugin)
    print("Loaded plugins:")
    for plugin in resolve_order(applied):
        print(f"  - {plugin.id} ({plugin.name}) v{plugin.version}")

    host = api_key = None
    if args.llm:
        load_dotenv()
        api_key = os.environ.get("OLLAMA_CLOUD_API_KEY")
        host = os.environ.get("OLLAMA_HOST", OLLAMA_CLOUD_HOST)
        if not api_key:
            raise SystemExit("--llm needs OLLAMA_CLOUD_API_KEY (set it in .env or the environment)")

    result = await _generate_world(actor, args, host=host, api_key=api_key)
    print(f"Generated world {args.seed!r}: {len(result.rooms)} rooms, "
          f"{len(result.characters)} characters.")

    if args.llm:
        from .llm_agents import OllamaAgent

        agent = OllamaAgent(model=args.ollama_model, host=host, api_key=api_key)
        print(f"Driving characters with Ollama model {args.ollama_model!r} at {host}.")
    else:
        agent = ScriptedAgent([])  # offline: characters wait, the world still ticks
        print("Offline demo (no --llm): characters will wait.")

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
        "--llm", action="store_true", help="drive characters with Ollama (needs llm extra)"
    )
    serve.add_argument(
        "--ollama-model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})"
    )
    serve.add_argument(
        "--recursive", action="store_true", help="generate the world breadth-first (graph-based)"
    )
    serve.add_argument(
        "--max-rooms", type=int, default=6, help="room budget for recursive generation"
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
