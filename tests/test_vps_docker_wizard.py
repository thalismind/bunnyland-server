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


def test_vps_docker_wizard_uses_stdin_answers_for_prompted_setup_values(
    tmp_path: Path,
) -> None:
    wizard_script, env, setup_log, data_dir = _build_wizard_fixture(tmp_path)
    # Prompt order: runtime, domain, data dir, admin user, admin password (x2), cert email,
    # world save, starter pack, custom favicon?, Discord invite URL, homepage domain, full
    # deployment?, MCP?, proceed?.
    stdin_answers = (
        f"\nlocalhost\n{data_dir}\neditor\nlocal\nlocal\n\n\npeaceful\n"
        "\nhttps://discord.gg/example\n\nn\nn\ny\n"
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
    ]


def test_vps_docker_wizard_rejects_non_http_discord_url_then_accepts_valid(
    tmp_path: Path,
) -> None:
    wizard_script, env, setup_log, data_dir = _build_wizard_fixture(tmp_path)
    # An invalid Discord URL must re-prompt rather than be written; the second answer is a
    # valid https URL that should propagate to the setup script.
    stdin_answers = (
        f"\nlocalhost\n{data_dir}\neditor\nlocal\nlocal\n\n\npeaceful\n"
        "\nftp://nope\nhttps://discord.gg/example\n\nn\nn\ny\n"
    )

    result = _run_wizard(wizard_script, env, stdin_answers)

    assert result.returncode == 0, result.stderr
    assert "Please enter an http(s) URL or leave blank." in result.stderr
    assert "discord_url=https://discord.gg/example" in setup_log.read_text().splitlines()


def test_vps_docker_wizard_omits_discord_url_when_blank(tmp_path: Path) -> None:
    wizard_script, env, setup_log, data_dir = _build_wizard_fixture(tmp_path)
    # Leaving the Discord prompt blank is valid and writes no value, so the setup script sees
    # an empty BUNNYLAND_DISCORD_URL. Blank answers in order: custom favicon?, Discord URL,
    # homepage domain.
    stdin_answers = (
        f"\nlocalhost\n{data_dir}\neditor\nlocal\nlocal\n\n\npeaceful\n\n\n\nn\nn\ny\n"
    )

    result = _run_wizard(wizard_script, env, stdin_answers)

    assert result.returncode == 0, result.stderr
    assert "Discord link" not in result.stdout
    assert "discord_url=" in setup_log.read_text().splitlines()
