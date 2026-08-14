"""Secure deterministic world and credentials for local multiplayer playtests."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path

import yaml
from pwdlib import PasswordHash

from ..core.world_actor import WorldActor
from ..persistence import WorldMeta, save_world
from ..plugins import apply_plugins, bunnyland_plugins, resolve_order, select
from ..secure_files import secure_directory, secure_write_text
from ..server.auth import WORLD_PLAY_SCOPE, TokenStore
from ..worldgen import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal, instantiate

DEFAULT_FIXTURE_PLAYERS = 10
DEFAULT_TOKEN_LIFETIME_SECONDS = 2 * 60 * 60


@dataclass(frozen=True)
class MultiplayerFixture:
    """Paths and non-secret roster metadata produced for one local exercise."""

    output: Path
    world: Path
    token_db: Path
    auth_users: Path
    environment: Path
    manifest: Path
    character_names: tuple[str, ...]
    token_environment_names: tuple[str, ...]


def fixture_proposal(player_count: int = DEFAULT_FIXTURE_PLAYERS) -> WorldProposal:
    """Build the deterministic shared-world proposal used by the release exercise."""

    if player_count < 1:
        raise ValueError("player_count must be positive")
    return WorldProposal(
        seed="ten-player-shared-green",
        rooms=[
            RoomSpec(
                key="green",
                title="Shared Green",
                biome="commons",
                description=(
                    "A broad village green with enough space for several conversations."
                ),
            ),
            RoomSpec(
                key="orchard",
                title="Coordination Orchard",
                biome="orchard",
                description="A quiet orchard connected to the shared green.",
            ),
        ],
        exits=[
            ExitSpec(from_key="green", direction="north", to_key="orchard"),
            ExitSpec(from_key="orchard", direction="south", to_key="green"),
        ],
        objects=[
            ObjectSpec(
                key="notice",
                room_key="green",
                name="the coordination notice",
                kind="paper",
                portable=False,
                description=(
                    "Introduce yourself, coordinate through ordinary speech, and verify "
                    "the result of each action."
                ),
            )
        ],
        characters=[
            CharacterSpec(
                key=f"playtester_{index:02d}",
                name=f"Playtester {index:02d}",
                room_key="green",
                controller="suspended",
                with_needs=False,
                with_memory=True,
                traits=("cooperative",),
                goals=("coordinate with the other players",),
            )
            for index in range(1, player_count + 1)
        ],
    )


async def prepare_multiplayer_fixture(
    output: Path,
    *,
    player_count: int = DEFAULT_FIXTURE_PLAYERS,
    token_lifetime_seconds: int = DEFAULT_TOKEN_LIFETIME_SECONDS,
) -> MultiplayerFixture:
    """Create one fresh local world, token database, and sourceable token environment."""

    if token_lifetime_seconds < 1:
        raise ValueError("token_lifetime_seconds must be positive")
    secure_directory(output)
    world_path = output / "world.json"
    token_db_path = output / "auth-tokens.sqlite3"
    auth_users_path = output / "auth-users.yml"
    environment_path = output / "players.env"
    manifest_path = output / "manifest.json"
    targets = (world_path, token_db_path, auth_users_path, environment_path, manifest_path)
    existing = [path for path in targets if path.exists()]
    if existing:
        raise FileExistsError(f"fixture output already exists: {existing[0]}")

    plugins = resolve_order(select(list(bunnyland_plugins()), None))
    actor = WorldActor()
    apply_plugins(plugins, actor)
    proposal = fixture_proposal(player_count)
    await instantiate(actor, proposal)
    save_world(
        actor,
        world_path,
        meta=WorldMeta(
            seed=proposal.seed,
            generator="multiplayer-playtest-fixture",
            plugins=tuple(plugin.id for plugin in plugins),
        ),
        backup_count=0,
    )

    environment_names = tuple(
        f"BUNNYLAND_PLAYER_{index:02d}_TOKEN"
        for index in range(1, player_count + 1)
    )
    store = TokenStore(token_db_path)
    try:
        tokens = tuple(
            store.issue(
                f"multiplayer-playtest-{index:02d}",
                [WORLD_PLAY_SCOPE],
                automatic_rotation=False,
                lifetime_seconds=token_lifetime_seconds,
            )[0]
            for index in range(1, player_count + 1)
        )
    finally:
        store.close()
    secure_write_text(
        auth_users_path,
        yaml.safe_dump(
            {
                "users": [
                    {
                        "username": "disabled-multiplayer-fixture-user",
                        "password_hash": PasswordHash.recommended().hash(
                            secrets.token_urlsafe(32)
                        ),
                        "enabled": False,
                        "scopes": [WORLD_PLAY_SCOPE],
                    }
                ]
            },
            sort_keys=False,
        ),
    )
    secure_write_text(
        environment_path,
        "".join(
            f"export {name}={token}\n"
            for name, token in zip(environment_names, tokens, strict=True)
        ),
    )
    character_names = tuple(character.name for character in proposal.characters)
    secure_write_text(
        manifest_path,
        json.dumps(
            {
                "schema_version": 1,
                "player_count": player_count,
                "world": world_path.name,
                "token_db": token_db_path.name,
                "auth_users": auth_users_path.name,
                "environment": environment_path.name,
                "characters": character_names,
                "token_environment_names": environment_names,
            },
            indent=2,
        )
        + "\n",
    )
    return MultiplayerFixture(
        output=output,
        world=world_path,
        token_db=token_db_path,
        auth_users=auth_users_path,
        environment=environment_path,
        manifest=manifest_path,
        character_names=character_names,
        token_environment_names=environment_names,
    )


__all__ = [
    "DEFAULT_FIXTURE_PLAYERS",
    "DEFAULT_TOKEN_LIFETIME_SECONDS",
    "MultiplayerFixture",
    "fixture_proposal",
    "prepare_multiplayer_fixture",
]
