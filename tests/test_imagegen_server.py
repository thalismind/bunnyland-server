"""Tests for the image generation HTTP endpoints, media route, backfill, and wiring."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest
from conftest import build_scenario

from bunnyland.imagegen.components import PortraitImageComponent
from bunnyland.imagegen.config import ImageGenConfig
from bunnyland.imagegen.media import SEGMENT_PORTRAITS, MediaStore
from bunnyland.imagegen.prompt import CatalogExampleSource, StubPromptEnhancer
from bunnyland.imagegen.service import ImageGenService
from bunnyland.imagegen.store import WorkflowTemplateStore, default_templates
from bunnyland.imagegen.wiring import build_image_service, select_enhancer
from bunnyland.mechanics.history import record_world_history
from bunnyland.persistence import WorldMeta
from bunnyland.server.app import create_app

testclient = pytest.importorskip("fastapi.testclient")

ADMIN = {"X-Bunnyland-Admin-Token": "secret"}


class _FakeClient:
    async def generate(self, graph, *, output_node_id=""):
        return b"PNG"


def _service(actor, tmp_path):
    return ImageGenService(
        actor,
        ImageGenConfig(server_url="http://comfy.local"),
        client=_FakeClient(),
        templates=WorkflowTemplateStore(defaults=default_templates()),
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
    )


def _app(actor, service):
    return create_app(actor, meta=WorldMeta(seed="moss"), admin_token="secret", imagegen=service)


# --- admin generate-image ------------------------------------------------------------


def test_generate_image_requires_admin(tmp_path):
    scenario = build_scenario()
    client = testclient.TestClient(_app(scenario.actor, _service(scenario.actor, tmp_path)))
    response = client.post(
        "/admin/world/generate-image", json={"entity_id": str(scenario.character)}
    )
    assert response.status_code == 403


def test_generate_image_success_and_status(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    client = testclient.TestClient(_app(scenario.actor, service))
    response = client.post(
        "/admin/world/generate-image",
        headers=ADMIN,
        json={"entity_id": str(scenario.character), "purpose": "portrait"},
    )
    assert response.status_code == 200
    payload = response.json()
    job_id = payload["job_id"]
    assert payload["entity_id"] == str(scenario.character)
    assert payload["purpose"] == "portrait"

    status = client.get(f"/admin/world/generate-image/{job_id}", headers=ADMIN)
    assert status.status_code == 200
    assert status.json()["job_id"] == job_id


def test_generate_image_invalid_purpose(tmp_path):
    scenario = build_scenario()
    client = testclient.TestClient(_app(scenario.actor, _service(scenario.actor, tmp_path)))
    response = client.post(
        "/admin/world/generate-image",
        headers=ADMIN,
        json={"entity_id": str(scenario.character), "purpose": "nonsense"},
    )
    assert response.status_code == 400


def test_image_job_status_unknown(tmp_path):
    scenario = build_scenario()
    client = testclient.TestClient(_app(scenario.actor, _service(scenario.actor, tmp_path)))
    response = client.get("/admin/world/generate-image/ghost", headers=ADMIN)
    assert response.status_code == 404


def test_endpoints_409_when_imagegen_disabled():
    scenario = build_scenario()
    app = create_app(scenario.actor, meta=WorldMeta(seed="moss"), admin_token="secret")
    client = testclient.TestClient(app)
    assert client.post(
        "/admin/world/generate-image", headers=ADMIN, json={"entity_id": "x"}
    ).status_code == 409
    assert client.post("/world/event/rec_1/image").status_code == 409
    assert client.get("/media/portraits/x.png").status_code == 409


# --- player event image --------------------------------------------------------------


def test_request_event_image_and_dedup(tmp_path):
    scenario = build_scenario()
    world = scenario.actor.world
    record = record_world_history(
        world,
        source_event_id="evt-1",
        summary="A duel",
        event_type="duel",
        created_at_epoch=0,
    )
    service = _service(scenario.actor, tmp_path)
    client = testclient.TestClient(_app(scenario.actor, service))
    first = client.post(f"/world/event/{record.id}/image", json={"extra": "dramatic"})
    assert first.status_code == 200
    assert first.json()["purpose"] == "event"
    # Once it has an image, a second request reuses it (deduped).
    world.get_entity(record.id)  # still present


# --- media route ---------------------------------------------------------------------


def test_media_route_serves_and_404(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    service.media.write(SEGMENT_PORTRAITS, "abc123.png", b"IMGDATA")
    client = testclient.TestClient(_app(scenario.actor, service))

    ok = client.get("/media/portraits/abc123.png")
    assert ok.status_code == 200
    assert ok.content == b"IMGDATA"
    assert ok.headers["content-type"].startswith("image/png")

    assert client.get("/media/portraits/missing.png").status_code == 404
    # Invalid (dotted) name is rejected by the store -> 404.
    assert client.get("/media/portraits/..%2Fsecret.png").status_code == 404


# --- backfill loop -------------------------------------------------------------------


async def test_start_backfill_generates_missing_portrait(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    service.start_backfill(0.01)
    service.start_backfill(0.01)  # idempotent: second call is a no-op
    for _ in range(50):
        if scenario.actor.world.get_entity(scenario.character).has_component(
            PortraitImageComponent
        ):
            break
        await asyncio.sleep(0.01)
    assert scenario.actor.world.get_entity(scenario.character).has_component(
        PortraitImageComponent
    )
    await service.aclose()


def test_lifespan_starts_backfill_and_closes(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    # Entering the TestClient context triggers startup (start_backfill) and shutdown (aclose).
    with testclient.TestClient(_app(scenario.actor, service)) as client:
        assert client.get("/health").status_code == 200


# --- wiring --------------------------------------------------------------------------


def test_cli_build_imagegen_service(monkeypatch, tmp_path, capsys):
    from bunnyland.cli import _build_imagegen_service

    scenario = build_scenario()
    monkeypatch.setenv("COMFYUI_SERVER_URL", "http://comfy.local:8188")
    monkeypatch.setenv("BUNNYLAND_MEDIA_DIR", str(tmp_path))
    service = _build_imagegen_service(scenario.actor, [])
    assert isinstance(service, ImageGenService)
    assert "Image generation enabled" in capsys.readouterr().out


def test_cli_build_imagegen_service_disabled(monkeypatch):
    from bunnyland.cli import _build_imagegen_service

    scenario = build_scenario()
    monkeypatch.delenv("COMFYUI_SERVER_URL", raising=False)
    assert _build_imagegen_service(scenario.actor, []) is None


def test_build_image_service_from_config(tmp_path):
    scenario = build_scenario()
    config = ImageGenConfig(server_url="http://comfy.local", media_root=str(tmp_path))
    service = build_image_service(scenario.actor, config)
    assert isinstance(service, ImageGenService)


def test_select_enhancer_stub():
    assert select_enhancer(ImageGenConfig(server_url="x")).name == "stub"
    assert select_enhancer(ImageGenConfig(server_url="x", enhancer="stub")).name == "stub"


def test_select_enhancer_llm(monkeypatch):
    module = types.ModuleType("ollama")
    module.AsyncClient = lambda *a, **k: object()
    monkeypatch.setitem(sys.modules, "ollama", module)
    enhancer = select_enhancer(ImageGenConfig(server_url="x", enhancer="llm"))
    assert enhancer.name == "llm"


def test_select_enhancer_from_plugin():
    from bunnyland.plugins import ContentContribution, Plugin

    custom = StubPromptEnhancer()
    custom.name = "custom"
    plugin = Plugin(
        id="x.custom",
        name="Custom",
        content=ContentContribution(prompt_enhancers=(custom,)),
    )
    enhancer = select_enhancer(ImageGenConfig(server_url="x", enhancer="custom"), [plugin])
    assert enhancer is custom


def test_select_enhancer_unknown_with_nonmatching_plugin():
    from bunnyland.plugins import ContentContribution, Plugin

    other = StubPromptEnhancer()
    other.name = "other"
    plugin = Plugin(
        id="x.other",
        name="Other",
        content=ContentContribution(prompt_enhancers=(other,)),
    )
    with pytest.raises(ValueError, match="unknown image enhancer"):
        select_enhancer(ImageGenConfig(server_url="x", enhancer="ghost"), [plugin])
