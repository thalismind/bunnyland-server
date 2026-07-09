"""Discord ECS components."""

from __future__ import annotations

from pydantic.dataclasses import dataclass
from relics import Component


@dataclass(frozen=True)
class DiscordRoomFeedComponent(Component):
    """Marks a room for Discord activity mirroring."""

    channel_id: int


__all__ = ["DiscordRoomFeedComponent"]
