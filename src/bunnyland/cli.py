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
import logging
import os
from pathlib import Path

from .core.world_actor import WorldActor
from .engine import GameLoop
from .llm_agents import DEFAULT_MODEL, ControllerDispatch, ScriptedAgent
from .persistence import WorldMeta, load_world, save_world
from .plugins import (
    PluginError,
    apply_plugins,
    bunnyland_plugins,
    collect_prompt_fragments,
    load_modules,
    resolve_order,
    select,
)
from .prompts.builder import PromptBuilder
from .worldgen import GenOptions, collect_generators

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


def select_plugins(modules: list[str], enabled_ids: list[str] | None) -> list:
    """Collect builtin + requested plugins and select which are enabled."""
    plugins = list(bunnyland_plugins())
    plugins.extend(load_modules(modules))
    return select(plugins, enabled_ids)


def build_actor(modules: list[str], enabled_ids: list[str] | None) -> tuple[WorldActor, list]:
    """Create an actor and apply builtin + requested plugins; return (actor, applied)."""
    chosen = select_plugins(modules, enabled_ids)
    actor = WorldActor()
    applied = apply_plugins(chosen, actor)
    return actor, applied


async def _serve(args) -> None:
    try:
        plugins = select_plugins(args.module, args.plugin)
        ordered_plugins = resolve_order(plugins)
    except PluginError as exc:
        logging.getLogger(__name__).error("plugin loading failed: %s", exc)
        raise SystemExit(2) from exc
    # TODO: add --auto-load-requires to include missing required plugins automatically.

    host = api_key = None
    if args.llm:
        load_dotenv()
        api_key = os.environ.get("OLLAMA_CLOUD_API_KEY")
        host = os.environ.get("OLLAMA_HOST", OLLAMA_CLOUD_HOST)
        if not api_key:
            raise SystemExit("--llm needs OLLAMA_CLOUD_API_KEY (set it in .env or the environment)")

    if args.load:
        actor, meta = load_world(args.load, plugins=plugins)
        print(f"Reloaded world from {args.load!r}: seed {meta.seed!r}, "
              f"generator {meta.generator!r}, game epoch {actor.epoch}s.")
    else:
        actor = WorldActor()
        apply_plugins(plugins, actor)
        print("Loaded plugins:")
        for plugin in ordered_plugins:
            print(f"  - {plugin.id} ({plugin.name}) v{plugin.version}")

        registry = collect_generators(plugins)
        generator = registry.get(args.generator)
        if generator is None:
            names = ", ".join(sorted(registry)) or "(none)"
            raise SystemExit(f"unknown generator {args.generator!r}; available: {names}")

        options = GenOptions(
            llm=args.llm, model=args.ollama_model, host=host, api_key=api_key,
            max_rooms=args.max_rooms,
        )
        result = await generator.generate(actor, args.seed, options)
        meta = WorldMeta(
            seed=args.seed,
            generator=generator.name,
            prompt=result.prompt,  # the literal DM system prompt (empty for stub builders)
            plugins=tuple(plugin.id for plugin in ordered_plugins),
        )
        print(f"Generated world {args.seed!r} via {generator.name!r}: "
              f"{len(result.rooms)} rooms, {len(result.characters)} characters.")

    if args.llm:
        from .llm_agents import OllamaAgent

        agent = OllamaAgent(model=args.ollama_model, host=host, api_key=api_key)
        print(f"Driving characters with Ollama model {args.ollama_model!r} at {host}.")
    else:
        agent = ScriptedAgent([])  # offline: characters wait, the world still ticks
        print("Offline demo (no --llm): characters will wait.")

    autosave = None
    if args.save and args.autosave_every > 0:
        def autosave(ticks: int) -> None:
            save_world(actor, args.save, meta=meta)
            print(f"  [autosave] tick {ticks} -> {args.save}")

    builder = PromptBuilder(actor.world, fragment_providers=collect_prompt_fragments(plugins))
    dispatch = ControllerDispatch(actor, builder, agent)
    loop = GameLoop(
        actor, dispatch, tick_seconds=args.tick_seconds, time_scale=args.time_scale,
        autosave=autosave, autosave_every=args.autosave_every,
    )
    max_ticks = args.ticks if args.ticks > 0 else None
    print(f"Running game loop ({'forever' if max_ticks is None else f'{max_ticks} ticks'})...")
    ticks = await loop.run(max_ticks=max_ticks)
    print(f"Stopped after {ticks} ticks at game epoch {actor.epoch}s.")

    if args.save:
        saved = save_world(actor, args.save, meta=meta)
        print(f"Saved world to {args.save!r} (seed {saved.seed!r}, epoch {saved.saved_at_epoch}s).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bunnyland")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="generate a world and run the game loop")
    serve.add_argument(
        "--module",
        "--import",
        dest="module",
        action="append",
        default=[],
        help="import a plugin module",
    )
    serve.add_argument("--plugin", action="append", default=None, help="enable a plugin id")
    serve.add_argument("--seed", default="a quiet marsh", help="world-generation seed")
    serve.add_argument(
        "--llm", action="store_true", help="drive characters with Ollama (needs llm extra)"
    )
    serve.add_argument(
        "--ollama-model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})"
    )
    serve.add_argument(
        "--generator", default="oneshot", help="world generator to use (e.g. oneshot, recursive)"
    )
    serve.add_argument(
        "--max-rooms", type=int, default=6, help="room budget for graph-based generators"
    )
    serve.add_argument("--load", default=None, help="reload a saved world (skips generation)")
    serve.add_argument("--save", default=None, help="save the world to this path on exit")
    serve.add_argument(
        "--autosave-every", type=int, default=0, help="autosave every N ticks (needs --save)"
    )
    serve.add_argument("--ticks", type=int, default=10, help="number of ticks (0 = run forever)")
    serve.add_argument("--tick-seconds", type=float, default=1.0, help="real seconds per tick")
    serve.add_argument(
        "--time-scale", type=float, default=3600.0, help="game seconds per real tick"
    )
    serve.add_argument(
        "--verbose", action="store_true", help="log decisions and world generation at INFO"
    )

    args = parser.parse_args(argv)
    if args.command != "serve":
        parser.print_help()
        return 0

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)

    asyncio.run(_serve(args))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
