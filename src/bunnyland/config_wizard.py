"""Python config wizard for Bunnyland deployment YAML."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from random import choice

from .config import (
    BunnylandConfig,
    DeploymentConfig,
    DiscordConfig,
    ImageGenConfigBlock,
    LlmConfig,
    McpConfig,
    PluginConfig,
    ServerConfig,
    WebConfig,
    WebTheme,
    WorldConfig,
)
from .plugins import Plugin, PluginError
from .worldgen import collect_generators

WORLD_PROMPT_PRESETS = (
    "a quiet marsh with old boardwalks",
    "a crowded night market under neon rain",
    "a mountain inn before the first snow",
    "a sunken library with breathing doors",
    "a desert rail station at dawn",
    "an overgrown greenhouse full of rumors",
    "a floating village tied to storm balloons",
    "a moonlit carnival after closing time",
    "a coastal lighthouse during a strange fog",
    "a tiny kingdom inside a ruined arcade",
    "a research bunker beneath wildflowers",
    "a clockwork garden where paths rearrange",
)


def available_plugins_for_wizard() -> tuple[tuple[Plugin, ...], tuple[str, ...]]:
    from .plugins import bunnyland_plugins

    plugins = tuple(bunnyland_plugins())
    return plugins, ()


def _resolve_enabled_plugin_ids(
    plugins: Sequence[Plugin],
    enabled_ids: Sequence[str] | None,
) -> frozenset[str] | None:
    if enabled_ids is None:
        return None

    by_id = {plugin.id: plugin for plugin in plugins}
    resolved = []
    for requested in enabled_ids:
        if requested in by_id:
            resolved.append(requested)
            continue
        suffix = f".{requested}"
        matches = [plugin.id for plugin in plugins if plugin.id.endswith(suffix)]
        if not matches:
            raise PluginError(f"unknown plugin id {requested!r}")
        if len(matches) > 1:
            raise PluginError(
                f"ambiguous plugin id {requested!r}; matches: {', '.join(sorted(matches))}"
            )
        resolved.append(matches[0])
    return frozenset(resolved)


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _prompt_required(label: str, default: str = "") -> str:
    while True:
        value = _prompt(label, default)
        if value:
            return value
        print("Please enter a value.", file=sys.stderr)


def _confirm(label: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    value = input(f"{label} {suffix}: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes"}


def _prompt_choice(label: str, choices: tuple[str, ...], default: str) -> str:
    while True:
        value = _prompt(label, default)
        if value in choices:
            return value
        print(f"Please enter one of: {', '.join(choices)}.", file=sys.stderr)


def _prompt_discord_url() -> str:
    while True:
        value = _prompt("Community Discord invite URL shown in web clients")
        if not value or value.startswith(("http://", "https://")):
            return value
        print("Please enter an http(s) URL or leave blank.", file=sys.stderr)


def _csv_values(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _csv_ints(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in _csv_values(value))


def _optional_int(value: str) -> int | None:
    return int(value) if value else None


def _optional_bool(value: str) -> bool | None:
    if value == "default":
        return None
    return value == "yes"


def _themes_text(themes: tuple[WebTheme, ...] | str) -> str:
    if isinstance(themes, str):
        return ""
    return ", ".join(
        f"{theme.value}={theme.label}:{theme.css_file}"
        if theme.css_file
        else f"{theme.value}={theme.label}"
        for theme in themes
    )


def _parse_themes_text(value: str) -> tuple[WebTheme, ...]:
    themes = []
    for item in _csv_values(value):
        if "=" not in item:
            raise ValueError("custom themes must use value=Label entries")
        theme_value, label = (part.strip() for part in item.split("=", 1))
        css_file = ""
        if ":" in label:
            label, css_file = (part.strip() for part in label.rsplit(":", 1))
        if not theme_value or not label:
            raise ValueError("custom themes must include both value and label")
        themes.append(WebTheme(value=theme_value, label=label, css_file=css_file))
    return tuple(themes)


def default_wizard_config() -> BunnylandConfig:
    return BunnylandConfig(
        deployment=DeploymentConfig(
            domain="sandbox.example.com",
            data_dir="/var/lib/bunnyland",
        ),
        llm=LlmConfig(enabled=True),
        server=ServerConfig(
            api_host="0.0.0.0",
            api_port=8765,
            character_chat=True,
            forwarded_allow_ips="172.28.0.2",
        ),
        world=WorldConfig(
            generator="lifesim-demo",
            save="/data/worlds/main.json",
            ticks=0,
            tick_seconds=30.0,
            time_scale=1800.0,
            autosave_every=20,
        ),
        imagegen=ImageGenConfigBlock(media_root="/data/media"),
    )


@dataclass(frozen=True)
class FieldHelp:
    text: str
    examples: tuple[str, ...]


def field_help(text: str, *examples: str) -> FieldHelp:
    return FieldHelp(text=text, examples=tuple(examples))


def _split_field_help(value: str) -> FieldHelp:
    text, _separator, examples = value.partition(" Examples: ")
    return field_help(
        text.rstrip("."),
        *(example.strip() for example in examples.rstrip(".").split(", ") if example.strip()),
    )


def _format_field_help(help_text: FieldHelp) -> str:
    if not help_text.examples:
        return help_text.text
    examples = "\n".join(f"- {example}" for example in help_text.examples)
    return f"{help_text.text}\n\nExamples:\n{examples}"


FIELD_HELP_TEXT = {
    "container-runtime": "Container engine used for Compose. Examples: docker, nerdctl.",
    "domain": "Public DNS name for this server. Examples: sandbox.example.com, play.example.net.",
    "data-dir": "Host storage for saves/config. Examples: /var/lib/bunnyland, /srv/bunnyland.",
    "cert-email": "Email for Let's Encrypt notices. Examples: admin@example.com, ops@example.net.",
    "tls": "Serve HTTPS with Let's Encrypt. Examples: enabled public, disabled local.",
    "cert-name": "Let's Encrypt certificate name. Examples: sandbox.example.com, bunnyland-prod.",
    "letsencrypt-dir": "Host Let's Encrypt cert dir. Examples: /etc/letsencrypt, /srv/letsencrypt.",
    "http-bind": "Host bind address for port 80. Examples: 0.0.0.0:80, 127.0.0.1:8080.",
    "https-bind": "Host bind address for port 443. Examples: 0.0.0.0:443, 127.0.0.1:8443.",
    "server-tag": "Container tag for bunnyland-server. Examples: main, v2026.07.05.",
    "web-tag": "Container tag for bunnyland-web. Examples: main, v2026.07.05.",
    "configure-firewall": "Add ufw rules. Examples: configure on VPS, leave behind proxy.",
    "auth-users-file": "Deployment-rendered Argon2 user file. Examples: /data/auth-users.yml.",
    "token-db": "Private opaque-token database. Examples: /data/auth-tokens.sqlite3.",
    "player-auth-required": "Prompt browser players to log in before auto-connect.",
    "cors-origins": "Optional absolute browser CORS origins, comma-separated.",
    "forwarded-allow-ips": "Exact trusted reverse-proxy address. Examples: 172.28.0.2.",
    "player-client-ids": (
        "Allow list of client IDs permitted to use player APIs, comma-separated. "
        "Examples: web, discord."
    ),
    "admin-client-ids": (
        "Allow list of client IDs permitted to use admin APIs, comma-separated. "
        "Examples: editor, inspector."
    ),
    "generator": "World generator used when no save is loaded. Examples: lifesim-demo, recursive.",
    "seed": "World prompt used by seed-aware generators. Examples: a quiet marsh, neon bazaar.",
    "starter-pack": (
        "Optional built-in plugin preset. Examples: peaceful includes lifesim + "
        "colonysim + gardensim, fantastic adds barbariansim + dragonsim, futuristic "
        "adds barbariansim + voidsim + nukesim."
    ),
    "world-save": "Existing host save to import/load. Examples: /srv/main.json, /tmp/demo.json.",
    "world-save-path": "Container active save path. Examples: /data/worlds/main.json.",
    "load-paused": "Start paused after load. Examples: enabled inspect, disabled live.",
    "max-rooms": "Room budget for graph generators. Examples: 6, 12.",
    "api-host": "Container listen address for the server API. Examples: 0.0.0.0, 127.0.0.1.",
    "api-port": "Container listen port for the server API. Examples: 8765, 9000.",
    "ticks": "Number of ticks before shutdown. Examples: 0 for forever, 10 for smoke tests.",
    "tick-seconds": "Real seconds between ticks. Examples: 30, 1.",
    "time-scale": "Game seconds advanced per tick. Examples: 1800, 3600.",
    "autosave-every": "Autosave interval in ticks. Examples: 20, 0 to disable.",
    "memory-backend": "Memory storage backend. Examples: in-memory, chroma.",
    "memory-path": "Persistent memory path. Examples: /data/memory, /data/memory.json.",
    "controller-definitions": "Controller definitions JSON. Examples: /data/controllers.json.",
    "claim-timeout-seconds": "Seconds before inactive claims expire. Examples: 900, 0 to disable.",
    "claim-timeout-controllers": "Controller kinds subject to timeout. Examples: discord, web.",
    "lifesim-natural-aging": "Override natural aging behavior. Examples: default, enabled.",
    "character-chat": "Enable character chat HTTP routes. Examples: enabled LLM, disabled smoke.",
    "character-sheets": "Character sheet pages and API projection. Examples: always enabled.",
    "discord-url": "Public invite shown in web clients. Examples: https://discord.gg/example.",
    "favicon-file": "Host favicon PNG to mount into nginx. Examples: /opt/bunnyland/favicon.png.",
    "home-domain": "Optional static homepage domain. Examples: bunnyland.example.com.",
    "home-dir": "Host directory for homepage files. Examples: /opt/bunnyland/home.",
    "home-cert-name": "Homepage certificate name. Examples: bunnyland.example.com.",
    "web-theme": "Default web theme value. Examples: purple-blue-dark, server-night.",
    "web-themes": "Replacement theme list. Examples: night=Night:/opt/themes/night.css.",
    "llm-enabled": "Enable LLM controllers. Examples: enabled live, disabled smoke.",
    "llm-provider": "Default LLM provider. Examples: ollama, openrouter.",
    "worldgen-provider": "LLM provider for world generation. Examples: same as LLM, openrouter.",
    "ollama-api-key": "Ollama Cloud API key. Examples: sk-...",
    "ollama-host": "Ollama endpoint. Examples: https://ollama.com, http://host:11434.",
    "openrouter-api-key": "OpenRouter API key. Examples: sk-or-...",
    "openrouter-url": "Optional OpenRouter-compatible endpoint. Examples: https://openrouter.ai/api/v1.",
    "worldgen-model": "Model used for world generation. Examples: deepseek-v4-pro, openai/gpt-4.1.",
    "character-model": "Character model. Examples: deepseek-v4-flash, openai/gpt-4.1-mini.",
    "discord-enabled": "Run Discord bot. Examples: enabled public sandbox, disabled local.",
    "discord-token": "Discord bot token. Examples: token from Discord developer portal.",
    "discord-user-id": "Optional startup Discord user ID to claim. Examples: 123456789012345678.",
    "discord-channel-id": "Optional startup Discord channel ID. Examples: 987654321098765432.",
    "discord-character": "Optional startup character name to claim. Examples: Juniper, Moss.",
    "discord-allow-child-claims": "Allow child-stage Discord claims. Examples: disabled public.",
    "discord-guild-ids": "Allowed Discord guild IDs, comma-separated. Examples: 111,222.",
    "discord-channel-ids": "Allowed Discord channel IDs, comma-separated. Examples: 333,444.",
    "discord-dm-user-ids": "Users allowed to DM the bot, comma-separated. Examples: 123,456.",
    "plugin-search": "Filter the plugin checklist. Examples: memory, lifesim.",
    "plugin-suggestions": "Install addon packages to make their entry-point plugins available.",
    "mcp-enabled": "Enable HTTP MCP endpoint. Examples: enabled for admin agents.",
    "imagegen-enabled": "Enable pluggable image generation.",
    "image-generator": "Default image generator. Examples: comfyui, in-memory, openrouter.",
    "image-generator-portrait": "Optional portrait generator override.",
    "image-generator-entity": "Optional entity generator override.",
    "image-generator-sprite": "Optional sprite generator override.",
    "image-generator-event": "Optional event generator override.",
    "image-openrouter-model": "OpenRouter image model required when OpenRouter is selected.",
    "comfy-url": "ComfyUI server URL reachable by the server container. Examples: http://comfy:8188.",
    "comfy-websocket": "Use ComfyUI websocket progress. Examples: enabled normal ComfyUI.",
    "comfy-poll-seconds": "Polling interval when websocket is disabled. Examples: 1, 2.5.",
    "comfy-timeout-seconds": "Image generation timeout. Examples: 120, 300.",
    "image-backfill-seconds": "Delay between image backfill attempts. Examples: 5, 30.",
    "image-media-root": "Container media directory. Examples: /data/media, media.",
    "image-workflows": "Workflow family. Examples: anima, flux2dev.",
    "image-public-url": "Public URL base for media. Examples: https://sandbox.example.com/media.",
    "image-templates-path": "Workflow template JSON path. Examples: /data/image-templates.json.",
    "image-prompt-style": "Prompt style override. Examples: tag, natural.",
    "image-enhancer": "Optional prompt/image enhancer. Examples: empty, ollama.",
    "image-model": "Model used for image prompt enhancement. Examples: deepseek-v4-flash.",
    "show-advanced": "Reveal low-frequency deployment/runtime fields. Examples: custom ports.",
}

FIELD_HELP = {key: _split_field_help(value) for key, value in FIELD_HELP_TEXT.items()}


def prompt_for_config() -> BunnylandConfig:
    deployment = DeploymentConfig(
        container_runtime=_prompt("Container runtime", "docker"),
        domain=_prompt_required("Public domain", "sandbox.example.com"),
        data_dir=_prompt_required("Host data directory", "/var/lib/bunnyland"),
        cert_email=_prompt("Let's Encrypt email"),
    )
    world = WorldConfig(
        starter_pack=_prompt_choice(
            "Starter pack (none/peaceful/fantastic/futuristic)",
            ("none", "peaceful", "fantastic", "futuristic"),
            "none",
        ).removeprefix("none"),
    )
    web = WebConfig(
        favicon_file=(
            _prompt_required("Custom favicon path") if _confirm("Use a custom favicon?") else ""
        ),
        home_domain=_prompt("Homepage domain served by this frontend container"),
        player_auth_required=_confirm("Require browser player login?", True),
    )
    if web.home_domain:
        web = WebConfig(
            favicon_file=web.favicon_file,
            home_domain=web.home_domain,
            home_dir=_prompt_required("Homepage files directory", "/opt/bunnyland/home"),
            home_cert_name=_prompt("Homepage certificate name", web.home_domain),
            player_auth_required=web.player_auth_required,
        )

    live_services = _confirm("Set up live services with an LLM provider and Discord now?", True)
    llm = LlmConfig(enabled=False)
    discord = DiscordConfig(enabled=False, public_url=_prompt_discord_url())
    server_character_chat = False
    if live_services:
        provider = _prompt_choice(
            "LLM provider for world generation and characters", ("ollama", "openrouter"), "ollama"
        )
        if provider == "ollama":
            llm = LlmConfig(
                enabled=True,
                provider=provider,
                worldgen_provider=provider,
                ollama_api_key=_prompt_required("OLLAMA_CLOUD_API_KEY"),
                ollama_host=_prompt("Ollama endpoint override", "https://ollama.com"),
            )
        else:
            llm = LlmConfig(
                enabled=True,
                provider=provider,
                worldgen_provider=provider,
                worldgen_model="openai/gpt-4.1",
                character_model="openai/gpt-4.1-mini",
                openrouter_api_key=_prompt_required("OPENROUTER_API_KEY"),
                openrouter_server_url=_prompt("OpenRouter endpoint override"),
            )
        llm = LlmConfig(
            enabled=True,
            provider=llm.provider,
            worldgen_provider=llm.worldgen_provider,
            worldgen_model=_prompt("Worldgen model", llm.worldgen_model),
            character_model=_prompt("Character model", llm.character_model),
            ollama_host=llm.ollama_host,
            ollama_api_key=llm.ollama_api_key,
            openrouter_api_key=llm.openrouter_api_key,
            openrouter_server_url=llm.openrouter_server_url,
        )
        server_character_chat = _confirm("Enable character chat web/API endpoints?", True)
        discord = DiscordConfig(
            enabled=True,
            token=_prompt_required("DISCORD_TOKEN"),
            user_id=_optional_int(_prompt("Startup Discord user id")),
            channel_id=_optional_int(_prompt("Startup Discord channel id")),
            character=_prompt("Startup character name"),
            public_url=discord.public_url,
        )

    mcp = McpConfig(enabled=_confirm("Enable the HTTP MCP endpoint for agentic clients?"))

    imagegen = ImageGenConfigBlock()
    if _confirm("Enable image generation via a ComfyUI server?"):
        imagegen = ImageGenConfigBlock(
            server_url=_prompt_required("ComfyUI server URL", "http://localhost:8188"),
            workflows=_prompt("Workflow family", "anima"),
            public_base_url=_prompt("Public base URL for Discord avatars"),
        )

    return BunnylandConfig(
        deployment=deployment,
        world=world,
        web=web,
        llm=llm,
        discord=discord,
        mcp=mcp,
        server=ServerConfig(
            character_chat=server_character_chat,
            forwarded_allow_ips="172.28.0.2",
        ),
        imagegen=imagegen,
    )


def review_lines(config: BunnylandConfig) -> list[str]:
    services = (
        "live services" if config.llm.enabled or config.discord.enabled else "offline smoke test"
    )
    lines = [
        "Review these settings before setup starts:",
        f"  Container runtime : {config.deployment.container_runtime or '(auto)'}",
        f"  Public domain     : {config.deployment.domain}",
        f"  Data directory    : {config.deployment.data_dir}",
        f"  User file         : {config.server.auth_users_file}",
        f"  Token database    : {config.server.token_db}",
        f"  Starter pack      : {config.world.starter_pack or '(none)'}",
        f"  Live services     : {services}",
    ]
    if config.discord.public_url:
        lines.append(f"  Discord link      : {config.discord.public_url}")
    if config.mcp.enabled:
        lines.append("  MCP endpoint      : enabled")
    if config.server.character_chat:
        lines.append("  Character chat    : enabled")
    if config.imagegen.server_url or config.imagegen.generator != "comfyui":
        detail = (
            config.imagegen.server_url
            if config.imagegen.generator == "comfyui"
            else config.imagegen.generator
        )
        lines.append(f"  Image generation  : {detail}")
    if config.plugins.enabled is None:
        lines.append("  Plugins           : default set")
    else:
        lines.append(f"  Plugins           : {len(config.plugins.enabled)} selected")
    return lines


def run_setup(
    config: BunnylandConfig,
    *,
    config_path: Path | None = None,
    web_config_path: Path | None = None,
    dry_run: bool = False,
) -> int:
    env = os.environ.copy()
    env.update(config.to_env(dry_run=dry_run))
    if config_path is not None:
        env["BUNNYLAND_CONFIG_FILE"] = str(config_path)
    if web_config_path is not None:
        env["BUNNYLAND_WEB_CONFIG_FILE"] = str(web_config_path)
    return subprocess.run(["scripts/vps-docker-setup"], env=env, check=False).returncode


def load_or_prompt_config(path: Path, *, non_interactive: bool) -> BunnylandConfig:
    if path.exists():
        return BunnylandConfig.load(path)
    if non_interactive:
        raise SystemExit(f"config file does not exist: {path}")
    return prompt_for_config()


def build_textual_wizard_app(
    initial: BunnylandConfig | None = None,
    *,
    enabled_plugins: Sequence[str] | None = None,
):
    from textual import on
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, ScrollableContainer, Vertical
    from textual.screen import ModalScreen
    from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, Select, Static

    initial = initial or default_wizard_config()
    plugin_options, _discovered_modules = available_plugins_for_wizard()
    world_generators = sorted(
        collect_generators(plugin_options).values(), key=lambda generator: generator.name
    )
    world_generator_uses_seed = {
        generator.name: generator.uses_seed for generator in world_generators
    }
    world_generator_options = [(generator.name, generator.name) for generator in world_generators]
    if initial.world.generator and initial.world.generator not in world_generator_uses_seed:
        world_generator_options.append((initial.world.generator, initial.world.generator))
        world_generator_uses_seed[initial.world.generator] = True
    explicit_plugin_ids = _resolve_enabled_plugin_ids(plugin_options, enabled_plugins)
    initial_plugin_ids = (
        frozenset(initial.plugins.enabled) | (explicit_plugin_ids or frozenset())
        if initial.plugins.enabled is not None
        else explicit_plugin_ids
        if explicit_plugin_ids is not None
        else frozenset(plugin.id for plugin in plugin_options if plugin.default_enabled)
    )
    default_plugin_ids = tuple(plugin.id for plugin in plugin_options if plugin.default_enabled)
    steps = (
        ("world", "World"),
        ("runtime", "Features"),
        ("imagegen", "Images"),
        ("llm", "LLM"),
        ("mcp", "MCP"),
        ("plugins", "Plugins"),
        ("web", "Web"),
        ("discord", "Discord"),
        ("deployment", "Deployment"),
        ("access", "Access"),
        ("review", "Review"),
    )
    field_titles: dict[str, str] = {}

    def yes_no(value: bool) -> str:
        return "yes" if value else "no"

    def field_label(
        text: str,
        widget_id: str,
        *,
        required: bool = False,
        advanced: bool = False,
    ) -> Horizontal:
        field_titles[widget_id] = text
        marker = " *" if required else ""
        classes = "field-label-row advanced-field" if advanced else "field-label-row"
        help_button = Button(
            "?",
            id=f"help-{widget_id}",
            classes="help-button",
            compact=True,
            tooltip=f"Open help for {text}",
        )
        return Horizontal(
            Label(f"{text}{marker}", classes="label field-label-text"),
            help_button,
            classes=classes,
        )

    class FieldHelpModal(ModalScreen[None]):
        BINDINGS = [Binding("escape", "close", "Close", show=False)]
        CSS = """
        FieldHelpModal { align: center middle; }
        #help-dialog {
            width: 72;
            max-width: 90%;
            height: auto;
            max-height: 80%;
            padding: 1 2;
            border: solid $accent;
            background: $surface;
        }
        #help-title { text-style: bold; color: $accent; padding-bottom: 1; }
        #help-body { padding-bottom: 1; }
        #help-close { width: 10; }
        """

        def __init__(self, title: str, help_text: FieldHelp) -> None:
            super().__init__()
            self.title_text = title
            self.help_text = help_text

        def compose(self) -> ComposeResult:
            with Vertical(id="help-dialog"):
                yield Label(self.title_text, id="help-title")
                yield Static(_format_field_help(self.help_text), id="help-body")
                yield Button("Close", id="help-close", variant="primary")

        @on(Button.Pressed, "#help-close")
        def close_pressed(self, _event: Button.Pressed) -> None:
            self.dismiss(None)

        def action_close(self) -> None:
            self.dismiss(None)

    class ConfigWizardApp(App[BunnylandConfig | None]):
        TITLE = "Bunnyland Config Wizard"
        BINDINGS = [
            Binding("ctrl+s", "save", "Save", show=True),
            Binding("escape", "cancel", "Close", show=True),
            Binding("ctrl+a", "toggle_advanced", "Advanced", show=True),
        ]

        CSS = """
        #body { height: 1fr; }
        #steps { width: 24; padding: 1; border-right: solid $panel; }
        .step-button { width: 100%; margin-bottom: 1; }
        #form { width: 1fr; padding: 1 2; }
        .page { height: auto; }
        .page-title { text-style: bold; color: $accent; padding-bottom: 1; }
        .label { padding-top: 1; color: $text-muted; }
        .field-label-row { height: auto; padding-top: 1; }
        .field-label-text { width: 1fr; padding-top: 0; }
        .help-button { width: 5; min-width: 5; margin-right: 1; }
        .password-row { height: auto; }
        .password-input { width: 1fr; }
        .generate-password-button { width: 12; margin-left: 1; }
        .copy-password-button { width: 18; margin-left: 1; }
        .prompt-row { height: auto; }
        .prompt-input { width: 1fr; }
        .random-prompt-button { width: 10; margin-left: 1; }
        .search-row { height: auto; }
        .search-input { width: 1fr; }
        .clear-search-button { width: 8; margin-left: 1; }
        #plugin-list { height: auto; border: solid $panel; padding: 0 1; }
        #buttons { height: auto; padding: 1 2 0 2; }
        #advanced-toggle { width: 12; margin-right: 2; }
        #back, #next, #save { margin-right: 1; }
        #error { color: $error; height: 1; padding: 0 2; }
        #review { height: auto; min-height: 10; }
        """

        def __init__(self) -> None:
            super().__init__()
            self.step_index = 0
            self.step_count = len(steps)
            self.last_error = ""
            self.advanced_visible = False

        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal(id="body"):
                with Vertical(id="steps"):
                    for index, (_step_id, label) in enumerate(steps):
                        yield Button(
                            f"{index + 1}. {label}",
                            id=f"step-{index}",
                            classes="step-button",
                        )
                with ScrollableContainer(id="form"):
                    yield Label("", id="error")
                    with Vertical(id="page-deployment", classes="page"):
                        yield Label("Deployment", classes="page-title")
                        yield field_label(
                            "Container runtime",
                            "container-runtime",
                            advanced=True,
                        )
                        yield Select(
                            [
                                ("auto", ""),
                                ("docker", "docker"),
                                ("nerdctl", "nerdctl"),
                                ("podman", "podman"),
                            ],
                            value=initial.deployment.container_runtime,
                            id="container-runtime",
                            allow_blank=False,
                            classes="advanced-field",
                        )
                        yield field_label("Public domain", "domain", required=True)
                        yield Input(value=initial.deployment.domain, id="domain")
                        yield field_label("Host data directory", "data-dir", required=True)
                        yield Input(value=initial.deployment.data_dir, id="data-dir")
                        yield field_label("Let's Encrypt email", "cert-email")
                        yield Input(value=initial.deployment.cert_email, id="cert-email")
                        yield field_label("TLS", "tls")
                        yield Select(
                            [("enabled", "yes"), ("disabled", "no")],
                            value=yes_no(initial.deployment.tls),
                            id="tls",
                            allow_blank=False,
                        )
                        yield field_label("Certificate name", "cert-name", advanced=True)
                        yield Input(
                            value=initial.deployment.cert_name,
                            id="cert-name",
                            classes="advanced-field",
                        )
                        yield field_label(
                            "Let's Encrypt directory",
                            "letsencrypt-dir",
                            advanced=True,
                        )
                        yield Input(
                            value=initial.deployment.letsencrypt_dir,
                            id="letsencrypt-dir",
                            classes="advanced-field",
                        )
                        yield field_label("HTTP bind address", "http-bind", advanced=True)
                        yield Input(
                            value=initial.deployment.http_bind,
                            id="http-bind",
                            classes="advanced-field",
                        )
                        yield field_label("HTTPS bind address", "https-bind", advanced=True)
                        yield Input(
                            value=initial.deployment.https_bind,
                            id="https-bind",
                            classes="advanced-field",
                        )
                        yield field_label("Server image tag", "server-tag", advanced=True)
                        yield Input(
                            value=initial.deployment.server_tag,
                            id="server-tag",
                            classes="advanced-field",
                        )
                        yield field_label("Web image tag", "web-tag", advanced=True)
                        yield Input(
                            value=initial.deployment.web_tag,
                            id="web-tag",
                            classes="advanced-field",
                        )
                        yield field_label("Firewall rules", "configure-firewall", advanced=True)
                        yield Select(
                            [("configure", "yes"), ("leave unchanged", "no")],
                            value=yes_no(initial.deployment.configure_firewall),
                            id="configure-firewall",
                            allow_blank=False,
                            classes="advanced-field",
                        )
                    with Vertical(id="page-access", classes="page"):
                        yield Label("Access", classes="page-title")
                        yield field_label("Browser player login", "player-auth-required")
                        yield Select(
                            [("required", "yes"), ("not prompted", "no")],
                            value=yes_no(initial.web.player_auth_required),
                            id="player-auth-required",
                            allow_blank=False,
                        )
                        yield field_label("Argon2 user file", "auth-users-file", required=True)
                        yield Input(
                            value=initial.server.auth_users_file,
                            id="auth-users-file",
                        )
                        yield field_label("Token database", "token-db", required=True)
                        yield Input(
                            value=initial.server.token_db,
                            id="token-db",
                        )
                        yield field_label("Allowed CORS origins", "cors-origins", advanced=True)
                        yield Input(
                            value=", ".join(initial.server.cors_origins),
                            id="cors-origins",
                            classes="advanced-field",
                        )
                        yield field_label(
                            "Trusted proxy address", "forwarded-allow-ips", advanced=True
                        )
                        yield Input(
                            value=initial.server.forwarded_allow_ips,
                            id="forwarded-allow-ips",
                            classes="advanced-field",
                        )
                        yield field_label(
                            "Player client ID allow list",
                            "player-client-ids",
                        )
                        yield Input(
                            value=", ".join(initial.server.player_client_ids),
                            id="player-client-ids",
                        )
                        yield field_label(
                            "Admin client ID allow list",
                            "admin-client-ids",
                        )
                        yield Input(
                            value=", ".join(initial.server.admin_client_ids),
                            id="admin-client-ids",
                        )
                    with Vertical(id="page-world", classes="page"):
                        yield Label("World", classes="page-title")
                        yield field_label("Starter pack", "starter-pack")
                        yield Select(
                            [
                                ("none", ""),
                                ("peaceful", "peaceful"),
                                ("fantastic", "fantastic"),
                                ("futuristic", "futuristic"),
                            ],
                            value=initial.world.starter_pack,
                            id="starter-pack",
                            allow_blank=False,
                        )
                        yield field_label("Generator", "generator")
                        yield Select(
                            world_generator_options,
                            value=initial.world.generator,
                            id="generator",
                            allow_blank=False,
                        )
                        yield field_label("World prompt", "seed")
                        with Horizontal(classes="prompt-row"):
                            yield Input(
                                value=initial.world.seed,
                                id="seed",
                                classes="prompt-input",
                            )
                            yield Button(
                                "Random",
                                id="random-world-prompt",
                                classes="random-prompt-button",
                                tooltip="Choose a preset world prompt",
                            )
                        yield field_label("Existing world save", "world-save")
                        yield Input(
                            value=initial.deployment.world_save or initial.world.load,
                            id="world-save",
                        )
                        yield field_label(
                            "Container save path",
                            "world-save-path",
                            advanced=True,
                        )
                        yield Input(
                            value=initial.world.save,
                            id="world-save-path",
                            classes="advanced-field",
                        )
                        yield field_label("Load paused", "load-paused", advanced=True)
                        yield Select(
                            [("enabled", "yes"), ("disabled", "no")],
                            value=yes_no(initial.world.load_paused),
                            id="load-paused",
                            allow_blank=False,
                            classes="advanced-field",
                        )
                        yield field_label("Max rooms", "max-rooms", advanced=True)
                        yield Input(
                            value=str(initial.world.max_rooms),
                            id="max-rooms",
                            classes="advanced-field",
                        )
                    with Vertical(id="page-runtime", classes="page"):
                        yield Label("Features", classes="page-title")
                        yield field_label("Character chat", "character-chat")
                        yield Select(
                            [("enabled", "yes"), ("disabled", "no")],
                            value=yes_no(initial.server.character_chat),
                            id="character-chat",
                            allow_blank=False,
                        )
                        yield field_label("Character sheets", "character-sheets")
                        yield Select(
                            [("enabled", "yes")],
                            value="yes",
                            id="character-sheets",
                            allow_blank=False,
                            disabled=True,
                        )
                        yield field_label("API host", "api-host", advanced=True)
                        yield Input(
                            value=initial.server.api_host,
                            id="api-host",
                            classes="advanced-field",
                        )
                        yield field_label("API port", "api-port", advanced=True)
                        yield Input(
                            value=(
                                ""
                                if initial.server.api_port is None
                                else str(initial.server.api_port)
                            ),
                            id="api-port",
                            classes="advanced-field",
                        )
                        yield field_label("Ticks", "ticks", advanced=True)
                        yield Input(
                            value=str(initial.world.ticks),
                            id="ticks",
                            classes="advanced-field",
                        )
                        yield field_label("Tick seconds", "tick-seconds", advanced=True)
                        yield Input(
                            value=str(initial.world.tick_seconds),
                            id="tick-seconds",
                            classes="advanced-field",
                        )
                        yield field_label("Time scale", "time-scale", advanced=True)
                        yield Input(
                            value=str(initial.world.time_scale),
                            id="time-scale",
                            classes="advanced-field",
                        )
                        yield field_label("Autosave every", "autosave-every", advanced=True)
                        yield Input(
                            value=str(initial.world.autosave_every),
                            id="autosave-every",
                            classes="advanced-field",
                        )
                        yield field_label("Memory backend", "memory-backend", advanced=True)
                        yield Select(
                            [
                                ("in memory", "in-memory"),
                                ("Chroma", "chroma"),
                                ("JSON", "json"),
                            ],
                            value=initial.world.memory_backend,
                            id="memory-backend",
                            allow_blank=False,
                            classes="advanced-field",
                        )
                        yield field_label("Memory path", "memory-path", advanced=True)
                        yield Input(
                            value=initial.world.memory_path,
                            id="memory-path",
                            classes="advanced-field",
                        )
                        yield field_label(
                            "Controller definitions",
                            "controller-definitions",
                            advanced=True,
                        )
                        yield Input(
                            value=initial.world.controller_definitions,
                            id="controller-definitions",
                            classes="advanced-field",
                        )
                        yield field_label(
                            "Claim timeout seconds",
                            "claim-timeout-seconds",
                            advanced=True,
                        )
                        yield Input(
                            value=""
                            if initial.world.claim_timeout_seconds is None
                            else str(initial.world.claim_timeout_seconds),
                            id="claim-timeout-seconds",
                            classes="advanced-field",
                        )
                        yield field_label(
                            "Claim timeout controllers",
                            "claim-timeout-controllers",
                            advanced=True,
                        )
                        yield Input(
                            value=", ".join(initial.world.claim_timeout_controllers),
                            id="claim-timeout-controllers",
                            classes="advanced-field",
                        )
                        yield field_label(
                            "Lifesim natural aging",
                            "lifesim-natural-aging",
                            advanced=True,
                        )
                        yield Select(
                            [
                                ("default", "default"),
                                ("enabled", "yes"),
                                ("disabled", "no"),
                            ],
                            value=(
                                "default"
                                if initial.world.lifesim_natural_aging is None
                                else yes_no(initial.world.lifesim_natural_aging)
                            ),
                            id="lifesim-natural-aging",
                            allow_blank=False,
                            classes="advanced-field",
                        )
                    with Vertical(id="page-web", classes="page"):
                        yield Label("Web", classes="page-title")
                        yield field_label("Community Discord invite URL", "discord-url")
                        yield Input(value=initial.discord.public_url, id="discord-url")
                        yield field_label("Custom favicon path", "favicon-file")
                        yield Input(value=initial.web.favicon_file, id="favicon-file")
                        yield field_label("Homepage domain", "home-domain", advanced=True)
                        yield Input(
                            value=initial.web.home_domain,
                            id="home-domain",
                            classes="advanced-field",
                        )
                        yield field_label(
                            "Homepage files directory",
                            "home-dir",
                            advanced=True,
                        )
                        yield Input(
                            value=initial.web.home_dir,
                            id="home-dir",
                            classes="advanced-field",
                        )
                        yield field_label(
                            "Homepage certificate name",
                            "home-cert-name",
                            advanced=True,
                        )
                        yield Input(
                            value=initial.web.home_cert_name,
                            id="home-cert-name",
                            classes="advanced-field",
                        )
                        yield field_label("Default web theme", "web-theme")
                        yield Input(value=initial.web.theme, id="web-theme")
                        yield field_label("Theme entries", "web-themes")
                        yield Input(
                            value=_themes_text(initial.web.themes),
                            placeholder="theme-id=Theme Label:/path/theme.css",
                            id="web-themes",
                        )
                    with Vertical(id="page-llm", classes="page"):
                        yield Label("LLM", classes="page-title")
                        yield field_label("LLM controllers", "llm-enabled")
                        yield Select(
                            [("enabled", "yes"), ("disabled", "no")],
                            value=yes_no(initial.llm.enabled),
                            id="llm-enabled",
                            allow_blank=False,
                        )
                        yield field_label("LLM provider", "llm-provider")
                        yield Select(
                            [("Ollama Cloud", "ollama"), ("OpenRouter", "openrouter")],
                            value=initial.llm.provider,
                            id="llm-provider",
                            allow_blank=False,
                        )
                        yield field_label("Worldgen provider", "worldgen-provider")
                        yield Select(
                            [
                                ("same as LLM", ""),
                                ("Ollama Cloud", "ollama"),
                                ("OpenRouter", "openrouter"),
                            ],
                            value=initial.llm.worldgen_provider,
                            id="worldgen-provider",
                            allow_blank=False,
                        )
                        yield field_label("Ollama API key", "ollama-api-key")
                        yield Input(
                            value=initial.llm.ollama_api_key,
                            password=True,
                            id="ollama-api-key",
                        )
                        yield field_label("Ollama endpoint", "ollama-host")
                        yield Input(value=initial.llm.ollama_host, id="ollama-host")
                        yield field_label("OpenRouter API key", "openrouter-api-key")
                        yield Input(
                            value=initial.llm.openrouter_api_key,
                            password=True,
                            id="openrouter-api-key",
                        )
                        yield field_label("OpenRouter endpoint", "openrouter-url")
                        yield Input(
                            value=initial.llm.openrouter_server_url,
                            id="openrouter-url",
                        )
                        yield field_label("Worldgen model", "worldgen-model")
                        yield Input(value=initial.llm.worldgen_model, id="worldgen-model")
                        yield field_label("Character model", "character-model")
                        yield Input(value=initial.llm.character_model, id="character-model")
                    with Vertical(id="page-discord", classes="page"):
                        yield Label("Discord", classes="page-title")
                        yield field_label("Discord bot", "discord-enabled")
                        yield Select(
                            [("enabled", "yes"), ("disabled", "no")],
                            value=yes_no(initial.discord.enabled),
                            id="discord-enabled",
                            allow_blank=False,
                        )
                        yield field_label("Discord bot token", "discord-token")
                        yield Input(
                            value=initial.discord.token,
                            password=True,
                            id="discord-token",
                        )
                        yield field_label("Startup Discord user id", "discord-user-id")
                        yield Input(
                            value=(
                                ""
                                if initial.discord.user_id is None
                                else str(initial.discord.user_id)
                            ),
                            id="discord-user-id",
                        )
                        yield field_label("Startup Discord channel id", "discord-channel-id")
                        yield Input(
                            value=""
                            if initial.discord.channel_id is None
                            else str(initial.discord.channel_id),
                            id="discord-channel-id",
                        )
                        yield field_label("Startup character name", "discord-character")
                        yield Input(value=initial.discord.character, id="discord-character")
                        yield field_label("Allow child claims", "discord-allow-child-claims")
                        yield Select(
                            [("enabled", "yes"), ("disabled", "no")],
                            value=yes_no(initial.discord.allow_child_claims),
                            id="discord-allow-child-claims",
                            allow_blank=False,
                        )
                        yield field_label("Allowed guild IDs", "discord-guild-ids")
                        yield Input(
                            value=", ".join(
                                str(value) for value in initial.discord.allowed_guild_ids
                            ),
                            id="discord-guild-ids",
                        )
                        yield field_label("Allowed channel IDs", "discord-channel-ids")
                        yield Input(
                            value=", ".join(
                                str(value) for value in initial.discord.allowed_channel_ids
                            ),
                            id="discord-channel-ids",
                        )
                        yield field_label("Allowed DM user IDs", "discord-dm-user-ids")
                        yield Input(
                            value=", ".join(
                                str(value) for value in initial.discord.allowed_dm_user_ids
                            ),
                            id="discord-dm-user-ids",
                        )
                    with Vertical(id="page-plugins", classes="page"):
                        yield Label("Plugins", classes="page-title")
                        yield Static(
                            "Security: only import plugin modules you trust. Importing a "
                            "Python module executes its code.",
                            id="plugin-security-note",
                        )
                        yield field_label("Search", "plugin-search")
                        with Horizontal(classes="search-row"):
                            yield Input(
                                placeholder="Filter by plugin id or name",
                                id="plugin-search",
                                classes="search-input",
                            )
                            yield Button(
                                "Clear",
                                id="clear-plugin-search",
                                classes="clear-search-button",
                            )
                        with Vertical(id="plugin-list"):
                            for index, plugin in enumerate(plugin_options):
                                yield Checkbox(
                                    f"{plugin.name} ({plugin.id})",
                                    value=plugin.id in initial_plugin_ids,
                                    id=f"plugin-{index}",
                                    classes="plugin-option",
                                )
                        yield Static("", id="plugin-suggestions")
                    with Vertical(id="page-mcp", classes="page"):
                        yield Label("MCP", classes="page-title")
                        yield field_label("HTTP MCP endpoint", "mcp-enabled")
                        yield Select(
                            [("enabled", "yes"), ("disabled", "no")],
                            value=yes_no(initial.mcp.enabled),
                            id="mcp-enabled",
                            allow_blank=False,
                        )
                    with Vertical(id="page-imagegen", classes="page"):
                        yield Label("Images", classes="page-title")
                        yield field_label("Image generation", "imagegen-enabled")
                        yield Select(
                            [("enabled", "yes"), ("disabled", "no")],
                            value=yes_no(
                                bool(initial.imagegen.server_url)
                                or initial.imagegen.generator != "comfyui"
                            ),
                            id="imagegen-enabled",
                            allow_blank=False,
                        )
                        yield field_label("Default generator", "image-generator")
                        yield Select(
                            [
                                ("ComfyUI", "comfyui"),
                                ("In-memory", "in-memory"),
                                ("OpenRouter", "openrouter"),
                            ],
                            value=initial.imagegen.generator,
                            id="image-generator",
                            allow_blank=False,
                        )
                        for purpose in ("portrait", "entity", "sprite", "event"):
                            yield field_label(
                                f"{purpose.title()} generator override",
                                f"image-generator-{purpose}",
                            )
                            yield Input(
                                value=initial.imagegen.generators.get(purpose, ""),
                                id=f"image-generator-{purpose}",
                            )
                        yield field_label("OpenRouter image model", "image-openrouter-model")
                        yield Input(
                            value=initial.imagegen.openrouter_image_model,
                            id="image-openrouter-model",
                        )
                        yield field_label("ComfyUI server URL", "comfy-url")
                        yield Input(value=initial.imagegen.server_url, id="comfy-url")
                        yield field_label("Use websocket", "comfy-websocket")
                        yield Select(
                            [("enabled", "yes"), ("disabled", "no")],
                            value=yes_no(initial.imagegen.use_websocket),
                            id="comfy-websocket",
                            allow_blank=False,
                        )
                        yield field_label("Poll interval seconds", "comfy-poll-seconds")
                        yield Input(
                            value=str(initial.imagegen.poll_interval_seconds),
                            id="comfy-poll-seconds",
                        )
                        yield field_label("Timeout seconds", "comfy-timeout-seconds")
                        yield Input(
                            value=str(initial.imagegen.timeout_seconds),
                            id="comfy-timeout-seconds",
                        )
                        yield field_label("Backfill interval seconds", "image-backfill-seconds")
                        yield Input(
                            value=str(initial.imagegen.backfill_interval_seconds),
                            id="image-backfill-seconds",
                        )
                        yield field_label("Media root", "image-media-root")
                        yield Input(value=initial.imagegen.media_root, id="image-media-root")
                        yield field_label("Workflow family", "image-workflows")
                        yield Input(value=initial.imagegen.workflows, id="image-workflows")
                        yield field_label("Public image base URL", "image-public-url")
                        yield Input(
                            value=initial.imagegen.public_base_url,
                            id="image-public-url",
                        )
                        yield field_label("Templates path", "image-templates-path")
                        yield Input(
                            value=initial.imagegen.templates_path,
                            id="image-templates-path",
                        )
                        yield field_label("Prompt style", "image-prompt-style")
                        yield Input(value=initial.imagegen.prompt_style, id="image-prompt-style")
                        yield field_label("Enhancer", "image-enhancer")
                        yield Input(value=initial.imagegen.enhancer, id="image-enhancer")
                        yield field_label("Image model", "image-model")
                        yield Input(value=initial.imagegen.model, id="image-model")
                    with Vertical(id="page-review", classes="page"):
                        yield Label("Review", classes="page-title")
                        yield Static("", id="review")
            with Horizontal(id="buttons"):
                advanced = Button("Advanced", id="advanced-toggle")
                advanced.tooltip = _format_field_help(FIELD_HELP["show-advanced"])
                yield advanced
                yield Button("Back", id="back")
                yield Button("Next", id="next", variant="primary")
                yield Button("Apply", id="save", variant="success", disabled=True)
                yield Button("Close", id="cancel")
            yield Footer()

        def on_mount(self) -> None:
            self._show_advanced(False)
            self._update_world_prompt_state()
            self._show_step(0)

        def _show_advanced(self, show: bool) -> None:
            self.advanced_visible = show
            for widget in self.query(".advanced-field"):
                widget.display = show
            button = self.query_one("#advanced-toggle", Button)
            button.variant = "warning" if show else "default"

        def _show_step(self, index: int) -> None:
            self.step_index = max(0, min(index, len(steps) - 1))
            for step_id, _label in steps:
                self.query_one(f"#page-{step_id}", Vertical).display = False
            step_id, _label = steps[self.step_index]
            self.query_one(f"#page-{step_id}", Vertical).display = True
            for step_index in range(len(steps)):
                button = self.query_one(f"#step-{step_index}", Button)
                button.variant = "primary" if step_index == self.step_index else "default"
            self.query_one("#back", Button).disabled = self.step_index == 0
            self.query_one("#next", Button).display = self.step_index < len(steps) - 1
            self._update_save_state()
            self.last_error = ""
            self.query_one("#error", Label).update("")
            if step_id == "review":
                self._update_review()

        def _required_fields_ready(self) -> bool:
            return bool(
                self._input("#domain")
                and self._input("#data-dir")
                and self._input("#auth-users-file")
                and self._input("#token-db")
            )

        def _update_save_state(self) -> None:
            self.query_one("#save", Button).disabled = not self._required_fields_ready()

        def _update_world_prompt_state(self) -> None:
            generator = self._select("#generator")
            enabled = world_generator_uses_seed.get(generator, True)
            self.query_one("#seed", Input).disabled = not enabled
            self.query_one("#random-world-prompt", Button).disabled = not enabled

        def _step_text(self) -> str:
            lines = []
            for index, (_step_id, label) in enumerate(steps):
                marker = ">" if index == self.step_index else " "
                lines.append(f"{marker} {index + 1}. {label}")
            return "\n".join(lines)

        def _input(self, widget_id: str) -> str:
            return self.query_one(widget_id, Input).value.strip()

        def _select(self, widget_id: str) -> str:
            value = self.query_one(widget_id, Select).value
            return "" if value is Select.BLANK else str(value)

        def _enabled(self, widget_id: str) -> bool:
            return self._select(widget_id) == "yes"

        def _selected_plugin_ids(self) -> tuple[str, ...]:
            selected = []
            for index, plugin in enumerate(plugin_options):
                if self.query_one(f"#plugin-{index}", Checkbox).value:
                    selected.append(plugin.id)
            return tuple(selected)

        def _enabled_plugin_ids(self) -> tuple[str, ...] | None:
            selected = self._selected_plugin_ids()
            if (
                initial.plugins.enabled is None
                and explicit_plugin_ids is None
                and selected == default_plugin_ids
            ):
                return None
            return selected

        def _filter_plugins(self) -> None:
            query = self._input("#plugin-search").casefold()
            for index, plugin in enumerate(plugin_options):
                haystack = f"{plugin.id} {plugin.name}".casefold()
                self.query_one(f"#plugin-{index}", Checkbox).display = (
                    not query or query in haystack
                )

        def _fail(self, message: str) -> None:
            self.last_error = message
            if self.step_index == len(steps) - 1:
                self.query_one("#error", Label).update("")
                self.query_one("#review", Static).update(message)
                return
            self.query_one("#error", Label).update(message)

        def _int(self, widget_id: str) -> int:
            return int(self._input(widget_id))

        def _float(self, widget_id: str) -> float:
            return float(self._input(widget_id))

        def _optional_int_input(self, widget_id: str) -> int | None:
            return _optional_int(self._input(widget_id))

        def _csv_int_input(self, widget_id: str) -> tuple[int, ...]:
            return _csv_ints(self._input(widget_id))

        def _build_config(self) -> BunnylandConfig | None:
            try:
                domain = self._input("#domain")
                data_dir = self._input("#data-dir")
                discord_url = self._input("#discord-url")
                llm_enabled = self._enabled("#llm-enabled")
                discord_enabled = self._enabled("#discord-enabled")
                mcp_enabled = self._enabled("#mcp-enabled")
                imagegen_enabled = self._enabled("#imagegen-enabled")

                if not domain or not data_dir:
                    self._fail("Domain and data directory are required.")
                    return None
                if not self._input("#auth-users-file") or not self._input("#token-db"):
                    self._fail("Authentication user file and token database are required.")
                    return None
                if discord_url and not discord_url.startswith(("http://", "https://")):
                    self._fail("Discord URL must be http(s).")
                    return None

                provider = self._select("#llm-provider")
                worldgen_provider = self._select("#worldgen-provider") or provider
                character_chat = self._enabled("#character-chat")
                if (
                    (llm_enabled or character_chat)
                    and (provider == "ollama" or worldgen_provider == "ollama")
                    and not self._input("#ollama-api-key")
                ):
                    self._fail("Ollama API key is required for Ollama-backed services.")
                    return None
                if (
                    (llm_enabled or character_chat)
                    and (provider == "openrouter" or worldgen_provider == "openrouter")
                    and not self._input("#openrouter-api-key")
                ):
                    self._fail("OpenRouter API key is required for OpenRouter services.")
                    return None
                if discord_enabled and not self._input("#discord-token"):
                    self._fail("Discord bot token is required when Discord is enabled.")
                    return None
                image_generator = self._select("#image-generator")
                image_generator_overrides = {
                    purpose: self._input(f"#image-generator-{purpose}")
                    for purpose in ("portrait", "entity", "sprite", "event")
                    if self._input(f"#image-generator-{purpose}")
                }
                selected_image_generators = {
                    image_generator,
                    *image_generator_overrides.values(),
                }
                if (
                    imagegen_enabled
                    and "comfyui" in selected_image_generators
                    and not self._input("#comfy-url")
                ):
                    self._fail("ComfyUI server URL is required for image generation.")
                    return None
                if (
                    imagegen_enabled
                    and "openrouter" in selected_image_generators
                    and not self._input("#image-openrouter-model")
                ):
                    self._fail("OpenRouter image model is required for image generation.")
                    return None
                if (
                    imagegen_enabled
                    and "openrouter" in selected_image_generators
                    and not self._input("#openrouter-api-key")
                ):
                    self._fail("OpenRouter API key is required for image generation.")
                    return None
                themes = _parse_themes_text(self._input("#web-themes"))

                deployment = DeploymentConfig(
                    container_runtime=self._select("#container-runtime"),
                    domain=domain,
                    data_dir=data_dir,
                    cert_email=self._input("#cert-email"),
                    tls=self._enabled("#tls"),
                    cert_name=self._input("#cert-name"),
                    letsencrypt_dir=self._input("#letsencrypt-dir"),
                    http_bind=self._input("#http-bind"),
                    https_bind=self._input("#https-bind"),
                    server_tag=self._input("#server-tag"),
                    web_tag=self._input("#web-tag"),
                    configure_firewall=self._enabled("#configure-firewall"),
                    world_save=self._input("#world-save"),
                )
                world = WorldConfig(
                    generator=self._select("#generator"),
                    seed=self._input("#seed"),
                    starter_pack=self._select("#starter-pack"),
                    load=self._input("#world-save"),
                    load_paused=self._enabled("#load-paused"),
                    max_rooms=self._int("#max-rooms"),
                    save=self._input("#world-save-path"),
                    ticks=self._int("#ticks"),
                    tick_seconds=self._float("#tick-seconds"),
                    time_scale=self._float("#time-scale"),
                    autosave_every=self._int("#autosave-every"),
                    memory_backend=self._select("#memory-backend"),
                    memory_path=self._input("#memory-path"),
                    controller_definitions=self._input("#controller-definitions"),
                    claim_timeout_seconds=self._optional_int_input("#claim-timeout-seconds"),
                    claim_timeout_controllers=_csv_values(
                        self._input("#claim-timeout-controllers")
                    ),
                    lifesim_natural_aging=_optional_bool(self._select("#lifesim-natural-aging")),
                )
                web = WebConfig(
                    theme=self._input("#web-theme"),
                    themes=themes,
                    favicon_file=self._input("#favicon-file"),
                    home_domain=self._input("#home-domain"),
                    home_dir=self._input("#home-dir"),
                    home_cert_name=self._input("#home-cert-name"),
                    player_auth_required=self._enabled("#player-auth-required"),
                )
                llm = LlmConfig(
                    enabled=llm_enabled,
                    provider=provider,
                    worldgen_provider=worldgen_provider,
                    worldgen_model=self._input("#worldgen-model"),
                    character_model=self._input("#character-model"),
                    ollama_host=self._input("#ollama-host"),
                    ollama_api_key=self._input("#ollama-api-key"),
                    openrouter_api_key=self._input("#openrouter-api-key"),
                    openrouter_server_url=self._input("#openrouter-url"),
                )
                discord = DiscordConfig(
                    enabled=discord_enabled,
                    token=self._input("#discord-token") if discord_enabled else "",
                    user_id=self._optional_int_input("#discord-user-id"),
                    channel_id=self._optional_int_input("#discord-channel-id"),
                    character=self._input("#discord-character"),
                    allow_child_claims=self._enabled("#discord-allow-child-claims"),
                    allowed_guild_ids=self._csv_int_input("#discord-guild-ids"),
                    allowed_channel_ids=self._csv_int_input("#discord-channel-ids"),
                    allowed_dm_user_ids=self._csv_int_input("#discord-dm-user-ids"),
                    public_url=discord_url,
                )
                server = ServerConfig(
                    api_host=self._input("#api-host"),
                    api_port=self._optional_int_input("#api-port"),
                    auth_users_file=self._input("#auth-users-file"),
                    token_db=self._input("#token-db"),
                    player_client_ids=_csv_values(self._input("#player-client-ids")),
                    admin_client_ids=_csv_values(self._input("#admin-client-ids")),
                    character_chat=character_chat,
                    cors_origins=_csv_values(self._input("#cors-origins")),
                    forwarded_allow_ips=self._input("#forwarded-allow-ips"),
                )
                imagegen = ImageGenConfigBlock()
                if imagegen_enabled:
                    imagegen = ImageGenConfigBlock(
                        server_url=self._input("#comfy-url"),
                        generator=image_generator,
                        generators=image_generator_overrides,
                        openrouter_image_model=self._input("#image-openrouter-model"),
                        use_websocket=self._enabled("#comfy-websocket"),
                        poll_interval_seconds=self._float("#comfy-poll-seconds"),
                        timeout_seconds=self._float("#comfy-timeout-seconds"),
                        backfill_interval_seconds=self._float("#image-backfill-seconds"),
                        media_root=self._input("#image-media-root"),
                        public_base_url=self._input("#image-public-url"),
                        templates_path=self._input("#image-templates-path"),
                        workflows=self._input("#image-workflows"),
                        prompt_style=self._input("#image-prompt-style"),
                        enhancer=self._input("#image-enhancer"),
                        model=self._input("#image-model"),
                    )
            except ValueError as exc:
                self._fail(str(exc))
                return None

            return BunnylandConfig(
                deployment=deployment,
                world=world,
                web=web,
                plugins=PluginConfig(
                    enabled=self._enabled_plugin_ids(),
                    config=dict(initial.plugins.config),
                ),
                llm=llm,
                discord=discord,
                mcp=McpConfig(enabled=mcp_enabled),
                server=server,
                imagegen=imagegen,
            )

        def _update_review(self) -> None:
            config = self._build_config()
            if config is None:
                self.query_one("#review", Static).update(
                    self.last_error or "Fix the highlighted issue before saving."
                )
                return
            self.query_one("#review", Static).update("\n".join(review_lines(config)))

        @on(Input.Changed, "#plugin-search")
        def plugin_search_changed(self, _event: Input.Changed) -> None:
            self._filter_plugins()

        @on(Button.Pressed, "#clear-plugin-search")
        def clear_plugin_search_pressed(self, _event: Button.Pressed) -> None:
            self.query_one("#plugin-search", Input).value = ""
            self._filter_plugins()

        @on(Input.Changed)
        def input_changed(self, _event: Input.Changed) -> None:
            self._update_save_state()

        @on(Select.Changed)
        def select_changed(self, _event: Select.Changed) -> None:
            self._update_save_state()

        @on(Select.Changed, "#generator")
        def generator_changed(self, _event: Select.Changed) -> None:
            self._update_world_prompt_state()

        @on(Button.Pressed, "#advanced-toggle")
        def advanced_pressed(self, _event: Button.Pressed) -> None:
            self.action_toggle_advanced()

        @on(Button.Pressed, "#random-world-prompt")
        def random_world_prompt_pressed(self, _event: Button.Pressed) -> None:
            self.query_one("#seed", Input).value = choice(WORLD_PROMPT_PRESETS)

        @on(Button.Pressed, ".help-button")
        def help_pressed(self, event: Button.Pressed) -> None:
            widget_id = (event.button.id or "").removeprefix("help-")
            help_text = FIELD_HELP.get(widget_id)
            if help_text is not None:
                self.push_screen(
                    FieldHelpModal(
                        field_titles.get(widget_id, widget_id.replace("-", " ").title()),
                        help_text,
                    )
                )

        @on(Button.Pressed, "#back")
        def back_pressed(self, _event: Button.Pressed) -> None:
            self._show_step(self.step_index - 1)

        @on(Button.Pressed, "#next")
        def next_pressed(self, _event: Button.Pressed) -> None:
            self._show_step(self.step_index + 1)

        @on(Button.Pressed, ".step-button")
        def step_pressed(self, event: Button.Pressed) -> None:
            button_id = event.button.id or ""
            if button_id.startswith("step-"):
                self._show_step(int(button_id.removeprefix("step-")))

        @on(Button.Pressed, "#save")
        def save_pressed(self, _event: Button.Pressed) -> None:
            self.action_save()

        def action_save(self) -> None:
            if not self._required_fields_ready():
                self._fail("Domain, data directory, and admin login are required.")
                return
            config = self._build_config()
            if config is not None:
                self.exit(config)

        @on(Button.Pressed, "#cancel")
        def cancel_pressed(self, _event: Button.Pressed) -> None:
            self.action_cancel()

        def action_cancel(self) -> None:
            self.exit(None)

        def action_toggle_advanced(self) -> None:
            self._show_advanced(not self.advanced_visible)

    return ConfigWizardApp()


def run_textual_wizard(
    path: Path,
    *,
    enabled_plugins: Sequence[str] | None = None,
) -> BunnylandConfig | None:
    initial = BunnylandConfig.load(path) if path.exists() else default_wizard_config()
    app = build_textual_wizard_app(
        initial,
        enabled_plugins=enabled_plugins,
    )
    return app.run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bunnyland config-wizard", description=__doc__)
    parser.add_argument("--config", default="bunnyland.yml")
    parser.add_argument("--write-config", default=None)
    parser.add_argument("--write-web-config", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--cli", action="store_true", help="use prompt mode instead of Textual")
    parser.add_argument(
        "--plugin",
        action="append",
        default=None,
        help="preselect a plugin id in the Textual checklist",
    )
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if not args.non_interactive and not args.cli and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            config = run_textual_wizard(
                config_path,
                enabled_plugins=args.plugin,
            )
        except ImportError:
            config = load_or_prompt_config(config_path, non_interactive=False)
        if config is None:
            print("aborted before setup; no changes were made")
            return 1
    else:
        config = load_or_prompt_config(config_path, non_interactive=args.non_interactive)
    for line in review_lines(config):
        print(line)
    if not args.non_interactive and not _confirm("Proceed with these settings?", True):
        print("aborted before setup; no changes were made")
        return 1

    write_path = Path(args.write_config or args.config)
    web_config_path = Path(args.write_web_config or write_path.with_suffix(".web.json"))
    config.save(write_path)
    print(f"Wrote {write_path}.")
    config.save_web_config(web_config_path)
    print(f"Wrote {web_config_path}.")
    return run_setup(
        config,
        config_path=write_path,
        web_config_path=web_config_path,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
