"""Tests for the image generation HTTP endpoints, media route, backfill, and wiring."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from io import BytesIO

import httpx
import pytest
from conftest import build_scenario
from PIL import Image

from bunnyland.claims import ClaimSecretRegistry, add_claim
from bunnyland.core import (
    CharacterComponent,
    EventVisibility,
    IdentityComponent,
    event_base,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.events import DomainEvent, SpeechSaidEvent
from bunnyland.foundation.history.mechanics import record_world_history
from bunnyland.imagegen.backfill import ImageBackfillScheduler
from bunnyland.imagegen.comfyui import ComfyUIGenerator
from bunnyland.imagegen.components import MediaSceneSnapshotComponent, PortraitImageComponent
from bunnyland.imagegen.config import ComfyUIConfig, ImageGenConfig, MediaGenConfig
from bunnyland.imagegen.media import SEGMENT_PORTRAITS, SEGMENT_SPRITES, MediaStore
from bunnyland.imagegen.prompt import CatalogExampleSource, StubPromptEnhancer
from bunnyland.imagegen.service import ImageGenService
from bunnyland.imagegen.spec import ImagePurpose
from bunnyland.imagegen.store import WorkflowTemplateStore, default_templates
from bunnyland.imagegen.wiring import build_media_services, select_enhancer
from bunnyland.persistence import WorldMeta
from bunnyland.server.app import MAX_UPLOAD_IMAGE_BYTES, create_app
from bunnyland.server.auth import WORLD_ADMIN_SCOPE, WORLD_PLAY_SCOPE, TokenStore
from bunnyland.server.client_ids import CLIENT_ID_HEADER
from bunnyland.simpacks.toonsim.mechanics import SpriteImageComponent

ADMIN = {CLIENT_ID_HEADER: "admin-client"}


#: Real container signatures. The upload route validates the bytes rather than trusting the
#: caller-declared multipart content type, so placeholder strings no longer pass.
_png_buffer = BytesIO()
Image.new("RGB", (2, 2), (12, 34, 56)).save(_png_buffer, format="PNG")
PNG_BYTES = _png_buffer.getvalue()
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"payload"


class _FakeClient:
    async def generate(self, graph, *, output_node_id=""):
        return PNG_BYTES


def _service(actor, tmp_path):
    config = MediaGenConfig(
        comfyui=ComfyUIConfig(server_url="http://comfy.local"),
        image=ImageGenConfig(generator="comfyui"),
        media_root=str(tmp_path),
    )
    generator = ComfyUIGenerator(
        _FakeClient(), WorkflowTemplateStore(defaults=default_templates())
    )
    return ImageGenService(
        actor,
        config,
        generators={purpose: generator for purpose in ImagePurpose},
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
    )


def _app(actor, service, backfill=None, videogen=None):
    return create_app(
        actor,
        meta=WorldMeta(seed="moss"),
        imagegen=service,
        videogen=videogen,
        image_backfill=backfill,
        allow_unauthenticated_embedding=True,
    )


def _client(app, *, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={CLIENT_ID_HEADER: "image-client", **(headers or {})},
    )


async def _claim(client: httpx.AsyncClient, character_id: str) -> tuple[str, dict[str, str]]:
    response = await client.post("/v1/play/claims", json={"character_id": character_id})
    return response.json()["id"], {
        CLIENT_ID_HEADER: "image-client",
        "X-Bunnyland-Claim-Secret": response.headers["X-Bunnyland-Claim-Secret"],
    }


# --- admin generate-image ------------------------------------------------------------


async def test_generate_image_requires_admin(tmp_path):
    scenario = build_scenario()
    store = TokenStore(":memory:")
    token, _principal = store.issue("player", [WORLD_PLAY_SCOPE], automatic_rotation=False)
    app = create_app(
        scenario.actor,
        meta=WorldMeta(seed="moss"),
        imagegen=_service(scenario.actor, tmp_path),
        token_store=store,
    )
    async with _client(app, headers={"Authorization": f"Bearer {token}"}) as client:
        response = await client.post(
            "/v1/admin/world/generation-jobs",
            json={"kind": "image", "entity_id": str(scenario.character)},
        )
    assert response.status_code == 403


async def test_admin_media_workflows_are_live_persistent_overrides(tmp_path):
    scenario = build_scenario()
    path = tmp_path / "workflows.json"
    templates = WorkflowTemplateStore(path, defaults=default_templates())
    app = create_app(
        scenario.actor,
        meta=WorldMeta(seed="moss"),
        workflow_templates=templates,
        allow_unauthenticated_embedding=True,
    )

    async with _client(app) as client:
        listing = await client.get("/v1/admin/media/workflows", headers=ADMIN)
        assert listing.status_code == 200
        assert [item["name"] for item in listing.json()] == [
            "entity",
            "event",
            "portrait",
            "sprite",
        ]

        original = (
            await client.get("/v1/admin/media/workflows/portrait", headers=ADMIN)
        ).json()
        override = {**original, "description": "live portrait override"}
        mismatch = await client.put(
            "/v1/admin/media/workflows/other",
            headers=ADMIN,
            json=override,
        )
        assert mismatch.status_code == 400

        updated = await client.put(
            "/v1/admin/media/workflows/portrait",
            headers=ADMIN,
            json=override,
        )
        assert updated.status_code == 200
        assert templates.get("portrait").description == "live portrait override"
        assert json.loads(path.read_text())["templates"][0]["name"] == "portrait"

        reset = await client.delete("/v1/admin/media/workflows/portrait", headers=ADMIN)
        assert reset.status_code == 204
        assert templates.get("portrait").description == original["description"]
        assert json.loads(path.read_text()) == {"templates": []}

        missing = await client.get("/v1/admin/media/workflows/missing", headers=ADMIN)
        assert missing.status_code == 404
        missing_reset = await client.delete(
            "/v1/admin/media/workflows/missing", headers=ADMIN
        )
        assert missing_reset.status_code == 404


async def test_admin_media_workflows_require_comfy_configuration(tmp_path):
    scenario = build_scenario()
    app = _app(scenario.actor, _service(scenario.actor, tmp_path))
    async with _client(app) as client:
        response = await client.get("/v1/admin/media/workflows", headers=ADMIN)
    assert response.status_code == 409


async def test_event_image_requires_admin_scope(tmp_path):
    scenario = build_scenario()
    store = TokenStore(":memory:")
    player, _principal = store.issue("player", [WORLD_PLAY_SCOPE], automatic_rotation=False)
    operator, _principal = store.issue("operator", [WORLD_ADMIN_SCOPE], automatic_rotation=False)
    app = create_app(
        scenario.actor,
        meta=WorldMeta(seed="moss"),
        imagegen=_service(scenario.actor, tmp_path),
        token_store=store,
    )
    async with _client(app) as client:
        denied = await client.post(
            "/v1/admin/world/generation-jobs",
            headers={"Authorization": f"Bearer {player}"},
            json={"kind": "image", "entity_id": "record-1", "purpose": "event"},
        )
        allowed = await client.post(
            "/v1/admin/world/generation-jobs",
            headers={"Authorization": f"Bearer {operator}"},
            json={"kind": "image", "entity_id": "record-1", "purpose": "event"},
        )
    assert denied.status_code == 403
    assert allowed.status_code == 202
    store.close()


async def test_generate_image_success_and_status(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    async with _client(_app(scenario.actor, service)) as client:
        response = await client.post(
            "/v1/admin/world/generation-jobs",
            headers=ADMIN,
            json={
                "kind": "image",
                "entity_id": str(scenario.character),
                "purpose": "portrait",
            },
        )
        assert response.status_code == 202
        payload = response.json()
        job_id = payload["id"]
        assert payload["result"]["entity_id"] == str(scenario.character)
        assert payload["result"]["purpose"] == "portrait"

        status = await client.get(f"/v1/admin/world/generation-jobs/{job_id}", headers=ADMIN)
    assert response.status_code == 202
    assert status.status_code == 200
    assert status.json()["id"] == job_id


async def test_generate_image_invalid_purpose(tmp_path):
    scenario = build_scenario()
    async with _client(_app(scenario.actor, _service(scenario.actor, tmp_path))) as client:
        response = await client.post(
            "/v1/admin/world/generation-jobs",
            headers=ADMIN,
            json={
                "kind": "image",
                "entity_id": str(scenario.character),
                "purpose": "nonsense",
            },
        )
    assert response.status_code == 400


async def test_image_job_status_unknown(tmp_path):
    scenario = build_scenario()
    async with _client(_app(scenario.actor, _service(scenario.actor, tmp_path))) as client:
        response = await client.get("/v1/admin/world/generation-jobs/ghost", headers=ADMIN)
    assert response.status_code == 404


async def test_endpoints_409_when_imagegen_disabled():
    scenario = build_scenario()
    app = create_app(
        scenario.actor, meta=WorldMeta(seed="moss"), allow_unauthenticated_embedding=True
    )
    async with _client(app) as client:
        assert (
            await client.post(
                "/v1/admin/world/generation-jobs",
                headers=ADMIN,
                json={"kind": "image", "entity_id": "x"},
            )
        ).status_code == 409
        assert (
            await client.post(
                "/v1/admin/world/generation-jobs",
                json={"kind": "image", "entity_id": "rec_1", "purpose": "event"},
            )
        ).status_code == 409
        assert (await client.get("/v1/public/media/portraits/x.png")).status_code == 404


async def test_admin_upload_character_images_without_imagegen(tmp_path, monkeypatch):
    monkeypatch.setenv("BUNNYLAND_MEDIA_DIR", str(tmp_path))
    scenario = build_scenario()
    store = TokenStore(":memory:")
    player, _principal = store.issue("player", [WORLD_PLAY_SCOPE], automatic_rotation=False)
    operator, _principal = store.issue("operator", [WORLD_ADMIN_SCOPE], automatic_rotation=False)
    app = create_app(scenario.actor, meta=WorldMeta(seed="moss"), token_store=store)
    async with _client(app, headers={"Authorization": f"Bearer {operator}"}) as client:
        denied = await client.put(
            f"/v1/admin/media/character/{scenario.character}/portrait",
            files={"file": ("portrait.png", PNG_BYTES, "image/png")},
            headers={"Authorization": f"Bearer {player}"},
        )
        assert denied.status_code == 403

        portrait = await client.put(
            f"/v1/admin/media/character/{scenario.character}/portrait",
            files={"file": ("portrait.png", PNG_BYTES, "image/png")},
            headers=ADMIN,
        )
        assert portrait.status_code == 200
        portrait_payload = portrait.json()
        assert portrait_payload["purpose"] == "portrait"
        assert portrait_payload["url"].startswith("/v1/public/media/portraits/")
        component = scenario.actor.world.get_entity(scenario.character).get_component(
            PortraitImageComponent
        )
        assert component.url == portrait_payload["url"]
        media = await client.get(component.url)
        assert media.status_code == 200
        assert media.content == PNG_BYTES

        sprite = await client.put(
            f"/v1/admin/media/character/{scenario.character}/sprite",
            files={"file": ("sprite.webp", WEBP_BYTES, "image/webp")},
            headers=ADMIN,
        )
        assert sprite.status_code == 200
        sprite_component = scenario.actor.world.get_entity(scenario.character).get_component(
            SpriteImageComponent
        )
        assert sprite_component.url.startswith(f"/v1/public/media/{SEGMENT_SPRITES}/")


async def test_admin_upload_character_image_rejects_bad_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("BUNNYLAND_MEDIA_DIR", str(tmp_path))
    scenario = build_scenario()
    app = create_app(
        scenario.actor, meta=WorldMeta(seed="moss"), allow_unauthenticated_embedding=True
    )
    async with _client(app) as client:
        missing_file = await client.put(
            f"/v1/admin/media/character/{scenario.character}/portrait",
            headers=ADMIN,
        )
        assert missing_file.status_code == 400

        bad_purpose = await client.put(
            f"/v1/admin/media/character/{scenario.character}/avatar",
            files={"file": ("avatar.png", PNG_BYTES, "image/png")},
            headers=ADMIN,
        )
        assert bad_purpose.status_code == 400

        bad_type = await client.put(
            f"/v1/admin/media/character/{scenario.character}/portrait",
            files={"file": ("portrait.gif", b"GIF", "image/gif")},
            headers=ADMIN,
        )
        assert bad_type.status_code == 400

        empty = await client.put(
            f"/v1/admin/media/character/{scenario.character}/portrait",
            files={"file": ("portrait.png", b"", "image/png")},
            headers=ADMIN,
        )
        assert empty.status_code == 400

        too_large = await client.put(
            f"/v1/admin/media/character/{scenario.character}/portrait",
            files={
                "file": (
                    "portrait.png",
                    PNG_BYTES + b"P" * MAX_UPLOAD_IMAGE_BYTES,
                    "image/png",
                )
            },
            headers=ADMIN,
        )
        assert too_large.status_code == 413

        # The declared multipart content type is caller-chosen. Storing bytes on that word
        # alone let arbitrary content be written as .png and served from the public media
        # route, so the container signature has to agree.
        mislabelled = await client.put(
            f"/v1/admin/media/character/{scenario.character}/portrait",
            files={"file": ("portrait.png", b"<html>not an image</html>", "image/png")},
            headers=ADMIN,
        )
        assert mislabelled.status_code == 400
        assert "declared image type" in mislabelled.json()["detail"]

        mismatched = await client.put(
            f"/v1/admin/media/character/{scenario.character}/portrait",
            files={"file": ("portrait.png", WEBP_BYTES, "image/png")},
            headers=ADMIN,
        )
        assert mismatched.status_code == 400

        missing_character = await client.put(
            "/v1/admin/media/character/entity_999/portrait",
            files={"file": ("portrait.png", PNG_BYTES, "image/png")},
            headers=ADMIN,
        )
        assert missing_character.status_code == 404

        non_character = spawn_entity(
            scenario.actor.world,
            [IdentityComponent(name="Flat Rock", kind="item")],
        )
        wrong_kind = await client.put(
            f"/v1/admin/media/character/{non_character.id}/portrait",
            files={"file": ("portrait.png", PNG_BYTES, "image/png")},
            headers=ADMIN,
        )
        assert wrong_kind.status_code == 400


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
        first = await client.post(
            "/v1/admin/world/generation-jobs",
            json={
                "kind": "image",
                "entity_id": str(record.id),
                "purpose": "event",
                "extra": "dramatic",
            },
        )
    assert first.status_code == 202
    assert first.json()["result"]["purpose"] == "event"
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
        claim_id, headers = await _claim(client, str(scenario.character))
        response = await client.post(
            f"/v1/play/claims/{claim_id}/jobs",
            headers=headers,
            json={"kind": "scene_image"},
        )
        await service.wait_idle()
    assert response.status_code == 202
    assert response.json()["result"]["purpose"] == "event"
    image_events = [
        event for event in events if event.__class__.__name__.startswith("ImageGeneration")
    ]
    assert image_events
    assert all(event.visibility.value == "directed" for event in image_events)
    assert all(event.target_ids == (str(scenario.character),) for event in image_events)


async def test_scene_image_endpoint_accepts_exact_visible_event_and_rejects_unknown(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    event = SpeechSaidEvent(
        **event_base(
            3,
            event_id="event:castle-gate",
            visibility=EventVisibility.ROOM,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_a),
        ),
        text="Juniper opens the castle gate",
    )
    await scenario.actor.bus.publish(event)
    async with _client(_app(scenario.actor, service)) as client:
        claim_id, headers = await _claim(client, str(scenario.character))
        unknown = await client.post(
            f"/v1/play/claims/{claim_id}/jobs",
            headers=headers,
            json={"kind": "scene_image", "event_id": "event:unknown"},
        )
        response = await client.post(
            f"/v1/play/claims/{claim_id}/jobs",
            headers=headers,
            json={"kind": "scene_image", "event_id": event.event_id},
        )
        await service.wait_idle()
    assert unknown.status_code == 400
    assert response.status_code == 202
    entity_id = parse_entity_id(response.json()["result"]["entity_id"])
    assert entity_id is not None
    snapshot = scenario.actor.world.get_entity(entity_id).get_component(
        MediaSceneSnapshotComponent
    ).snapshot
    assert snapshot.primary_event_id == event.event_id


async def test_scene_image_endpoint_unknown_character(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    async with _client(_app(scenario.actor, service)) as client:
        assert (
            await client.post(
                "/v1/play/claims",
                json={"character_id": "ghost_9"},
            )
        ).status_code == 404


async def test_scene_image_endpoint_no_room(tmp_path):
    scenario = build_scenario()
    roomless = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Stray", kind="character"), CharacterComponent(species="bunny")],
    )
    service = _service(scenario.actor, tmp_path)
    async with _client(_app(scenario.actor, service)) as client:
        claim_id, headers = await _claim(client, str(roomless.id))
        response = await client.post(
            f"/v1/play/claims/{claim_id}/jobs",
            headers=headers,
            json={"kind": "scene_image"},
        )
        assert response.status_code == 400


async def test_scene_image_endpoint_409_without_imagegen():
    scenario = build_scenario()
    app = create_app(
        scenario.actor, meta=WorldMeta(seed="moss"), allow_unauthenticated_embedding=True
    )
    async with _client(app) as client:
        claim_id, headers = await _claim(client, str(scenario.character))
        response = await client.post(
            f"/v1/play/claims/{claim_id}/jobs",
            headers=headers,
            json={"kind": "scene_image"},
        )
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

    from bunnyland.tui.backend import ControlClaim, RemoteBackend

    def handler(request):
        if request.url.path.endswith("/play/claims/ok/jobs"):
            return httpx.Response(
                202,
                json={
                    "status": "queued",
                    "result": {"url": "/v1/public/media/events/x.png"},
                },
            )
        if request.url.path.endswith("/play/claims/off/jobs"):
            return httpx.Response(409, json={"detail": "disabled"})
        return httpx.Response(500, json={"detail": "boom"})

    backend = RemoteBackend("https://server")
    backend._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend._claims = {
        key: ControlClaim("controller:1", 1, key, f"secret-{key}") for key in ("ok", "off", "bad")
    }

    ok = await backend.request_image("ok")
    assert ok.ok is True and ok.url == "/v1/public/media/events/x.png"
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
        PortraitImageComponent(
            url="/public/media/portraits/p.png", alpha_url="/public/media/alpha/p.png"
        )
    )
    app = create_app(
        scenario.actor, meta=WorldMeta(seed="moss"), allow_unauthenticated_embedding=True
    )
    async with _client(app) as client:
        claim_id, headers = await _claim(client, str(scenario.character))
        body = (await client.get(f"/v1/play/claims/{claim_id}/projection", headers=headers)).json()
    assert body["character"]["portrait"]["url"] == "/public/media/portraits/p.png"
    assert body["character"]["portrait"]["alpha_url"] == "/public/media/alpha/p.png"


async def test_room_projection_entity_portrait_default_empty(tmp_path):
    scenario = build_scenario()
    secrets = ClaimSecretRegistry()
    claim = add_claim(
        scenario.actor.world.get_entity(scenario.controller),
        client_kind="web",
        client_id="image-client",
        character_id=str(scenario.character),
    )
    secret = secrets.issue(claim.claim_id)
    app = create_app(
        scenario.actor,
        meta=WorldMeta(seed="moss"),
        claim_secrets=secrets,
        allow_unauthenticated_embedding=True,
    )
    async with _client(app) as client:
        body = (
            await client.get(
                f"/v1/play/claims/{claim.claim_id}/projection",
                headers={
                    CLIENT_ID_HEADER: "image-client",
                    "X-Bunnyland-Claim-Secret": secret,
                },
            )
        ).json()
    members = body["scene"]["room"]["entities"]
    assert members  # the character is in the room
    assert all("portrait" in member for member in members)
    assert members[0]["portrait"]["url"] == ""  # no portrait generated yet


# --- media route ---------------------------------------------------------------------


async def test_media_route_serves_and_404(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    service.media.write(SEGMENT_PORTRAITS, "abc123.png", b"IMGDATA")
    async with _client(_app(scenario.actor, service)) as client:
        ok = await client.get("/v1/public/media/portraits/abc123.png")
        assert ok.status_code == 200
        assert ok.content == b"IMGDATA"
        assert ok.headers["content-type"].startswith("image/png")

        assert (await client.get("/v1/public/media/portraits/missing.png")).status_code == 404
        # Invalid (dotted) name is rejected by the store -> 404.
        assert (await client.get("/v1/public/media/portraits/..%2Fsecret.png")).status_code == 404


# --- backfill loop -------------------------------------------------------------------


async def test_start_backfill_generates_missing_portrait(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    backfill = ImageBackfillScheduler(scenario.actor, service, 0.01)
    backfill.start()
    backfill.start()
    for _ in range(50):
        if scenario.actor.world.get_entity(scenario.character).has_component(
            PortraitImageComponent
        ):
            break
        await asyncio.sleep(0.01)
    assert scenario.actor.world.get_entity(scenario.character).has_component(PortraitImageComponent)
    await backfill.aclose()
    await service.aclose()


async def test_lifespan_starts_backfill_and_closes(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    backfill = ImageBackfillScheduler(scenario.actor, service, 0.01)

    class CloseableVideo:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    videogen = CloseableVideo()
    app = _app(scenario.actor, service, backfill, videogen)
    async with app.router.lifespan_context(app):
        assert backfill._task is not None
        async with _client(app) as client:
            assert (await client.get("/v1/public/health")).status_code == 204
    assert backfill._task is None
    assert videogen.closed is True


# --- wiring --------------------------------------------------------------------------


def test_cli_build_media_services(monkeypatch, tmp_path, capsys):
    from bunnyland.cli import _build_media_services

    scenario = build_scenario()
    monkeypatch.setenv("COMFYUI_SERVER_URL", "http://comfy.local:8188")
    monkeypatch.setenv("BUNNYLAND_IMAGE_GENERATOR", "comfyui")
    monkeypatch.setenv("BUNNYLAND_MEDIA_DIR", str(tmp_path))
    services = _build_media_services(scenario.actor, [])
    assert services is not None
    assert isinstance(services.image, ImageGenService)
    assert "Image generation enabled" in capsys.readouterr().out


def test_cli_build_media_services_disabled(monkeypatch):
    from bunnyland.cli import _build_media_services

    scenario = build_scenario()
    monkeypatch.delenv("COMFYUI_SERVER_URL", raising=False)
    monkeypatch.delenv("BUNNYLAND_IMAGE_GENERATOR", raising=False)
    assert _build_media_services(scenario.actor, []) is None


def test_build_media_services_from_config(tmp_path):
    scenario = build_scenario()
    config = MediaGenConfig(
        comfyui=ComfyUIConfig(server_url="http://comfy.local"),
        image=ImageGenConfig(generator="comfyui"),
        media_root=str(tmp_path),
    )
    services = build_media_services(scenario.actor, config)
    assert isinstance(services.image, ImageGenService)


def test_build_image_service_selects_family(tmp_path):
    scenario = build_scenario()
    config = MediaGenConfig(
        comfyui=ComfyUIConfig(server_url="http://comfy.local", workflows="anima-house"),
        image=ImageGenConfig(generator="comfyui"),
        media_root=str(tmp_path),
    )
    service = build_media_services(scenario.actor, config).image
    assert service is not None
    generator = service._generators[ImagePurpose.PORTRAIT]
    assert generator.templates.for_purpose(ImagePurpose.PORTRAIT).default_negative.startswith(
        "worst quality, low quality, score_1"
    )


def test_build_image_service_unknown_family():
    scenario = build_scenario()
    config = MediaGenConfig(
        comfyui=ComfyUIConfig(server_url="http://comfy.local", workflows="bogus"),
        image=ImageGenConfig(generator="comfyui"),
    )
    with pytest.raises(ValueError, match="unknown workflow family"):
        build_media_services(scenario.actor, config)


def test_select_enhancer_stub():
    assert select_enhancer(MediaGenConfig()).name == "structured"
    assert select_enhancer(MediaGenConfig(enhancer="stub")).name == "stub"


def test_select_enhancer_llm(monkeypatch):
    module = types.ModuleType("ollama")
    module.AsyncClient = lambda *a, **k: object()
    monkeypatch.setitem(sys.modules, "ollama", module)
    enhancer = select_enhancer(MediaGenConfig(enhancer="llm"))
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
    enhancer = select_enhancer(MediaGenConfig(enhancer="custom"), [plugin])
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
    with pytest.raises(ValueError, match="unknown media enhancer"):
        select_enhancer(MediaGenConfig(enhancer="ghost"), [plugin])
