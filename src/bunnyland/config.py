"""YAML configuration for Bunnyland server and deployment setup."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, TypeAdapter
from pydantic.dataclasses import dataclass

from .cli_defaults import DEFAULT_CHARACTER_MODEL, DEFAULT_WORLDGEN_MODEL, OLLAMA_CLOUD_HOST


def _csv(values: Sequence[int | str] | None) -> str:
    return ",".join(str(value) for value in values or ())


def _set_if(env: dict[str, str], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        env[key] = "1" if value else "0"
        return
    text = str(value)
    if text != "":
        env[key] = text


def _web_themes_json(themes: tuple[WebTheme, ...] | str) -> str:
    if isinstance(themes, str):
        return themes or "[]"
    return json.dumps(
        [{"value": theme.value, "label": theme.label} for theme in themes],
        separators=(",", ":"),
    )


def _web_theme_css_files(themes: tuple[WebTheme, ...] | str) -> str:
    if isinstance(themes, str):
        return ""
    return "\n".join(theme.css_file for theme in themes if theme.css_file)


@dataclass(frozen=True)
class WorldConfig:
    generator: str = "recursive"
    seed: str = "a quiet marsh"
    starter_pack: str = ""
    save: str = ""
    load: str = ""
    load_paused: bool = False
    max_rooms: int = 6
    ticks: int = 10
    tick_seconds: float = 1.0
    time_scale: float = 3600.0
    autosave_every: int = 0
    memory_backend: str = "in-memory"
    memory_path: str = ""
    controller_definitions: str = ""
    claim_timeout_seconds: int | None = None
    claim_timeout_controllers: tuple[str, ...] = ()
    lifesim_natural_aging: bool | None = None


@dataclass(frozen=True)
class PluginConfig:
    enabled: tuple[str, ...] | None = None
    config: dict[str, dict[str, Any]] = Field(default_factory=dict)


@dataclass(frozen=True)
class AddonConfig:
    modules: tuple[str, ...] = ()
    config: dict[str, dict[str, Any]] = Field(default_factory=dict)


@dataclass(frozen=True)
class LlmConfig:
    enabled: bool = False
    provider: str = "ollama"
    worldgen_provider: str = ""
    worldgen_model: str = DEFAULT_WORLDGEN_MODEL
    character_model: str = DEFAULT_CHARACTER_MODEL
    ollama_host: str = OLLAMA_CLOUD_HOST
    ollama_api_key: str = ""
    openrouter_api_key: str = ""
    openrouter_server_url: str = ""


@dataclass(frozen=True)
class DiscordConfig:
    enabled: bool = False
    token: str = ""
    user_id: int | None = None
    channel_id: int | None = None
    character: str = ""
    allow_child_claims: bool = False
    allowed_guild_ids: tuple[int, ...] = ()
    allowed_channel_ids: tuple[int, ...] = ()
    allowed_dm_user_ids: tuple[int, ...] = ()
    allowed_bot_user_ids: tuple[int, ...] = ()
    public_url: str = ""
    cooldown_seconds: int = 0


@dataclass(frozen=True)
class McpConfig:
    enabled: bool = False


@dataclass(frozen=True)
class ServerConfig:
    api_host: str = "127.0.0.1"
    api_port: int | None = None
    auth_users_file: str = "data/auth-users.yml"
    token_db: str = "data/auth-tokens.sqlite3"
    player_client_ids: tuple[str, ...] = ()
    admin_client_ids: tuple[str, ...] = ()
    character_chat: bool = False
    http_rate_limit_requests: int = 0
    http_rate_limit_window_seconds: float = 1.0
    cors_origins: tuple[str, ...] = ()
    forwarded_allow_ips: str = "127.0.0.1"


@dataclass(frozen=True)
class WebTheme:
    value: str
    label: str
    css_file: str = ""


@dataclass(frozen=True)
class WebConfig:
    theme: str = ""
    themes: tuple[WebTheme, ...] | str = ()
    favicon_file: str = ""
    home_domain: str = ""
    home_dir: str = ""
    home_cert_name: str = ""
    player_auth_required: bool = False


@dataclass(frozen=True)
class ImageGenConfigBlock:
    server_url: str = ""
    use_websocket: bool = True
    poll_interval_seconds: float = 1.0
    timeout_seconds: float = 120.0
    backfill_interval_seconds: float = 5.0
    media_root: str = "media"
    public_base_url: str = ""
    templates_path: str = ""
    workflows: str = "anima"
    prompt_style: str = ""
    enhancer: str = ""
    model: str = DEFAULT_CHARACTER_MODEL


@dataclass(frozen=True)
class DeploymentConfig:
    domain: str = ""
    data_dir: str = ""
    container_runtime: str = ""
    server_tag: str = "main"
    web_tag: str = "main"
    tls: bool = True
    cert_email: str = ""
    cert_name: str = ""
    letsencrypt_dir: str = "/etc/letsencrypt"
    http_bind: str = "0.0.0.0:80"
    https_bind: str = "0.0.0.0:443"
    configure_firewall: bool = True
    world_save: str = ""


@dataclass(frozen=True)
class BunnylandConfig:
    server: ServerConfig = Field(default_factory=ServerConfig)
    world: WorldConfig = Field(default_factory=WorldConfig)
    plugins: PluginConfig = Field(default_factory=PluginConfig)
    addons: AddonConfig = Field(default_factory=AddonConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    deployment: DeploymentConfig = Field(default_factory=DeploymentConfig)
    imagegen: ImageGenConfigBlock = Field(default_factory=ImageGenConfigBlock)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> BunnylandConfig:
        mapped = dict(data or {})
        obsolete: list[str] = []
        if "auth" in mapped:
            obsolete.append("auth")
        for section, names in {
            "server": {"admin_token", "trust_x_real_ip"},
            "deployment": {"nginx_auth_dir"},
        }.items():
            values = mapped.get(section)
            if isinstance(values, Mapping):
                obsolete.extend(f"{section}.{name}" for name in names if name in values)
        if obsolete:
            joined = ", ".join(sorted(obsolete))
            raise ValueError(
                f"obsolete authentication configuration: {joined}; configure "
                "server.auth_users_file/token_db and WebConfig.player_auth_required instead"
            )
        return _CONFIG_ADAPTER.validate_python(mapped)

    @classmethod
    def load(cls, path: str | Path) -> BunnylandConfig:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if raw is None:
            raw = {}
        if not isinstance(raw, Mapping):
            raise ValueError("Bunnyland config YAML must contain a mapping at the top level")
        return cls.from_mapping(raw)

    def to_mapping(self) -> dict[str, Any]:
        return _CONFIG_ADAPTER.dump_python(self, mode="json", exclude_none=True)

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(self.to_mapping(), sort_keys=False)
        target.write_text(text, encoding="utf-8")
        os.chmod(target, 0o600)

    def to_web_config(self) -> dict[str, Any]:
        web_config: dict[str, Any] = {
            "serverUrl": "/api/",
            "autoConnect": True,
            "playerAuthRequired": self.web.player_auth_required,
        }
        if self.discord.public_url:
            web_config["discordUrl"] = self.discord.public_url
        if self.web.theme:
            web_config["theme"] = self.web.theme
        if self.web.themes and not isinstance(self.web.themes, str):
            web_config["replaceThemes"] = True
            web_config["themes"] = [
                {"value": theme.value, "label": theme.label} for theme in self.web.themes
            ]
        elif isinstance(self.web.themes, str) and self.web.themes not in {"", "[]"}:
            web_config["replaceThemes"] = True
            web_config["themes"] = json.loads(self.web.themes)
        return web_config

    def save_web_config(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_web_config(), indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        os.chmod(target, 0o600)

    def to_serve_args(self) -> dict[str, Any]:
        world = self.world
        server = self.server
        llm = self.llm
        discord = self.discord
        plugins = self.plugins
        imagegen = self.imagegen
        return {
            "plugin": list(plugins.enabled) if plugins.enabled is not None else None,
            "starter_pack": world.starter_pack or None,
            "seed": world.seed,
            "llm": llm.enabled,
            "llm_provider": llm.provider,
            "worldgen_provider": llm.worldgen_provider or None,
            "worldgen_model": llm.worldgen_model,
            "character_model": llm.character_model,
            "generator": world.generator,
            "max_rooms": world.max_rooms,
            "load": world.load or None,
            "load_paused": world.load_paused,
            "memory_backend": world.memory_backend,
            "memory_path": world.memory_path or None,
            "save": world.save or None,
            "controller_definitions": world.controller_definitions or None,
            "autosave_every": world.autosave_every,
            "ticks": world.ticks,
            "tick_seconds": world.tick_seconds,
            "time_scale": world.time_scale,
            "claim_timeout_seconds": world.claim_timeout_seconds,
            "claim_timeout_controller": list(world.claim_timeout_controllers) or None,
            "lifesim_natural_aging": world.lifesim_natural_aging,
            "api_host": server.api_host,
            "api_port": server.api_port,
            "discord": discord.enabled,
            "discord_user_id": discord.user_id,
            "discord_channel_id": discord.channel_id,
            "discord_character": discord.character or None,
            "discord_allow_child_claims": discord.allow_child_claims,
            "discord_allowed_guild_id": list(discord.allowed_guild_ids) or None,
            "discord_allowed_channel_id": list(discord.allowed_channel_ids) or None,
            "discord_allowed_dm_user_id": list(discord.allowed_dm_user_ids) or None,
            "discord_allowed_bot_user_id": list(discord.allowed_bot_user_ids) or None,
            "mcp": self.mcp.enabled,
            "character_chat": server.character_chat,
            "auth_users_file": server.auth_users_file,
            "token_db": server.token_db,
            "player_client_id": list(server.player_client_ids) or None,
            "admin_client_id": list(server.admin_client_ids) or None,
            "cors_origin": list(server.cors_origins) or None,
            "forwarded_allow_ips": server.forwarded_allow_ips,
            "ollama_host": llm.ollama_host,
            "ollama_api_key": llm.ollama_api_key,
            "openrouter_api_key": llm.openrouter_api_key,
            "openrouter_server_url": llm.openrouter_server_url,
            "discord_token": discord.token,
            "imagegen_config": imagegen if imagegen.server_url else None,
            "plugin_config": dict(self.plugins.config),
            "addon_config": dict(self.addons.config),
        }

    def to_env(self, *, dry_run: bool = False) -> dict[str, str]:
        env: dict[str, str] = {}
        deployment = self.deployment
        world = self.world
        llm = self.llm
        discord = self.discord
        server = self.server
        web = self.web
        imagegen = self.imagegen

        _set_if(env, "BUNNYLAND_CONTAINER_RUNTIME", deployment.container_runtime)
        _set_if(env, "BUNNYLAND_DOMAIN", deployment.domain)
        _set_if(env, "BUNNYLAND_DATA_DIR", deployment.data_dir)
        _set_if(env, "BUNNYLAND_WORLD_SAVE", deployment.world_save or world.load)
        _set_if(env, "BUNNYLAND_FAVICON_FILE", web.favicon_file)
        _set_if(env, "BUNNYLAND_HOME_DOMAIN", web.home_domain)
        _set_if(env, "BUNNYLAND_HOME_DIR", web.home_dir)
        _set_if(env, "BUNNYLAND_HOME_CERT_NAME", web.home_cert_name)
        _set_if(env, "BUNNYLAND_CERT_NAME", deployment.cert_name)
        _set_if(env, "BUNNYLAND_LETSENCRYPT_DIR", deployment.letsencrypt_dir)
        _set_if(env, "BUNNYLAND_HTTP_BIND", deployment.http_bind)
        _set_if(env, "BUNNYLAND_HTTPS_BIND", deployment.https_bind)
        _set_if(env, "BUNNYLAND_SERVER_TAG", deployment.server_tag)
        _set_if(env, "BUNNYLAND_WEB_TAG", deployment.web_tag)
        _set_if(env, "BUNNYLAND_TLS", deployment.tls)
        _set_if(env, "BUNNYLAND_CONFIGURE_FIREWALL", deployment.configure_firewall)
        _set_if(env, "BUNNYLAND_CERT_EMAIL", deployment.cert_email)
        _set_if(env, "BUNNYLAND_GENERATOR", world.generator)
        _set_if(env, "BUNNYLAND_STARTER_PACK", world.starter_pack)
        _set_if(env, "BUNNYLAND_TICK_SECONDS", world.tick_seconds)
        _set_if(env, "BUNNYLAND_TIME_SCALE", world.time_scale)
        _set_if(env, "BUNNYLAND_AUTOSAVE_EVERY", world.autosave_every)
        _set_if(env, "BUNNYLAND_MEMORY_BACKEND", world.memory_backend)
        _set_if(env, "BUNNYLAND_MEMORY_PATH", world.memory_path)
        _set_if(env, "BUNNYLAND_ENABLE_LLM", llm.enabled)
        _set_if(env, "BUNNYLAND_LLM_PROVIDER", llm.provider)
        _set_if(env, "BUNNYLAND_WORLDGEN_PROVIDER", llm.worldgen_provider or llm.provider)
        _set_if(env, "BUNNYLAND_WORLDGEN_MODEL", llm.worldgen_model)
        _set_if(env, "BUNNYLAND_CHARACTER_MODEL", llm.character_model)
        _set_if(env, "BUNNYLAND_ENABLE_DISCORD", discord.enabled)
        _set_if(env, "BUNNYLAND_ENABLE_MCP", self.mcp.enabled)
        _set_if(env, "BUNNYLAND_ENABLE_CHARACTER_CHAT", server.character_chat)
        _set_if(env, "BUNNYLAND_AUTH_USERS_FILE", server.auth_users_file)
        _set_if(env, "BUNNYLAND_TOKEN_DB", server.token_db)
        _set_if(env, "BUNNYLAND_PLAYER_CLIENT_IDS", _csv(server.player_client_ids))
        _set_if(env, "BUNNYLAND_ADMIN_CLIENT_IDS", _csv(server.admin_client_ids))
        _set_if(env, "BUNNYLAND_CORS_ORIGINS", _csv(server.cors_origins))
        _set_if(env, "BUNNYLAND_FORWARDED_ALLOW_IPS", server.forwarded_allow_ips)
        _set_if(env, "BUNNYLAND_PLAYER_AUTH_REQUIRED", web.player_auth_required)
        _set_if(env, "BUNNYLAND_HTTP_RATE_LIMIT_REQUESTS", server.http_rate_limit_requests)
        _set_if(
            env,
            "BUNNYLAND_HTTP_RATE_LIMIT_WINDOW_SECONDS",
            server.http_rate_limit_window_seconds,
        )
        _set_if(env, "BUNNYLAND_DISCORD_URL", discord.public_url)
        _set_if(env, "BUNNYLAND_WEB_THEME", web.theme)
        _set_if(env, "BUNNYLAND_WEB_THEMES", _web_themes_json(web.themes))
        _set_if(env, "BUNNYLAND_WEB_REPLACE_THEMES", bool(web.themes))
        _set_if(env, "BUNNYLAND_WEB_THEME_CSS_FILES", _web_theme_css_files(web.themes))
        _set_if(env, "OLLAMA_CLOUD_API_KEY", llm.ollama_api_key)
        _set_if(env, "OLLAMA_HOST", llm.ollama_host)
        _set_if(env, "OPENROUTER_API_KEY", llm.openrouter_api_key)
        _set_if(env, "OPENROUTER_SERVER_URL", llm.openrouter_server_url)
        _set_if(env, "DISCORD_TOKEN", discord.token)
        _set_if(env, "BUNNYLAND_DISCORD_USER_ID", discord.user_id)
        _set_if(env, "BUNNYLAND_DISCORD_CHANNEL_ID", discord.channel_id)
        _set_if(env, "BUNNYLAND_DISCORD_CHARACTER", discord.character)
        _set_if(env, "BUNNYLAND_DISCORD_ALLOWED_GUILD_IDS", _csv(discord.allowed_guild_ids))
        _set_if(env, "BUNNYLAND_DISCORD_ALLOWED_CHANNEL_IDS", _csv(discord.allowed_channel_ids))
        _set_if(env, "BUNNYLAND_DISCORD_ALLOWED_DM_USER_IDS", _csv(discord.allowed_dm_user_ids))
        _set_if(env, "BUNNYLAND_DISCORD_ALLOWED_BOT_USER_IDS", _csv(discord.allowed_bot_user_ids))
        _set_if(env, "BUNNYLAND_DISCORD_COOLDOWN_SECONDS", discord.cooldown_seconds)
        _set_if(env, "COMFYUI_SERVER_URL", imagegen.server_url)
        _set_if(env, "COMFYUI_USE_WEBSOCKET", imagegen.use_websocket)
        _set_if(env, "COMFYUI_POLL_INTERVAL_SECONDS", imagegen.poll_interval_seconds)
        _set_if(env, "COMFYUI_TIMEOUT_SECONDS", imagegen.timeout_seconds)
        _set_if(env, "BUNNYLAND_IMAGE_BACKFILL_SECONDS", imagegen.backfill_interval_seconds)
        _set_if(env, "BUNNYLAND_MEDIA_DIR", imagegen.media_root)
        _set_if(env, "BUNNYLAND_PUBLIC_BASE_URL", imagegen.public_base_url)
        _set_if(env, "BUNNYLAND_IMAGE_TEMPLATES", imagegen.templates_path)
        _set_if(env, "BUNNYLAND_IMAGE_WORKFLOWS", imagegen.workflows)
        _set_if(env, "BUNNYLAND_IMAGE_PROMPT_STYLE", imagegen.prompt_style)
        _set_if(env, "BUNNYLAND_IMAGE_ENHANCER", imagegen.enhancer)
        _set_if(env, "BUNNYLAND_IMAGE_MODEL", imagegen.model)
        if dry_run:
            env["BUNNYLAND_SETUP_DRY_RUN"] = "1"
        return env


_CONFIG_ADAPTER = TypeAdapter(BunnylandConfig)


__all__ = [
    "AddonConfig",
    "BunnylandConfig",
    "DeploymentConfig",
    "DiscordConfig",
    "ImageGenConfigBlock",
    "LlmConfig",
    "McpConfig",
    "PluginConfig",
    "ServerConfig",
    "WebConfig",
    "WebTheme",
    "WorldConfig",
]
