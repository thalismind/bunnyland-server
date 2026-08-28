from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from bunnyland.claims import (
    ClaimSecretRegistry,
    character_control_claim_rejection,
    claimable_characters,
    ensure_character_control_claim_allowed,
)
from bunnyland.core import (
    CharacterComponent,
    ControlledBy,
    IdentityComponent,
    LLMControllerComponent,
    WorldActor,
    spawn_entity,
)
from bunnyland.discord.claim import assign_discord_controller
from bunnyland.imagegen.service import ImageGenJob
from bunnyland.imagegen.spec import ImagePurpose
from bunnyland.imagegen.video_service import VideoGenJob
from bunnyland.mcp.server import assign_mcp_controller
from bunnyland.moderation import (
    IdentityKind,
    ModerationActionKind,
    ModerationIdentity,
    ModerationService,
    ModerationStore,
)
from bunnyland.persistence import WorldMeta
from bunnyland.plugins import (
    ContentContribution,
    HttpContribution,
    HttpZone,
    Plugin,
    PluginRuntimeContext,
    PolicyContribution,
    RuntimeContribution,
    apply_plugins,
)
from bunnyland.plugins.loader import PluginError
from bunnyland.plugins.registry import PluginRegistry
from bunnyland.server.addons import AddonMediaFacade, PlayWebSocketAuthenticator
from bunnyland.server.app import create_app
from bunnyland.server.auth import WORLD_PLAY_SCOPE, RequestAuthenticator, TokenStore
from bunnyland.worldgen import GenOptions, InstantiatedWorld, WorldGenerator


@dataclass(frozen=True)
class _ExclusiveGuard:
    id: str = "bunnyland.test.exclusive"

    def rejection_reason(self, actor, character) -> str | None:
        del actor
        identity = character.get_component(IdentityComponent)
        return "character has an exclusive influence claim" if identity.name == "Mira" else None


def _guarded_actor() -> tuple[WorldActor, object, object]:
    actor = WorldActor()
    character = spawn_entity(
        actor.world,
        [CharacterComponent(), IdentityComponent(name="Mira", kind="character")],
    )
    controller = spawn_entity(
        actor.world,
        [LLMControllerComponent(profile_name="traveler", model="local", provider="ollama")],
    )
    generation = actor.assign_controller(character.id, controller.id)
    assert generation == 0
    apply_plugins(
        [
            Plugin(
                id="bunnyland.test",
                name="Test Guard",
                policy=PolicyContribution(
                    character_control_claim_guards=(_ExclusiveGuard(),)
                ),
            )
        ],
        actor,
    )
    return actor, character, controller


def test_contributed_control_claim_guard_filters_and_rejects_without_controller_mutation():
    actor, character, controller = _guarded_actor()
    original_edges = character.get_relationships(ControlledBy)

    assert claimable_characters(actor, [character], allow_child_claims=True) == []
    with pytest.raises(RuntimeError, match="exclusive influence claim"):
        ensure_character_control_claim_allowed(actor, character)
    with pytest.raises(RuntimeError, match="exclusive influence claim"):
        assign_discord_controller(
            actor,
            discord_user_id=42,
            character_name="Mira",
        )
    with pytest.raises(RuntimeError, match="exclusive influence claim"):
        assign_mcp_controller(actor, client_id="mcp-test", character_name="Mira")

    assert character.get_relationships(ControlledBy) == original_edges
    assert original_edges[0][1] == controller.id


class _Socket:
    def __init__(
        self,
        token: str = "",
        *,
        authorization: str | None = None,
        cookie: str = "",
    ) -> None:
        selected = authorization if authorization is not None else (
            f"Bearer {token}" if token else ""
        )
        self.headers = {"Authorization": selected} if selected else {}
        self.cookies: dict[str, str] = {"bunnyland_token": cookie} if cookie else {}


def test_play_websocket_authenticator_reuses_scope_and_revocation_policy(tmp_path):
    actor = WorldActor()
    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    moderation_store = ModerationStore(tmp_path / "moderation.sqlite3")
    moderation = ModerationService(actor, moderation_store, ClaimSecretRegistry())
    token, principal = tokens.issue(
        "studio-owner",
        [WORLD_PLAY_SCOPE],
        automatic_rotation=False,
    )
    helper = PlayWebSocketAuthenticator(
        RequestAuthenticator(tokens),
        moderation,
        allowed_client_ids=frozenset({"studio-web"}),
    )

    session = helper.authenticate(
        _Socket(token),
        {"type": "authenticate", "data": {"client_id": "studio-web"}},
    )

    assert session.subject == principal.subject
    assert session.client_id == "studio-web"
    assert session.reauthorize()
    tokens.revoke_token(principal.token_id)
    assert not session.reauthorize()

    tokens.close()
    moderation_store.close()


def test_play_websocket_authenticator_requires_allowed_client_id(tmp_path):
    actor = WorldActor()
    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    moderation_store = ModerationStore(tmp_path / "moderation.sqlite3")
    helper = PlayWebSocketAuthenticator(
        RequestAuthenticator(tokens),
        ModerationService(actor, moderation_store, ClaimSecretRegistry()),
        allowed_client_ids=frozenset({"studio-web"}),
    )
    token, _principal = tokens.issue(
        "studio-owner",
        [WORLD_PLAY_SCOPE],
        automatic_rotation=False,
    )

    with pytest.raises(HTTPException, match="player client_id is not allowed"):
        helper.authenticate(
            _Socket(token),
            {"type": "authenticate", "data": {"client_id": "other-web"}},
        )

    tokens.close()
    moderation_store.close()


@pytest.mark.parametrize(
    ("frame", "detail"),
    [
        (None, "invalid authentication frame"),
        ({"type": "ready"}, "invalid authentication frame"),
        ({"type": "authenticate", "data": None}, "invalid authentication frame"),
        (
            {"type": "authenticate", "data": {"token": 42}},
            "invalid bearer token",
        ),
    ],
)
def test_play_websocket_authenticator_rejects_malformed_frames(tmp_path, frame, detail):
    actor = WorldActor()
    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    moderation_store = ModerationStore(tmp_path / "moderation.sqlite3")
    helper = PlayWebSocketAuthenticator(
        RequestAuthenticator(tokens),
        ModerationService(actor, moderation_store, ClaimSecretRegistry()),
    )

    with pytest.raises(HTTPException, match=detail):
        helper.authenticate(_Socket(), frame)

    tokens.close()
    moderation_store.close()


def test_play_websocket_authenticator_requires_configured_auth(tmp_path):
    actor = WorldActor()
    moderation_store = ModerationStore(tmp_path / "moderation.sqlite3")
    helper = PlayWebSocketAuthenticator(
        None,
        ModerationService(actor, moderation_store, ClaimSecretRegistry()),
    )

    with pytest.raises(HTTPException, match="authentication is not configured"):
        helper.authenticate(_Socket(), {"type": "authenticate", "data": {}})

    moderation_store.close()


@pytest.mark.parametrize("authorization", ["bad", "Basic token", "Bearer different"])
def test_play_websocket_authenticator_rejects_conflicting_frame_tokens(
    tmp_path, authorization
):
    actor = WorldActor()
    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    moderation_store = ModerationStore(tmp_path / "moderation.sqlite3")
    token, _principal = tokens.issue(
        "studio-owner", [WORLD_PLAY_SCOPE], automatic_rotation=False
    )
    helper = PlayWebSocketAuthenticator(
        RequestAuthenticator(tokens),
        ModerationService(actor, moderation_store, ClaimSecretRegistry()),
    )

    with pytest.raises(HTTPException, match="conflicting bearer credentials"):
        helper.authenticate(
            _Socket(authorization=authorization),
            {
                "type": "authenticate",
                "data": {"token": token, "client_id": "studio-web"},
            },
        )

    tokens.close()
    moderation_store.close()


def test_play_websocket_authenticator_accepts_frame_and_cookie_tokens(tmp_path):
    actor = WorldActor()
    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    moderation_store = ModerationStore(tmp_path / "moderation.sqlite3")
    moderation = ModerationService(actor, moderation_store, ClaimSecretRegistry())
    token, _principal = tokens.issue(
        "studio-owner", [WORLD_PLAY_SCOPE], automatic_rotation=False
    )
    helper = PlayWebSocketAuthenticator(RequestAuthenticator(tokens), moderation)

    framed = helper.authenticate(
        _Socket(),
        {
            "type": "authenticate",
            "data": {"token": token, "client_id": "studio-web"},
        },
    )
    cookied = helper.authenticate(
        _Socket(cookie=token),
        {"type": "authenticate", "data": {"client_id": "studio-web"}},
    )
    matching_header = helper.authenticate(
        _Socket(token),
        {
            "type": "authenticate",
            "data": {"token": token, "client_id": "studio-web"},
        },
    )

    assert framed.access_token == token
    assert cookied.access_token == token
    assert matching_header.access_token == token
    tokens.close()
    moderation_store.close()


@pytest.mark.parametrize("client_id", [None, 42, "   "])
def test_play_websocket_authenticator_requires_text_client_identity(tmp_path, client_id):
    actor = WorldActor()
    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    moderation_store = ModerationStore(tmp_path / "moderation.sqlite3")
    token, _principal = tokens.issue(
        "studio-owner", [WORLD_PLAY_SCOPE], automatic_rotation=False
    )
    helper = PlayWebSocketAuthenticator(
        RequestAuthenticator(tokens),
        ModerationService(actor, moderation_store, ClaimSecretRegistry()),
    )

    with pytest.raises(HTTPException, match="client identity is required"):
        helper.authenticate(
            _Socket(token),
            {"type": "authenticate", "data": {"client_id": client_id}},
        )

    tokens.close()
    moderation_store.close()


def test_play_websocket_session_rechecks_scope_subject_and_moderation(tmp_path):
    actor = WorldActor()
    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    moderation_store = ModerationStore(tmp_path / "moderation.sqlite3")
    moderation = ModerationService(actor, moderation_store, ClaimSecretRegistry())
    token, principal = tokens.issue(
        "studio-owner", [WORLD_PLAY_SCOPE], automatic_rotation=False
    )
    helper = PlayWebSocketAuthenticator(RequestAuthenticator(tokens), moderation)
    session = helper.authenticate(
        _Socket(token),
        {"type": "authenticate", "data": {"client_id": "studio-web"}},
    )

    class ChangedAuthenticator:
        def __init__(self, replacement):
            self.replacement = replacement

        def verify_token(self, access_token):
            assert access_token == token
            return self.replacement

    no_scope = replace(
        session,
        _authenticator=ChangedAuthenticator(replace(principal, scopes=frozenset())),
    )
    other_subject = replace(
        session,
        _authenticator=ChangedAuthenticator(replace(principal, subject="someone-else")),
    )
    assert not no_scope.reauthorize()
    assert not other_subject.reauthorize()

    moderation_store.apply(
        ModerationActionKind.BAN,
        ModerationIdentity(IdentityKind.WEB, "studio-owner"),
        ModerationIdentity(IdentityKind.WEB, "admin"),
        "test restriction",
        now=datetime.now(UTC),
    )
    assert not session.reauthorize()
    with pytest.raises(Exception, match="identity is banned"):
        helper.authenticate(
            _Socket(token),
            {"type": "authenticate", "data": {"client_id": "studio-web"}},
        )

    tokens.close()
    moderation_store.close()


def test_play_websocket_access_token_requires_a_credential():
    with pytest.raises(HTTPException, match="bearer token required"):
        PlayWebSocketAuthenticator._access_token(
            header_auth=None,
            cookie_token=None,
            frame_token=None,
        )


async def test_addon_media_facade_exposes_only_bounded_scene_jobs(monkeypatch):
    actor = WorldActor()
    unavailable = AddonMediaFacade(actor)
    assert not unavailable.image_available
    assert not unavailable.video_available
    with pytest.raises(RuntimeError, match="image generation is not configured"):
        await unavailable.request_character_scene_image("entity_1", requested_by="owner")
    with pytest.raises(RuntimeError, match="video generation is not configured"):
        await unavailable.request_character_scene_video("entity_1", requested_by="owner")

    image_job = ImageGenJob(
        job_id="image-job",
        entity_id="event_1",
        purpose=ImagePurpose.EVENT,
        status="queued",
        source_event_id="arrival",
        url="/media/image.png",
    )
    video_job = VideoGenJob(
        job_id="video-job",
        entity_id="event_2",
        status="failed",
        source_event_id="breakdown",
        error="offline",
    )

    async def image_request(actor_arg, service, **kwargs):
        assert actor_arg is actor
        assert service == "image-service"
        assert kwargs == {
            "character_id": "entity_1",
            "requested_by": "owner",
            "event_id": "arrival",
        }
        return image_job

    async def video_request(actor_arg, service, **kwargs):
        assert actor_arg is actor
        assert service == "video-service"
        assert kwargs["event_id"] == "breakdown"
        return video_job

    monkeypatch.setattr("bunnyland.server.addons.request_scene_image", image_request)
    monkeypatch.setattr("bunnyland.server.addons.request_scene_video", video_request)
    available = AddonMediaFacade(
        actor,
        image_service="image-service",
        video_service="video-service",
    )

    image = await available.request_character_scene_image(
        "entity_1", requested_by="owner", event_id="arrival"
    )
    video = await available.request_character_scene_video(
        "entity_1", requested_by="owner", event_id="breakdown"
    )

    assert available.image_available
    assert available.video_available
    assert image is not None and image.id == "image-job" and image.kind == "image"
    assert video is not None and video.error == "offline" and video.kind == "video"


async def test_addon_media_facade_preserves_empty_scene_result(monkeypatch):
    async def no_scene(*args, **kwargs):
        del args, kwargs
        return None

    monkeypatch.setattr("bunnyland.server.addons.request_scene_image", no_scene)
    facade = AddonMediaFacade(WorldActor(), image_service="image-service")

    assert (
        await facade.request_character_scene_image("missing", requested_by="owner") is None
    )


def test_control_claim_guard_rejects_invalid_contract_and_ignores_blank_reasons():
    actor = WorldActor()
    character = spawn_entity(
        actor.world,
        [CharacterComponent(), IdentityComponent(name="Other", kind="character")],
    )

    class InvalidGuard:
        id = "bunnyland.test.invalid"

    actor.plugins = PluginRegistry(
        [
            Plugin(
                id="bunnyland.test",
                name="Invalid Guard",
                policy=PolicyContribution(
                    character_control_claim_guards=(InvalidGuard(),)
                ),
            )
        ]
    )
    with pytest.raises(TypeError, match="public protocol"):
        character_control_claim_rejection(actor, character)

    @dataclass(frozen=True)
    class BlankGuard:
        id: str = "bunnyland.test.blank"

        def rejection_reason(self, actor_arg, character_arg):
            del actor_arg, character_arg
            return "   "

    actor.plugins = PluginRegistry(
        [
            Plugin(
                id="bunnyland.test",
                name="Blank Guard",
                policy=PolicyContribution(character_control_claim_guards=(BlankGuard(),)),
            )
        ]
    )
    assert character_control_claim_rejection(actor, character) is None


def test_control_claim_guard_ids_must_be_plugin_namespaced():
    with pytest.raises(PluginError, match="must be namespaced"):
        PluginRegistry(
            [
                Plugin(
                    id="bunnyland.test",
                    name="Wrong Namespace",
                    policy=PolicyContribution(
                        character_control_claim_guards=(
                            _ExclusiveGuard(id="someone.else.guard"),
                        )
                    ),
                )
            ]
        )


def test_web_claim_guard_returns_addon_rejection_without_mutation():
    actor, character, controller = _guarded_actor()
    plugin = actor.plugins.plugin("bunnyland.test")
    app = create_app(
        actor,
        plugins=[plugin],
        allow_unauthenticated_embedding=True,
    )
    client = pytest.importorskip("fastapi.testclient").TestClient(
        app,
        headers={"X-Bunnyland-Client-Id": "web-test"},
    )

    response = client.post(
        "/v1/play/claims",
        json={"character_id": str(character.id), "delivery": "header"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "character has an exclusive influence claim"
    assert character.get_relationships(ControlledBy)[0][1] == controller.id


def test_admin_generation_forwards_typed_generator_config():
    captured: dict[str, object] = {}

    async def generate(actor: WorldActor, seed: str, options: GenOptions) -> InstantiatedWorld:
        del actor, seed
        captured.update(options.generator_config)
        return InstantiatedWorld()

    plugin = Plugin(
        id="bunnyland.generator-test",
        name="Generator Test",
        content=ContentContribution(
            world_generators=(
                WorldGenerator(name="config-capture", generate=generate),
            )
        ),
    )
    actor = WorldActor()
    app = create_app(
        actor,
        plugins=[plugin],
        allow_unauthenticated_embedding=True,
    )
    client = pytest.importorskip("fastapi.testclient").TestClient(
        app,
        headers={"X-Bunnyland-Client-Id": "generator-test"},
    )

    response = client.post(
        "/v1/admin/world/generation-jobs",
        json={
            "kind": "world",
            "confirm_reset": True,
            "generator": "config-capture",
            "generator_config": {
                "origin": {"osm_id": 123, "name": "Chicago"},
                "waypoints": ["Milwaukee", "Madison"],
            },
        },
    )

    assert response.status_code == 202
    assert captured == {
        "origin": {"osm_id": 123, "name": "Chicago"},
        "waypoints": ["Milwaukee", "Madison"],
    }


def test_http_registrar_receives_narrow_addon_runtime_capabilities():
    captured: dict[str, object] = {}

    def registrar(router, actor, *, addon_media, play_websocket_auth, **context) -> None:
        del router, actor, context
        captured["media"] = addon_media
        captured["websocket"] = play_websocket_auth

    plugin = Plugin(
        id="bunnyland.runtime-test",
        name="Runtime Test",
        runtime=RuntimeContribution(
            http=(
                HttpContribution(zone=HttpZone.PLAY, registrars=(registrar,)),
            )
        ),
    )
    actor = WorldActor()
    context = PluginRuntimeContext()
    actor.configure_persistence(
        save_path=None,
        meta=WorldMeta(),
        plugins=(plugin,),
        plugin_context=context,
    )

    create_app(
        actor,
        plugins=[plugin],
        allow_unauthenticated_embedding=True,
    )

    assert isinstance(captured["media"], AddonMediaFacade)
    assert isinstance(captured["websocket"], PlayWebSocketAuthenticator)
    assert context.addon_media is captured["media"]
    assert context.play_websocket_auth is captured["websocket"]
