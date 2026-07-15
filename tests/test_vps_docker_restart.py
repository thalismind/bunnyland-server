from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def test_vps_docker_restart_pulls_images_before_up(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    test_repo = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    command_log = tmp_path / "compose.log"

    (test_repo / "scripts").mkdir(parents=True)
    fake_bin.mkdir()
    (test_repo / "compose.yml").write_text("services: {}\n")
    (test_repo / "compose.user.yml").write_text("services: {}\n")

    restart_script = test_repo / "scripts" / "vps-docker-restart"
    shutil.copy2(repo_root / "scripts" / "vps-docker-restart", restart_script)
    restart_script.chmod(0o755)

    sudo_bin = fake_bin / "sudo"
    sudo_bin.write_text('#!/bin/sh\nexec "$@"\n')
    sudo_bin.chmod(0o755)

    docker_bin = fake_bin / "docker"
    docker_bin.write_text(
        """#!/bin/sh
printf '%s\n' "$*" >> "$BUNNYLAND_FAKE_COMPOSE_LOG"
if [ "$1" = "compose" ]; then
  exit 0
fi
exit 1
"""
    )
    docker_bin.chmod(0o755)

    env = os.environ.copy()
    env["BUNNYLAND_CONTAINER_RUNTIME"] = "docker"
    env["BUNNYLAND_FAKE_COMPOSE_LOG"] = str(command_log)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [str(restart_script)],
        check=False,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr

    commands = command_log.read_text().splitlines()
    config_index = next(
        i for i, command in enumerate(commands) if command.endswith(" config --quiet")
    )
    pull_index = next(i for i, command in enumerate(commands) if command.endswith(" pull"))
    up_index = next(i for i, command in enumerate(commands) if command.endswith(" up -d"))
    ps_index = next(i for i, command in enumerate(commands) if command.endswith(" ps"))

    assert config_index < pull_index < up_index < ps_index


def test_vps_verify_distinguishes_anonymous_and_player_admin_denials() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    verify = (repo_root / "scripts" / "vps-docker-verify").read_text()

    assert 'BUNNYLAND_VERIFY_ADMIN_UNAUTH_STATUS:-401' in verify
    assert 'BUNNYLAND_VERIFY_ADMIN_PLAY_STATUS:-403' in verify
    assert '"admin rejects player scope"' in verify
    assert "admin_play_status," in verify
