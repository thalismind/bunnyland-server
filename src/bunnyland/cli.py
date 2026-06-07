"""bunnyland command-line entrypoint.

``serve`` wires plugins onto a world actor, generates a world, and runs the game loop so
LLM-controlled characters act each tick. By default (no ``--llm``) it uses the
deterministic stub world and a waiting agent, so the loop is runnable without the ``llm``
extra; with ``--llm`` it generates via Ollama and drives characters with a real agent.
The default character provider is Ollama, and OpenRouter can be enabled per controller
with ``OPENROUTER_API_KEY``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from collections.abc import Awaitable
from pathlib import Path

from .core.claim_timeout import CLAIM_TIMEOUT_DEFAULT_SECONDS, normalize_claim_timeout
from .core.systems import ClaimTimeoutSystem
from .core.world_actor import WorldActor
from .discord.claim import assign_discord_controller
from .engine import GameLoop
from .llm_agents import DEFAULT_MODEL, ControllerDispatch, ScriptedAgent
from .mechanics.lifesim import configure_lifesim_aging
from .memory import install_memory
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
from .plugins.builtin import (
    BARBARIANSIM,
    COLONYSIM,
    CORE_VERBS,
    DRAGONSIM,
    GARDENSIM,
    LIFESIM,
    MCP,
    NUKESIM,
    VOIDSIM,
    WORLDGEN,
)
from .prompts.builder import PromptBuilder
from .worldgen import DEFAULT_WORLDGEN_MODEL, GenOptions, collect_generators

BUILTIN_MODULE = "bunnyland.plugins.builtin"
#: Ollama Cloud endpoint; the API key authenticates against it.
OLLAMA_CLOUD_HOST = "https://ollama.com"
STARTER_PACKS: dict[str, tuple[str, ...]] = {
    "peaceful": (CORE_VERBS, WORLDGEN, LIFESIM, COLONYSIM, GARDENSIM),
    "fantastic": (CORE_VERBS, WORLDGEN, LIFESIM, BARBARIANSIM, DRAGONSIM),
    "futuristic": (CORE_VERBS, WORLDGEN, LIFESIM, NUKESIM, VOIDSIM),
}


def _dedupe_plugin_ids(plugin_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for plugin_id in plugin_ids:
        if plugin_id in seen:
            continue
        seen.add(plugin_id)
        result.append(plugin_id)
    return result


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


def select_plugins(
    modules: list[str],
    enabled_ids: list[str] | None,
    extra_enabled_ids: tuple[str, ...] = (),
    starter_pack: str | None = None,
) -> list:
    """Collect builtin + requested plugins and select which are enabled."""
    plugins = list(bunnyland_plugins())
    plugins.extend(load_modules(modules))
    if starter_pack:
        pack_ids = STARTER_PACKS.get(starter_pack)
        if pack_ids is None:
            names = ", ".join(sorted(STARTER_PACKS))
            raise PluginError(f"unknown starter pack {starter_pack!r}; available: {names}")
        enabled_ids = _dedupe_plugin_ids([*(enabled_ids or ()), *pack_ids])
    if not extra_enabled_ids:
        return select(plugins, enabled_ids)
    if enabled_ids is not None:
        return select(plugins, _dedupe_plugin_ids([*enabled_ids, *extra_enabled_ids]))
    selected = select(plugins, None)
    selected_ids = {plugin.id for plugin in selected}
    for plugin in select(plugins, extra_enabled_ids):
        if plugin.id not in selected_ids:
            selected.append(plugin)
            selected_ids.add(plugin.id)
    return selected


def build_actor(modules: list[str], enabled_ids: list[str] | None) -> tuple[WorldActor, list]:
    """Create an actor and apply builtin + requested plugins; return (actor, applied)."""
    chosen = select_plugins(modules, enabled_ids)
    actor = WorldActor()
    applied = apply_plugins(chosen, actor)
    return actor, applied


def configure_memory_backend(actor: WorldActor, backend: str, path: str | None = None) -> None:
    if backend == "in-memory":
        return
    if backend != "chroma":
        raise ValueError(f"unknown memory backend {backend!r}")
    from .memory.chroma import ChromaMemoryStore

    install_memory(actor, ChromaMemoryStore(persist_path=path))


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return None
    return int(value)


def _env_bool(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be one of 1/0, true/false, yes/no, or on/off")


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
    if args.discord and args.discord_playtest:
        raise SystemExit(
            "--discord-playtest uses a mocked Discord adapter; do not combine it with --discord"
        )
    if args.api_port is not None and args.discord_playtest:
        raise SystemExit("--discord-playtest cannot be combined with --api-port yet")
    if args.mcp and args.api_port is None:
        raise SystemExit("--mcp mounts on the HTTP API and needs --api-port")

    try:
        plugins = select_plugins(
            args.module,
            args.plugin,
            extra_enabled_ids=(MCP,) if args.mcp else (),
            starter_pack=args.starter_pack or os.environ.get("BUNNYLAND_STARTER_PACK") or None,
        )
        ordered_plugins = resolve_order(plugins)
    except PluginError as exc:
        logging.getLogger(__name__).error("plugin loading failed: %s", exc)
        raise SystemExit(2) from exc
    # TODO: add --auto-load-requires to include missing required plugins automatically.

    load_dotenv()
    try:
        lifesim_natural_aging = (
            args.lifesim_natural_aging
            if args.lifesim_natural_aging is not None
            else _env_bool("BUNNYLAND_LIFESIM_NATURAL_AGING")
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    worldgen_provider = args.worldgen_provider or args.llm_provider
    host = api_key = worldgen_api_key = discord_token = None
    openrouter_api_key = openrouter_server_url = None
    if args.llm:
        openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")
        openrouter_server_url = os.environ.get("OPENROUTER_SERVER_URL")
        host = os.environ.get("OLLAMA_HOST", OLLAMA_CLOUD_HOST)
        api_key = os.environ.get("OLLAMA_CLOUD_API_KEY")
        if args.llm_provider == "openrouter" and not openrouter_api_key:
            raise SystemExit("--llm-provider openrouter needs OPENROUTER_API_KEY")
        if args.llm_provider == "ollama" and not api_key:
            raise SystemExit(
                "--llm-provider ollama needs OLLAMA_CLOUD_API_KEY "
                "(set it in .env or the environment)"
            )
        if worldgen_provider == "openrouter" and not openrouter_api_key:
            raise SystemExit("--worldgen-provider openrouter needs OPENROUTER_API_KEY")
        if worldgen_provider == "ollama" and (not args.load) and not api_key:
            raise SystemExit(
                "--worldgen-provider ollama needs OLLAMA_CLOUD_API_KEY "
                "(set it in .env or the environment)"
            )
        worldgen_api_key = openrouter_api_key if worldgen_provider == "openrouter" else api_key
    worldgen_model = args.worldgen_model or args.ollama_model or DEFAULT_WORLDGEN_MODEL
    character_model = args.character_model or args.ollama_model or DEFAULT_MODEL
    if args.discord:
        discord_token = os.environ.get("DISCORD_TOKEN")
        if not discord_token:
            raise SystemExit("--discord needs DISCORD_TOKEN (set it in .env or the environment)")
    discord_playtest = None
    if args.discord_playtest:
        from .discord.playtest import load_discord_playtest

        discord_playtest = load_discord_playtest(args.discord_playtest)

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
            print(
                f"Generating world with {worldgen_provider} model "
                f"{worldgen_model!r}."
            )
        options = GenOptions(
            llm=args.llm,
            provider=worldgen_provider,
            model=worldgen_model,
            host=host,
            api_key=worldgen_api_key,
            server_url=openrouter_server_url,
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

    if lifesim_natural_aging is not None:
        configure_lifesim_aging(actor, natural_aging=lifesim_natural_aging)

    try:
        configure_memory_backend(actor, args.memory_backend, args.memory_path)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if args.memory_backend != "in-memory":
        print(
            f"Using {args.memory_backend!r} memory backend"
            f"{f' at {args.memory_path}' if args.memory_path else ''}."
        )

    if args.llm:
        from .llm_agents import OllamaAgent, OpenRouterAgent, ProviderRouterAgent

        providers = {}
        if api_key:
            providers["ollama"] = OllamaAgent(model=character_model, host=host, api_key=api_key)
        if openrouter_api_key:
            providers["openrouter"] = OpenRouterAgent(
                model=character_model,
                api_key=openrouter_api_key,
                server_url=openrouter_server_url,
            )
        if args.llm_provider not in providers:
            raise SystemExit(f"no LLM agent configured for provider {args.llm_provider!r}")
        agent = ProviderRouterAgent(providers, default_provider=args.llm_provider)
        print(
            f"Driving characters with default {args.llm_provider} model "
            f"{character_model!r}."
        )
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
    claim_timeout_seconds = args.claim_timeout_seconds
    if claim_timeout_seconds is None:
        env_claim_timeout_seconds = _env_int("BUNNYLAND_CLAIM_TIMEOUT_SECONDS")
        claim_timeout_seconds = (
            env_claim_timeout_seconds
            if env_claim_timeout_seconds is not None
            else CLAIM_TIMEOUT_DEFAULT_SECONDS
        )
    if claim_timeout_seconds > 0:
        normalize_claim_timeout(claim_timeout_seconds)
        actor.register_after_tick(
            ClaimTimeoutSystem(
                default_timeout_seconds=claim_timeout_seconds,
                controller_kinds=tuple(args.claim_timeout_controller or ("discord", "web")),
                default_llm_model=character_model,
                default_llm_provider=args.llm_provider,
            )
        )
    loop = GameLoop(
        actor, dispatch, tick_seconds=args.tick_seconds, time_scale=args.time_scale,
        autosave=autosave, autosave_every=args.autosave_every,
        paused=bool(args.load and args.load_paused),
    )
    discord_bot = None
    if args.discord:
        from .discord import DiscordBot, DiscordMessageFilters, parse_discord_id_list

        guild_filter_ids = tuple(
            args.discord_allowed_guild_id
            or parse_discord_id_list(os.environ.get("BUNNYLAND_DISCORD_ALLOWED_GUILD_IDS"))
        )
        channel_filter_ids = tuple(
            args.discord_allowed_channel_id
            or parse_discord_id_list(os.environ.get("BUNNYLAND_DISCORD_ALLOWED_CHANNEL_IDS"))
        )
        dm_user_filter_ids = tuple(
            args.discord_allowed_dm_user_id
            or parse_discord_id_list(os.environ.get("BUNNYLAND_DISCORD_ALLOWED_DM_USER_IDS"))
        )

        discord_bot = DiscordBot(
            actor,
            token=discord_token,
            allow_child_claims=args.discord_allow_child_claims,
            llm_provider=args.llm_provider,
            character_model=character_model,
            pause_status=lambda: loop.paused,
            message_filters=DiscordMessageFilters(
                guild_ids=guild_filter_ids,
                channel_ids=channel_filter_ids,
                dm_user_ids=dm_user_filter_ids,
            ),
        )
        claim_user_id = args.discord_user_id or _env_int("BUNNYLAND_DISCORD_USER_ID")
        claim_channel_id = args.discord_channel_id or _env_int("BUNNYLAND_DISCORD_CHANNEL_ID") or 0
        claim_character = args.discord_character or os.environ.get("BUNNYLAND_DISCORD_CHARACTER")
        if claim_user_id is not None:
            try:
                claimed = assign_discord_controller(
                    actor,
                    discord_user_id=claim_user_id,
                    default_channel_id=claim_channel_id,
                    character_name=claim_character,
                    allow_child_claims=args.discord_allow_child_claims,
                )
            except RuntimeError as exc:
                print(f"Skipped startup Discord claim for user {claim_user_id}: {exc}")
            else:
                print(f"Assigned Discord user {claim_user_id} to {claimed!r}.")
                if args.save:
                    save_world(actor, args.save, meta=meta)
        else:
            print("Discord bot enabled without a startup character claim.")

    max_ticks = args.ticks if args.ticks > 0 else None
    display_ticks = (
        discord_playtest.resolved_ticks(max_ticks)
        if discord_playtest is not None
        else max_ticks
    )
    print(
        f"Running game loop "
        f"({'forever' if display_ticks is None else f'{display_ticks} ticks'})..."
    )
    if discord_playtest is not None:
        from .discord.playtest import run_discord_playtest

        result = await run_discord_playtest(loop, discord_playtest, max_ticks=max_ticks)
        ticks = result.ticks
        print(
            f"Discord playtest passed: {len(result.inputs)} input(s), "
            f"{len(result.messages)} message(s)."
        )
    elif args.api_port is None:
        ticks = await _run_with_optional_discord(loop.run(max_ticks=max_ticks), loop, discord_bot)
    else:
        from .server.runtime import run_loop_with_api

        print(f"Serving client API at http://{args.api_host}:{args.api_port}.")
        if args.mcp:
            print(f"Serving MCP at http://{args.api_host}:{args.api_port}/mcp.")
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
                        provider=worldgen_provider,
                        model=worldgen_model,
                        host=host,
                        api_key=worldgen_api_key,
                        server_url=openrouter_server_url,
                        max_rooms=args.max_rooms,
                    ),
                    plugins=plugins,
                    mcp_admin_token=args.mcp_admin_token
                    or os.environ.get("BUNNYLAND_MCP_ADMIN_TOKEN"),
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
    serve.add_argument(
        "--starter-pack",
        choices=tuple(sorted(STARTER_PACKS)),
        default=None,
        help=(
            "enable a preset plugin group at startup "
            "(peaceful, fantastic, futuristic; env: BUNNYLAND_STARTER_PACK)"
        ),
    )
    serve.add_argument("--seed", default="a quiet marsh", help="world-generation seed")
    serve.add_argument(
        "--llm", action="store_true", help="drive characters with an LLM (needs llm extra)"
    )
    serve.add_argument(
        "--llm-provider",
        choices=("ollama", "openrouter"),
        default="ollama",
        help="default LLM provider for character controllers (default: ollama)",
    )
    serve.add_argument(
        "--worldgen-provider",
        choices=("ollama", "openrouter"),
        default=None,
        help="LLM provider for world generation (default: --llm-provider)",
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
        "--generator", default="recursive", help="world generator to use (e.g. oneshot, recursive)"
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
    serve.add_argument(
        "--memory-backend",
        choices=("in-memory", "chroma"),
        default="in-memory",
        help="memory store backend for notes and remember/search",
    )
    serve.add_argument(
        "--memory-path",
        default=None,
        help="persistent Chroma directory when --memory-backend=chroma",
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
        "--claim-timeout-seconds",
        type=int,
        default=None,
        help=(
            "default wall-clock seconds before inactive player claims expire "
            "(300-3600; 0 disables; env: BUNNYLAND_CLAIM_TIMEOUT_SECONDS)"
        ),
    )
    serve.add_argument(
        "--claim-timeout-controller",
        action="append",
        choices=("discord", "web"),
        default=None,
        help=(
            "controller kind subject to claim timeout; repeat for more "
            "(default: discord and web)"
        ),
    )
    serve.add_argument(
        "--lifesim-natural-aging",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "enable or disable lifesim ageing into elderhood and natural-cause death "
            "(env: BUNNYLAND_LIFESIM_NATURAL_AGING)"
        ),
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
    serve.add_argument(
        "--discord-allowed-guild-id",
        action="append",
        type=int,
        default=None,
        help=(
            "allow Discord commands from this guild id; repeat for more "
            "(env: BUNNYLAND_DISCORD_ALLOWED_GUILD_IDS)"
        ),
    )
    serve.add_argument(
        "--discord-allowed-channel-id",
        action="append",
        type=int,
        default=None,
        help=(
            "allow Discord commands from this guild channel id; repeat for more "
            "(env: BUNNYLAND_DISCORD_ALLOWED_CHANNEL_IDS)"
        ),
    )
    serve.add_argument(
        "--discord-allowed-dm-user-id",
        action="append",
        type=int,
        default=None,
        help=(
            "allow Discord DM commands from this user id; repeat for more "
            "(env: BUNNYLAND_DISCORD_ALLOWED_DM_USER_IDS)"
        ),
    )
    serve.add_argument(
        "--discord-playtest",
        default=None,
        help="run a JSON playtest through a mocked Discord adapter instead of Discord",
    )
    serve.add_argument(
        "--mcp",
        action="store_true",
        help="mount the HTTP MCP server on the existing API port (needs mcp and server extras)",
    )
    serve.add_argument(
        "--mcp-admin-token",
        default=None,
        help="admin token required by MCP world mutation tools (or BUNNYLAND_MCP_ADMIN_TOKEN)",
    )

    tui = sub.add_parser("tui", help="open the terminal client (needs the tui extra)")
    tui.add_argument("--server", help="connect to a running server (e.g. http://localhost:8765)")
    tui.add_argument("--seed", default="a quiet marsh", help="seed for a locally hosted world")
    tui.add_argument(
        "--generator", default="apartment-demo", help="generator for a locally hosted world"
    )
    tui.add_argument(
        "--claim-fallback",
        choices=("suspend", "llm"),
        default=None,
        help="controller fallback when the TUI claim times out",
    )
    tui.add_argument(
        "--claim-timeout-minutes",
        type=int,
        default=None,
        help="claim timeout override in minutes, between 5 and 60",
    )

    args = parser.parse_args(argv)

    if args.command == "tui":
        from .tui import main as tui_main

        tui_args = (
            ["--server", args.server]
            if args.server
            else ["--seed", args.seed, "--generator", args.generator]
        )
        if args.claim_fallback:
            tui_args.extend(["--claim-fallback", args.claim_fallback])
        if args.claim_timeout_minutes is not None:
            tui_args.extend(
                ["--claim-timeout-minutes", str(args.claim_timeout_minutes)]
            )
        return tui_main(tui_args)

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
