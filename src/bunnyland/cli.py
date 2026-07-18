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
import json
import logging
import os
import sys
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from pathlib import Path

from bunnyland.simpacks.lifesim.mechanics import configure_lifesim_aging

from . import telemetry
from .claims import ClaimSecretRegistry
from .core.claim_timeout import CLAIM_TIMEOUT_DEFAULT_SECONDS, normalize_claim_timeout
from .core.systems import ClaimTimeoutSystem
from .core.world_actor import WorldActor
from .discord.claim import assign_discord_controller
from .engine import GameLoop
from .llm_agents import DEFAULT_MODEL, ControllerDispatch, ScriptedAgent
from .memory import install_memory
from .migrations import migrate_snapshot
from .persistence import (
    WorldMeta,
    build_recovery_manifest,
    load_world,
    read_world_meta,
    save_world,
    write_recovery_manifest,
)
from .persistence_yaml import YAMLPersistenceDriver
from .plugins import (
    PluginError,
    PluginRegistry,
    PluginRuntimeContext,
    apply_plugins,
    bunnyland_plugins,
    collect_persona_fragments,
    collect_prompt_fragments,
    resolve_order,
    select,
    validate_plugin_config,
)
from .plugins.ids import (
    BARBARIANSIM,
    COLONYSIM,
    CORE_VERBS,
    DRAGONSIM,
    GARDENSIM,
    LIFESIM,
    MCP,
    MEDIA,
    NUKESIM,
    PROMPT_FILTERS,
    VOIDSIM,
    WORLDGEN,
)
from .prompts.builder import PromptBuilder
from .worldgen import (
    DEFAULT_WORLDGEN_MODEL,
    GenOptions,
    collect_generators,
    traced_generate,
)

#: Ollama Cloud endpoint; the API key authenticates against it.
OLLAMA_CLOUD_HOST = "https://ollama.com"
STARTER_PACKS: dict[str, tuple[str, ...]] = {
    "peaceful": (CORE_VERBS, WORLDGEN, LIFESIM, COLONYSIM, GARDENSIM),
    "fantastic": (
        CORE_VERBS,
        WORLDGEN,
        LIFESIM,
        COLONYSIM,
        GARDENSIM,
        BARBARIANSIM,
        DRAGONSIM,
    ),
    "futuristic": (
        CORE_VERBS,
        WORLDGEN,
        LIFESIM,
        COLONYSIM,
        GARDENSIM,
        BARBARIANSIM,
        VOIDSIM,
        NUKESIM,
    ),
}


@dataclass(frozen=True)
class ServeModels:
    worldgen_model: str
    character_model: str


@dataclass(frozen=True)
class ServeCredentials:
    worldgen_provider: str
    host: str | None = None
    api_key: str | None = None
    worldgen_api_key: str | None = None
    openrouter_api_key: str | None = None
    openrouter_server_url: str | None = None
    discord_token: str | None = None


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
    enabled_ids: list[str] | None,
    extra_enabled_ids: tuple[str, ...] = (),
    starter_pack: str | None = None,
) -> list:
    """Discover installed plugins and select which are enabled."""
    plugins = list(bunnyland_plugins())
    if enabled_ids is not None:
        enabled_ids = _dedupe_plugin_ids([MEDIA, PROMPT_FILTERS, *enabled_ids])
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


def build_actor(enabled_ids: list[str] | None) -> tuple[WorldActor, list]:
    """Create an actor and apply installed requested plugins; return (actor, applied)."""
    chosen = select_plugins(enabled_ids)
    actor = WorldActor()
    applied = apply_plugins(chosen, actor)
    return actor, applied


def configure_memory_backend(actor: WorldActor, backend: str, path: str | None = None) -> None:
    if backend == "in-memory":
        return
    if backend == "json":
        if path is None:
            raise RuntimeError(
                "json memory backend requires --memory-path or --save to choose a file"
            )
        from .memory.jsonfile import JsonMemoryStore

        install_memory(actor, JsonMemoryStore(path))
        return
    if backend != "chroma":
        raise ValueError(f"unknown memory backend {backend!r}")
    from .memory.chroma import ChromaMemoryStore

    install_memory(actor, ChromaMemoryStore(persist_path=path))


def _resolve_memory_path(args) -> str | None:
    if args.memory_path:
        return args.memory_path
    if not args.save:
        return None
    save_path = Path(args.save)
    if args.memory_backend == "chroma":
        return str(save_path.with_name(f"{save_path.stem}.memory") / "chroma")
    if args.memory_backend == "json":
        return str(save_path.with_name(f"{save_path.stem}.memory.json"))
    return None


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


def _validate_serve_args(args) -> None:
    if args.discord and args.discord_playtest:
        raise SystemExit(
            "--discord-playtest uses a mocked Discord adapter; do not combine it with --discord"
        )
    if args.api_port is not None and args.discord_playtest:
        raise SystemExit("--discord-playtest cannot be combined with --api-port yet")
    if args.mcp and args.api_port is None:
        raise SystemExit("--mcp mounts on the HTTP API and needs --api-port")
    if getattr(args, "character_chat", False) and args.api_port is None:
        raise SystemExit("--character-chat mounts on the HTTP API and needs --api-port")


def _load_serve_plugins(args) -> tuple[list, list, PluginRuntimeContext]:
    try:
        plugins = select_plugins(
            args.plugin,
            extra_enabled_ids=(MCP,) if args.mcp else (),
            starter_pack=args.starter_pack or os.environ.get("BUNNYLAND_STARTER_PACK") or None,
        )
        ordered_plugins = resolve_order(plugins)
        plugin_config = validate_plugin_config(
            ordered_plugins, getattr(args, "plugin_config", None)
        )
    except PluginError as exc:
        logging.getLogger(__name__).error("plugin loading failed: %s", exc)
        raise SystemExit(2) from exc
    # TODO: add --auto-load-requires to include missing required plugins automatically.
    return (
        plugins,
        ordered_plugins,
        PluginRuntimeContext(
            plugin_config=plugin_config,
            addon_config=getattr(args, "addon_config", None) or {},
        ),
    )


def _lifesim_natural_aging_setting(args) -> bool | None:
    try:
        if args.lifesim_natural_aging is not None:
            return args.lifesim_natural_aging
        return _env_bool("BUNNYLAND_LIFESIM_NATURAL_AGING")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _serve_models(args) -> ServeModels:
    return ServeModels(
        worldgen_model=args.worldgen_model or args.ollama_model or DEFAULT_WORLDGEN_MODEL,
        character_model=args.character_model or args.ollama_model or DEFAULT_MODEL,
    )


def _serve_credentials(args) -> ServeCredentials:
    worldgen_provider = args.worldgen_provider or args.llm_provider
    discord_token = None
    host = api_key = worldgen_api_key = None
    openrouter_api_key = openrouter_server_url = None

    if args.llm or getattr(args, "character_chat", False):
        openrouter_api_key = getattr(args, "openrouter_api_key", None) or os.environ.get(
            "OPENROUTER_API_KEY"
        )
        openrouter_server_url = getattr(args, "openrouter_server_url", None) or os.environ.get(
            "OPENROUTER_SERVER_URL"
        )
        host = getattr(args, "ollama_host", None) or os.environ.get(
            "OLLAMA_HOST", OLLAMA_CLOUD_HOST
        )
        api_key = getattr(args, "ollama_api_key", None) or os.environ.get("OLLAMA_CLOUD_API_KEY")
        if args.llm_provider == "openrouter" and not openrouter_api_key:
            raise SystemExit("--llm-provider openrouter needs OPENROUTER_API_KEY")
        if args.llm_provider == "ollama" and not api_key:
            raise SystemExit(
                "--llm-provider ollama needs OLLAMA_CLOUD_API_KEY "
                "(set it in .env or the environment)"
            )
        if args.llm and worldgen_provider == "openrouter" and not openrouter_api_key:
            raise SystemExit("--worldgen-provider openrouter needs OPENROUTER_API_KEY")
        if args.llm and worldgen_provider == "ollama" and (not args.load) and not api_key:
            raise SystemExit(
                "--worldgen-provider ollama needs OLLAMA_CLOUD_API_KEY "
                "(set it in .env or the environment)"
            )
        worldgen_api_key = openrouter_api_key if worldgen_provider == "openrouter" else api_key

    if args.discord:
        discord_token = getattr(args, "discord_token", None) or os.environ.get("DISCORD_TOKEN")
        if not discord_token:
            raise SystemExit("--discord needs DISCORD_TOKEN (set it in .env or the environment)")

    return ServeCredentials(
        worldgen_provider=worldgen_provider,
        host=host,
        api_key=api_key,
        worldgen_api_key=worldgen_api_key,
        openrouter_api_key=openrouter_api_key,
        openrouter_server_url=openrouter_server_url,
        discord_token=discord_token,
    )


def _load_discord_playtest(args):
    if not args.discord_playtest:
        return None
    from .discord.playtest import load_discord_playtest

    return load_discord_playtest(args.discord_playtest)


async def _load_or_generate_world(
    args,
    plugins: list,
    ordered_plugins: list,
    credentials: ServeCredentials,
    models: ServeModels,
    plugin_context: PluginRuntimeContext | None = None,
) -> tuple[WorldActor, WorldMeta]:
    plugin_context = plugin_context or PluginRuntimeContext()
    if args.load:
        try:
            actor, meta = load_world(
                args.load,
                registry=PluginRegistry(plugins),
                plugin_context=plugin_context,
            )
        except PluginError as exc:
            logging.getLogger(__name__).error("plugin loading failed: %s", exc)
            raise SystemExit(2) from exc
        print(
            f"Reloaded world from {args.load!r}: seed {meta.seed!r}, "
            f"generator {meta.generator!r}, game epoch {actor.epoch}s."
        )
        return actor, meta

    actor = WorldActor()
    apply_plugins(plugins, actor, plugin_context)
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
            f"Generating world with {credentials.worldgen_provider} model "
            f"{models.worldgen_model!r}."
        )
    options = _worldgen_options(args, credentials, models)
    result = await traced_generate(generator, actor, args.seed, options)
    meta = WorldMeta(
        seed=args.seed,
        generator=generator.name,
        prompt=result.prompt,  # the literal DM system prompt (empty for stub builders)
        plugins=tuple(plugin.id for plugin in ordered_plugins),
    )
    print(
        f"Generated world {args.seed!r} via {generator.name!r}: "
        f"{len(result.rooms)} rooms, {len(result.characters)} characters."
    )
    return actor, meta


def _worldgen_options(args, credentials: ServeCredentials, models: ServeModels) -> GenOptions:
    return GenOptions(
        llm=args.llm,
        provider=credentials.worldgen_provider,
        model=models.worldgen_model,
        host=credentials.host,
        api_key=credentials.worldgen_api_key,
        server_url=credentials.openrouter_server_url,
        max_rooms=args.max_rooms,
    )


def _configure_actor_backends(
    actor: WorldActor,
    args,
    lifesim_natural_aging: bool | None,
) -> None:
    if lifesim_natural_aging is not None:
        configure_lifesim_aging(actor, natural_aging=lifesim_natural_aging)

    memory_path = _resolve_memory_path(args)
    try:
        configure_memory_backend(actor, args.memory_backend, memory_path)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if args.memory_backend != "in-memory":
        print(
            f"Using {args.memory_backend!r} memory backend"
            f"{f' at {memory_path}' if memory_path else ''}."
        )


def _build_provider_agent(args, credentials: ServeCredentials, models: ServeModels):
    from .llm_agents import OllamaAgent, OpenRouterAgent, ProviderRouterAgent

    providers = {}
    if credentials.api_key:
        providers["ollama"] = OllamaAgent(
            model=models.character_model,
            host=credentials.host,
            api_key=credentials.api_key,
        )
    if credentials.openrouter_api_key:
        providers["openrouter"] = OpenRouterAgent(
            model=models.character_model,
            api_key=credentials.openrouter_api_key,
            server_url=credentials.openrouter_server_url,
        )
    if args.llm_provider not in providers:
        raise SystemExit(f"no LLM agent configured for provider {args.llm_provider!r}")
    agent = ProviderRouterAgent(providers, default_provider=args.llm_provider)
    print(f"Driving characters with default {args.llm_provider} model {models.character_model!r}.")
    return agent


def _build_serve_agent(args, credentials: ServeCredentials, models: ServeModels):
    if not args.llm:
        print("Offline demo (no --llm): characters will wait.")
        return ScriptedAgent([])  # offline: characters wait, the world still ticks
    return _build_provider_agent(args, credentials, models)


def _build_character_chat_service(args, actor, builder, credentials, models):
    if not getattr(args, "character_chat", False):
        return None
    from .server.character_chat import build_character_chat_service

    agent = _build_provider_agent(args, credentials, models)
    print("Character chat enabled for current LLM-controlled characters.")
    return build_character_chat_service(actor, builder, agent)


def _make_autosave(actor: WorldActor, args, meta: WorldMeta):
    if not args.save or args.autosave_every <= 0:
        return None

    def autosave(ticks: int) -> None:
        save_world(actor, args.save, meta=meta)
        print(f"  [autosave] tick {ticks} -> {args.save}")

    return autosave


def _configure_claim_timeout(actor: WorldActor, args, models: ServeModels) -> None:
    claim_timeout_seconds = args.claim_timeout_seconds
    if claim_timeout_seconds is None:
        env_claim_timeout_seconds = _env_int("BUNNYLAND_CLAIM_TIMEOUT_SECONDS")
        claim_timeout_seconds = (
            env_claim_timeout_seconds
            if env_claim_timeout_seconds is not None
            else CLAIM_TIMEOUT_DEFAULT_SECONDS
        )
    if claim_timeout_seconds <= 0:
        return

    normalize_claim_timeout(claim_timeout_seconds)
    actor.register_after_tick(
        ClaimTimeoutSystem(
            default_timeout_seconds=claim_timeout_seconds,
            controller_kinds=tuple(args.claim_timeout_controller or ("discord", "web")),
            default_llm_model=models.character_model,
            default_llm_provider=args.llm_provider,
        )
    )


def _discord_filter_ids(
    args,
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    from .discord import parse_discord_id_list

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
    allowed_bot_user_ids = tuple(
        args.discord_allowed_bot_user_id
        or parse_discord_id_list(os.environ.get("BUNNYLAND_DISCORD_ALLOWED_BOT_USER_IDS"))
    )
    return guild_filter_ids, channel_filter_ids, dm_user_filter_ids, allowed_bot_user_ids


def _setup_discord_bot(
    actor: WorldActor,
    loop: GameLoop,
    args,
    credentials: ServeCredentials,
    models: ServeModels,
    meta: WorldMeta,
    claim_secrets: ClaimSecretRegistry,
    imagegen=None,
):
    if not args.discord:
        return None

    from .discord import DiscordBot, DiscordMessageFilters

    guild_filter_ids, channel_filter_ids, dm_user_filter_ids, allowed_bot_user_ids = (
        _discord_filter_ids(args)
    )
    discord_bot = DiscordBot(
        actor,
        token=credentials.discord_token,
        allow_child_claims=args.discord_allow_child_claims,
        llm_provider=args.llm_provider,
        character_model=models.character_model,
        pause_status=lambda: loop.paused,
        message_filters=DiscordMessageFilters(
            guild_ids=guild_filter_ids,
            channel_ids=channel_filter_ids,
            dm_user_ids=dm_user_filter_ids,
            allowed_bot_user_ids=allowed_bot_user_ids,
        ),
        imagegen=imagegen,
        claim_secrets=claim_secrets,
        cooldown_seconds=max(
            0,
            _env_int("BUNNYLAND_DISCORD_COOLDOWN_SECONDS") or 0,
        ),
    )
    _maybe_assign_startup_discord_claim(actor, args, meta, claim_secrets)
    return discord_bot


def _maybe_assign_startup_discord_claim(
    actor: WorldActor,
    args,
    meta: WorldMeta,
    claim_secrets: ClaimSecretRegistry,
) -> None:
    claim_user_id = args.discord_user_id or _env_int("BUNNYLAND_DISCORD_USER_ID")
    claim_channel_id = args.discord_channel_id or _env_int("BUNNYLAND_DISCORD_CHANNEL_ID") or 0
    claim_character = args.discord_character or os.environ.get("BUNNYLAND_DISCORD_CHARACTER")
    if claim_user_id is None:
        print("Discord bot enabled without a startup character claim.")
        return

    try:
        claimed = assign_discord_controller(
            actor,
            discord_user_id=claim_user_id,
            default_channel_id=claim_channel_id,
            character_name=claim_character,
            allow_child_claims=args.discord_allow_child_claims,
            claim_secrets=claim_secrets,
        )
    except RuntimeError as exc:
        print(f"Skipped startup Discord claim for user {claim_user_id}: {exc}")
        return

    print(f"Assigned Discord user {claim_user_id} to {claimed!r}.")
    if args.save:
        save_world(actor, args.save, meta=meta)


async def _run_serve_runtime(
    loop: GameLoop,
    actor: WorldActor,
    meta: WorldMeta,
    args,
    plugins: list,
    discord_playtest,
    discord_bot,
    credentials: ServeCredentials,
    models: ServeModels,
    imagegen=None,
    character_chat=None,
    claim_secrets: ClaimSecretRegistry | None = None,
) -> int:
    max_ticks = args.ticks if args.ticks > 0 else None
    display_ticks = (
        discord_playtest.resolved_ticks(max_ticks) if discord_playtest is not None else max_ticks
    )
    print(
        f"Running game loop ({'forever' if display_ticks is None else f'{display_ticks} ticks'})..."
    )
    if discord_playtest is not None:
        return await _run_discord_playtest_runtime(loop, discord_playtest, max_ticks)
    if args.api_port is None:
        return await _run_with_optional_discord(loop.run(max_ticks=max_ticks), loop, discord_bot)
    return await _run_api_runtime(
        loop,
        actor,
        meta,
        args,
        plugins,
        discord_bot,
        credentials,
        models,
        max_ticks,
        imagegen=imagegen,
        character_chat=character_chat,
        claim_secrets=claim_secrets,
    )


async def _run_discord_playtest_runtime(loop: GameLoop, discord_playtest, max_ticks: int | None):
    from .discord.playtest import run_discord_playtest

    result = await run_discord_playtest(loop, discord_playtest, max_ticks=max_ticks)
    print(
        f"Discord playtest passed: {len(result.inputs)} input(s), "
        f"{len(result.messages)} message(s)."
    )
    return result.ticks


async def _run_api_runtime(
    loop: GameLoop,
    actor: WorldActor,
    meta: WorldMeta,
    args,
    plugins: list,
    discord_bot,
    credentials: ServeCredentials,
    models: ServeModels,
    max_ticks: int | None,
    imagegen=None,
    character_chat=None,
    claim_secrets: ClaimSecretRegistry | None = None,
) -> int:
    from .server.runtime import run_loop_with_api

    print(f"Serving client API at http://{args.api_host}:{args.api_port}.")
    if args.mcp:
        print(f"Serving MCP at http://{args.api_host}:{args.api_port}/mcp.")
    try:
        return await _run_with_optional_discord(
            run_loop_with_api(
                loop,
                actor,
                meta,
                host=args.api_host,
                port=args.api_port,
                save_path=args.save,
                definitions_path=args.controller_definitions,
                worldgen_options=_worldgen_options(args, credentials, models),
                plugins=plugins,
                    auth_users_path=getattr(args, "auth_users_file", "data/auth-users.yml"),
                    token_db_path=getattr(args, "token_db", "data/auth-tokens.sqlite3"),
                player_client_ids=getattr(args, "player_client_id", None),
                admin_client_ids=getattr(args, "admin_client_id", None),
                cors_origins=getattr(args, "cors_origin", None),
                forwarded_allow_ips=getattr(args, "forwarded_allow_ips", "127.0.0.1"),
                imagegen=imagegen,
                character_chat=character_chat,
                claim_secrets=claim_secrets,
                max_ticks=max_ticks,
            ),
            loop,
            discord_bot,
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


def _build_imagegen_service(actor, plugins, config_block=None, plugin_config=None):
    """Build image generation when a provider is selected or ComfyUI is configured."""
    from .imagegen.config import ImageGenConfig
    from .imagegen.wiring import build_image_service

    if config_block is None:
        config = ImageGenConfig.from_env()
    else:
        config = ImageGenConfig(
            server_url=config_block.server_url.rstrip("/"),
            generator=config_block.generator,
            generators=dict(config_block.generators),
            openrouter_image_model=config_block.openrouter_image_model,
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", "").strip(),
            openrouter_server_url=os.environ.get("OPENROUTER_SERVER_URL", "").strip(),
            use_websocket=config_block.use_websocket,
            poll_interval_seconds=config_block.poll_interval_seconds,
            timeout_seconds=config_block.timeout_seconds,
            backfill_interval_seconds=config_block.backfill_interval_seconds,
            media_root=config_block.media_root,
            public_base_url=config_block.public_base_url.rstrip("/"),
            templates_path=config_block.templates_path,
            workflows=config_block.workflows,
            prompt_style=config_block.prompt_style,
            enhancer=config_block.enhancer,
            model=config_block.model,
        )
    if config is None:
        return None
    names = sorted(
        {
            config.generator_for(purpose)
            for purpose in ("portrait", "entity", "sprite", "event")
        }
    )
    print(f"Image generation enabled via {', '.join(names)}.")
    if plugin_config is None:
        return build_image_service(actor, config, plugins=plugins)
    return build_image_service(actor, config, plugins=plugins, plugin_config=plugin_config)


_CONFIG_ARG_FLAGS: dict[str, tuple[str, ...]] = {
    "plugin": ("--plugin",),
    "starter_pack": ("--starter-pack",),
    "seed": ("--seed",),
    "llm": ("--llm",),
    "llm_provider": ("--llm-provider",),
    "worldgen_provider": ("--worldgen-provider",),
    "worldgen_model": ("--worldgen-model",),
    "character_model": ("--character-model",),
    "generator": ("--generator",),
    "max_rooms": ("--max-rooms",),
    "load": ("--load",),
    "load_paused": ("--load-paused",),
    "memory_backend": ("--memory-backend",),
    "memory_path": ("--memory-path",),
    "save": ("--save",),
    "controller_definitions": ("--controller-definitions",),
    "autosave_every": ("--autosave-every",),
    "ticks": ("--ticks",),
    "tick_seconds": ("--tick-seconds",),
    "time_scale": ("--time-scale",),
    "claim_timeout_seconds": ("--claim-timeout-seconds",),
    "claim_timeout_controller": ("--claim-timeout-controller",),
    "lifesim_natural_aging": ("--lifesim-natural-aging", "--no-lifesim-natural-aging"),
    "api_host": ("--api-host",),
    "api_port": ("--api-port",),
    "discord": ("--discord",),
    "discord_user_id": ("--discord-user-id",),
    "discord_channel_id": ("--discord-channel-id",),
    "discord_character": ("--discord-character",),
    "discord_allow_child_claims": ("--discord-allow-child-claims",),
    "discord_allowed_guild_id": ("--discord-allowed-guild-id",),
    "discord_allowed_channel_id": ("--discord-allowed-channel-id",),
    "discord_allowed_dm_user_id": ("--discord-allowed-dm-user-id",),
    "discord_allowed_bot_user_id": ("--discord-allowed-bot-user-id",),
    "mcp": ("--mcp",),
    "character_chat": ("--character-chat",),
    "auth_users_file": ("--auth-users-file",),
    "token_db": ("--token-db",),
    "player_client_id": ("--player-client-id",),
    "admin_client_id": ("--admin-client-id",),
    "cors_origin": ("--cors-origin",),
    "forwarded_allow_ips": ("--forwarded-allow-ips",),
}


def _raw_flag_present(raw_argv: Sequence[str], flags: tuple[str, ...]) -> bool:
    for arg in raw_argv:
        for flag in flags:
            if arg == flag or arg.startswith(f"{flag}="):
                return True
    return False


def _apply_config_to_serve_args(args, raw_argv: Sequence[str]) -> None:
    if not getattr(args, "config", None):
        return
    from .config import BunnylandConfig

    config = BunnylandConfig.load(args.config)
    values = config.to_serve_args()
    for name, value in values.items():
        flags = _CONFIG_ARG_FLAGS.get(name)
        if flags is not None and _raw_flag_present(raw_argv, flags):
            continue
        setattr(args, name, value)


async def _serve(args) -> None:
    _validate_serve_args(args)
    plugins, ordered_plugins, plugin_context = _load_serve_plugins(args)
    load_dotenv()
    telemetry.init_telemetry()
    lifesim_natural_aging = _lifesim_natural_aging_setting(args)
    models = _serve_models(args)
    credentials = _serve_credentials(args)
    discord_playtest = _load_discord_playtest(args)
    actor, meta = await _load_or_generate_world(
        args,
        plugins,
        ordered_plugins,
        credentials,
        models,
        plugin_context,
    )
    actor.configure_persistence(
        save_path=args.save,
        meta=meta,
        plugins=tuple(plugins),
        plugin_context=plugin_context,
    )
    telemetry.register_world_gauges(actor)
    _configure_actor_backends(actor, args, lifesim_natural_aging)
    imagegen = _build_imagegen_service(
        actor,
        plugins,
        getattr(args, "imagegen_config", None),
        plugin_context.plugin_config,
    )
    agent = _build_serve_agent(args, credentials, models)
    autosave = _make_autosave(actor, args, meta)
    builder = PromptBuilder(
        actor.world,
        fragment_providers=collect_prompt_fragments(plugins),
        persona_providers=collect_persona_fragments(plugins),
    )
    dispatch = ControllerDispatch(actor, builder, agent)
    character_chat = _build_character_chat_service(args, actor, builder, credentials, models)
    _configure_claim_timeout(actor, args, models)
    claim_secrets = ClaimSecretRegistry()
    loop = GameLoop(
        actor,
        dispatch,
        tick_seconds=args.tick_seconds,
        time_scale=args.time_scale,
        autosave=autosave,
        autosave_every=args.autosave_every,
        paused=bool(args.load and args.load_paused),
    )
    discord_bot = _setup_discord_bot(
        actor,
        loop,
        args,
        credentials,
        models,
        meta,
        claim_secrets,
        imagegen,
    )
    ticks = await _run_serve_runtime(
        loop,
        actor,
        meta,
        args,
        plugins,
        discord_playtest,
        discord_bot,
        credentials,
        models,
        imagegen=imagegen,
        character_chat=character_chat,
        claim_secrets=claim_secrets,
    )
    print(f"Stopped after {ticks} ticks at game epoch {actor.epoch}s.")

    if args.save:
        saved = save_world(actor, args.save, meta=meta)
        print(f"Saved world to {args.save!r} (seed {saved.seed!r}, epoch {saved.saved_at_epoch}s).")


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)

    # Terminal clients own their complete argument surfaces. Dispatch before the
    # server parser so their parsers and the ``bunnyland`` subcommands stay identical.
    if raw_argv and raw_argv[0] == "tui":
        from .tui import main as tui_main

        return tui_main(raw_argv[1:])
    if raw_argv and raw_argv[0] == "repl":
        from .repl import main as repl_main

        return repl_main(raw_argv[1:])

    parser = argparse.ArgumentParser(prog="bunnyland")
    sub = parser.add_subparsers(dest="command")

    migrate_world = sub.add_parser(
        "migrate-world", help="convert a schema-v1/v2/v3 JSON or YAML world to schema v4"
    )
    migrate_world.add_argument("source", help="source world; never modified")
    migrate_world.add_argument("dest", help="destination JSON or YAML world")

    recovery_manifest = sub.add_parser(
        "recovery-manifest",
        help="create a checksummed release recovery manifest for a saved world",
    )
    recovery_manifest.add_argument("snapshot", help="checksummed JSON or YAML world snapshot")
    recovery_manifest.add_argument("media_manifest", help="media checksum manifest")
    recovery_manifest.add_argument("output", help="recovery manifest JSON path")
    recovery_manifest.add_argument("--release", required=True, help="release manifest name")
    recovery_manifest.add_argument(
        "--pin",
        action="append",
        required=True,
        metavar="REPOSITORY=COMMIT",
        help="pinned repository commit; repeat for every release repository",
    )
    recovery_manifest.add_argument(
        "--rollback-checkpoint",
        required=True,
        help="verified rollback snapshot or checkpoint identifier",
    )

    auth = sub.add_parser("auth", help="manage Bunnyland users and opaque access tokens")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_hash = auth_sub.add_parser("hash-password", help="generate an Argon2 password hash")
    auth_hash.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from stdin instead of a protected prompt",
    )
    auth_provision = auth_sub.add_parser(
        "provision-token", help="provision a manual-rotation automation token"
    )
    auth_provision.add_argument("--db", required=True, help="private token SQLite database")
    auth_provision.add_argument("--subject", required=True)
    auth_provision.add_argument("--scope", action="append", required=True)
    auth_provision.add_argument("--expires-days", type=int, default=90)
    auth_list = auth_sub.add_parser("list-tokens", help="list token metadata without secrets")
    auth_list.add_argument("--db", required=True, help="private token SQLite database")
    auth_import = auth_sub.add_parser(
        "import-token-digest", help="idempotently import pre-generated automation metadata"
    )
    auth_import.add_argument("--db", required=True, help="private token SQLite database")
    auth_import.add_argument("--token-id", required=True)
    auth_import.add_argument("--digest", required=True)
    auth_import.add_argument("--subject", required=True)
    auth_import.add_argument("--scope", action="append", required=True)
    auth_import.add_argument("--expires-at", type=int, required=True)
    auth_revoke = auth_sub.add_parser("revoke", help="revoke one token id or all subject tokens")
    auth_revoke.add_argument("--db", required=True, help="private token SQLite database")
    revoke_target = auth_revoke.add_mutually_exclusive_group(required=True)
    revoke_target.add_argument("--token-id")
    revoke_target.add_argument("--subject")
    auth_replace = auth_sub.add_parser("replace-token", help="replace and revoke a manual token")
    auth_replace.add_argument("--db", required=True, help="private token SQLite database")
    auth_replace.add_argument("--token-id", required=True)

    serve = sub.add_parser("serve", help="generate a world and run the game loop")
    serve.add_argument("--config", default=None, help="read server settings from YAML")
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
        choices=("in-memory", "chroma", "json"),
        default="in-memory",
        help="memory store backend for notes and remember/search",
    )
    serve.add_argument(
        "--memory-path",
        default=None,
        help=(
            "persistent Chroma directory when --memory-backend=chroma, "
            "or JSON file when --memory-backend=json"
        ),
    )
    serve.add_argument("--save", default=None, help="save the world to this path on exit")
    serve.add_argument(
        "--controller-definitions",
        default=None,
        help="JSON file storing editor-loaded scripted/behavioral controller definitions; "
        "loaded on boot and updated when the script editor registers new ones",
    )
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
            "controller kind subject to claim timeout; repeat for more (default: discord and web)"
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
        "--discord-allowed-bot-user-id",
        action="append",
        type=int,
        default=None,
        help=(
            "allow Discord commands from this bot user id; repeat for more "
            "(env: BUNNYLAND_DISCORD_ALLOWED_BOT_USER_IDS)"
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
        "--character-chat",
        action="store_true",
        help="enable opt-in character chat routes on the HTTP API (needs llm and server extras)",
    )
    serve.add_argument(
        "--auth-users-file",
        default=os.environ.get("BUNNYLAND_AUTH_USERS_FILE", "data/auth-users.yml"),
        help="deployment-rendered YAML user credential file",
    )
    serve.add_argument(
        "--token-db",
        default=os.environ.get("BUNNYLAND_TOKEN_DB", "data/auth-tokens.sqlite3"),
        help="private SQLite opaque-token store",
    )
    serve.add_argument(
        "--player-client-id",
        action="append",
        default=None,
        help=(
            "allow this player client_id; repeat or use comma-separated values "
            "(env: BUNNYLAND_PLAYER_CLIENT_IDS)"
        ),
    )
    serve.add_argument(
        "--admin-client-id",
        action="append",
        default=None,
        help=(
            "allow this admin client_id; repeat or use comma-separated values "
            "(env: BUNNYLAND_ADMIN_CLIENT_IDS)"
        ),
    )
    serve.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        help="allow one absolute browser CORS origin; repeat as needed",
    )
    serve.add_argument(
        "--forwarded-allow-ips",
        default=os.environ.get("BUNNYLAND_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        help="exact trusted reverse-proxy address passed to Uvicorn",
    )

    sub.add_parser("tui", add_help=False, help="open the terminal client (needs the tui extra)")
    sub.add_parser("repl", add_help=False, help="open the terminal REPL (needs the repl extra)")

    chat = sub.add_parser("chat", help="chat with an LLM-controlled character")
    chat.add_argument("--server", default="http://127.0.0.1:8765/v1")
    chat.add_argument("--character", default="", help="character id or exact name")

    config_wizard = sub.add_parser("config-wizard", help="create or validate bunnyland.yml")
    config_wizard.add_argument("--config", default="bunnyland.yml")
    config_wizard.add_argument("--write-config", default=None)
    config_wizard.add_argument("--write-web-config", default=None)
    config_wizard.add_argument("--dry-run", action="store_true")
    config_wizard.add_argument("--non-interactive", action="store_true")
    config_wizard.add_argument(
        "--cli", action="store_true", help="use prompt mode instead of Textual"
    )
    config_wizard.add_argument(
        "--plugin",
        action="append",
        default=None,
        help="preselect a plugin id in the Textual checklist",
    )

    args = parser.parse_args(raw_argv)

    if args.command == "migrate-world":
        source = Path(args.source)
        dest = Path(args.dest)
        if source.resolve() == dest.resolve():
            parser.error("migrate-world SOURCE and DEST must be different paths")
        driver = YAMLPersistenceDriver()
        snapshot = (
            driver.read_snapshot(source)
            if source.suffix.lower() in {".yaml", ".yml"}
            else json.loads(source.read_text())
        )
        migrated = migrate_snapshot(snapshot)
        WorldMeta.model_validate(migrated.get("bunnyland", {}))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.suffix.lower() in {".yaml", ".yml"}:
            driver.save_snapshot(migrated, dest)
        else:
            dest.write_text(json.dumps(migrated, indent=2) + "\n")
        print(f"Migrated {source} -> {dest} (schema v4).")
        return 0

    if args.command == "recovery-manifest":
        pins: dict[str, str] = {}
        for value in args.pin:
            repository, separator, commit = value.partition("=")
            if not separator or not repository.strip() or not commit.strip():
                parser.error("--pin must use REPOSITORY=COMMIT")
            pins[repository.strip()] = commit.strip()
        snapshot = Path(args.snapshot)
        manifest = build_recovery_manifest(
            snapshot,
            meta=read_world_meta(snapshot),
            release=args.release,
            release_pins=pins,
            media_manifest_path=args.media_manifest,
            rollback_checkpoint=args.rollback_checkpoint,
        )
        write_recovery_manifest(args.output, manifest)
        print(f"Wrote recovery manifest to {args.output!r} for world {manifest.world_id}.")
        return 0

    if args.command == "auth":
        from .server.auth import TokenStore, hash_password

        if args.auth_command == "hash-password":
            if args.password_stdin:
                password = sys.stdin.readline().rstrip("\r\n")
            else:
                from getpass import getpass

                password = getpass("Password: ")
                if password != getpass("Confirm password: "):
                    parser.error("passwords do not match")
            if not password:
                parser.error("password must not be empty")
            print(hash_password(password))
            return 0
        token_store = TokenStore(args.db)
        try:
            if args.auth_command == "provision-token":
                if args.expires_days <= 0:
                    parser.error("--expires-days must be positive")
                token, _principal = token_store.issue(
                    args.subject,
                    args.scope,
                    automatic_rotation=False,
                    lifetime_seconds=args.expires_days * 24 * 60 * 60,
                )
                print(token)
                return 0
            if args.auth_command == "list-tokens":
                print(json.dumps(token_store.list_metadata(), indent=2, sort_keys=True))
                return 0
            if args.auth_command == "import-token-digest":
                try:
                    imported = token_store.import_digest(
                        args.token_id,
                        args.digest,
                        args.subject,
                        args.scope,
                        expires_at=args.expires_at,
                    )
                except ValueError as exc:
                    parser.error(str(exc))
                print(json.dumps({"imported": imported}))
                return 0
            if args.auth_command == "revoke":
                count = (
                    int(token_store.revoke_token(args.token_id))
                    if args.token_id
                    else token_store.revoke_subject(args.subject)
                )
                print(json.dumps({"revoked": count}))
                return 0
            # The parser requires one of the commands handled above; replacement is the
            # only remaining choice here.
            try:
                token, _principal = token_store.replace(args.token_id)
            except KeyError:
                parser.error("token id does not exist")
            print(token)
            return 0
        finally:
            token_store.close()

    if args.command == "chat":
        from .chat import main as chat_main

        chat_args = ["--server", args.server]
        if args.character:
            chat_args.extend(["--character", args.character])
        return chat_main(chat_args)

    if args.command == "config-wizard":
        from .config_wizard import main as config_wizard_main

        wizard_args = ["--config", args.config]
        if args.write_config:
            wizard_args.extend(["--write-config", args.write_config])
        if args.write_web_config:
            wizard_args.extend(["--write-web-config", args.write_web_config])
        if args.dry_run:
            wizard_args.append("--dry-run")
        if args.non_interactive:
            wizard_args.append("--non-interactive")
        if args.cli:
            wizard_args.append("--cli")
        for plugin in args.plugin or []:
            wizard_args.extend(["--plugin", plugin])
        return config_wizard_main(wizard_args)

    if args.command != "serve":
        parser.print_help()
        return 0

    _apply_config_to_serve_args(args, raw_argv)

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)

    asyncio.run(_serve(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
