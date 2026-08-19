"""Canonical shared media plugin entrypoint."""

from __future__ import annotations

import os

from ...plugins.ids import MEDIA
from ...plugins.model import (
    HttpContribution,
    HttpZone,
    Plugin,
    PluginPlacement,
    RuntimeContribution,
)
from .service import (
    DEFAULT_MEDIA_CAPACITY_BYTES,
    MediaError,
    MediaService,
    content_type_for,
)


def _install_service(actor) -> None:
    if getattr(actor, "media_service", None) is None:
        root = os.environ.get("BUNNYLAND_MEDIA_DIR", "media").strip() or "media"
        capacity = int(
            os.environ.get(
                "BUNNYLAND_MEDIA_CAPACITY_BYTES", str(DEFAULT_MEDIA_CAPACITY_BYTES)
            )
        )
        actor.media_service = MediaService(root, capacity_bytes=capacity)


def _install_routes(router, actor, **_context) -> None:
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    @router.get("/media/{namespace}/{name}")
    async def get_media(namespace: str, name: str):
        try:
            path = actor.media_service.path_for(namespace, name)
            if not path.is_file():
                raise MediaError(f"media not found: {namespace}/{name}")
            content_type = content_type_for(name)
        except MediaError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(
            path,
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                # Set here rather than relying on the edge: this route is public and its
                # bytes are uploaded, and only one of the shipped nginx shapes used to send
                # any security headers at all.
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "inline",
            },
        )


def plugin() -> Plugin:
    return Plugin(
        id=MEDIA,
        name="Media Storage",
        placement=PluginPlacement.FOUNDATION,
        runtime=RuntimeContribution(
            service_factories=(_install_service,),
            http=(HttpContribution(zone=HttpZone.PUBLIC, registrars=(_install_routes,)),),
        ),
    )


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
