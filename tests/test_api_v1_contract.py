from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from conftest import build_scenario

from bunnyland.plugins import HttpContribution, HttpZone, Plugin, RuntimeContribution
from bunnyland.server.app import (
    AuthorizationSurface,
    create_app,
    route_surface_matrix,
)
from bunnyland.server.client_ids import CLIENT_ID_HEADER
from bunnyland.server.contract_compat import (
    ContractCompatibilityError,
    assert_openapi_compatible,
    assert_schema_compatible,
)

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

    snapshot = json.loads((CONTRACTS / "http-v1-routes.json").read_text())
    for zone, methods in snapshot["routes"].items():
        expected_surface = AuthorizationSurface(zone)
        for method, paths in methods.items():
            protocol = "websocket" if method == "WEBSOCKET" else "http"
            for path in paths:
                assert (protocol, path, expected_surface) in route_surface_matrix(app)


def test_v1_openapi_and_json_schema_are_backward_compatible() -> None:
    app = create_app(build_scenario().actor, allow_unauthenticated_embedding=True)
    current = app.openapi()
    baseline = json.loads((CONTRACTS / "openapi-v1.json").read_text())

    assert_openapi_compatible(baseline, current)

    standalone = json.loads((CONTRACTS / "json-schema-v1.json").read_text())
    for name, schema in standalone["$defs"].items():
        assert name in current["components"]["schemas"]
        assert_schema_compatible(
            schema,
            current["components"]["schemas"][name],
            baseline_root=standalone,
            current_root=current,
            path=f"$defs.{name}",
        )


@pytest.mark.parametrize(
    ("baseline", "current", "message"),
    [
        (
            {"type": "object", "properties": {"name": {"type": "string"}}},
            {"type": "object", "properties": {}},
            "removed or renamed",
        ),
        (
            {"type": "object", "properties": {"name": {"type": "string"}}},
            {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            "new required fields",
        ),
        (
            {"type": "string", "enum": ["queued", "running"]},
            {"type": "string", "enum": ["queued"]},
            "enum values were removed",
        ),
    ],
)
def test_v1_schema_compatibility_rejects_breaking_changes(
    baseline: dict[str, object], current: dict[str, object], message: str
) -> None:
    with pytest.raises(ContractCompatibilityError, match=message):
        assert_schema_compatible(baseline, current)


def test_v1_schema_compatibility_allows_additive_fields_and_enum_values() -> None:
    baseline = {
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["queued"]}},
        "required": ["status"],
    }
    current = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["queued", "running"]},
            "detail": {"type": "string"},
        },
        "required": ["status"],
    }

    assert_schema_compatible(baseline, current)


@pytest.mark.parametrize(
    ("baseline", "current", "message"),
    [
        ({"type": ["string", "null"]}, {"type": "string"}, "type narrowed"),
        ({"const": "old"}, {"const": "new"}, "const value changed"),
        ({"anyOf": [{"type": "string"}]}, {"type": "string"}, "removed anyOf"),
        (
            {"oneOf": [{"type": "string"}, {"type": "number"}]},
            {"oneOf": [{"type": "boolean"}]},
            "no compatible current branch",
        ),
        ({"properties": {"name": {}}}, {"properties": []}, "properties were removed"),
        ({"items": {"type": "string"}}, {"items": []}, "item schema was removed"),
        ({}, {"minimum": 0}, "added minimum"),
        ({"minimum": 0}, {"minimum": 1}, "tightened minimum"),
        ({}, {"maximum": 10}, "added maximum"),
        ({"maximum": 10}, {"maximum": 9}, "tightened maximum"),
        ({}, {"format": "uuid"}, "added or changed format"),
    ],
)
def test_v1_schema_compatibility_rejects_other_narrowing(
    baseline: dict[str, object], current: dict[str, object], message: str
) -> None:
    with pytest.raises(ContractCompatibilityError, match=message):
        assert_schema_compatible(baseline, current)


def test_v1_schema_compatibility_handles_references_and_non_object_keywords() -> None:
    with pytest.raises(ContractCompatibilityError, match="reference is not a schema"):
        assert_schema_compatible(
            {"$ref": "#/$defs/Old"},
            {"type": "string"},
            baseline_root={"$defs": {"Old": "not-a-schema"}},
        )

    assert_schema_compatible(
        {"properties": [], "items": [], "type": ["string", "null"]},
        {"properties": [], "items": [], "type": ["string", "null", "number"]},
    )


def _openapi(operation: dict[str, object] | None = None) -> dict[str, object]:
    return {"paths": {"/things": {"get": operation or {}}}}


@pytest.mark.parametrize(
    ("baseline", "current", "message"),
    [
        (_openapi(), {"paths": {}}, "route was removed"),
        (_openapi(), {"paths": {"/things": {}}}, "operation was removed"),
        (
            _openapi({"security": [{"claim": []}]}),
            _openapi({"security": [{"admin": []}]}),
            "authorization declaration changed",
        ),
        (
            _openapi({"parameters": [{"in": "query", "name": "cursor"}]}),
            _openapi({"parameters": []}),
            "parameter .* was removed or renamed",
        ),
        (
            _openapi({"parameters": []}),
            _openapi(
                {
                    "parameters": [
                        {"in": "query", "name": "cursor", "required": True}
                    ]
                }
            ),
            "new required parameter",
        ),
        (
            _openapi(
                {
                    "requestBody": {
                        "content": {"application/json": {"schema": {"type": "string"}}}
                    }
                }
            ),
            _openapi(),
            "request body was removed",
        ),
        (
            _openapi(
                {
                    "requestBody": {
                        "content": {"application/json": {"schema": {"type": "string"}}}
                    }
                }
            ),
            _openapi({"requestBody": {"content": {}}}),
            "request media type was removed",
        ),
        (
            _openapi(),
            _openapi({"requestBody": {"required": True}}),
            "new required request body",
        ),
        (
            _openapi({"responses": {"200": {}}}),
            _openapi({"responses": {}}),
            "response 200 was removed",
        ),
        (
            _openapi(
                {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {"schema": {"type": "string"}}
                            }
                        }
                    }
                }
            ),
            _openapi({"responses": {"200": {"content": {}}}}),
            "response 200 media type was removed",
        ),
    ],
)
def test_v1_openapi_compatibility_rejects_breaking_changes(
    baseline: dict[str, object], current: dict[str, object], message: str
) -> None:
    with pytest.raises(ContractCompatibilityError, match=message):
        assert_openapi_compatible(baseline, current)


def test_v1_openapi_compatibility_allows_optional_parameter_and_metadata() -> None:
    content = {
        "text/plain": {"example": "ignored"},
        "application/json": {"schema": {"type": "string"}},
    }
    baseline = {
        "paths": {
            "/things": {
                "x-owner": "bunnyland",
                "parameters": [],
                "get": {
                    "parameters": [
                        {
                            "in": "query",
                            "name": "cursor",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "requestBody": {"content": content},
                    "responses": {"200": {"content": content}},
                },
            }
        }
    }
    current = {
        "paths": {
            "/things": {
                "x-owner": "bunnyland",
                "parameters": [],
                "get": {
                    "parameters": [
                        {
                            "in": "query",
                            "name": "cursor",
                            "required": False,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "requestBody": {"content": content},
                    "responses": {"200": {"content": content}},
                },
            }
        }
    }

    assert_openapi_compatible(baseline, current)


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
