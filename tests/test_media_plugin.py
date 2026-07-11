from __future__ import annotations

import asyncio
import struct

import pytest

from bunnyland.core import WorldActor
from bunnyland.foundation.media import MediaError, MediaService, require_media_service
from bunnyland.foundation.media.plugin import bunnyland_plugins, plugin
from bunnyland.plugins import apply_plugins


def test_media_service_supports_content_addressed_models_and_rejects_traversal(tmp_path):
    service = MediaService(tmp_path)
    data = b"glTF" + struct.pack("<II", 2, 12)

    name, path = service.put_content("models3d", data, "glb")

    assert path.read_bytes() == data
    assert service.put_content("models3d", data, "glb")[0] == name
    assert service.url_for("models3d", name) == f"/media/models3d/{name}"
    assert service.public_url_for("models3d", name, base_url="") == service.url_for(
        "models3d", name
    )
    assert (
        service.public_url_for("models3d", name, base_url="https://example.test/")
        == f"https://example.test/media/models3d/{name}"
    )
    with pytest.raises(MediaError):
        service.path_for("../models", name)
    with pytest.raises(MediaError):
        service.path_for("models3d", "../model.glb")


def test_media_plugin_owns_compatible_immutable_route(tmp_path, monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    monkeypatch.setenv("BUNNYLAND_MEDIA_DIR", str(tmp_path))
    actor = WorldActor()
    with pytest.raises(RuntimeError, match="not installed"):
        require_media_service(actor)
    plugins = [plugin()]
    apply_plugins(plugins, actor)
    original_service = actor.media_service
    apply_plugins(plugins, actor)
    assert actor.media_service is original_service
    assert require_media_service(actor) is original_service
    assert bunnyland_plugins()[0].id == "bunnyland.media"
    name, _path = actor.media_service.put_content("models3d", b"model", "glb")
    app = fastapi.FastAPI()
    plugins[0].runtime.server_routers[0](app, actor)
    endpoint = next(
        route.endpoint for route in app.routes if route.path == "/media/{namespace}/{name}"
    )

    response = asyncio.run(endpoint("models3d", name))

    assert response.status_code == 200
    assert response.body == b"model"
    assert response.media_type == "model/gltf-binary"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    with pytest.raises(fastapi.HTTPException) as exc:
        asyncio.run(endpoint("models3d", "missing.glb"))
    assert exc.value.status_code == 404
