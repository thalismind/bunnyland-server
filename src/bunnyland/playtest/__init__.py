"""Reusable live-player playtest harnesses."""

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
    "DEFAULT_PLAYER_SYSTEM_PROMPT",
    "MultiplayerHarness",
    "MultiplayerHarnessConfig",
    "MultiplayerHarnessError",
    "MultiplayerRunResult",
    "NdjsonAdminTraceWriter",
    "PlayerResult",
    "PlayerSpec",
    "load_multiplayer_config",
]
