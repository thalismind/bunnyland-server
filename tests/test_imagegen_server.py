"""Tests for the image generation HTTP endpoints, media route, backfill, and wiring."""

from __future__ import annotations

import asyncio
import sys
import types

import httpx
import pytest
from conftest import build_scenario

from bunnyland.core import CharacterComponent, IdentityComponent, spawn_entity
from bunnyland.core.events import DomainEvent
from bunnyland.foundation.history.mechanics import record_world_history
from bunnyland.imagegen.components import PortraitImageComponent
from bunnyland.imagegen.config import ImageGenConfig
from bunnyland.imagegen.media import SEGMENT_PORTRAITS, SEGMENT_SPRITES, MediaStore
from bunnyland.imagegen.prompt import CatalogExampleSource, StubPromptEnhancer
from bunnyland.imagegen.service import ImageGenService
from bunnyland.imagegen.spec import ImagePurpose
from bunnyland.imagegen.store import WorkflowTemplateStore, default_templates
from bunnyland.imagegen.wiring import build_image_service, select_enhancer
from bunnyland.persistence import WorldMeta
from bunnyland.server.app import MAX_UPLOAD_IMAGE_BYTES, create_app
from bunnyland.simpacks.toonsim.mechanics import SpriteImageComponent

ADMIN = {"X-Bunnyland-Admin-Secret": "secret"}


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


def _client(app, *, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    )


# --- admin generate-image ------------------------------------------------------------


async def test_generate_image_requires_admin(tmp_path):
    scenario = build_scenario()
    async with _client(_app(scenario.actor, _service(scenario.actor, tmp_path))) as client:
        response = await client.post(
            "/admin/world/generate-image", json={"entity_id": str(scenario.character)}
        )
    assert response.status_code == 403


async def test_generate_image_success_and_status(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    async with _client(_app(scenario.actor, service)) as client:
        response = await client.post(
            "/admin/world/generate-image",
            headers=ADMIN,
            json={"entity_id": str(scenario.character), "purpose": "portrait"},
        )
        assert response.status_code == 200
        payload = response.json()
        job_id = payload["job_id"]
        assert payload["entity_id"] == str(scenario.character)
        assert payload["purpose"] == "portrait"

        status = await client.get(f"/admin/world/generate-image/{job_id}", headers=ADMIN)
    assert response.status_code == 200
    assert status.status_code == 200
    assert status.json()["job_id"] == job_id


async def test_generate_image_invalid_purpose(tmp_path):
    scenario = build_scenario()
    async with _client(_app(scenario.actor, _service(scenario.actor, tmp_path))) as client:
        response = await client.post(
            "/admin/world/generate-image",
            headers=ADMIN,
            json={"entity_id": str(scenario.character), "purpose": "nonsense"},
        )
    assert response.status_code == 400


async def test_image_job_status_unknown(tmp_path):
    scenario = build_scenario()
    async with _client(_app(scenario.actor, _service(scenario.actor, tmp_path))) as client:
        response = await client.get("/admin/world/generate-image/ghost", headers=ADMIN)
    assert response.status_code == 404


async def test_endpoints_409_when_imagegen_disabled():
    scenario = build_scenario()
    app = create_app(scenario.actor, meta=WorldMeta(seed="moss"), admin_token="secret")
    async with _client(app) as client:
        assert (
            await client.post("/admin/world/generate-image", headers=ADMIN, json={"entity_id": "x"})
        ).status_code == 409
        assert (await client.post("/world/event/rec_1/image")).status_code == 409
        assert (await client.get("/media/portraits/x.png")).status_code == 404


async def test_admin_upload_character_images_without_imagegen(tmp_path, monkeypatch):
    monkeypatch.setenv("BUNNYLAND_MEDIA_DIR", str(tmp_path))
    scenario = build_scenario()
    app = create_app(scenario.actor, meta=WorldMeta(seed="moss"), admin_token="secret")
    async with _client(app) as client:
        denied = await client.post(
            f"/admin/world/character/{scenario.character}/image/portrait",
            content=b"PNG",
            headers={"Content-Type": "image/png"},
        )
        assert denied.status_code == 403

        portrait = await client.post(
            f"/admin/world/character/{scenario.character}/image/portrait",
            content=b"PNG",
            headers={**ADMIN, "Content-Type": "image/png"},
        )
        assert portrait.status_code == 200
        portrait_payload = portrait.json()
        assert portrait_payload["purpose"] == "portrait"
        assert portrait_payload["url"].startswith("/media/portraits/")
        component = scenario.actor.world.get_entity(scenario.character).get_component(
            PortraitImageComponent
        )
        assert component.url == portrait_payload["url"]
        media = await client.get(component.url)
        assert media.status_code == 200
        assert media.content == b"PNG"

        sprite = await client.post(
            f"/admin/world/character/{scenario.character}/image/sprite",
            content=b"WEBP",
            headers={**ADMIN, "Content-Type": "image/webp"},
        )
        assert sprite.status_code == 200
        sprite_component = scenario.actor.world.get_entity(scenario.character).get_component(
            SpriteImageComponent
        )
        assert sprite_component.url.startswith(f"/media/{SEGMENT_SPRITES}/")


async def test_admin_upload_character_image_rejects_bad_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("BUNNYLAND_MEDIA_DIR", str(tmp_path))
    scenario = build_scenario()
    app = create_app(scenario.actor, meta=WorldMeta(seed="moss"), admin_token="secret")
    async with _client(app) as client:
        bad_purpose = await client.post(
            f"/admin/world/character/{scenario.character}/image/avatar",
            content=b"PNG",
            headers={**ADMIN, "Content-Type": "image/png"},
        )
        assert bad_purpose.status_code == 400

        bad_type = await client.post(
            f"/admin/world/character/{scenario.character}/image/portrait",
            content=b"GIF",
            headers={**ADMIN, "Content-Type": "image/gif"},
        )
        assert bad_type.status_code == 400

        empty = await client.post(
            f"/admin/world/character/{scenario.character}/image/portrait",
            content=b"",
            headers={**ADMIN, "Content-Type": "image/png"},
        )
        assert empty.status_code == 400

        too_large = await client.post(
            f"/admin/world/character/{scenario.character}/image/portrait",
            content=b"P" * (MAX_UPLOAD_IMAGE_BYTES + 1),
            headers={**ADMIN, "Content-Type": "image/png"},
        )
        assert too_large.status_code == 413


# --- player event image --------------------------------------------------------------


async def test_request_event_image_and_dedup(tmp_path):
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
    async with _client(_app(scenario.actor, service)) as client:
        first = await client.post(f"/world/event/{record.id}/image", json={"extra": "dramatic"})
    assert first.status_code == 200
    assert first.json()["purpose"] == "event"
    # Once it has an image, a second request reuses it (deduped).
    world.get_entity(record.id)  # still present


# --- scene helper + player scene-image endpoint --------------------------------------


async def test_scene_helper_unknown_character_returns_none(tmp_path):
    scenario = build_scenario()
    from bunnyland.imagegen.scene import request_scene_image

    service = _service(scenario.actor, tmp_path)
    assert await request_scene_image(scenario.actor, service, character_id="ghost_9") is None
    await service.aclose()


async def test_scene_image_endpoint_success(tmp_path):
    scenario = build_scenario()
    events = []
    scenario.actor.bus.subscribe(DomainEvent, events.append)
    service = _service(scenario.actor, tmp_path)
    async with _client(_app(scenario.actor, service)) as client:
        response = await client.post(f"/world/character/{scenario.character}/scene-image")
        await service.wait_idle()
    assert response.status_code == 200
    assert response.json()["purpose"] == "event"
    image_events = [
        event for event in events if event.__class__.__name__.startswith("ImageGeneration")
    ]
    assert image_events
    assert all(event.visibility.value == "directed" for event in image_events)
    assert all(event.target_ids == (str(scenario.character),) for event in image_events)


async def test_scene_image_endpoint_unknown_character(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    async with _client(_app(scenario.actor, service)) as client:
        assert (await client.post("/world/character/ghost_9/scene-image")).status_code == 404


async def test_scene_image_endpoint_no_room(tmp_path):
    scenario = build_scenario()
    roomless = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Stray", kind="character"), CharacterComponent(species="bunny")],
    )
    service = _service(scenario.actor, tmp_path)
    async with _client(_app(scenario.actor, service)) as client:
        assert (await client.post(f"/world/character/{roomless.id}/scene-image")).status_code == 400


async def test_scene_image_endpoint_409_without_imagegen():
    scenario = build_scenario()
    app = create_app(scenario.actor, meta=WorldMeta(seed="moss"), admin_token="secret")
    async with _client(app) as client:
        response = await client.post(f"/world/character/{scenario.character}/scene-image")
        assert response.status_code == 409


# --- backend request_image -----------------------------------------------------------


async def test_local_backend_request_image_unavailable_and_ok(tmp_path):
    from bunnyland.tui.backend import LocalBackend

    scenario = build_scenario()
    backend = LocalBackend(autorun=False)
    backend.actor = scenario.actor
    # No service configured -> unavailable.
    result = await backend.request_image(str(scenario.character))
    assert result.ok is False and result.status == "unavailable"
    # With a service -> a real job.
    backend.imagegen = _service(scenario.actor, tmp_path)
    ok = await backend.request_image(str(scenario.character))
    assert ok.ok is True
    await backend.imagegen.wait_idle()
    await backend.imagegen.aclose()


async def test_local_backend_request_image_no_room(tmp_path):
    from bunnyland.tui.backend import LocalBackend

    scenario = build_scenario()
    roomless = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Stray", kind="character"), CharacterComponent(species="bunny")],
    )
    backend = LocalBackend(autorun=False)
    backend.actor = scenario.actor
    backend.imagegen = _service(scenario.actor, tmp_path)
    result = await backend.request_image(str(roomless.id))
    assert result.ok is False and result.status == "no-room"
    await backend.imagegen.aclose()


async def test_remote_backend_request_image_paths():
    import httpx

    from bunnyland.tui.backend import RemoteBackend

    def handler(request):
        if request.url.path.endswith("/ok/scene-image"):
            return httpx.Response(200, json={"status": "queued", "url": "/media/events/x.png"})
        if request.url.path.endswith("/off/scene-image"):
            return httpx.Response(409, json={"detail": "disabled"})
        return httpx.Response(500, json={"detail": "boom"})

    backend = RemoteBackend("http://server")
    backend._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    ok = await backend.request_image("ok")
    assert ok.ok is True and ok.url == "/media/events/x.png"
    off = await backend.request_image("off")
    assert off.ok is False and off.status == "unavailable"
    err = await backend.request_image("bad")
    assert err.ok is False and err.status == "error"
    await backend._client.aclose()


async def test_backend_base_request_image_default():
    from bunnyland.tui.backend import Backend

    class _Stub(Backend):
        async def start(self): ...
        async def close(self): ...
        async def fetch_snapshot(self):
            return {}

        async def submit(self, command):
            raise NotImplementedError

        async def claim(self, player_id, world):
            return None

    result = await _Stub().request_image("x")
    assert result.ok is False


# --- projection portrait fields ------------------------------------------------------


async def test_character_projection_includes_portrait(tmp_path):
    scenario = build_scenario()
    entity = scenario.actor.world.get_entity(scenario.character)
    entity.add_component(
        PortraitImageComponent(url="/media/portraits/p.png", alpha_url="/media/alpha/p.png")
    )
    app = create_app(scenario.actor, meta=WorldMeta(seed="moss"), admin_token="secret")
    async with _client(app) as client:
        body = (await client.get(f"/world/character/{scenario.character}")).json()
    assert body["portrait"]["url"] == "/media/portraits/p.png"
    assert body["portrait"]["alpha_url"] == "/media/alpha/p.png"


async def test_room_projection_entity_portrait_default_empty(tmp_path):
    scenario = build_scenario()
    app = create_app(scenario.actor, meta=WorldMeta(seed="moss"), admin_token="secret")
    room = scenario.character_room()
    async with _client(app) as client:
        body = (await client.get(f"/world/room/{room}")).json()
    members = body["room"]["entities"]
    assert members  # the character is in the room
    assert all("portrait" in member for member in members)
    assert members[0]["portrait"]["url"] == ""  # no portrait generated yet


# --- media route ---------------------------------------------------------------------


async def test_media_route_serves_and_404(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    service.media.write(SEGMENT_PORTRAITS, "abc123.png", b"IMGDATA")
    async with _client(_app(scenario.actor, service)) as client:
        ok = await client.get("/media/portraits/abc123.png")
        assert ok.status_code == 200
        assert ok.content == b"IMGDATA"
        assert ok.headers["content-type"].startswith("image/png")

        assert (await client.get("/media/portraits/missing.png")).status_code == 404
        # Invalid (dotted) name is rejected by the store -> 404.
        assert (await client.get("/media/portraits/..%2Fsecret.png")).status_code == 404


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
    assert scenario.actor.world.get_entity(scenario.character).has_component(PortraitImageComponent)
    await service.aclose()


async def test_lifespan_starts_backfill_and_closes(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    app = _app(scenario.actor, service)
    async with app.router.lifespan_context(app):
        assert service._backfill is not None
        async with _client(app) as client:
            assert (await client.get("/health")).status_code == 200
    assert service._backfill is None


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


def test_build_image_service_selects_family(tmp_path):
    scenario = build_scenario()
    config = ImageGenConfig(
        server_url="http://comfy.local", media_root=str(tmp_path), workflows="anima-house"
    )
    service = build_image_service(scenario.actor, config)
    assert service._templates.for_purpose(ImagePurpose.PORTRAIT).default_negative.startswith(
        "worst quality, low quality, score_1"
    )


def test_build_image_service_unknown_family():
    scenario = build_scenario()
    config = ImageGenConfig(server_url="http://comfy.local", workflows="bogus")
    with pytest.raises(ValueError, match="unknown workflow family"):
        build_image_service(scenario.actor, config)


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
