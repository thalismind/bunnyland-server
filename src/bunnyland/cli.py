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
from collections.abc import Awaitable
from pathlib import Path

from .core.world_actor import WorldActor
from .discord.claim import assign_discord_controller
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
from .worldgen import DEFAULT_WORLDGEN_MODEL, GenOptions, collect_generators

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


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return None
    return int(value)


async def _run_with_optional_discord(
    runtime: Awaitable[int],
    loop: GameLoop,
    discord_bot,
) -> int:
    runtime_task = asyncio.create_task(runtime)
    if discord_bot is None:
        return await runtime_task

    discord_task = asyncio.create_task(discord_bot.start())
    done, _pending = await asyncio.wait(
        {runtime_task, discord_task}, return_when=asyncio.FIRST_COMPLETED
    )

    if runtime_task in done:
        try:
            return runtime_task.result()
        finally:
            await discord_bot.close()
            await asyncio.gather(discord_task, return_exceptions=True)

    loop.stop()
    runtime_task.cancel()
    await asyncio.gather(runtime_task, return_exceptions=True)
    exc = discord_task.exception()
    if exc is not None:
        raise RuntimeError("Discord bot stopped unexpectedly") from exc
    raise RuntimeError("Discord bot stopped unexpectedly")


async def _serve(args) -> None:
    try:
        plugins = select_plugins(args.module, args.plugin)
        ordered_plugins = resolve_order(plugins)
    except PluginError as exc:
        logging.getLogger(__name__).error("plugin loading failed: %s", exc)
        raise SystemExit(2) from exc
    # TODO: add --auto-load-requires to include missing required plugins automatically.

    host = api_key = discord_token = None
    if args.llm or args.discord:
        load_dotenv()
    if args.llm:
        api_key = os.environ.get("OLLAMA_CLOUD_API_KEY")
        host = os.environ.get("OLLAMA_HOST", OLLAMA_CLOUD_HOST)
        if not api_key:
            raise SystemExit("--llm needs OLLAMA_CLOUD_API_KEY (set it in .env or the environment)")
    worldgen_model = args.worldgen_model or args.ollama_model or DEFAULT_WORLDGEN_MODEL
    character_model = args.character_model or args.ollama_model or DEFAULT_MODEL
    if args.discord:
        discord_token = os.environ.get("DISCORD_TOKEN")
        if not discord_token:
            raise SystemExit("--discord needs DISCORD_TOKEN (set it in .env or the environment)")

    if args.load:
        try:
            actor, meta = load_world(args.load, plugins=plugins)
        except PluginError as exc:
            logging.getLogger(__name__).error("plugin loading failed: %s", exc)
            raise SystemExit(2) from exc
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

        if args.llm:
            print(f"Generating world with Ollama model {worldgen_model!r} at {host}.")
        options = GenOptions(
            llm=args.llm, model=worldgen_model, host=host, api_key=api_key,
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

        agent = OllamaAgent(model=character_model, host=host, api_key=api_key)
        print(f"Driving characters with default Ollama model {character_model!r} at {host}.")
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
        paused=bool(args.load and args.load_paused),
    )
    discord_bot = None
    if args.discord:
        from .discord import DiscordBot

        discord_bot = DiscordBot(
            actor, token=discord_token, allow_child_claims=args.discord_allow_child_claims
        )
        claim_user_id = args.discord_user_id or _env_int("BUNNYLAND_DISCORD_USER_ID")
        claim_channel_id = args.discord_channel_id or _env_int("BUNNYLAND_DISCORD_CHANNEL_ID") or 0
        claim_character = args.discord_character or os.environ.get("BUNNYLAND_DISCORD_CHARACTER")
        if claim_user_id is not None:
            claimed = assign_discord_controller(
                actor,
                discord_user_id=claim_user_id,
                default_channel_id=claim_channel_id,
                character_name=claim_character,
                allow_child_claims=args.discord_allow_child_claims,
            )
            print(f"Assigned Discord user {claim_user_id} to {claimed!r}.")
            if args.save:
                save_world(actor, args.save, meta=meta)
        else:
            print("Discord bot enabled without a startup character claim.")

    max_ticks = args.ticks if args.ticks > 0 else None
    print(f"Running game loop ({'forever' if max_ticks is None else f'{max_ticks} ticks'})...")
    if args.api_port is None:
        ticks = await _run_with_optional_discord(loop.run(max_ticks=max_ticks), loop, discord_bot)
    else:
        from .server.runtime import run_loop_with_api

        print(f"Serving client API at http://{args.api_host}:{args.api_port}.")
        try:
            ticks = await _run_with_optional_discord(
                run_loop_with_api(
                    loop,
                    actor,
                    meta,
                    host=args.api_host,
                    port=args.api_port,
                    save_path=args.save,
                    worldgen_options=GenOptions(
                        llm=args.llm,
                        model=worldgen_model,
                        host=host,
                        api_key=api_key,
                        max_rooms=args.max_rooms,
                    ),
                    max_ticks=max_ticks,
                ),
                loop,
                discord_bot,
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
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
        "--ollama-model",
        default=None,
        help=(
            "shared Ollama model override for generation and characters "
            f"(defaults: worldgen {DEFAULT_WORLDGEN_MODEL}, characters {DEFAULT_MODEL})"
        ),
    )
    serve.add_argument(
        "--worldgen-model",
        default=None,
        help=f"Ollama model for world generation (default: {DEFAULT_WORLDGEN_MODEL})",
    )
    serve.add_argument(
        "--character-model",
        default=None,
        help=f"default Ollama model for character controllers (default: {DEFAULT_MODEL})",
    )
    serve.add_argument(
        "--generator", default="oneshot", help="world generator to use (e.g. oneshot, recursive)"
    )
    serve.add_argument(
        "--max-rooms", type=int, default=6, help="room budget for graph-based generators"
    )
    serve.add_argument("--load", default=None, help="reload a saved world (skips generation)")
    serve.add_argument(
        "--load-paused",
        action="store_true",
        help="start the tick cycle paused when reloading with --load",
    )
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
        "--api-host",
        default="127.0.0.1",
        help="host for the optional HTTP/websocket client API",
    )
    serve.add_argument(
        "--api-port",
        type=int,
        default=None,
        help="port for the optional HTTP/websocket client API",
    )
    serve.add_argument(
        "--verbose", action="store_true", help="log decisions and world generation at INFO"
    )
    serve.add_argument(
        "--discord",
        action="store_true",
        help="run the Discord bot against this server process (needs DISCORD_TOKEN)",
    )
    serve.add_argument(
        "--discord-user-id",
        type=int,
        default=None,
        help="assign this Discord user id to a character at startup",
    )
    serve.add_argument(
        "--discord-channel-id",
        type=int,
        default=None,
        help="default Discord channel id for the startup controller",
    )
    serve.add_argument(
        "--discord-character",
        default=None,
        help="character name to assign to the startup Discord controller",
    )
    serve.add_argument(
        "--discord-allow-child-claims",
        action="store_true",
        help="allow Discord users to claim child life-stage characters",
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
