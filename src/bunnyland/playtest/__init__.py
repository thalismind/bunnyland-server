"""Reusable live-player playtest harnesses."""

from .fixture import (
    DEFAULT_FIXTURE_PLAYERS,
    DEFAULT_TOKEN_LIFETIME_SECONDS,
    MultiplayerFixture,
    fixture_proposal,
    prepare_multiplayer_fixture,
)
from .multiplayer import (
    DEFAULT_PLAYER_SYSTEM_PROMPT,
    AdminTraceRecord,
    MultiplayerHarness,
    MultiplayerHarnessConfig,
    MultiplayerHarnessError,
    MultiplayerRunResult,
    NdjsonAdminTraceWriter,
    PlayerResult,
    PlayerSpec,
    load_multiplayer_config,
)

__all__ = [
    "AdminTraceRecord",
    "DEFAULT_FIXTURE_PLAYERS",
    "DEFAULT_PLAYER_SYSTEM_PROMPT",
    "DEFAULT_TOKEN_LIFETIME_SECONDS",
    "MultiplayerHarness",
    "MultiplayerHarnessConfig",
    "MultiplayerHarnessError",
    "MultiplayerFixture",
    "MultiplayerRunResult",
    "NdjsonAdminTraceWriter",
    "PlayerResult",
    "PlayerSpec",
    "fixture_proposal",
    "load_multiplayer_config",
    "prepare_multiplayer_fixture",
]
