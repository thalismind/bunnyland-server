"""Dependency-free capability contracts populated by optional server runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AddonMediaJob:
    """Stable addon-facing media job shape without exposing generation services."""

    id: str
    kind: str
    status: str
    source_event_id: str
    url: str
    error: str | None


class AddonMediaCapability:
    """Narrow character-scene media surface supplied by the HTTP runtime."""

    @property
    def image_available(self) -> bool:
        raise NotImplementedError

    @property
    def video_available(self) -> bool:
        raise NotImplementedError

    async def request_character_scene_image(
        self, character_id: str, *, requested_by: str, event_id: str = ""
    ) -> AddonMediaJob | None:
        raise NotImplementedError

    async def request_character_scene_video(
        self, character_id: str, *, requested_by: str, event_id: str = ""
    ) -> AddonMediaJob | None:
        raise NotImplementedError

    def get_character_scene_media_job(
        self, job_id: str, *, kind: Literal["image", "video"]
    ) -> AddonMediaJob | None:
        """Return current bounded job state without exposing a generation service."""

        raise NotImplementedError


class PlayWebSocketAuthSessionCapability:
    """Authenticated play identity whose credentials can be periodically rechecked."""

    client_id: str

    @property
    def subject(self) -> str:
        raise NotImplementedError

    def reauthorize(self) -> bool:
        raise NotImplementedError


class PlayWebSocketAuthCapability:
    """Authenticate an addon WebSocket through the configured play policy."""

    def authenticate(
        self, websocket: object, frame: object
    ) -> PlayWebSocketAuthSessionCapability:
        raise NotImplementedError


__all__ = [
    "AddonMediaCapability",
    "AddonMediaJob",
    "PlayWebSocketAuthCapability",
    "PlayWebSocketAuthSessionCapability",
]
