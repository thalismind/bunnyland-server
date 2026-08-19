from __future__ import annotations

import asyncio
import struct
from concurrent.futures import ThreadPoolExecutor

import pytest

from bunnyland.core import WorldActor
from bunnyland.foundation.media import (
    MediaError,
    MediaQuotaError,
    MediaService,
    require_media_service,
)
from bunnyland.foundation.media.plugin import bunnyland_plugins, plugin
from bunnyland.plugins import apply_plugins


def test_media_service_supports_content_addressed_models_and_rejects_traversal(tmp_path):
    service = MediaService(tmp_path)
    data = b"glTF" + struct.pack("<II", 2, 12)

    name, path = service.put_content("models3d", data, "glb")

    assert path.read_bytes() == data
    assert service.put_content("models3d", data, "glb")[0] == name
    assert service.url_for("models3d", name) == f"/v1/public/media/models3d/{name}"
    assert service.public_url_for("models3d", name, base_url="") == service.url_for(
        "models3d", name
    )
    assert (
        service.public_url_for("models3d", name, base_url="https://example.test/")
        == f"https://example.test/v1/public/media/models3d/{name}"
    )
    with pytest.raises(MediaError):
        service.path_for("../models", name)
    with pytest.raises(MediaError):
        service.path_for("models3d", "../model.glb")


def test_media_service_enforces_capacity_and_supports_deletion(tmp_path):
    with pytest.raises(ValueError, match="media capacity must be positive"):
        MediaService(tmp_path, capacity_bytes=0)

    service = MediaService(tmp_path, capacity_bytes=8)
    service.write("events", "first.png", b"1234")
    service.write("events", "second.png", b"5678")

    assert service.total_bytes() == 8
    with pytest.raises(MediaQuotaError, match="media storage quota exceeded"):
        service.write("events", "third.png", b"9")
    assert service.delete("events", "first.png") is True
    assert service.delete("events", "first.png") is False
    assert service.total_bytes() == 4


def test_media_service_reports_zero_bytes_before_storage_root_exists(tmp_path):
    service = MediaService(tmp_path / "not-created-yet")

    assert service.total_bytes() == 0
    assert not service.root.exists()


def test_media_service_serializes_concurrent_quota_writes(tmp_path):
    service = MediaService(tmp_path, capacity_bytes=6)

    def write(name: str) -> bool:
        try:
            service.write("events", name, b"1234")
        except MediaQuotaError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(write, ("first.png", "second.png")))

    assert sorted(outcomes) == [False, True]
    assert service.total_bytes() == 4
    assert not list(tmp_path.rglob("*.tmp"))


def test_media_plugin_owns_compatible_immutable_route(tmp_path, monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    monkeypatch.setenv("BUNNYLAND_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("BUNNYLAND_MEDIA_CAPACITY_BYTES", "6")
    actor = WorldActor()
    with pytest.raises(RuntimeError, match="not installed"):
        require_media_service(actor)
    plugins = [plugin()]
    apply_plugins(plugins, actor)
    original_service = actor.media_service
    apply_plugins(plugins, actor)
    assert actor.media_service is original_service
    assert require_media_service(actor) is original_service
    assert actor.media_service.capacity_bytes == 6
    assert bunnyland_plugins()[0].id == "bunnyland.media"
    name, _path = actor.media_service.put_content("models3d", b"model", "glb")
    contribution = plugins[0].runtime.http[0]
    router = fastapi.APIRouter(prefix=f"/{contribution.zone.value}")
    contribution.registrars[0](router, actor)
    endpoint = next(
        route.endpoint
        for route in router.routes
        if route.path == "/public/media/{namespace}/{name}"
    )

    response = asyncio.run(endpoint("models3d", name))

    assert response.status_code == 200
    assert response.path == _path
    assert response.media_type == "model/gltf-binary"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    with pytest.raises(fastapi.HTTPException) as exc:
        asyncio.run(endpoint("models3d", "missing.glb"))
    assert exc.value.status_code == 404
    # The public serving route refuses path-traversal / invalid segments with a 404 rather
    # than reading outside the namespaced media root.
    for bad_namespace, bad_name in (("..", name), ("models3d", "../secret.glb")):
        with pytest.raises(fastapi.HTTPException) as traversal:
            asyncio.run(endpoint(bad_namespace, bad_name))
        assert traversal.value.status_code == 404
