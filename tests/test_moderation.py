from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from conftest import build_scenario

from bunnyland.claims import ClaimOwner, ClaimSecretRegistry, add_claim, current_controller
from bunnyland.cli import main as cli_main
from bunnyland.core import (
    LLMControllerComponent,
    RoomComponent,
    WebControllerComponent,
    spawn_entity,
)
from bunnyland.core.claim_timeout import apply_claim_timeout_settings
from bunnyland.core.controllers import ClaimedComponent
from bunnyland.discord.bot import (
    DiscordBot,
    parse_moderation_duration,
    parse_moderation_target,
)
from bunnyland.moderation import (
    IdentityKind,
    ModerationActionKind,
    ModerationConnectionRegistry,
    ModerationIdentity,
    ModerationRestrictedError,
    ModerationService,
    ModerationStore,
    RestrictionKind,
    _utc_timestamp,
)
from bunnyland.server.app import create_app
from bunnyland.server.auth import (
    WORLD_ADMIN_SCOPE,
    WORLD_PLAY_SCOPE,
    TokenStore,
    UserCredential,
    UserCredentialStore,
    hash_password,
)
from bunnyland.server.client_ids import CLIENT_ID_HEADER
from bunnyland.server.jobs import JobRegistry
from bunnyland.server.models import CharacterChatResponse
from bunnyland.server.v1_models import ChatJobRequest, JobResource, ModerationActionRequest


def test_moderation_store_persists_expires_lifts_and_audits(tmp_path) -> None:
    path = tmp_path / "security.sqlite3"
    target = ModerationIdentity(IdentityKind.WEB, "player")
    administrator = ModerationIdentity(IdentityKind.WEB, "operator")
    now = datetime(2026, 8, 1, tzinfo=UTC)
    store = ModerationStore(path)

    suspension = store.apply(
        ModerationActionKind.SUSPEND,
        target,
        administrator,
        "cool down",
        duration_seconds=60,
        now=now,
    )
    assert suspension.expires_at == now + timedelta(seconds=60)
    assert store.restriction(target, now=now).kind is RestrictionKind.SUSPENDED
    assert store.restriction(target, now=now + timedelta(seconds=60)) is None
    store.apply(ModerationActionKind.BAN, target, administrator, "repeat abuse", now=now)
    concurrent = ModerationStore(path)
    assert concurrent.restriction(target, now=now) is not None
    assert len(concurrent.history(target=target)) == 2
    concurrent.close()
    store.close()
    store._lock_permissions()

    reopened = ModerationStore(path)
    restriction = reopened.restriction(target, now=now)
    assert restriction is not None
    assert restriction.kind is RestrictionKind.BANNED
    assert restriction.expires_at is None
    reopened.apply(ModerationActionKind.LIFT, target, administrator, "appeal accepted", now=now)
    assert reopened.restriction(target, now=now) is None
    assert [entry.action for entry in reopened.history(target=target)] == [
        ModerationActionKind.LIFT,
        ModerationActionKind.BAN,
        ModerationActionKind.SUSPEND,
    ]


def test_token_and_moderation_repositories_share_one_database(tmp_path) -> None:
    path = tmp_path / "security.sqlite3"
    tokens = TokenStore(path)
    moderation = ModerationStore(path)
    token, _principal = tokens.issue("player", (WORLD_PLAY_SCOPE,), automatic_rotation=False)
    target = ModerationIdentity(IdentityKind.WEB, "player")
    moderation.apply(
        ModerationActionKind.BAN,
        target,
        ModerationIdentity(IdentityKind.WEB, "operator"),
        "abuse",
    )
    moderation.close()
    tokens.close()

    reopened_tokens = TokenStore(path)
    reopened_moderation = ModerationStore(path)
    assert reopened_tokens.verify(token) is not None
    assert reopened_moderation.restriction(target) is not None
    reopened_moderation.close()
    reopened_tokens.close()


@pytest.mark.parametrize("duration", [0, -1])
def test_moderation_store_rejects_non_positive_suspension(duration: int) -> None:
    store = ModerationStore(":memory:")
    with pytest.raises(ValueError, match="must be positive"):
        store.apply(
            ModerationActionKind.SUSPEND,
            ModerationIdentity(IdentityKind.CLIENT, "player"),
            ModerationIdentity(IdentityKind.WEB, "operator"),
            "reason",
            duration_seconds=duration,
        )


def test_moderation_store_validates_identity_action_and_timestamp_boundaries() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        ModerationIdentity(IdentityKind.WEB, " ")
    with pytest.raises(ValueError, match="decimal snowflake"):
        ModerationIdentity(IdentityKind.DISCORD, "not-a-number")
    with pytest.raises(ValueError, match="must include"):
        ModerationIdentity.parse("missing-prefix")
    with pytest.raises(ValueError, match="target kind"):
        ModerationIdentity.parse("unknown:value")
    with pytest.raises(ValueError, match="timezone-aware"):
        _utc_timestamp(datetime(2026, 1, 1))

    store = ModerationStore(":memory:")
    target = ModerationIdentity(IdentityKind.CLIENT, "player")
    actor = ModerationIdentity(IdentityKind.WEB, "operator")
    with pytest.raises(ValueError, match="reason is required"):
        store.apply(ModerationActionKind.KICK, target, actor, " ")
    with pytest.raises(ValueError, match="required for suspension"):
        store.apply(ModerationActionKind.SUSPEND, target, actor, "reason")
    with pytest.raises(ValueError, match="only valid"):
        store.apply(
            ModerationActionKind.BAN,
            target,
            actor,
            "reason",
            duration_seconds=1,
        )
    with pytest.raises(ValueError, match="valid UTC expiration"):
        store.suspension_expiration(10**30)
    assert store.history() == []
    assert store.known_identities() == set()


def test_moderation_store_filters_and_bounds_history() -> None:
    store = ModerationStore(":memory:")
    target = ModerationIdentity(IdentityKind.CLIENT, "player")
    other = ModerationIdentity(IdentityKind.CLIENT, "other")
    actor = ModerationIdentity(IdentityKind.WEB, "operator")
    store.apply(ModerationActionKind.KICK, target, actor, "one")
    store.apply(ModerationActionKind.BAN, target, actor, "two")
    store.apply(ModerationActionKind.KICK, other, actor, "three")

    assert [entry.reason for entry in store.history(action=ModerationActionKind.KICK)] == [
        "three",
        "one",
    ]
    assert [entry.reason for entry in store.history(target=target, limit=1)] == ["two"]
    assert len(store.history(limit=10_000)) == 3


def test_moderation_service_releases_all_claims_revokes_secrets_tokens_and_falls_back() -> None:
    scenario = build_scenario()
    registry = ClaimSecretRegistry()
    token_store = TokenStore(":memory:")
    target = ModerationIdentity(IdentityKind.WEB, "player")
    administrator = ModerationIdentity(IdentityKind.WEB, "operator")
    controllers = []
    characters = [scenario.actor.world.get_entity(scenario.character)]
    for index in range(2):
        controller = spawn_entity(
            scenario.actor.world,
            [WebControllerComponent(client_id=f"browser-{index}", label="web")],
        )
        claim = add_claim(
            controller,
            client_kind="web",
            client_id=f"browser-{index}",
            character_id=str(scenario.character),
        )
        registry.issue(claim.claim_id, ClaimOwner("rest", target.id))
        apply_claim_timeout_settings(
            controller,
            now_unix=1,
            fallback_controller="suspend",
        )
        controllers.append((controller, claim))
    scenario.actor.assign_controller(scenario.character, controllers[0][0].id)
    token, _principal = token_store.issue(
        target.id,
        (WORLD_PLAY_SCOPE,),
        automatic_rotation=False,
    )
    service = ModerationService(
        scenario.actor,
        ModerationStore(":memory:"),
        registry,
        token_store=token_store,
    )

    asyncio.run(
        service.execute(
            ModerationActionKind.KICK,
            target,
            administrator,
            "session reset",
        )
    )

    assert all(not controller.has_component(ClaimedComponent) for controller, _ in controllers)
    assert all(not registry.has_secret(claim.claim_id) for _, claim in controllers)
    assert token_store.verify(token) is None
    active = current_controller(scenario.actor, characters[0])
    assert active is not None
    assert scenario.actor._controller_kind(active[0].id) == "suspended"
    assert service.store.restriction(target) is None


def test_moderation_service_rejects_self_target_and_enforces_restriction() -> None:
    scenario = build_scenario()
    identity = ModerationIdentity(IdentityKind.WEB, "operator")
    service = ModerationService(
        scenario.actor,
        ModerationStore(":memory:"),
        ClaimSecretRegistry(),
    )
    with pytest.raises(PermissionError, match="own identity"):
        asyncio.run(service.execute(ModerationActionKind.BAN, identity, identity, "bad idea"))
    target = ModerationIdentity(IdentityKind.DISCORD, "123")
    asyncio.run(service.execute(ModerationActionKind.BAN, target, identity, "abuse"))
    with pytest.raises(ModerationRestrictedError):
        service.require_allowed(target)


class _FakeSocket:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.closed: list[tuple[int, str | None]] = []

    async def close(self, *, code: int, reason: str | None = None) -> None:
        self.closed.append((code, reason))
        if self.fail:
            raise RuntimeError("socket already closed")


def test_moderation_connections_close_all_and_discard_safely() -> None:
    registry = ModerationConnectionRegistry()
    identity = ModerationIdentity(IdentityKind.WEB, "player")
    first = _FakeSocket()
    second = _FakeSocket(fail=True)
    registry.discard(identity, first)
    registry.add(identity, first)
    registry.add(identity, second)
    registry.discard(identity, first)
    registry.add(identity, first)
    asyncio.run(registry.close_identity(identity, "x" * 200))
    assert first.closed == [(1008, "x" * 123)]
    assert second.closed == [(1008, "x" * 123)]
    asyncio.run(registry.close_identity(identity, "again"))


def test_moderation_service_identity_mapping_fallbacks_and_callbacks() -> None:
    scenario = build_scenario()
    registry = ClaimSecretRegistry()
    store = ModerationStore(":memory:")
    cancelled: list[ModerationIdentity] = []

    async def cancel(identity: ModerationIdentity) -> None:
        cancelled.append(identity)

    service = ModerationService(scenario.actor, store, registry)
    service.configure_runtime()
    service.configure_runtime(token_store=object(), cancel_identity=cancel)

    claims = [
        ("discord", "123", ClaimOwner("discord", "123")),
        ("web", "browser", ClaimOwner("rest", "web-player")),
        ("web", "embed-player", ClaimOwner("rest", "embedded:embed-player")),
        ("web", "anonymous", None),
    ]
    controllers = []
    for kind, client_id, owner in claims:
        controller = spawn_entity(
            scenario.actor.world,
            [WebControllerComponent(client_id=client_id, label=kind)],
        )
        claim = add_claim(
            controller,
            client_kind=kind,
            client_id=client_id,
            character_id="missing-character",
        )
        if owner is not None:
            registry.issue(claim.claim_id, owner)
        controllers.append(controller)

    assert service.known_claim_identities() == {
        ModerationIdentity(IdentityKind.DISCORD, "123"),
        ModerationIdentity(IdentityKind.WEB, "web-player"),
        ModerationIdentity(IdentityKind.CLIENT, "embed-player"),
        ModerationIdentity(IdentityKind.CLIENT, "anonymous"),
    }
    assert len(service.claims_for(ModerationIdentity(IdentityKind.DISCORD, "123"))) == 1
    assert len(service.claims_for(ModerationIdentity(IdentityKind.CLIENT, "anonymous"))) == 1
    assert len(service.claims_for(ModerationIdentity(IdentityKind.CLIENT, "embed-player"))) == 1

    asyncio.run(
        service.execute(
            ModerationActionKind.KICK,
            ModerationIdentity(IdentityKind.CLIENT, "anonymous"),
            ModerationIdentity(IdentityKind.WEB, "operator"),
            "reset",
        )
    )
    asyncio.run(
        service.execute(
            ModerationActionKind.KICK,
            ModerationIdentity(IdentityKind.WEB, "web-player"),
            ModerationIdentity(IdentityKind.WEB, "operator"),
            "reset",
        )
    )
    assert cancelled == [
        ModerationIdentity(IdentityKind.CLIENT, "anonymous"),
        ModerationIdentity(IdentityKind.WEB, "web-player"),
    ]


def test_moderation_service_uses_existing_and_llm_fallbacks() -> None:
    scenario = build_scenario()
    registry = ClaimSecretRegistry()
    service = ModerationService(scenario.actor, ModerationStore(":memory:"), registry)
    character = scenario.actor.world.get_entity(scenario.character)
    existing_fallback = spawn_entity(
        scenario.actor.world,
        [LLMControllerComponent(profile_name="existing", model="model")],
    )

    for index, fallback in enumerate((str(existing_fallback.id), "llm")):
        controller = spawn_entity(
            scenario.actor.world,
            [WebControllerComponent(client_id=f"client-{index}", label="web")],
        )
        claim = add_claim(
            controller,
            client_kind="web",
            client_id=f"client-{index}",
            character_id=str(character.id),
        )
        owner = ModerationIdentity(IdentityKind.WEB, f"player-{index}")
        registry.issue(claim.claim_id, ClaimOwner("rest", owner.id))
        if fallback == "llm":
            apply_claim_timeout_settings(
                controller,
                now_unix=1,
                fallback_controller="llm",
                llm_profile_name="fallback-profile",
                llm_model="fallback-model",
                llm_provider="openrouter",
            )
        else:
            apply_claim_timeout_settings(controller, now_unix=1, fallback_controller=fallback)
        scenario.actor.assign_controller(character.id, controller.id)
        asyncio.run(
            service.execute(
                ModerationActionKind.KICK,
                owner,
                ModerationIdentity(IdentityKind.WEB, "operator"),
                "reset",
            )
        )
        active = current_controller(scenario.actor, character)
        assert active is not None
        if index == 0:
            assert active[0].id == existing_fallback.id
        else:
            llm = active[0].get_component(LLMControllerComponent)
            assert (llm.profile_name, llm.model, llm.provider) == (
                "fallback-profile",
                "fallback-model",
                "openrouter",
            )

    non_character = spawn_entity(scenario.actor.world, [RoomComponent(title="room")])
    detached = spawn_entity(
        scenario.actor.world,
        [WebControllerComponent(client_id="detached", label="web")],
    )
    claim = add_claim(
        detached,
        client_kind="web",
        client_id="detached",
        character_id=str(non_character.id),
    )
    registry.issue(claim.claim_id, ClaimOwner("rest", "detached"))
    asyncio.run(
        service.execute(
            ModerationActionKind.KICK,
            ModerationIdentity(IdentityKind.WEB, "detached"),
            ModerationIdentity(IdentityKind.WEB, "operator"),
            "reset",
        )
    )


def test_job_registry_discards_matching_owner_and_attributes() -> None:
    registry = JobRegistry()
    now = datetime.now(UTC)
    first = JobResource(
        world_id="world",
        world_epoch=1,
        id="one",
        kind="chat",
        status="queued",
        created_at=now,
        updated_at=now,
    )
    second = first.model_copy(update={"id": "two"})
    registry.put(first, owner="client", attributes={"subject": "player"})
    registry.put(second, owner="other", attributes={"subject": "player"})
    assert registry.discard_matching(owner="client", attributes={"subject": "other"}) == set()
    assert registry.discard_matching(attributes={"subject": "player"}) == {"one", "two"}


def test_moderation_request_duration_contract() -> None:
    target = {"kind": "web", "id": "player"}
    with pytest.raises(ValueError, match="positive"):
        ModerationActionRequest(action="suspend", target=target, reason="reason")
    with pytest.raises(ValueError, match="only valid"):
        ModerationActionRequest(action="kick", target=target, reason="reason", duration_seconds=1)


def test_moderation_api_contract_and_restricted_existing_token() -> None:
    scenario = build_scenario()
    token_store = TokenStore(":memory:")
    admin_token, _admin = token_store.issue(
        "operator",
        (WORLD_ADMIN_SCOPE,),
        automatic_rotation=False,
    )
    player_token, _player = token_store.issue(
        "player",
        (WORLD_PLAY_SCOPE,),
        automatic_rotation=False,
    )
    moderation_store = ModerationStore(":memory:")
    app = create_app(
        scenario.actor,
        token_store=token_store,
        moderation_store=moderation_store,
    )
    admin_headers = {
        "Authorization": f"Bearer {admin_token}",
        CLIENT_ID_HEADER: "admin-browser",
    }
    player_headers = {
        "Authorization": f"Bearer {player_token}",
        CLIENT_ID_HEADER: "player-browser",
    }

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            created = await client.post(
                "/v1/admin/moderation/actions",
                headers=admin_headers,
                json={
                    "action": "ban",
                    "target": {"kind": "web", "id": "player"},
                    "reason": "abuse",
                },
            )
            assert created.status_code == 201, created.text
            listed = await client.get("/v1/admin/moderation/players", headers=admin_headers)
            assert listed.status_code == 200
            assert any(
                item["identity"] == {"kind": "web", "id": "player"}
                and item["restriction"]["kind"] == "banned"
                for item in listed.json()["players"]
            )
            history = await client.get(
                "/v1/admin/moderation/actions?target_kind=web&target_id=player",
                headers=admin_headers,
            )
            assert [item["action"] for item in history.json()["actions"]] == ["ban"]
            restricted = await client.get("/v1/play/characters", headers=player_headers)
            assert restricted.status_code == 403
            assert restricted.json()["code"] == "account_banned"
            assert restricted.json()["restriction_reason"] == "abuse"
            public = await client.get("/v1/public/world")
            assert public.status_code == 200
            openapi = await client.get("/v1/admin/openapi.json", headers=admin_headers)
            schemas = openapi.json()["components"]["schemas"]
            assert "ModerationActionRequest" in schemas
            assert "ModerationPlayerCollection" in schemas

    asyncio.run(exercise())


def test_moderation_api_lists_claims_admins_filters_and_validation(tmp_path) -> None:
    scenario = build_scenario()
    token_store = TokenStore(":memory:")
    admin_token, _admin = token_store.issue(
        "operator", (WORLD_ADMIN_SCOPE,), automatic_rotation=False
    )

    class Credentials:
        def current_users(self) -> tuple[UserCredential, ...]:
            return (
                UserCredential(
                    username="operator",
                    password_hash="not-read-for-automation-token",
                    enabled=True,
                    scopes=frozenset({WORLD_ADMIN_SCOPE, WORLD_PLAY_SCOPE}),
                ),
                UserCredential(
                    username="ordinary-player",
                    password_hash="not-read-for-automation-token",
                    enabled=True,
                    scopes=frozenset({WORLD_PLAY_SCOPE}),
                ),
            )

        def current_user(self, _username: str) -> None:
            return None

    registry = ClaimSecretRegistry()
    controller = spawn_entity(
        scenario.actor.world,
        [WebControllerComponent(client_id="browser", label="web")],
    )
    claim = add_claim(
        controller,
        client_kind="web",
        client_id="browser",
        character_id=str(scenario.character),
    )
    registry.issue(claim.claim_id, ClaimOwner("rest", "claimed-player"))
    missing_controller = spawn_entity(
        scenario.actor.world,
        [WebControllerComponent(client_id="missing", label="web")],
    )
    missing_claim = add_claim(
        missing_controller,
        client_kind="web",
        client_id="missing",
        character_id="missing-character",
    )
    registry.issue(missing_claim.claim_id, ClaimOwner("rest", "missing-player"))
    room = spawn_entity(scenario.actor.world, [RoomComponent(title="not a character")])
    room_controller = spawn_entity(
        scenario.actor.world,
        [WebControllerComponent(client_id="room", label="web")],
    )
    room_claim = add_claim(
        room_controller,
        client_kind="web",
        client_id="room",
        character_id=str(room.id),
    )
    registry.issue(room_claim.claim_id, ClaimOwner("rest", "room-player"))
    scenario.actor.assign_controller(scenario.character, controller.id)
    moderation_store = ModerationStore(tmp_path / "security.sqlite3")
    app = create_app(
        scenario.actor,
        token_store=token_store,
        user_credentials=Credentials(),
        moderation_store=moderation_store,
        claim_secrets=registry,
    )
    headers = {
        "Authorization": f"Bearer {admin_token}",
        CLIENT_ID_HEADER: "admin-browser",
    }

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            listed = await client.get(
                "/v1/admin/moderation/players?search=claimed", headers=headers
            )
            [player] = listed.json()["players"]
            assert player["claims"][0]["character_name"] == "Juniper"
            by_character = await client.get(
                "/v1/admin/moderation/players?search=juniper", headers=headers
            )
            assert by_character.json()["players"][0]["identity"] == {
                "kind": "web",
                "id": "claimed-player",
            }
            admins = await client.get(
                "/v1/admin/moderation/players?search=operator", headers=headers
            )
            assert admins.json()["players"][0]["admin"] is True
            ordinary = await client.get(
                "/v1/admin/moderation/players?search=ordinary", headers=headers
            )
            assert ordinary.json()["players"][0]["admin"] is False
            for query in ("missing-player", "room-player"):
                response = await client.get(
                    f"/v1/admin/moderation/players?search={query}", headers=headers
                )
                assert response.json()["players"][0]["claims"][0]["character_name"] == ""
            assert (
                await client.get("/v1/admin/moderation/actions", headers=headers)
            ).status_code == 200
            assert (
                await client.get(
                    "/v1/admin/moderation/actions?action=kick", headers=headers
                )
            ).status_code == 200
            partial = await client.get(
                "/v1/admin/moderation/actions?target_kind=web", headers=headers
            )
            assert partial.status_code == 422
            self_target = await client.post(
                "/v1/admin/moderation/actions",
                headers=headers,
                json={
                    "action": "ban",
                    "target": {"kind": "web", "id": "operator"},
                    "reason": "self",
                },
            )
            assert self_target.status_code == 409
            assert self_target.json()["code"] == "moderation_self_target"
            invalid_duration = await client.post(
                "/v1/admin/moderation/actions",
                headers=headers,
                json={
                    "action": "suspend",
                    "target": {"kind": "client", "id": "large"},
                    "reason": "invalid",
                    "duration_seconds": 10**30,
                },
            )
            assert invalid_duration.status_code == 422
            invalid_discord = await client.post(
                "/v1/admin/moderation/actions",
                headers=headers,
                json={
                    "action": "ban",
                    "target": {"kind": "discord", "id": "not-a-snowflake"},
                    "reason": "invalid identity",
                },
            )
            assert invalid_discord.status_code == 422
            for kind, identity_id in (("client", "embed"), ("discord", "987")):
                response = await client.post(
                    "/v1/admin/moderation/actions",
                    headers=headers,
                    json={
                        "action": "kick",
                        "target": {"kind": kind, "id": identity_id},
                        "reason": "reset",
                    },
                )
                assert response.status_code == 201

    asyncio.run(exercise())


def test_moderation_action_cancels_target_owned_chat_job() -> None:
    scenario = build_scenario()
    llm = spawn_entity(
        scenario.actor.world,
        [LLMControllerComponent(profile_name="idle", model="model")],
    )
    scenario.actor.assign_controller(scenario.character, llm.id)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class BlockingChat:
        allowed_tools: tuple[str, ...] = ()

        async def chat(self, character_id: str, request) -> CharacterChatResponse:
            if request.message == "complete":
                return CharacterChatResponse(
                    world_epoch=scenario.actor.epoch,
                    character_id=character_id,
                    reply="done",
                )
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()
            raise AssertionError("unreachable")

    token_store = TokenStore(":memory:")
    admin_token, _admin = token_store.issue(
        "operator", (WORLD_ADMIN_SCOPE,), automatic_rotation=False
    )
    player_token, _player = token_store.issue(
        "player", (WORLD_PLAY_SCOPE,), automatic_rotation=False
    )
    completed_token, _completed = token_store.issue(
        "completed-player", (WORLD_PLAY_SCOPE,), automatic_rotation=False
    )
    app = create_app(
        scenario.actor,
        token_store=token_store,
        character_chat=BlockingChat(),
    )
    admin_headers = {
        "Authorization": f"Bearer {admin_token}",
        CLIENT_ID_HEADER: "admin-browser",
    }
    player_headers = {
        "Authorization": f"Bearer {player_token}",
        CLIENT_ID_HEADER: "player-browser",
    }
    completed_headers = {
        "Authorization": f"Bearer {completed_token}",
        CLIENT_ID_HEADER: "completed-browser",
    }

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            submitted = await client.post(
                f"/v1/chat/characters/{scenario.character}/jobs",
                headers=player_headers,
                json=ChatJobRequest(kind="chat", message="hello").model_dump(mode="json"),
            )
            assert submitted.status_code == 202, submitted.text
            await asyncio.wait_for(started.wait(), timeout=1)
            kicked = await client.post(
                "/v1/admin/moderation/actions",
                headers=admin_headers,
                json={
                    "action": "kick",
                    "target": {"kind": "web", "id": "player"},
                    "reason": "reset",
                },
            )
            assert kicked.status_code == 201, kicked.text
            await asyncio.wait_for(cancelled.wait(), timeout=1)
            completed = await client.post(
                f"/v1/chat/characters/{scenario.character}/jobs",
                headers=completed_headers,
                json=ChatJobRequest(kind="chat", message="complete").model_dump(mode="json"),
            )
            assert completed.status_code == 202, completed.text
            location = completed.headers["Location"]
            for _attempt in range(20):
                fetched = await client.get(location, headers=completed_headers)
                if fetched.json()["status"] == "succeeded":
                    break
                await asyncio.sleep(0)
            assert fetched.json()["status"] == "succeeded"
            kicked_completed = await client.post(
                "/v1/admin/moderation/actions",
                headers=admin_headers,
                json={
                    "action": "kick",
                    "target": {"kind": "web", "id": "completed-player"},
                    "reason": "clear completed work",
                },
            )
            assert kicked_completed.status_code == 201, kicked_completed.text

    asyncio.run(exercise())


def test_login_restriction_problem_and_token_subject_lookup(tmp_path) -> None:
    users_path = tmp_path / "users.yml"
    users_path.write_text(
        "users:\n"
        "  player:\n"
        f"    password_hash: {hash_password('secret')}\n"
        "    scopes: [world:play]\n"
    )
    credentials = UserCredentialStore(users_path)
    credentials.validate()
    tokens = TokenStore(":memory:")
    moderation = ModerationStore(":memory:")
    moderation.apply(
        ModerationActionKind.SUSPEND,
        ModerationIdentity(IdentityKind.WEB, "player"),
        ModerationIdentity(IdentityKind.WEB, "operator"),
        "cool down",
        duration_seconds=60,
    )
    app = create_app(
        build_scenario().actor,
        token_store=tokens,
        user_credentials=credentials,
        moderation_store=moderation,
    )

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/v1/auth/session",
                json={"username": "player", "password": "secret", "delivery": "body"},
            )
            assert response.status_code == 403
            assert response.json()["code"] == "account_suspended"

    asyncio.run(exercise())
    assert credentials.current_users()[0].username == "player"
    assert tokens.subject_for_credential("not-a-token") is None
    assert tokens.subject_for_credential("blt_0000000000000000_" + "a" * 32) is None


def test_embedded_client_restriction_blocks_private_but_not_public_routes() -> None:
    scenario = build_scenario()
    moderation = ModerationStore(":memory:")
    moderation.apply(
        ModerationActionKind.BAN,
        ModerationIdentity(IdentityKind.CLIENT, "embed"),
        ModerationIdentity(IdentityKind.WEB, "operator"),
        "abuse",
    )
    app = create_app(
        scenario.actor,
        allow_unauthenticated_embedding=True,
        moderation_store=moderation,
    )

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            blocked = await client.get("/v1/play/characters", headers={CLIENT_ID_HEADER: "embed"})
            assert blocked.status_code == 403
            assert blocked.json()["code"] == "account_banned"
            assert (await client.get("/v1/public/world")).status_code == 200

    asyncio.run(exercise())

    admin_app = create_app(
        build_scenario().actor,
        allow_unauthenticated_embedding=True,
        admin_client_ids=["embed-admin"],
    )

    async def exercise_embedded_admin() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=admin_app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/v1/admin/moderation/actions",
                headers={CLIENT_ID_HEADER: "embed-admin"},
                json={
                    "action": "kick",
                    "target": {"kind": "client", "id": "other-client"},
                    "reason": "reset",
                },
            )
            assert response.status_code == 201, response.text
            assert response.json()["administrator"] == {
                "kind": "client",
                "id": "embed-admin",
            }
            listed = await client.get(
                "/v1/admin/moderation/players",
                headers={CLIENT_ID_HEADER: "embed-admin"},
            )
            assert listed.status_code == 200

    asyncio.run(exercise_embedded_admin())


def test_cli_moderation_lift_is_audited(tmp_path, capsys) -> None:
    path = tmp_path / "security.sqlite3"
    store = ModerationStore(path)
    target = ModerationIdentity(IdentityKind.WEB, "operator")
    store.apply(
        ModerationActionKind.BAN,
        target,
        ModerationIdentity(IdentityKind.WEB, "other"),
        "mistake",
    )
    store.close()
    assert (
        cli_main(
            [
                "moderation",
                "lift",
                "--db",
                str(path),
                "--target",
                target.canonical,
                "--reason",
                "recovery",
            ]
        )
        == 0
    )
    assert '"lifted": "web:operator"' in capsys.readouterr().out
    reopened = ModerationStore(path)
    assert reopened.restriction(target) is None

    with pytest.raises(SystemExit):
        cli_main(
            [
                "moderation",
                "lift",
                "--db",
                str(path),
                "--target",
                "bad-target",
                "--reason",
                "recovery",
            ]
        )


def test_discord_moderation_target_and_duration_parsing() -> None:
    assert parse_moderation_target("<@!123>").canonical == "discord:123"
    assert parse_moderation_target("456").canonical == "discord:456"
    assert parse_moderation_target("web:alice").canonical == "web:alice"
    assert parse_moderation_target("client:embed-a").canonical == "client:embed-a"
    assert [parse_moderation_duration(value) for value in ("30s", "15m", "2h", "7d", "4w")] == [
        30,
        900,
        7200,
        604800,
        2419200,
    ]
    with pytest.raises(ValueError, match="duration"):
        parse_moderation_duration("forever")


class _ModerationDiscordContext:
    def __init__(self, *, user_id: int, role_ids: tuple[int, ...] = (), dm: bool = False):
        self.author = SimpleNamespace(
            id=user_id,
            roles=[SimpleNamespace(id=role_id) for role_id in role_ids],
        )
        self.guild = None if dm else SimpleNamespace(id=999)
        self.message = SimpleNamespace(guild=self.guild)
        self.channel = SimpleNamespace(id=456)
        self.replies: list[str] = []

    async def reply(self, body: str, *, mention_author: bool = False) -> None:
        del mention_author
        self.replies.append(body)


def _moderation_discord_bot(service: ModerationService) -> DiscordBot:
    bot = object.__new__(DiscordBot)
    bot.moderation_service = service
    bot.moderator_user_ids = frozenset({10})
    bot.moderator_role_ids = frozenset({20})
    return bot


def test_discord_moderation_authorizes_users_roles_and_dm_before_target_parsing() -> None:
    scenario = build_scenario()
    service = ModerationService(
        scenario.actor,
        ModerationStore(":memory:"),
        ClaimSecretRegistry(),
    )
    bot = _moderation_discord_bot(service)
    unauthorized = _ModerationDiscordContext(user_id=30, role_ids=(30,))
    asyncio.run(bot._handle_moderation_command(unauthorized, "ban not-a-target reason"))
    assert unauthorized.replies == ["You are not authorized to moderate Bunnyland players."]

    role_moderator = _ModerationDiscordContext(user_id=11, role_ids=(20,))
    asyncio.run(bot._handle_moderation_command(role_moderator, "ban <@123> spam"))
    assert (
        service.store.restriction(ModerationIdentity(IdentityKind.DISCORD, "123")).kind
        is RestrictionKind.BANNED
    )

    dm_role_only = _ModerationDiscordContext(user_id=11, role_ids=(20,), dm=True)
    asyncio.run(bot._handle_moderation_command(dm_role_only, "lift <@123> appeal"))
    assert dm_role_only.replies == ["You are not authorized to moderate Bunnyland players."]

    dm_user = _ModerationDiscordContext(user_id=10, dm=True)
    asyncio.run(bot._handle_moderation_command(dm_user, "lift discord:123 appeal"))
    assert service.store.restriction(ModerationIdentity(IdentityKind.DISCORD, "123")) is None


def test_discord_moderation_command_validation_status_and_history() -> None:
    scenario = build_scenario()
    service = ModerationService(
        scenario.actor,
        ModerationStore(":memory:"),
        ClaimSecretRegistry(),
    )
    bot = _moderation_discord_bot(service)
    ctx = _ModerationDiscordContext(user_id=10)

    async def command(text: str) -> str:
        ctx.replies.clear()
        await bot._handle_moderation_command(ctx, text)
        return ctx.replies[-1]

    async def exercise() -> None:
        missing_service = object.__new__(DiscordBot)
        assert await reply_from(missing_service, "ban discord:1 reason") == (
            "Moderation is not configured."
        )
        assert "Usage:" in await command("")
        assert "must include" in await command("ban invalid reason")
        assert "own identity" in await command("ban discord:10 reason")
        assert "Usage:" in await command("status discord:1 extra")
        assert await command("status discord:1") == "discord:1 is not restricted."
        assert "Usage:" in await command("history discord:1 extra")
        assert await command("history discord:1") == "No moderation history for discord:1."
        assert "must be kick" in await command("freeze discord:1 reason")
        assert "Usage:" in await command("suspend discord:1")
        assert "duration must use" in await command("suspend discord:1 tomorrow reason")
        assert "reason is required" in await command("kick discord:1")
        assert "Suspend applied" in await command("suspend discord:1 30s cool-down")
        assert "suspended until" in await command("status discord:1")
        assert "cool-down" in await command("history discord:1")
        assert "Ban applied" in await command("ban web:player abuse")
        assert "banned permanently" in await command("status web:player")

    async def reply_from(target_bot: DiscordBot, text: str) -> str:
        ctx.replies.clear()
        await target_bot._handle_moderation_command(ctx, text)
        return ctx.replies[-1]

    asyncio.run(exercise())


def test_discord_moderation_reports_service_errors_and_blocks_restricted_commands() -> None:
    scenario = build_scenario()
    service = ModerationService(
        scenario.actor,
        ModerationStore(":memory:"),
        ClaimSecretRegistry(),
    )
    bot = _moderation_discord_bot(service)
    bot.actor = scenario.actor
    bot.command_cooldown = SimpleNamespace(check=lambda _user_id: 0)
    ctx = _ModerationDiscordContext(user_id=10)

    original_execute = service.execute

    async def fail(*_args, **_kwargs):
        raise PermissionError("service refused")

    service.execute = fail
    asyncio.run(bot._handle_moderation_command(ctx, "kick discord:1 reason"))
    assert ctx.replies[-1] == "service refused"
    service.execute = original_execute

    asyncio.run(bot.handle_text_command(ctx, "mod status discord:1"))
    assert ctx.replies[-1] == "discord:1 is not restricted."
    service.store.apply(
        ModerationActionKind.BAN,
        ModerationIdentity(IdentityKind.DISCORD, "10"),
        ModerationIdentity(IdentityKind.WEB, "operator"),
        "abuse",
    )
    asyncio.run(bot.handle_text_command(ctx, "look"))
    assert "Your Bunnyland account is banned" in ctx.replies[-1]


def test_discord_bot_closes_owned_moderation_store() -> None:
    class Client:
        async def close(self) -> None:
            return None

    scenario = build_scenario()
    store = ModerationStore(":memory:")
    closed: list[bool] = []
    original_close = store.close

    def close() -> None:
        closed.append(True)
        original_close()

    store.close = close
    bot = object.__new__(DiscordBot)
    bot.actor = scenario.actor
    bot.imagegen = None
    bot.client = Client()
    bot.moderation_service = ModerationService(scenario.actor, store, ClaimSecretRegistry())
    bot._close_moderation_store = True
    asyncio.run(bot.close())
    assert closed == [True]
