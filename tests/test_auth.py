from __future__ import annotations

import hashlib
import sqlite3
import threading
import time

import httpx
import pytest
import yaml
from conftest import build_scenario
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials, SecurityScopes
from starlette.requests import Request

from bunnyland.server.app import create_app
from bunnyland.server.auth import (
    HUMAN_ROTATE_AFTER_SECONDS,
    ROTATION_GRACE_SECONDS,
    WORLD_ADMIN_SCOPE,
    WORLD_PLAY_SCOPE,
    RequestAuthenticator,
    TokenStore,
    UserCredentialStore,
    hash_password,
)


def test_token_store_uses_digests_and_persists_revocation(tmp_path) -> None:
    path = tmp_path / "tokens.sqlite3"
    store = TokenStore(path)
    token, principal = store.issue(
        "agent-one", [WORLD_PLAY_SCOPE], automatic_rotation=False, now=100
    )

    assert token.startswith(f"blt_{principal.token_id}_")
    assert path.stat().st_mode & 0o777 == 0o600
    assert store.verify(token, now=101) == principal
    assert store.verify(f"{token}wrong", now=101) is None
    assert token not in path.read_bytes().decode("utf-8", errors="ignore")
    metadata = store.list_metadata()
    assert metadata[0]["token_id"] == principal.token_id
    assert "digest" not in metadata[0]
    store.close()

    reopened = TokenStore(path)
    assert reopened.verify(token, now=101) == principal
    assert reopened.revoke_token(principal.token_id, now=102)
    assert reopened.verify(token, now=102) is None
    reopened.close()


def test_token_store_imports_pre_generated_digest_idempotently(tmp_path) -> None:
    token = "blt_0123456789abcdef_operator_secret_0123456789abcdef"
    digest = hashlib.sha256(token.encode()).hexdigest()
    store = TokenStore(tmp_path / "tokens.sqlite3")

    assert store.import_digest(
        "0123456789abcdef",
        digest,
        "automation",
        [WORLD_ADMIN_SCOPE],
        expires_at=2_000_000_000,
        created_at=1_900_000_000,
    )
    assert not store.import_digest(
        "0123456789abcdef",
        digest,
        "automation",
        [WORLD_ADMIN_SCOPE],
        expires_at=2_000_000_000,
    )
    assert store.verify(token, now=1_950_000_000).scopes == {
        WORLD_PLAY_SCOPE,
        WORLD_ADMIN_SCOPE,
    }
    store.close()


def test_human_rotation_grace_and_manual_rotation_policy(tmp_path) -> None:
    store = TokenStore(tmp_path / "tokens.sqlite3")
    token, principal = store.issue(
        "player",
        [WORLD_PLAY_SCOPE],
        automatic_rotation=True,
        now=100,
    )
    with pytest.raises(ValueError, match="not eligible"):
        store.rotate(token, now=principal.rotate_after - 1)

    replacement, replacement_principal = store.rotate(token, now=principal.rotate_after)
    assert replacement_principal.family_id == principal.family_id
    assert store.verify(token, now=principal.rotate_after + ROTATION_GRACE_SECONDS - 1)
    assert store.verify(token, now=principal.rotate_after + ROTATION_GRACE_SECONDS) is None
    assert store.verify(replacement, now=principal.rotate_after + ROTATION_GRACE_SECONDS)

    manual, _manual_principal = store.issue(
        "automation", [WORLD_ADMIN_SCOPE], automatic_rotation=False, now=100
    )
    with pytest.raises(PermissionError, match="manual rotation"):
        store.rotate(manual, now=100 + HUMAN_ROTATE_AFTER_SECONDS)
    store.close()


def test_human_rotation_rejects_expired_and_revoked_sources(tmp_path) -> None:
    store = TokenStore(tmp_path / "tokens.sqlite3")
    unknown = f"blt_{'0' * 16}_{'x' * 32}"
    with pytest.raises(PermissionError, match="invalid token"):
        store.rotate(unknown, now=100)

    valid, valid_principal = store.issue(
        "digest", [WORLD_PLAY_SCOPE], automatic_rotation=True, now=100
    )
    mismatched = f"blt_{valid_principal.token_id}_{'x' * 32}"
    assert mismatched != valid
    with pytest.raises(PermissionError, match="invalid token"):
        store.rotate(mismatched, now=valid_principal.rotate_after)

    expired, _ = store.issue(
        "expired",
        [WORLD_PLAY_SCOPE],
        automatic_rotation=True,
        lifetime_seconds=1,
        now=100,
    )
    with pytest.raises(PermissionError, match="invalid token"):
        store.rotate(expired, now=101)

    revoked, principal = store.issue(
        "revoked", [WORLD_PLAY_SCOPE], automatic_rotation=True, now=100
    )
    assert store.revoke_token(revoked, now=101)
    with pytest.raises(PermissionError, match="invalid token"):
        store.rotate(revoked, now=principal.rotate_after)
    assert len(store.list_metadata()) == 3
    store.close()


def test_human_rotation_is_atomic_across_connections(tmp_path) -> None:
    path = tmp_path / "tokens.sqlite3"
    issuer = TokenStore(path)
    token, principal = issuer.issue(
        "player", [WORLD_PLAY_SCOPE], automatic_rotation=True, now=100
    )
    issuer.close()
    stores = (TokenStore(path), TokenStore(path))
    barrier = threading.Barrier(2)
    results: list[tuple[str, object]] = []

    def rotate(store: TokenStore) -> None:
        barrier.wait()
        try:
            results.append(("ok", store.rotate(token, now=principal.rotate_after)))
        except Exception as exc:  # noqa: BLE001 - the result type is the assertion target
            results.append(("error", exc))

    threads = [threading.Thread(target=rotate, args=(store,)) for store in stores]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [kind for kind, _value in results].count("ok") == 1
    errors = [value for kind, value in results if kind == "error"]
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert str(errors[0]) == "token has already been rotated"
    metadata = stores[0].list_metadata()
    assert len(metadata) == 2
    assert sum(row["replaced_by"] is None for row in metadata) == 1
    replacement = next(value[0] for kind, value in results if kind == "ok")
    assert stores[0].verify(token, now=principal.rotate_after + ROTATION_GRACE_SECONDS - 1)
    assert stores[0].verify(
        token, now=principal.rotate_after + ROTATION_GRACE_SECONDS
    ) is None
    for store in stores:
        store.close()
    reopened = TokenStore(path)
    assert reopened.verify(replacement, now=principal.rotate_after + ROTATION_GRACE_SECONDS)
    assert len(reopened.list_metadata()) == 2
    reopened.close()


def test_expired_and_digest_mismatched_tokens_are_rejected(tmp_path) -> None:
    path = tmp_path / "tokens.sqlite3"
    store = TokenStore(path)
    token, principal = store.issue(
        "short", [WORLD_PLAY_SCOPE], automatic_rotation=False, lifetime_seconds=1, now=100
    )
    assert store.verify(token, now=101) is None
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE auth_tokens SET digest = ? WHERE token_id = ?",
            ("0" * 64, principal.token_id),
        )
    assert store.verify(token, now=100) is None
    assert store.verify("not-a-token", now=100) is None
    store.close()


def test_token_operator_lifecycle_and_rejection_paths(tmp_path) -> None:
    store = TokenStore(tmp_path / "tokens.sqlite3")
    with pytest.raises(ValueError, match="token id"):
        store.import_digest("bad", "0" * 64, "x", [], expires_at=200)
    with pytest.raises(ValueError, match="digest"):
        store.import_digest("0" * 16, "bad", "x", [], expires_at=200)
    with pytest.raises(PermissionError, match="invalid"):
        store.rotate("not-a-token", now=100)

    token, principal = store.issue("robot", [WORLD_PLAY_SCOPE], automatic_rotation=False, now=100)
    replacement, replacement_principal = store.replace(principal.token_id, now=101)
    assert store.verify(token, now=101) is None
    assert store.verify(replacement, now=101) == replacement_principal
    assert store.revoke_subject("robot", now=102) == 1
    assert store.revoke_subject("missing", now=102) == 0
    with pytest.raises(KeyError):
        store.replace("missing", now=103)

    human, human_principal = store.issue(
        "human", [WORLD_PLAY_SCOPE], automatic_rotation=True, now=100
    )
    store.rotate(human, now=human_principal.rotate_after)
    with pytest.raises(ValueError, match="already"):
        store.rotate(human, now=human_principal.rotate_after)
    store.close()


def test_user_store_tolerates_bad_inventory_and_hashes(tmp_path, monkeypatch) -> None:
    missing = UserCredentialStore(tmp_path / "missing.yml")
    assert missing.authenticate("x", "y") is None
    path = tmp_path / "users.yml"
    path.write_text("users: nope\n")
    assert UserCredentialStore(path).authenticate("x", "y") is None
    path.write_text("users:\n  ignored: nope\n  valid:\n    password_hash: bad\n    scopes: nope\n")
    assert UserCredentialStore(path).authenticate("valid", "y") is None
    path.write_text("users:\n  - nope\n  - username: ''\n    password_hash: bad\n")
    assert UserCredentialStore(path).authenticate("", "y") is None

    monkeypatch.setitem(__import__("sys").modules, "pwdlib", None)
    path.write_text("users:\n  user:\n    password_hash: bad\n")
    with pytest.raises(RuntimeError, match="pwdlib"):
        UserCredentialStore(path).authenticate("user", "y")


def _request(headers: list[tuple[bytes, bytes]] = ()) -> Request:
    return Request({"type": "http", "headers": headers, "method": "GET", "path": "/"})


async def test_request_authenticator_dependency_and_cached_principal() -> None:
    store = TokenStore(":memory:")
    token, principal = store.issue("player", [WORLD_PLAY_SCOPE], automatic_rotation=False)
    auth = RequestAuthenticator(store)
    with pytest.raises(HTTPException) as malformed:
        auth.authenticate_values(authorization="Basic nope", cookie_token=None)
    assert malformed.value.status_code == 401

    request = _request([(b"authorization", f"Bearer {token}".encode())])
    assert auth.authenticate_request(request, required_scopes=(WORLD_PLAY_SCOPE,)) == principal
    assert auth.authenticate_request(request) == principal
    with pytest.raises(HTTPException) as missing_scope:
        auth.authenticate_request(request, required_scopes=(WORLD_ADMIN_SCOPE,))
    assert missing_scope.value.status_code == 403

    fresh = _request([(b"authorization", f"Bearer {token}".encode())])
    assert await auth(
        SecurityScopes([WORLD_PLAY_SCOPE]),
        fresh,
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
        None,
    ) == principal
    assert await auth(SecurityScopes(), fresh, None, None) == principal
    with pytest.raises(HTTPException):
        await auth(SecurityScopes([WORLD_ADMIN_SCOPE]), fresh, None, None)
    store.close()


def _credentials(tmp_path, *, enabled: bool = True) -> UserCredentialStore:
    path = tmp_path / "users.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "users": [
                    {
                        "username": "player",
                        "password_hash": hash_password("correct horse"),
                        "enabled": enabled,
                        "scopes": [WORLD_PLAY_SCOPE],
                    },
                    {
                        "username": "admin",
                        "password_hash": hash_password("admin horse"),
                        "enabled": True,
                        "scopes": [WORLD_ADMIN_SCOPE],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return UserCredentialStore(path)


@pytest.mark.asyncio
async def test_http_login_cookie_header_conflicts_and_scope_boundaries(tmp_path) -> None:
    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    app = create_app(
        build_scenario().actor,
        token_store=tokens,
        user_credentials=_credentials(tmp_path),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        missing = await client.get("/world/characters")
        assert missing.status_code == 401
        assert missing.headers["www-authenticate"] == "Bearer"
        assert (await client.get("/world/schema")).status_code == 200

        login = await client.post(
            "/auth/login",
            json={"username": "player", "password": "correct horse", "delivery": "cookie"},
        )
        assert login.status_code == 200
        assert login.json()["token"] is None
        assert "Secure" in login.headers["set-cookie"]
        assert "HttpOnly" in login.headers["set-cookie"]
        assert "SameSite=strict" in login.headers["set-cookie"]
        assert (await client.get("/world/characters")).status_code == 200
        assert (await client.get("/world/snapshot")).status_code == 403

        body_login = await client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin horse", "delivery": "body"},
        )
        operator_token = body_login.json()["token"]
        assert operator_token.startswith("blt_")
        assert (
            await client.get(
                "/world/snapshot",
                headers={"Authorization": f"Bearer {operator_token}"},
                cookies={},
            )
        ).status_code == 401

        client.cookies.clear()
        assert (
            await client.get(
                "/world/snapshot", headers={"Authorization": f"Bearer {operator_token}"}
            )
        ).status_code == 200

    tokens.close()


@pytest.mark.asyncio
async def test_login_rotation_logout_and_rate_limit(tmp_path) -> None:
    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    app = create_app(
        build_scenario().actor,
        token_store=tokens,
        user_credentials=_credentials(tmp_path),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        for _ in range(5):
            response = await client.post(
                "/auth/login",
                json={"username": "missing", "password": "wrong", "delivery": "body"},
            )
            assert response.status_code == 401
        limited = await client.post(
            "/auth/login",
            json={"username": "missing", "password": "wrong", "delivery": "body"},
        )
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) >= 1

        now = int(time.time())
        old_token, _principal = tokens.issue(
            "player",
            [WORLD_PLAY_SCOPE],
            automatic_rotation=True,
            now=now - HUMAN_ROTATE_AFTER_SECONDS,
        )
        rotated = await client.post(
            "/auth/rotate", headers={"Authorization": f"Bearer {old_token}"}
        )
        assert rotated.status_code == 200, rotated.text
        replacement = rotated.json()["token"]
        assert replacement.startswith("blt_")
        assert tokens.verify(old_token, now=now + ROTATION_GRACE_SECONDS - 1)
        assert tokens.verify(old_token, now=now + ROTATION_GRACE_SECONDS) is None

        logged_out = await client.post(
            "/auth/logout", headers={"Authorization": f"Bearer {replacement}"}
        )
        assert logged_out.status_code == 200
        assert tokens.verify(replacement) is None
    tokens.close()


@pytest.mark.asyncio
async def test_auth_metadata_rotation_delivery_and_failure_rate_limit(tmp_path) -> None:
    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    app = create_app(
        build_scenario().actor,
        token_store=tokens,
        user_credentials=_credentials(tmp_path),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        manual, _ = tokens.issue("robot", [WORLD_PLAY_SCOPE], automatic_rotation=False)
        me = await client.get("/auth/me", headers={"Authorization": f"Bearer {manual}"})
        assert me.status_code == 200
        assert me.json()["subject"] == "robot"
        refused = await client.post(
            "/auth/rotate", headers={"Authorization": f"Bearer {manual}"}
        )
        assert refused.status_code == 403

        early, _ = tokens.issue("player", [WORLD_PLAY_SCOPE], automatic_rotation=True)
        too_early = await client.post(
            "/auth/rotate", headers={"Authorization": f"Bearer {early}"}
        )
        assert too_early.status_code == 409

        eligible, _ = tokens.issue(
            "player",
            [WORLD_PLAY_SCOPE],
            automatic_rotation=True,
            now=int(time.time()) - HUMAN_ROTATE_AFTER_SECONDS,
        )
        client.cookies.set("bunnyland_token", eligible)
        rotated = await client.post("/auth/rotate")
        assert rotated.status_code == 200
        assert rotated.json()["token"] is None
        assert "bunnyland_token=" in rotated.headers["set-cookie"]
        client.cookies.clear()

        for _ in range(20):
            invalid = await client.get(
                "/world/characters", headers={"Authorization": "Bearer invalid"}
            )
            assert invalid.status_code == 401
        limited = await client.get(
            "/world/characters", headers={"Authorization": "Bearer invalid"}
        )
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) >= 1
    tokens.close()


@pytest.mark.asyncio
async def test_login_limits_ip_spraying_and_distributed_username_attempts(tmp_path) -> None:
    class RejectingCredentials:
        def authenticate(self, username: str, password: str):
            del username, password
            return None

    async def login(client, username: str, address: str):
        return await client.post(
            "/auth/login",
            headers={"X-Real-IP": address},
            json={"username": username, "password": "wrong", "delivery": "body"},
        )

    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    app = create_app(
        build_scenario().actor,
        token_store=tokens,
        user_credentials=RejectingCredentials(),
        trust_x_real_ip=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        for index in range(5):
            assert (await login(client, f"missing-{index}", "192.0.2.10")).status_code == 401
        assert (await login(client, "another-user", "192.0.2.10")).status_code == 429
    tokens.close()

    tokens = TokenStore(tmp_path / "distributed.sqlite3")
    app = create_app(
        build_scenario().actor,
        token_store=tokens,
        user_credentials=RejectingCredentials(),
        trust_x_real_ip=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        for index in range(5):
            username = " TARGET " if index % 2 else "target"
            assert (await login(client, username, f"192.0.2.{index + 20}")).status_code == 401
        assert (await login(client, "Target", "192.0.2.30")).status_code == 429
    tokens.close()


@pytest.mark.asyncio
async def test_proxy_trust_and_token_failure_buckets_use_resolved_ip(tmp_path) -> None:
    class RejectingCredentials:
        def authenticate(self, username: str, password: str):
            del username, password
            return None

    tokens = TokenStore(tmp_path / "untrusted.sqlite3")
    untrusted = create_app(
        build_scenario().actor,
        token_store=tokens,
        user_credentials=RejectingCredentials(),
        trust_x_real_ip=False,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=untrusted, client=("198.51.100.5", 1234)),
        base_url="https://testserver",
    ) as client:
        for index in range(5):
            response = await client.post(
                "/auth/login",
                headers={"X-Real-IP": f"192.0.2.{index}"},
                json={"username": f"user-{index}", "password": "wrong"},
            )
            assert response.status_code == 401
        limited = await client.post(
            "/auth/login",
            headers={"X-Real-IP": "192.0.2.100"},
            json={"username": "user-6", "password": "wrong"},
        )
        assert limited.status_code == 429
    tokens.close()

    tokens = TokenStore(tmp_path / "trusted.sqlite3")
    trusted = create_app(
        build_scenario().actor,
        token_store=tokens,
        user_credentials=RejectingCredentials(),
        trust_x_real_ip=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=trusted), base_url="https://testserver"
    ) as client:
        for _ in range(20):
            response = await client.get(
                "/world/characters",
                headers={"Authorization": "Bearer invalid", "X-Real-IP": "192.0.2.40"},
            )
            assert response.status_code == 401
        assert (
            await client.get(
                "/world/characters",
                headers={"Authorization": "Bearer invalid", "X-Real-IP": "192.0.2.40"},
            )
        ).status_code == 429
        assert (
            await client.get(
                "/world/characters",
                headers={"Authorization": "Bearer invalid", "X-Real-IP": "192.0.2.41"},
            )
        ).status_code == 401
        assert (
            await client.get(
                "/world/characters",
                headers={"Authorization": "Bearer invalid", "X-Real-IP": "not-an-ip"},
            )
        ).status_code == 401
    tokens.close()


@pytest.mark.asyncio
async def test_auth_cors_never_allows_cross_origin_credentials(tmp_path) -> None:
    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    app = create_app(
        build_scenario().actor,
        token_store=tokens,
        user_credentials=_credentials(tmp_path),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        preflight = await client.options(
            "/world/characters",
            headers={
                "Origin": "https://other.example",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in preflight.headers
    tokens.close()


@pytest.mark.asyncio
async def test_auth_routes_reject_when_authentication_is_not_configured() -> None:
    app = create_app(build_scenario().actor)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        assert (await client.get("/auth/me")).status_code == 503
        assert (await client.get("/world/characters")).status_code == 503
        assert (await client.get("/world/snapshot")).status_code == 503
        assert (await client.get("/world/schema")).status_code == 200
        login = await client.post(
            "/auth/login",
            json={"username": "player", "password": "password", "delivery": "body"},
        )
        assert login.status_code == 401


def test_disabled_user_cannot_authenticate(tmp_path) -> None:
    credentials = _credentials(tmp_path, enabled=False)
    assert credentials.authenticate("player", "correct horse") is None
    assert credentials.authenticate("missing", "correct horse") is None


def test_websockets_authenticate_in_first_frame_with_scopes(tmp_path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    websocket_error = pytest.importorskip("starlette.websockets").WebSocketDisconnect
    scenario = build_scenario()
    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    player_token, _ = tokens.issue(
        "player", [WORLD_PLAY_SCOPE], automatic_rotation=False
    )
    operator_token, _ = tokens.issue(
        "admin", [WORLD_ADMIN_SCOPE], automatic_rotation=False
    )
    expired_token, _ = tokens.issue(
        "expired", [WORLD_PLAY_SCOPE], automatic_rotation=False, lifetime_seconds=1, now=1
    )
    app = create_app(
        scenario.actor,
        token_store=tokens,
        user_credentials=_credentials(tmp_path),
    )
    client = testclient.TestClient(app)

    character_path = f"/world/character/{scenario.character}/updates"
    with client.websocket_connect(character_path) as socket:
        socket.send_json(
            {
                "type": "authenticate",
                "data": {"token": player_token, "claim_id": None, "claim_secret": None},
            }
        )
        assert socket.receive_json()["type"] == "ready"

    with client.websocket_connect(character_path) as socket:
        socket.send_json(
            {
                "type": "authenticate",
                "data": {"token": expired_token, "claim_id": None, "claim_secret": None},
            }
        )
        with pytest.raises(websocket_error) as rejected:
            socket.receive_json()
        assert rejected.value.code == 1008

    with client.websocket_connect("/world/updates") as socket:
        socket.send_json({"type": "authenticate", "data": {"token": player_token}})
        with pytest.raises(websocket_error) as rejected:
            socket.receive_json()
        assert rejected.value.code == 1008

    with client.websocket_connect("/world/updates") as socket:
        socket.send_json({"type": "authenticate", "data": {"token": operator_token}})
        assert socket.receive_json()["type"] == "snapshot"

    tokens.close()


def test_websocket_authentication_rejection_and_header_paths(tmp_path, monkeypatch) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    websocket_error = pytest.importorskip("starlette.websockets").WebSocketDisconnect
    scenario = build_scenario()
    tokens = TokenStore(tmp_path / "tokens.sqlite3")
    player_token, _ = tokens.issue("player", [WORLD_PLAY_SCOPE], automatic_rotation=False)
    operator_token, _ = tokens.issue(
        "admin", [WORLD_ADMIN_SCOPE], automatic_rotation=False
    )
    other_admin, _ = tokens.issue("other", [WORLD_ADMIN_SCOPE], automatic_rotation=False)
    app = create_app(
        scenario.actor,
        token_store=tokens,
        user_credentials=_credentials(tmp_path),
    )
    client = testclient.TestClient(app)

    for frame in (
        {"type": "wrong", "data": {}},
        {"type": "authenticate", "data": {"token": 42}},
    ):
        with client.websocket_connect("/world/updates") as socket:
            socket.send_json(frame)
            with pytest.raises(websocket_error) as rejected:
                socket.receive_json()
            assert rejected.value.code == 1008

    with client.websocket_connect(
        "/world/updates", headers={"Authorization": f"Bearer {operator_token}"}
    ) as socket:
        socket.send_json({"type": "authenticate", "data": {"token": other_admin}})
        with pytest.raises(websocket_error):
            socket.receive_json()

    with client.websocket_connect(
        "/world/updates", headers={"Authorization": f"Bearer {operator_token}"}
    ) as socket:
        socket.send_json({"type": "authenticate", "data": {}})
        assert socket.receive_json()["type"] == "snapshot"

    character_path = f"/world/character/{scenario.character}/updates"
    with client.websocket_connect(character_path) as socket:
        socket.send_json(
            {
                "type": "authenticate",
                "data": {"token": 42, "claim_id": None, "claim_secret": None},
            }
        )
        with pytest.raises(websocket_error):
            socket.receive_json()
    with client.websocket_connect(
        character_path, headers={"Authorization": f"Bearer {player_token}"}
    ) as socket:
        socket.send_json(
            {
                "type": "authenticate",
                "data": {
                    "token": operator_token,
                    "claim_id": None,
                    "claim_secret": None,
                },
            }
        )
        with pytest.raises(websocket_error):
            socket.receive_json()
    with client.websocket_connect(
        character_path, headers={"Authorization": f"Bearer {player_token}"}
    ) as socket:
        socket.send_json(
            {
                "type": "authenticate",
                "data": {"claim_id": None, "claim_secret": None},
            }
        )
        assert socket.receive_json()["type"] == "ready"

    original_verify = tokens.verify
    verifications = 0

    def expires_after_auth(token, **kwargs):
        nonlocal verifications
        verifications += 1
        return original_verify(token, **kwargs) if verifications == 1 else None

    monkeypatch.setattr(tokens, "verify", expires_after_auth)
    with client.websocket_connect("/world/updates") as socket:
        socket.send_json({"type": "authenticate", "data": {"token": operator_token}})
        assert socket.receive_json()["type"] == "snapshot"
        with pytest.raises(websocket_error):
            socket.receive_json()

    verifications = 0
    with client.websocket_connect(character_path) as socket:
        socket.send_json(
            {
                "type": "authenticate",
                "data": {"token": player_token, "claim_id": None, "claim_secret": None},
            }
        )
        with pytest.raises(websocket_error):
            socket.receive_json()
    tokens.close()


def test_websockets_fail_closed_without_configured_authentication() -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    client = testclient.TestClient(create_app(build_scenario().actor))
    websocket_error = pytest.importorskip("starlette.websockets").WebSocketDisconnect
    for path in ("/world/updates", "/world/character/1/updates"):
        with pytest.raises(websocket_error) as rejected, client.websocket_connect(path):
            pass
        assert rejected.value.code == 1013


def test_explicit_unauthenticated_embedding_supports_http_and_websocket() -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    client = testclient.TestClient(
        create_app(build_scenario().actor, allow_unauthenticated=True)
    )
    assert client.get("/world/characters").status_code == 200
    assert client.get("/auth/me").status_code == 503
    with client.websocket_connect("/world/updates") as socket:
        assert socket.receive_json()["type"] == "snapshot"
