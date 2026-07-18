from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from conftest import build_scenario

from bunnyland.plugins import HttpContribution, HttpZone, Plugin, RuntimeContribution
from bunnyland.server.app import create_app, route_surface_matrix
from bunnyland.server.client_ids import CLIENT_ID_HEADER

CONTRACTS = Path(__file__).parents[1] / "contracts"


def _expected_http_routes() -> set[tuple[str, str]]:
    snapshot = json.loads((CONTRACTS / "http-v1-routes.json").read_text())
    return {
        (method, path)
        for methods in snapshot["routes"].values()
        for method, paths in methods.items()
        for path in paths
    }


def test_v1_route_allowlist_and_scope_matrix_are_exact() -> None:
    app = create_app(build_scenario().actor, allow_unauthenticated_embedding=True)
    infrastructure = set(
        json.loads((CONTRACTS / "http-v1-routes.json").read_text())["infrastructure"]
    )
    actual = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if path in infrastructure:
            continue
        methods = getattr(route, "methods", None)
        if methods is None:
            actual.add(("WEBSOCKET", path))
        else:
            actual.update((method, path) for method in methods)

    assert actual == _expected_http_routes()
    assert all(path.startswith("/v1/") for _protocol, path, _surface in route_surface_matrix(app))


@pytest.mark.anyio
async def test_v1_public_resources_and_legacy_absence() -> None:
    app = create_app(build_scenario().actor, allow_unauthenticated_embedding=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        health = await client.get("/v1/public/health")
        features = await client.get("/v1/public/features")
        legacy = await client.get("/public/features")

    assert health.status_code == 204
    assert health.content == b""
    assert features.status_code == 200
    assert "ok" not in features.json()
    assert "schema_version" not in features.json()
    assert legacy.status_code == 404
    assert legacy.headers["content-type"].startswith("application/problem+json")
    assert legacy.json()["code"] == "not_found"


@pytest.mark.anyio
async def test_claim_paths_derive_identity_and_reject_spoof_fields() -> None:
    scenario = build_scenario()
    app = create_app(scenario.actor, allow_unauthenticated_embedding=True)
    headers = {CLIENT_ID_HEADER: "browser-a"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/play/claims",
            headers=headers,
            json={"character_id": str(scenario.character)},
        )
        claim = created.json()
        secret = created.headers["X-Bunnyland-Claim-Secret"]
        claim_headers = {**headers, "X-Bunnyland-Claim-Secret": secret}
        projection = await client.get(
            f"/v1/play/claims/{claim['id']}/projection", headers=claim_headers
        )
        spoof = await client.post(
            f"/v1/play/claims/{claim['id']}/commands",
            headers=claim_headers,
            json={
                "command_type": "wait",
                "character_id": "character:spoofed",
                "controller_id": "controller:spoofed",
                "controller_generation": 999,
                "client_id": "browser-b",
                "claim_id": "claim:spoofed",
            },
        )

    assert created.status_code == 201
    assert created.headers["Location"] == f"/v1/play/claims/{claim['id']}"
    assert "claim_secret" not in claim
    assert projection.status_code == 200
    assert projection.json()["claim"]["character_id"] == str(scenario.character)
    assert projection.json()["world_id"]
    assert spoof.status_code == 422
    assert spoof.json()["code"] == "validation_error"


def test_addon_http_routes_are_namespaced_by_zone_and_plugin() -> None:
    def register(router, _actor, **_context):
        @router.get("/status")
        async def status() -> dict[str, str]:
            return {"status": "ready"}

    plugin = Plugin(
        id="example.weather",
        name="Weather",
        runtime=RuntimeContribution(
            http=(HttpContribution(zone=HttpZone.PLAY, registrars=(register,)),)
        ),
    )
    app = create_app(
        build_scenario().actor,
        plugins=[plugin],
        allow_unauthenticated_embedding=True,
    )
    paths = {getattr(route, "path", "") for route in app.routes}

    assert "/v1/play/extensions/example.weather/status" in paths
    assert "/play/example.weather/status" not in paths
