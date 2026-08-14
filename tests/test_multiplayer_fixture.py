"""Deterministic coverage for the private multiplayer release fixture."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from bunnyland.core import CharacterComponent, IdentityComponent, SuspendedComponent
from bunnyland.persistence import load_world
from bunnyland.playtest.fixture import fixture_proposal, prepare_multiplayer_fixture
from bunnyland.playtest.multiplayer import load_multiplayer_config
from bunnyland.plugins import PluginRegistry, bunnyland_plugins
from bunnyland.server.auth import TokenStore


def test_fixture_proposal_has_distinct_claimable_players_and_shared_rooms():
    proposal = fixture_proposal()

    assert len(proposal.characters) == 10
    assert len({character.key for character in proposal.characters}) == 10
    assert [character.name for character in proposal.characters] == [
        f"Playtester {index:02d}" for index in range(1, 11)
    ]
    assert all(character.controller == "suspended" for character in proposal.characters)
    assert {room.key for room in proposal.rooms} == {"green", "orchard"}
    with pytest.raises(ValueError, match="player_count must be positive"):
        fixture_proposal(0)


@pytest.mark.asyncio
async def test_prepare_fixture_writes_private_distinct_tokens_and_loadable_world(
    tmp_path: Path,
):
    output = tmp_path / "fixture"

    fixture = await prepare_multiplayer_fixture(
        output,
        player_count=3,
        token_lifetime_seconds=300,
    )

    assert fixture.character_names == ("Playtester 01", "Playtester 02", "Playtester 03")
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert stat.S_IMODE(fixture.environment.stat().st_mode) == 0o600
    assert stat.S_IMODE(fixture.token_db.stat().st_mode) == 0o600
    assert stat.S_IMODE(fixture.auth_users.stat().st_mode) == 0o600
    assert "enabled: false" in fixture.auth_users.read_text(encoding="utf-8")
    environment_lines = fixture.environment.read_text(encoding="utf-8").splitlines()
    assert [line.split("=", 1)[0] for line in environment_lines] == [
        f"export BUNNYLAND_PLAYER_{index:02d}_TOKEN" for index in range(1, 4)
    ]
    assert len({line.split("=", 1)[1] for line in environment_lines}) == 3

    store = TokenStore(fixture.token_db)
    try:
        assert len(store.list_metadata()) == 3
    finally:
        store.close()
    actor, meta = load_world(fixture.world, registry=PluginRegistry(bunnyland_plugins()))
    characters = tuple(
        actor.world.query()
        .with_all([CharacterComponent, IdentityComponent, SuspendedComponent])
        .execute_entities()
    )
    assert sorted(character.get_component(IdentityComponent).name for character in characters) == [
        "Playtester 01",
        "Playtester 02",
        "Playtester 03",
    ]
    assert meta.generator == "multiplayer-playtest-fixture"

    with pytest.raises(FileExistsError, match="fixture output already exists"):
        await prepare_multiplayer_fixture(output, player_count=3)


@pytest.mark.asyncio
async def test_prepare_fixture_rejects_invalid_token_lifetime(tmp_path: Path):
    with pytest.raises(ValueError, match="token_lifetime_seconds must be positive"):
        await prepare_multiplayer_fixture(tmp_path / "fixture", token_lifetime_seconds=0)


def test_release_roster_loads_ten_deepseek_players_without_credentials():
    path = Path("examples/playtests/multiplayer-llm-10.yml")

    config = load_multiplayer_config(path)

    assert config.shared_provider == "ollama-cloud"
    assert config.shared_model == "deepseek-v4-flash"
    assert config.turns == 12
    assert config.max_concurrency == 10
    assert len(config.players) == 10
    assert len({player.name for player in config.players}) == 10
    assert len({player.character for player in config.players}) == 10
    assert [player.access_token_env for player in config.players] == [
        f"BUNNYLAND_PLAYER_{index:02d}_TOKEN" for index in range(1, 11)
    ]
