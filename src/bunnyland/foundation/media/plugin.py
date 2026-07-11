"""Canonical shared media plugin entrypoint."""

from __future__ import annotations

import os

from ...plugins.ids import MEDIA
from ...plugins.model import Plugin, PluginPlacement, RuntimeContribution
from .service import MediaError, MediaService, content_type_for


def _install_service(actor) -> None:
    if getattr(actor, "media_service", None) is None:
        root = os.environ.get("BUNNYLAND_MEDIA_DIR", "media").strip() or "media"
        actor.media_service = MediaService(root)


def _install_routes(app, actor, **_context) -> None:
    from fastapi import HTTPException, Response

    @app.get("/media/{namespace}/{name}")
    async def get_media(namespace: str, name: str):
        try:
            data = actor.media_service.read(namespace, name)
            content_type = content_type_for(name)
        except MediaError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=data,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )


def plugin() -> Plugin:
    return Plugin(
        id=MEDIA,
        name="Media Storage",
        placement=PluginPlacement.FOUNDATION,
        runtime=RuntimeContribution(
            service_factories=(_install_service,),
            server_routers=(_install_routes,),
        ),
    )


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
