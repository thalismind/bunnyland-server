from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _build_wizard_fixture(tmp_path: Path) -> tuple[Path, dict[str, str], Path, Path]:
    """Set up an isolated wizard run with a stub setup script that logs its env.

    Returns the wizard script path, the scrubbed environment, the setup log path the stub
    writes its received BUNNYLAND_* values to, and the host data directory used in answers.
    """
    repo_root = Path(__file__).resolve().parents[1]
    test_repo = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    setup_log = tmp_path / "setup.env"

    (test_repo / "scripts").mkdir(parents=True)
    fake_bin.mkdir()

    wizard_script = test_repo / "scripts" / "vps-docker-wizard"
    shutil.copy2(repo_root / "scripts" / "vps-docker-wizard", wizard_script)
    wizard_script.chmod(0o755)

    setup_script = test_repo / "scripts" / "vps-docker-setup"
    setup_script.write_text(
        """#!/bin/sh
{
  printf 'runtime=%s\\n' "$BUNNYLAND_CONTAINER_RUNTIME"
  printf 'domain=%s\\n' "$BUNNYLAND_DOMAIN"
  printf 'data_dir=%s\\n' "$BUNNYLAND_DATA_DIR"
  printf 'admin_user=%s\\n' "$BUNNYLAND_ADMIN_USER"
  printf 'admin_password=%s\\n' "$BUNNYLAND_ADMIN_PASSWORD"
  printf 'starter_pack=%s\\n' "$BUNNYLAND_STARTER_PACK"
  printf 'discord_url=%s\\n' "$BUNNYLAND_DISCORD_URL"
  printf 'enable_llm=%s\\n' "$BUNNYLAND_ENABLE_LLM"
  printf 'enable_discord=%s\\n' "$BUNNYLAND_ENABLE_DISCORD"
  printf 'enable_mcp=%s\\n' "$BUNNYLAND_ENABLE_MCP"
  printf 'enable_character_chat=%s\\n' "$BUNNYLAND_ENABLE_CHARACTER_CHAT"
} > "$WIZARD_TEST_SETUP_LOG"
"""
    )
    setup_script.chmod(0o755)

    sudo_bin = fake_bin / "sudo"
    sudo_bin.write_text("#!/bin/sh\nexec \"$@\"\n")
    sudo_bin.chmod(0o755)

    docker_bin = fake_bin / "docker"
    docker_bin.write_text(
        """#!/bin/sh
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$1" = "ps" ]; then
  exit 0
fi
exit 1
"""
    )
    docker_bin.chmod(0o755)

    curl_bin = fake_bin / "curl"
    curl_bin.write_text("#!/bin/sh\nexit 1\n")
    curl_bin.chmod(0o755)

    env = {
        key: value
        for key, value in os.environ.copy().items()
        if not key.startswith("BUNNYLAND_")
        and key
        not in {
            "DISCORD_TOKEN",
            "OLLAMA_CLOUD_API_KEY",
            "OLLAMA_HOST",
            "OPENROUTER_API_KEY",
            "OPENROUTER_SERVER_URL",
        }
    }
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["WIZARD_TEST_SETUP_LOG"] = str(setup_log)
    data_dir = tmp_path / "data"
    return wizard_script, env, setup_log, data_dir


def _answers(*lines: str) -> str:
    """Join wizard prompt answers into stdin text, one answer per line.

    Far easier to keep aligned with the prompts than a single ``\\n``-joined string; each
    element is one answer in prompt order.
    """
    return "".join(f"{line}\n" for line in lines)


def _run_wizard(
    wizard_script: Path, env: dict[str, str], stdin_answers: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(wizard_script)],
        input=stdin_answers,
        check=False,
        env=env,
        text=True,
        capture_output=True,
    )


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


def test_vps_docker_setup_renders_memory_flags_and_env_values() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    text = (repo_root / "scripts" / "vps-docker-setup").read_text()

    assert 'memory_backend="${BUNNYLAND_MEMORY_BACKEND:-in-memory}"' in text
    assert 'memory_path="${BUNNYLAND_MEMORY_PATH:-}"' in text
    assert "unsupported BUNNYLAND_MEMORY_BACKEND" in text
    assert "--memory-backend %s" in text
    assert "--memory-path %s" in text
    assert "BUNNYLAND_MEMORY_BACKEND: %s" in text
    assert "BUNNYLAND_MEMORY_PATH: %s" in text


def test_vps_docker_wizard_uses_stdin_answers_for_prompted_setup_values(
    tmp_path: Path,
) -> None:
    wizard_script, env, setup_log, data_dir = _build_wizard_fixture(tmp_path)
    stdin_answers = _answers(
        "",  # container runtime (blank = first available)
        "localhost",  # sandbox domain
        str(data_dir),  # host data directory
        "editor",  # admin username
        "local",  # admin password
        "local",  # admin password (confirm)
        "",  # Let's Encrypt email
        "",  # existing world save
        "peaceful",  # starter pack
        "",  # use a custom favicon? (blank = no)
        "https://discord.gg/example",  # community Discord invite URL
        "",  # homepage domain (blank to skip)
        "n",  # full deployment with LLM + Discord?
        "n",  # enable HTTP MCP endpoint?
        "y",  # proceed?
    )

    result = _run_wizard(wizard_script, env, stdin_answers)

    assert result.returncode == 0, result.stderr
    assert "Please enter a value" not in result.stderr
    assert "Starter pack      : peaceful" in result.stdout
    assert "Discord link      : https://discord.gg/example" in result.stdout
    assert setup_log.read_text().splitlines() == [
        "runtime=docker",
        "domain=localhost",
        f"data_dir={data_dir}",
        "admin_user=editor",
        "admin_password=local",
        "starter_pack=peaceful",
        "discord_url=https://discord.gg/example",
        "enable_llm=0",
        "enable_discord=0",
        "enable_mcp=0",
        "enable_character_chat=0",
    ]


def test_vps_docker_wizard_rejects_non_http_discord_url_then_accepts_valid(
    tmp_path: Path,
) -> None:
    wizard_script, env, setup_log, data_dir = _build_wizard_fixture(tmp_path)
    # The invalid Discord URL must re-prompt rather than be written; the following valid
    # https URL is then accepted and should propagate to the setup script.
    stdin_answers = _answers(
        "",  # container runtime
        "localhost",  # sandbox domain
        str(data_dir),  # host data directory
        "editor",  # admin username
        "local",  # admin password
        "local",  # admin password (confirm)
        "",  # Let's Encrypt email
        "",  # existing world save
        "peaceful",  # starter pack
        "",  # use a custom favicon?
        "ftp://nope",  # Discord invite URL (rejected, re-prompts)
        "https://discord.gg/example",  # Discord invite URL (accepted)
        "",  # homepage domain (blank to skip)
        "n",  # full deployment?
        "n",  # enable HTTP MCP endpoint?
        "y",  # proceed?
    )

    result = _run_wizard(wizard_script, env, stdin_answers)

    assert result.returncode == 0, result.stderr
    assert "Please enter an http(s) URL or leave blank." in result.stderr
    assert "discord_url=https://discord.gg/example" in setup_log.read_text().splitlines()


def test_vps_docker_wizard_omits_discord_url_when_blank(tmp_path: Path) -> None:
    wizard_script, env, setup_log, data_dir = _build_wizard_fixture(tmp_path)
    # Leaving the Discord prompt blank is valid and writes no value, so the setup script sees
    # an empty BUNNYLAND_DISCORD_URL.
    stdin_answers = _answers(
        "",  # container runtime
        "localhost",  # sandbox domain
        str(data_dir),  # host data directory
        "editor",  # admin username
        "local",  # admin password
        "local",  # admin password (confirm)
        "",  # Let's Encrypt email
        "",  # existing world save
        "peaceful",  # starter pack
        "",  # use a custom favicon?
        "",  # community Discord invite URL (blank)
        "",  # homepage domain (blank to skip)
        "n",  # full deployment?
        "n",  # enable HTTP MCP endpoint?
        "y",  # proceed?
    )

    result = _run_wizard(wizard_script, env, stdin_answers)

    assert result.returncode == 0, result.stderr
    assert "Discord link" not in result.stdout
    assert "discord_url=" in setup_log.read_text().splitlines()
