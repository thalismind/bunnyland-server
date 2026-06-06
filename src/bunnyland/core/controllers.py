"""Controller components (spec section 7).

A character is a persistent entity; its controller is a separate, replaceable entity
linked by the ``ControlledBy`` edge. Every control change increments the edge's
``generation`` so that late/stale commands from a previous controller are rejected.
"""

from __future__ import annotations

from pydantic.dataclasses import dataclass
from relics import Component


@dataclass(frozen=True)
class ClaimTimeoutComponent(Component):
    """Player-controller timeout state and fallback preference.

    Server runtime configuration decides whether this controller kind is timed out and
    after how many game seconds. The component stores player-owned preference: what kind
    of controller should take over if the claim expires.
    """

    fallback_controller: str = "suspend"
    fallback_reason: str = "claim timed out"
    llm_profile_name: str = "default"
    llm_model: str = ""
    llm_provider: str = ""
    #: Player-selected timeout in wall-clock seconds; 0 means use the server default.
    timeout_seconds: int = 0
    claimed_at_unix: int = 0
    last_command_unix: int = 0


@dataclass(frozen=True)
class DiscordControllerComponent(Component):
    discord_user_id: int
    default_channel_id: int
    mention_on_ready: bool = True
    allow_dm: bool = False


@dataclass(frozen=True)
class MCPControllerComponent(Component):
    agent_id: str
    label: str = ""


@dataclass(frozen=True)
class LLMControllerComponent(Component):
    profile_name: str
    model: str
    provider: str = "ollama"
    temperature: float = 0.7
    max_tokens: int = 1024
    system_style: str = "in_character"
    tool_policy: str = "character_actions"
    #: Only let this controller act once every N dispatch ticks (>=1). Higher values make
    #: the character take fewer turns, letting environmental systems run faster than it.
    act_every_ticks: int = 1


@dataclass(frozen=True)
class WebControllerComponent(Component):
    """A human at an interactive client (web room client, TUI). Submits commands directly;
    the engine never proposes actions for it the way it does for an LLM controller."""

    client_id: str = ""
    label: str = "web"


@dataclass(frozen=True)
class SuspendedControllerComponent(Component):
    """A no-op controller. The character regenerates but takes no actions (spec 7.7)."""

    reason: str = "offline"


__all__ = [
    "ClaimTimeoutComponent",
    "DiscordControllerComponent",
    "LLMControllerComponent",
    "MCPControllerComponent",
    "SuspendedControllerComponent",
    "WebControllerComponent",
]
