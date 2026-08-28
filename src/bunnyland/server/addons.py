"""Narrow runtime capabilities exposed to out-of-tree HTTP addons."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException

from ..core.world_actor import WorldActor
from ..imagegen.scene import request_scene_image, request_scene_video
from ..imagegen.service import ImageGenJob, ImageGenService
from ..imagegen.video_service import VideoGenJob, VideoGenService
from ..moderation import (
    IdentityKind,
    ModerationIdentity,
    ModerationRestrictedError,
    ModerationService,
)
from ..plugins.runtime import (
    AddonMediaCapability,
    AddonMediaJob,
    PlayWebSocketAuthCapability,
    PlayWebSocketAuthSessionCapability,
)
from .auth import (
    AUTH_COOKIE_NAME,
    WORLD_PLAY_SCOPE,
    RequestAuthenticator,
    TokenPrincipal,
    scope_granted,
)
from .client_ids import CLIENT_ID_HEADER, require_allowed_client_id


class AddonWebSocket(Protocol):
    """The credential-bearing portion of a Starlette WebSocket used during auth."""

    headers: Mapping[str, str]
    cookies: Mapping[str, str]


class AddonMediaFacade(AddonMediaCapability):
    """Claim-agnostic character-scene media operations for trusted addon routes.

    Addons remain responsible for authorizing their own claim before calling this facade.
    Only current-scene image and video operations are exposed; raw services and arbitrary
    entity generation are deliberately unavailable.
    """

    def __init__(
        self,
        actor: WorldActor,
        *,
        image_service: ImageGenService | None = None,
        video_service: VideoGenService | None = None,
    ) -> None:
        self._actor = actor
        self._image_service = image_service
        self._video_service = video_service

    @property
    def image_available(self) -> bool:
        return self._image_service is not None

    @property
    def video_available(self) -> bool:
        return self._video_service is not None

    async def request_character_scene_image(
        self,
        character_id: str,
        *,
        requested_by: str,
        event_id: str = "",
    ) -> AddonMediaJob | None:
        if self._image_service is None:
            raise RuntimeError("image generation is not configured")
        job = await request_scene_image(
            self._actor,
            self._image_service,
            character_id=character_id,
            requested_by=requested_by,
            event_id=event_id,
        )
        return self._job(job, "image")

    async def request_character_scene_video(
        self,
        character_id: str,
        *,
        requested_by: str,
        event_id: str = "",
    ) -> AddonMediaJob | None:
        if self._video_service is None:
            raise RuntimeError("video generation is not configured")
        job = await request_scene_video(
            self._actor,
            self._video_service,
            character_id=character_id,
            requested_by=requested_by,
            event_id=event_id,
        )
        return self._job(job, "video")

    @staticmethod
    def _job(job: ImageGenJob | VideoGenJob | None, kind: str) -> AddonMediaJob | None:
        if job is None:
            return None
        return AddonMediaJob(
            id=job.job_id,
            kind=kind,
            status=job.status,
            source_event_id=job.source_event_id,
            url=job.url,
            error=job.error,
        )


@dataclass(frozen=True)
class PlayWebSocketAuthSession(PlayWebSocketAuthSessionCapability):
    """Authenticated play-scoped identity with reusable periodic reauthorization."""

    access_token: str
    principal: TokenPrincipal
    client_id: str
    moderation_identity: ModerationIdentity
    _authenticator: RequestAuthenticator
    _moderation: ModerationService

    @property
    def subject(self) -> str:
        return self.principal.subject

    def reauthorize(self) -> bool:
        principal = self._authenticator.verify_token(self.access_token)
        if principal is None or not scope_granted(principal.scopes, WORLD_PLAY_SCOPE):
            return False
        if principal.subject != self.principal.subject:
            return False
        try:
            self._moderation.require_allowed(self.moderation_identity)
        except ModerationRestrictedError:
            return False
        return True


class PlayWebSocketAuthenticator(PlayWebSocketAuthCapability):
    """Authenticate an addon's first WebSocket frame using core play policy."""

    def __init__(
        self,
        authenticator: RequestAuthenticator | None,
        moderation: ModerationService,
        *,
        allowed_client_ids: frozenset[str] = frozenset(),
    ) -> None:
        self._authenticator = authenticator
        self._moderation = moderation
        self._allowed_client_ids = allowed_client_ids

    def authenticate(
        self,
        websocket: AddonWebSocket,
        frame: object,
    ) -> PlayWebSocketAuthSession:
        if self._authenticator is None:
            raise HTTPException(status_code=503, detail="authentication is not configured")
        if not isinstance(frame, dict) or frame.get("type") != "authenticate":
            raise HTTPException(status_code=401, detail="invalid authentication frame")
        data = frame.get("data")
        if not isinstance(data, dict):
            raise HTTPException(status_code=401, detail="invalid authentication frame")
        frame_token = data.get("token")
        if frame_token is not None and not isinstance(frame_token, str):
            raise HTTPException(status_code=401, detail="invalid bearer token")
        header_auth = websocket.headers.get("Authorization")
        if frame_token:
            if header_auth:
                scheme, separator, value = header_auth.partition(" ")
                if not separator or scheme.lower() != "bearer" or value.strip() != frame_token:
                    raise HTTPException(status_code=401, detail="conflicting bearer credentials")
            header_auth = f"Bearer {frame_token}"
        principal = self._authenticator.authenticate_values(
            authorization=header_auth,
            cookie_token=websocket.cookies.get(AUTH_COOKIE_NAME),
            required_scopes=(WORLD_PLAY_SCOPE,),
        )
        client_id_value = data.get("client_id") or websocket.headers.get(CLIENT_ID_HEADER)
        if not isinstance(client_id_value, str) or not client_id_value.strip():
            raise HTTPException(status_code=403, detail="client identity is required")
        try:
            allowed = require_allowed_client_id(
                client_id_value,
                self._allowed_client_ids,
                "player",
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        token = self._access_token(
            header_auth=header_auth,
            cookie_token=websocket.cookies.get(AUTH_COOKIE_NAME),
            frame_token=frame_token,
        )
        identity = ModerationIdentity(IdentityKind.WEB, principal.subject)
        self._moderation.require_allowed(identity)
        return PlayWebSocketAuthSession(
            access_token=token,
            principal=principal,
            client_id=allowed,
            moderation_identity=identity,
            _authenticator=self._authenticator,
            _moderation=self._moderation,
        )

    @staticmethod
    def _access_token(
        *, header_auth: str | None, cookie_token: str | None, frame_token: str | None
    ) -> str:
        if frame_token:
            return frame_token
        if cookie_token:
            return cookie_token
        token = header_auth.partition(" ")[2].strip() if header_auth else ""
        if not token:
            raise HTTPException(status_code=401, detail="bearer token required")
        return token


__all__ = [
    "AddonMediaFacade",
    "AddonMediaJob",
    "PlayWebSocketAuthSession",
    "PlayWebSocketAuthenticator",
]
