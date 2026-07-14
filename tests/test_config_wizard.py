from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from conftest import install_plugin_module

from bunnyland.config import (
    AuthConfig,
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
from bunnyland.config_wizard import (
    WORLD_PROMPT_PRESETS,
    _format_field_help,
    _optional_bool,
    _parse_themes_text,
    _prompt_required,
    _resolve_enabled_plugin_ids,
    _themes_text,
    available_plugins_for_wizard,
    build_textual_wizard_app,
    field_help,
    load_or_prompt_config,
    main,
    prompt_for_config,
    review_lines,
    run_setup,
    run_textual_wizard,
)
from bunnyland.plugins import Plugin


async def _advance_textual_wizard_to_review(app, pilot) -> None:
    from textual.widgets import Button

    while app.step_index < app.step_count - 1:
        app.query_one("#next", Button).press()
        await pilot.pause()


def test_compose_startup_commands_wire_memory_env_flags() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    for compose_file in ("compose.yml", "compose.load.yml"):
        text = (repo_root / compose_file).read_text()
        assert 'memory_backend="$${BUNNYLAND_MEMORY_BACKEND:-in-memory}"' in text
        assert 'set -- "$$@" --memory-backend "$$memory_backend"' in text
        assert 'set -- "$$@" --memory-path "$${BUNNYLAND_MEMORY_PATH}"' in text

    base_compose = (repo_root / "compose.yml").read_text()
    assert "BUNNYLAND_MEMORY_BACKEND: ${BUNNYLAND_MEMORY_BACKEND:-in-memory}" in base_compose
    assert "BUNNYLAND_MEMORY_PATH: ${BUNNYLAND_MEMORY_PATH:-}" in base_compose


def test_vps_docker_setup_directs_operators_to_coordinated_ansible_flow() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    text = (repo_root / "scripts" / "vps-docker-setup").read_text()

    assert "standalone VPS setup flow has been retired" in text
    assert "bunnyland-vps Ansible playbook" in text


def test_home_nginx_template_denies_hidden_paths() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    text = (repo_root / "deploy" / "nginx" / "frontend-tls-home.conf").read_text()

    assert "root /usr/share/nginx/home;" in text
    assert "location ~ /\\.(?!well-known/) {" in text
    assert "return 404;" in text


def test_api_nginx_template_forwards_bearer_and_cookie_without_basic_auth() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    text = (repo_root / "deploy" / "nginx" / "api-locations.inc").read_text()

    health_location = text.index("location = /api/health")
    player_location = text.index("location /api/ {")

    assert health_location < player_location
    assert "auth_basic" not in text
    assert "auth_basic_user_file" not in text
    assert "proxy_set_header Authorization $http_authorization;" in text
    assert "proxy_set_header Cookie $http_cookie;" in text
    assert "proxy_set_header X-Bunnyland-Client-Id $http_x_bunnyland_client_id;" in text
    assert "proxy_set_header X-Bunnyland-Client-Id $remote_user;" not in text


def test_generic_player_proxy_carries_character_websocket_upgrades() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    text = (repo_root / "deploy" / "nginx" / "api-locations.inc").read_text()
    player_location = text[text.index("location /api/ {") :]

    assert "proxy_set_header Upgrade $http_upgrade;" in player_location
    assert "proxy_set_header Connection $connection_upgrade;" in player_location
    assert "proxy_read_timeout 3600s;" in player_location
    assert "location = /api/world/character/" not in text


def test_nginx_api_limits_return_retry_after_without_limiting_health() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    locations = (repo_root / "deploy" / "nginx" / "api-locations.inc").read_text()
    frontend = (repo_root / "deploy" / "nginx" / "frontend-tls.conf").read_text()
    health = locations[
        locations.index("location = /api/health") : locations.index("location /api/ {")
    ]

    assert "limit_req_zone $binary_remote_addr zone=bunnyland_api:10m" in frontend
    assert "limit_req_status 429;" in locations
    assert 'add_header Retry-After "${BUNNYLAND_EDGE_RETRY_AFTER}" always;' in locations
    assert "limit_req zone=bunnyland_api" not in health
    assert locations.count("limit_req zone=bunnyland_api") == 1


def test_bunnyland_config_round_trips_yaml_with_private_mode(tmp_path: Path) -> None:
    path = tmp_path / "bunnyland.yml"
    config = BunnylandConfig(
        deployment=DeploymentConfig(domain="localhost", data_dir="/tmp/bunnyland"),
        auth=AuthConfig(admin_user="editor", admin_password="local"),
        world=WorldConfig(starter_pack="peaceful", memory_backend="json"),
        llm=LlmConfig(enabled=True, ollama_api_key="ollama-key"),
        discord=DiscordConfig(enabled=True, token="discord-token"),
        server=ServerConfig(character_chat=True),
    )

    config.save(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    loaded = BunnylandConfig.load(path)
    assert loaded.auth.admin_password == "local"
    assert loaded.llm.ollama_api_key == "ollama-key"
    assert loaded.world.memory_backend == "json"


def test_bunnyland_config_loads_empty_file_as_defaults(tmp_path: Path) -> None:
    path = tmp_path / "empty.yml"
    path.write_text("")

    assert BunnylandConfig.load(path) == BunnylandConfig()


def test_bunnyland_config_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    path = tmp_path / "list.yml"
    path.write_text("- nope\n")

    try:
        BunnylandConfig.load(path)
    except ValueError as exc:
        assert "top level" in str(exc)
    else:
        raise AssertionError("expected non-mapping YAML to fail")


def test_bunnyland_config_renders_setup_env() -> None:
    config = BunnylandConfig(
        deployment=DeploymentConfig(
            domain="sandbox.example.com",
            data_dir="/var/lib/bunnyland",
            container_runtime="docker",
        ),
        auth=AuthConfig(admin_user="editor", admin_password="local"),
        world=WorldConfig(starter_pack="peaceful"),
        discord=DiscordConfig(
            public_url="https://discord.gg/example",
            allowed_bot_user_ids=(123,),
            cooldown_seconds=3,
        ),
        server=ServerConfig(
            http_rate_limit_requests=20,
            http_rate_limit_window_seconds=2.5,
            trust_x_real_ip=True,
        ),
    )

    env = config.to_env(dry_run=True)

    assert env["BUNNYLAND_DOMAIN"] == "sandbox.example.com"
    assert env["BUNNYLAND_DATA_DIR"] == "/var/lib/bunnyland"
    assert env["BUNNYLAND_ADMIN_USER"] == "editor"
    assert env["BUNNYLAND_ADMIN_PASSWORD"] == "local"
    assert env["BUNNYLAND_STARTER_PACK"] == "peaceful"
    assert env["BUNNYLAND_DISCORD_URL"] == "https://discord.gg/example"
    assert env["BUNNYLAND_DISCORD_ALLOWED_BOT_USER_IDS"] == "123"
    assert env["BUNNYLAND_DISCORD_COOLDOWN_SECONDS"] == "3"
    assert env["BUNNYLAND_HTTP_RATE_LIMIT_REQUESTS"] == "20"
    assert env["BUNNYLAND_HTTP_RATE_LIMIT_WINDOW_SECONDS"] == "2.5"
    assert env["BUNNYLAND_TRUST_X_REAL_IP"] == "1"
    assert env["BUNNYLAND_SETUP_DRY_RUN"] == "1"


def test_bunnyland_config_renders_web_config_and_theme_assets(tmp_path: Path) -> None:
    css_file = tmp_path / "night.css"
    css_file.write_text(":root.bl-theme-night {}\n")
    config = BunnylandConfig(
        auth=AuthConfig(player_user="player", player_password="secret"),
        discord=DiscordConfig(public_url="https://discord.gg/example"),
        web=WebConfig(
            theme="night",
            themes=(WebTheme(value="night", label="Night", css_file=str(css_file)),),
        ),
    )

    env = config.to_env()
    web_config = config.to_web_config()

    assert env["BUNNYLAND_WEB_THEME_CSS_FILES"] == str(css_file)
    assert web_config["discordUrl"] == "https://discord.gg/example"
    assert web_config["playerAuthRequired"] is True
    assert web_config["theme"] == "night"
    assert web_config["replaceThemes"] is True
    assert web_config["themes"] == [{"value": "night", "label": "Night"}]


def test_bunnyland_config_renders_string_web_themes() -> None:
    config = BunnylandConfig(web=WebConfig(themes='[{"value":"day","label":"Day"}]'))

    env = config.to_env()
    web_config = config.to_web_config()

    assert env["BUNNYLAND_WEB_THEMES"] == '[{"value":"day","label":"Day"}]'
    assert "BUNNYLAND_WEB_THEME_CSS_FILES" not in env
    assert web_config["replaceThemes"] is True
    assert web_config["themes"] == [{"value": "day", "label": "Day"}]


def test_bunnyland_config_renders_setup_env_without_dry_run() -> None:
    env = BunnylandConfig().to_env()

    assert "BUNNYLAND_SETUP_DRY_RUN" not in env


def test_config_wizard_review_masks_secrets() -> None:
    lines = review_lines(
        BunnylandConfig(
            deployment=DeploymentConfig(domain="sandbox.example.com", data_dir="/data"),
            auth=AuthConfig(admin_user="editor", admin_password="secret"),
            discord=DiscordConfig(public_url="https://discord.gg/example"),
        )
    )

    text = "\n".join(lines)
    assert "Admin password    : (set)" in text
    assert "secret" not in text
    assert "Discord link      : https://discord.gg/example" in text
    assert "Live services     : offline smoke test" in text
    assert "Plugins           : default set" in text


def test_config_wizard_review_lists_optional_services() -> None:
    lines = review_lines(
        BunnylandConfig(
            mcp=McpConfig(enabled=True),
            server=ServerConfig(character_chat=True),
            imagegen=ImageGenConfigBlock(server_url="http://comfy.local:8188"),
        )
    )

    text = "\n".join(lines)
    assert "MCP endpoint      : enabled" in text
    assert "Character chat    : enabled" in text
    assert "Image generation  : http://comfy.local:8188" in text


def test_config_wizard_review_counts_custom_plugins() -> None:
    lines = review_lines(BunnylandConfig(plugins=PluginConfig(enabled=("core_verbs", "memory"))))

    assert "Plugins           : 2 selected" in "\n".join(lines)


def test_config_wizard_helper_branches(monkeypatch) -> None:
    assert _format_field_help(field_help("plain help")) == "plain help"
    assert _themes_text("[]") == ""
    assert _optional_bool("no") is False
    assert _parse_themes_text("night=Night:/themes/night.css") == (
        WebTheme(value="night", label="Night", css_file="/themes/night.css"),
    )

    for value in ("night", "night="):
        try:
            _parse_themes_text(value)
        except ValueError as exc:
            assert "custom themes" in str(exc)
        else:
            raise AssertionError("expected invalid theme text to fail")

    prompts = iter(["", "value"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(prompts))
    assert _prompt_required("Required") == "value"


def test_config_wizard_resolves_plugin_ids() -> None:
    plugins = (
        Plugin(id="package.alpha", name="Alpha"),
        Plugin(id="other.alpha", name="Other Alpha"),
        Plugin(id="package.beta", name="Beta"),
    )

    assert _resolve_enabled_plugin_ids(plugins, None) is None
    assert _resolve_enabled_plugin_ids(plugins, ("package.alpha",)) == frozenset({"package.alpha"})
    assert _resolve_enabled_plugin_ids(plugins, ("beta",)) == frozenset({"package.beta"})

    for requested, expected in (("missing", "unknown plugin"), ("alpha", "ambiguous")):
        try:
            _resolve_enabled_plugin_ids(plugins, (requested,))
        except Exception as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected plugin id resolution to fail")


def test_config_wizard_prompt_smoke_path(monkeypatch) -> None:
    answers = iter(
        [
            "docker",
            "localhost",
            "/data",
            "",
            "editor",
            "",
            "bad-pack",
            "peaceful",
            "n",
            "",
            "n",
            "ftp://bad",
            "https://discord.gg/example",
            "n",
            "n",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    config = prompt_for_config()

    assert config.deployment.domain == "localhost"
    assert str(UUID(config.auth.admin_password)) == config.auth.admin_password
    assert config.world.starter_pack == "peaceful"
    assert config.discord.public_url == "https://discord.gg/example"
    assert config.llm.enabled is False
    assert config.mcp.enabled is False


def test_config_wizard_prompt_full_ollama_path(monkeypatch) -> None:
    answers = iter(
        [
            "",
            "sandbox.example.com",
            "/var/lib/bunnyland",
            "",
            "editor",
            "secret",
            "none",
            "n",
            "",
            "",
            "",
            "ollama",
            "sk-ollama",
            "",
            "",
            "",
            "n",
            "discord-token",
            "",
            "",
            "",
            "n",
            "n",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    config = prompt_for_config()

    assert config.deployment.container_runtime == "docker"
    assert config.world.starter_pack == ""
    assert config.llm.provider == "ollama"
    assert config.llm.ollama_api_key == "sk-ollama"
    assert config.discord.user_id is None
    assert config.server.character_chat is False


def test_config_wizard_prompt_full_openrouter_path(monkeypatch) -> None:
    answers = iter(
        [
            "podman",
            "sandbox.example.com",
            "/var/lib/bunnyland",
            "admin@example.com",
            "editor",
            "secret",
            "fantastic",
            "y",
            "/opt/favicon.png",
            "example.com",
            "/opt/home",
            "example.com",
            "",
            "",
            "openrouter",
            "sk-or",
            "https://openrouter.local",
            "world-model",
            "chat-model",
            "y",
            "discord-token",
            "123",
            "456",
            "Juniper",
            "y",
            "y",
            "http://comfy.local:8188",
            "flux2dev",
            "https://cdn.example.com/media",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    config = prompt_for_config()

    assert config.deployment.container_runtime == "podman"
    assert config.web.favicon_file == "/opt/favicon.png"
    assert config.web.home_domain == "example.com"
    assert config.llm.provider == "openrouter"
    assert config.llm.openrouter_api_key == "sk-or"
    assert config.server.character_chat is True
    assert config.discord.user_id == 123
    assert config.mcp.enabled is True
    assert config.imagegen.workflows == "flux2dev"


async def test_textual_config_wizard_saves_config() -> None:
    from textual.widgets import Button, Input, Select, Static

    app = build_textual_wizard_app()

    async with app.run_test() as pilot:
        assert str(app.query_one("#step-0", Button).label) == "1. World"
        assert app.query_one("#domain", Input).value == "sandbox.example.com"
        assert app.query_one("#data-dir", Input).value == "/var/lib/bunnyland"
        assert app.query_one("#admin-user", Input).value == "admin"
        world_input_ids = [
            widget.id for widget in app.query_one("#page-world").query("Input, Select") if widget.id
        ]
        assert world_input_ids[:3] == ["starter-pack", "generator", "seed"]
        assert str(app.query_one("#cancel", Button).label) == "Close"
        assert app.query_one("#generator", Select).value == "lifesim-demo"
        assert app.query_one("#seed", Input).disabled is True
        assert app.query_one("#random-world-prompt", Button).disabled is True
        app.query_one("#generator", Select).value = "recursive"
        await pilot.pause()
        assert app.query_one("#seed", Input).disabled is False
        assert app.query_one("#random-world-prompt", Button).disabled is False
        app.query_one("#random-world-prompt", Button).press()
        await pilot.pause()
        assert app.query_one("#seed", Input).value in WORLD_PROMPT_PRESETS
        app.query_one("#llm-enabled", Select).value = "no"
        await pilot.pause()
        assert app.query_one("#character-chat", Select).value == "yes"
        app.query_one("#character-chat", Select).value = "no"
        initial_password = app.query_one("#admin-password", Input).value
        assert str(UUID(initial_password)) == initial_password
        help_buttons = list(app.query(Button).filter(".help-button"))
        assert help_buttons
        assert all(str(button.label) == "?" for button in help_buttons)
        assert all(button.tooltip for button in help_buttons)
        app.query_one("#help-generator", Button).press()
        await pilot.pause()
        help_body = str(app.screen.query_one("#help-body", Static).render())
        assert "World generator" in help_body
        assert "lifesim-demo" in help_body
        app.screen.query_one("#help-close", Button).press()
        await pilot.pause()
        app.query_one("#help-starter-pack", Button).press()
        await pilot.pause()
        starter_help = str(app.screen.query_one("#help-body", Static).render())
        assert "- peaceful includes lifesim + colonysim + gardensim" in starter_help
        assert "- futuristic adds barbariansim + voidsim + nukesim" in starter_help
        app.screen.query_one("#help-close", Button).press()
        await pilot.pause()
        assert app.query_one("#save", Button).display is True
        assert app.query_one("#save", Button).disabled is False
        assert app.query_one("#container-runtime", Select).display is False
        assert app.query_one("#api-port", Input).display is False
        assert app.query_one("#player2-user", Input).display is False
        assert app.query_one("#player2-password", Input).display is False
        await pilot.press("ctrl+a")
        await pilot.pause()
        assert app.query_one("#api-port", Input).display is True
        assert app.query_one("#container-runtime", Select).display is True
        assert app.query_one("#player2-user", Input).display is True
        assert app.query_one("#player2-password", Input).display is True
        app.query_one("#generate-admin-password", Button).press()
        await pilot.pause()
        generated_password = app.query_one("#admin-password", Input).value
        assert str(UUID(generated_password)) == generated_password
        assert generated_password != initial_password
        app.query_one("#admin-user", Input).value = "editor"
        app.query_one("#admin-password", Input).value = "secret"
        assert app.query_one("#save", Button).disabled is False
        app.query_one("#starter-pack", Select).value = "peaceful"
        app.query_one("#discord-url", Input).value = "https://discord.gg/example"
        app.query_one("#next", Button).press()
        await pilot.pause()
        app.query_one("#step-4", Button).press()
        await pilot.pause()
        assert app.step_index == 4
        app.query_one("#back", Button).press()
        await pilot.pause()
        assert app.step_index == 3
        await _advance_textual_wizard_to_review(app, pilot)
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert app.return_value.deployment.domain == "sandbox.example.com"
    assert app.return_value.deployment.data_dir == "/var/lib/bunnyland"
    assert app.return_value.auth.admin_user == "editor"
    assert app.return_value.auth.admin_password == "secret"
    assert app.return_value.world.generator == "recursive"
    assert app.return_value.world.starter_pack == "peaceful"
    assert app.return_value.discord.public_url == "https://discord.gg/example"
    assert app.return_value.server.api_host == "0.0.0.0"
    assert app.return_value.server.api_port == 8765


async def test_textual_config_wizard_saves_live_services_and_addons() -> None:
    from textual.widgets import Button, Input, Select

    app = build_textual_wizard_app()

    async with app.run_test() as pilot:
        app.query_one("#domain", Input).value = "sandbox.example.com"
        app.query_one("#data-dir", Input).value = "/var/lib/bunnyland"
        app.query_one("#admin-user", Input).value = "editor"
        app.query_one("#admin-password", Input).value = "secret"
        app.query_one("#llm-enabled", Select).value = "yes"
        app.query_one("#llm-provider", Select).value = "openrouter"
        app.query_one("#worldgen-provider", Select).value = "openrouter"
        app.query_one("#openrouter-api-key", Input).value = "sk-or"
        app.query_one("#openrouter-url", Input).value = "https://openrouter.local"
        app.query_one("#worldgen-model", Input).value = "world-model"
        app.query_one("#character-model", Input).value = "chat-model"
        app.query_one("#discord-enabled", Select).value = "yes"
        app.query_one("#discord-token", Input).value = "discord-token"
        app.query_one("#character-chat", Select).value = "yes"
        app.query_one("#mcp-enabled", Select).value = "yes"
        app.query_one("#imagegen-enabled", Select).value = "yes"
        app.query_one("#comfy-url", Input).value = "http://comfy.local:8188"
        app.query_one("#image-workflows", Input).value = "flux2dev"
        app.query_one("#image-public-url", Input).value = "https://cdn.example.com/media"
        await _advance_textual_wizard_to_review(app, pilot)
        app.query_one("#save", Button).press()
        await pilot.pause()

    assert app.return_value.llm.enabled is True
    assert app.return_value.llm.provider == "openrouter"
    assert app.return_value.llm.worldgen_provider == "openrouter"
    assert app.return_value.llm.openrouter_api_key == "sk-or"
    assert app.return_value.discord.enabled is True
    assert app.return_value.discord.token == "discord-token"
    assert app.return_value.server.character_chat is True
    assert app.return_value.mcp.enabled is True
    assert app.return_value.imagegen.server_url == "http://comfy.local:8188"
    assert app.return_value.imagegen.workflows == "flux2dev"


async def test_textual_config_wizard_filters_and_selects_plugins() -> None:
    from textual.widgets import Button, Checkbox, Input, Select

    app = build_textual_wizard_app()

    async with app.run_test() as pilot:
        app.query_one("#domain", Input).value = "sandbox.example.com"
        app.query_one("#data-dir", Input).value = "/var/lib/bunnyland"
        app.query_one("#admin-user", Input).value = "editor"
        app.query_one("#admin-password", Input).value = "secret"
        app.query_one("#llm-enabled", Select).value = "no"
        app.query_one("#character-chat", Select).value = "no"
        app.query_one("#plugin-search", Input).value = "memory"
        app._filter_plugins()
        memory_checkbox = next(
            checkbox
            for checkbox in app.query(Checkbox)
            if "bunnyland.memory" in str(checkbox.label)
        )
        assert app.query_one("#plugin-0", Checkbox).display is False
        assert memory_checkbox.display is True
        app.clear_plugin_search_pressed(SimpleNamespace())
        assert app.query_one("#plugin-search", Input).value == ""
        assert app.query_one("#plugin-0", Checkbox).display is True
        memory_checkbox.value = False
        await _advance_textual_wizard_to_review(app, pilot)
        app.query_one("#save", Button).press()
        await pilot.pause()

    assert "bunnyland.memory" not in app.return_value.plugins.enabled
    assert "bunnyland.core_verbs" in app.return_value.plugins.enabled


def test_available_plugins_for_wizard_ignores_env_plugin_modules(monkeypatch) -> None:
    install_plugin_module(monkeypatch, "module_foo", [Plugin(id="bar", name="Bar")])
    monkeypatch.setenv("BUNNYLAND_PLUGIN_MODULES", "module_foo")
    monkeypatch.delitem(__import__("sys").modules, "module_foo")

    plugins, modules = available_plugins_for_wizard()

    assert modules == ()
    assert all(plugin.id != "module_foo.bar" for plugin in plugins)


async def test_textual_config_wizard_validates_and_cancels() -> None:
    from textual.widgets import Button, Input, Label, Static

    app = build_textual_wizard_app()

    async with app.run_test() as pilot:
        app.query_one("#domain", Input).value = ""
        await _advance_textual_wizard_to_review(app, pilot)
        await pilot.pause()
        assert str(app.query_one("#error", Label).render()) == ""
        assert "required" in str(app.query_one("#review", Static).render())

        app.query_one("#domain", Input).value = "sandbox.example.com"
        app.query_one("#data-dir", Input).value = "/var/lib/bunnyland"
        app.query_one("#admin-user", Input).value = "editor"
        app.query_one("#admin-password", Input).value = "secret"
        app.query_one("#discord-url", Input).value = "ftp://bad"
        await pilot.pause()
        app.query_one("#save", Button).press()
        await pilot.pause()
        assert str(app.query_one("#error", Label).render()) == ""
        assert "http(s)" in str(app.query_one("#review", Static).render())

        await pilot.press("escape")
        await pilot.pause()

    assert app.return_value is None


async def test_textual_config_wizard_handles_unlisted_initial_generator() -> None:
    from textual.widgets import Input, Select

    app = build_textual_wizard_app(
        BunnylandConfig(
            deployment=DeploymentConfig(domain="sandbox.example.com", data_dir="/data"),
            auth=AuthConfig(admin_user="admin", admin_password="secret"),
            world=WorldConfig(generator="custom-generator"),
        )
    )

    async with app.run_test():
        assert app.query_one("#generator", Select).value == "custom-generator"
        assert app.query_one("#seed", Input).disabled is False


async def test_textual_config_wizard_non_review_errors_and_button_paths() -> None:
    from textual.widgets import Input, Label

    app = build_textual_wizard_app()

    async with app.run_test():
        app.query_one("#domain", Input).value = ""
        app.action_save()
        assert "required" in str(app.query_one("#error", Label).render())

        app._show_advanced(True)
        assert app.advanced_visible is True
        app.advanced_pressed(SimpleNamespace())
        assert app.advanced_visible is False
        assert "1. World" in app._step_text()

        app.help_pressed(SimpleNamespace(button=SimpleNamespace(id="help-missing")))
        app.step_pressed(SimpleNamespace(button=SimpleNamespace(id="not-a-step")))
        app.cancel_pressed(SimpleNamespace())


async def test_textual_config_wizard_reuse_admin_readiness() -> None:
    from textual.widgets import Button, Input, Select

    app = build_textual_wizard_app()

    async with app.run_test():
        app.query_one("#admin-user", Input).value = ""
        app.query_one("#admin-password", Input).value = ""
        app._update_save_state()
        assert app._required_fields_ready() is False

        app.query_one("#reuse-admin", Select).value = "yes"
        app._update_save_state()
        assert app._required_fields_ready() is True
        assert app.query_one("#save", Button).disabled is False


async def test_textual_config_wizard_direct_handler_branches(monkeypatch) -> None:
    from textual.widgets import Input

    app = build_textual_wizard_app()
    monkeypatch.setattr(
        "bunnyland.config_wizard.choice",
        lambda values: tuple(values)[0],
    )

    async with app.run_test():
        modal_class = app.help_pressed.__func__.__closure__[0].cell_contents
        modal = modal_class("Field", field_help("Help"))
        dismissed = []
        modal.dismiss = lambda value=None: dismissed.append(value)
        modal.action_close()
        assert dismissed == [None]

        app.random_world_prompt_pressed(SimpleNamespace())
        assert app.query_one("#seed", Input).value == WORLD_PROMPT_PRESETS[0]

        app.back_pressed(SimpleNamespace())
        assert app.step_index == 0
        app.next_pressed(SimpleNamespace())
        assert app.step_index == 1
        app.step_pressed(SimpleNamespace(button=SimpleNamespace(id="step-0")))
        assert app.step_index == 0

        app.query_one("#domain", Input).value = "sandbox.example.com"
        app.query_one("#data-dir", Input).value = "/var/lib/bunnyland"
        app.query_one("#admin-user", Input).value = "admin"
        app.query_one("#admin-password", Input).value = "secret"
        app.query_one("#llm-enabled").value = "no"
        app.query_one("#character-chat").value = "no"
        app.save_pressed(SimpleNamespace())

    assert app.return_value is not None


async def test_textual_config_wizard_validation_branches() -> None:
    from textual.widgets import Input, Select, Static

    async def assert_review_error(
        message: str,
        mutate,
    ) -> None:
        app = build_textual_wizard_app()
        async with app.run_test():
            app.query_one("#domain", Input).value = "sandbox.example.com"
            app.query_one("#data-dir", Input).value = "/var/lib/bunnyland"
            app.query_one("#admin-user", Input).value = "admin"
            app.query_one("#admin-password", Input).value = "secret"
            app.query_one("#llm-enabled", Select).value = "no"
            app.query_one("#character-chat", Select).value = "no"
            app.step_index = app.step_count - 1
            mutate(app)
            assert app._build_config() is None
            assert message in str(app.query_one("#review", Static).render())

    await assert_review_error(
        "Reuse admin cannot",
        lambda app: app.query_one("#reuse-admin", Select).__setattr__("value", "yes"),
    )
    await assert_review_error(
        "Admin username and password",
        lambda app: app.query_one("#admin-password", Input).__setattr__("value", ""),
    )
    await assert_review_error(
        "Player username and password",
        lambda app: app.query_one("#player-user", Input).__setattr__("value", "player"),
    )
    await assert_review_error(
        "Second player username and password",
        lambda app: app.query_one("#player2-user", Input).__setattr__("value", "player2"),
    )
    await assert_review_error(
        "Player usernames must be different",
        lambda app: (
            app.query_one("#player-user", Input).__setattr__("value", "same"),
            app.query_one("#player-password", Input).__setattr__("value", "secret"),
            app.query_one("#player2-user", Input).__setattr__("value", "same"),
            app.query_one("#player2-password", Input).__setattr__("value", "secret"),
        ),
    )
    await assert_review_error(
        "Ollama API key",
        lambda app: (
            app.query_one("#llm-enabled", Select).__setattr__("value", "yes"),
            app.query_one("#character-chat", Select).__setattr__("value", "no"),
        ),
    )
    await assert_review_error(
        "OpenRouter API key",
        lambda app: (
            app.query_one("#llm-enabled", Select).__setattr__("value", "yes"),
            app.query_one("#llm-provider", Select).__setattr__("value", "openrouter"),
        ),
    )
    await assert_review_error(
        "Discord bot token",
        lambda app: app.query_one("#discord-enabled", Select).__setattr__("value", "yes"),
    )
    await assert_review_error(
        "ComfyUI server URL",
        lambda app: app.query_one("#imagegen-enabled", Select).__setattr__("value", "yes"),
    )
    await assert_review_error(
        "invalid literal",
        lambda app: app.query_one("#max-rooms", Input).__setattr__("value", "many"),
    )


def test_load_or_prompt_config_rejects_missing_noninteractive(tmp_path: Path) -> None:
    try:
        load_or_prompt_config(tmp_path / "missing.yml", non_interactive=True)
    except SystemExit as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("expected missing non-interactive config to exit")


def test_load_or_prompt_config_prompts_when_interactive(tmp_path: Path, monkeypatch) -> None:
    prompted = BunnylandConfig(
        deployment=DeploymentConfig(domain="prompted.example.com", data_dir="/data")
    )
    monkeypatch.setattr("bunnyland.config_wizard.prompt_for_config", lambda: prompted)

    assert load_or_prompt_config(tmp_path / "missing.yml", non_interactive=False) == prompted


def test_run_setup_passes_config_env(monkeypatch) -> None:
    calls = {}

    def fake_run(command, *, env, check):
        calls["command"] = command
        calls["env"] = env
        calls["check"] = check
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr("subprocess.run", fake_run)

    result = run_setup(
        BunnylandConfig(
            deployment=DeploymentConfig(domain="sandbox.example.com", data_dir="/data")
        ),
        config_path=Path("/tmp/bunnyland.yml"),
        web_config_path=Path("/tmp/bunnyland.web.json"),
        dry_run=True,
    )

    assert result == 7
    assert calls["command"] == ["scripts/vps-docker-setup"]
    assert calls["env"]["BUNNYLAND_DOMAIN"] == "sandbox.example.com"
    assert calls["env"]["BUNNYLAND_SETUP_DRY_RUN"] == "1"
    assert calls["env"]["BUNNYLAND_CONFIG_FILE"] == "/tmp/bunnyland.yml"
    assert calls["env"]["BUNNYLAND_WEB_CONFIG_FILE"] == "/tmp/bunnyland.web.json"
    assert calls["check"] is False


def test_run_setup_omits_optional_config_paths(monkeypatch) -> None:
    calls = {}

    def fake_run(command, *, env, check):
        calls["command"] = command
        calls["env"] = env
        calls["check"] = check
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    assert run_setup(BunnylandConfig()) == 0
    assert "BUNNYLAND_CONFIG_FILE" not in calls["env"]
    assert "BUNNYLAND_WEB_CONFIG_FILE" not in calls["env"]


def test_config_wizard_main_noninteractive_writes_and_runs(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "in.yml"
    write_path = tmp_path / "out.yml"
    BunnylandConfig(
        deployment=DeploymentConfig(domain="sandbox.example.com", data_dir="/data")
    ).save(config_path)
    monkeypatch.setattr(
        "bunnyland.config_wizard.run_setup",
        lambda config, *, config_path, web_config_path, dry_run: 3,
    )

    result = main(
        [
            "--config",
            str(config_path),
            "--write-config",
            str(write_path),
            "--dry-run",
            "--non-interactive",
            "--cli",
        ]
    )

    assert result == 3
    assert BunnylandConfig.load(write_path).deployment.domain == "sandbox.example.com"
    assert (tmp_path / "out.web.json").exists()


def test_config_wizard_main_can_abort_prompted_setup(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "in.yml"
    BunnylandConfig(
        deployment=DeploymentConfig(domain="sandbox.example.com", data_dir="/data")
    ).save(config_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    result = main(["--config", str(config_path)])

    assert result == 1


def test_config_wizard_main_uses_textual_when_tty(tmp_path: Path, monkeypatch) -> None:
    config = BunnylandConfig(
        deployment=DeploymentConfig(domain="textual.example.com", data_dir="/data")
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(
        "bunnyland.config_wizard.run_textual_wizard",
        lambda path, *, enabled_plugins: config,
    )
    monkeypatch.setattr(
        "bunnyland.config_wizard.run_setup",
        lambda config, *, config_path, web_config_path, dry_run: 4,
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    result = main(["--config", str(tmp_path / "new.yml")])

    assert result == 4


def test_run_textual_wizard_loads_initial_config(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "bunnyland.yml"
    BunnylandConfig(
        deployment=DeploymentConfig(domain="textual.example.com", data_dir="/data")
    ).save(config_path)
    calls = {}

    class FakeApp:
        def run(self):
            return calls["initial"]

    def fake_build_textual_wizard_app(initial, *, enabled_plugins=None):
        calls["initial"] = initial
        calls["enabled_plugins"] = enabled_plugins
        return FakeApp()

    monkeypatch.setattr(
        "bunnyland.config_wizard.build_textual_wizard_app", fake_build_textual_wizard_app
    )

    assert run_textual_wizard(config_path).deployment.domain == "textual.example.com"
    fresh_config = run_textual_wizard(tmp_path / "missing.yml")
    assert fresh_config.deployment.domain == "sandbox.example.com"
    assert fresh_config.auth.admin_user == "admin"
    assert str(UUID(fresh_config.auth.admin_password)) == fresh_config.auth.admin_password
    run_textual_wizard(tmp_path / "missing.yml", enabled_plugins=("bar",))
    assert calls["enabled_plugins"] == ("bar",)


def test_config_wizard_main_aborts_when_textual_returns_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(
        "bunnyland.config_wizard.run_textual_wizard",
        lambda path, *, enabled_plugins: None,
    )

    result = main(["--config", str(tmp_path / "new.yml")])

    assert result == 1


def test_config_wizard_main_falls_back_when_textual_missing(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "bunnyland.yml"
    BunnylandConfig(
        deployment=DeploymentConfig(domain="fallback.example.com", data_dir="/data")
    ).save(config_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(
        "bunnyland.config_wizard.run_textual_wizard",
        lambda path, *, enabled_plugins: (_ for _ in ()).throw(ImportError("no textual")),
    )
    monkeypatch.setattr(
        "bunnyland.config_wizard.run_setup",
        lambda config, *, config_path, web_config_path, dry_run: 5,
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    result = main(["--config", str(config_path)])

    assert result == 5
