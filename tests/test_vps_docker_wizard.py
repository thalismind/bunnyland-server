from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def test_vps_docker_wizard_uses_stdin_answers_for_prompted_setup_values(
    tmp_path: Path,
) -> None:
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

    env = os.environ.copy()
    env = {
        key: value
        for key, value in env.items()
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
    stdin_answers = (
        f"\nlocalhost\n{data_dir}\neditor\nlocal\nlocal\n\n\npeaceful\n\n\nn\nn\ny\n"
    )

    result = subprocess.run(
        [str(wizard_script)],
        input=stdin_answers,
        check=False,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Please enter a value" not in result.stderr
    assert "Starter pack      : peaceful" in result.stdout
    assert setup_log.read_text().splitlines() == [
        "runtime=docker",
        "domain=localhost",
        f"data_dir={data_dir}",
        "admin_user=editor",
        "admin_password=local",
        "starter_pack=peaceful",
        "enable_llm=0",
        "enable_discord=0",
        "enable_mcp=0",
    ]
