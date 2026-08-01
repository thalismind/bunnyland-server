"""Structural checks on the shipped nginx configs.

These guard invariants that are easy to lose when one deployment shape is edited and the
others are not. Two such drifts were already present: only the tunnel config carried any
security headers, so anyone serving from the http/tls shapes silently lost CSP, nosniff and
framing protection; and no config had limit_conn at all, so a single address could hold
websockets open until nginx ran out of worker connections.

This is a syntax-free structural check. It does not replace `nginx -t` against the rendered
templates, which needs the frontend image.
"""

from __future__ import annotations

from pathlib import Path

import pytest

NGINX = Path(__file__).resolve().parents[1] / "deploy" / "nginx"
SECURITY_HEADERS_INCLUDE = "include /etc/nginx/conf.d/security-headers.inc;"
API_LOCATIONS_INCLUDE = "include /etc/nginx/conf.d/api-locations.inc;"

SERVER_CONFIGS = sorted(path.name for path in NGINX.glob("frontend-*.conf"))


def _read(name: str) -> str:
    return (NGINX / name).read_text()


def _block_body(text: str, opener: str) -> str:
    """Return the body of one nginx block, tracking depth so ``${VAR}`` does not end it."""

    start = text.index(opener) + len(opener)
    depth = 1
    for index in range(start, len(text)):
        character = text[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[start:index]
    raise AssertionError(f"unterminated block for {opener!r}")


def test_every_frontend_config_is_covered_by_this_test() -> None:
    # A new deployment shape must be added here deliberately rather than skipping the checks.
    assert SERVER_CONFIGS == [
        "frontend-http.conf",
        "frontend-tls-home.conf",
        "frontend-tls.conf",
        "frontend-tunnel.conf",
    ]


@pytest.mark.parametrize("name", SERVER_CONFIGS)
def test_configs_that_proxy_the_api_declare_the_connection_zone(name: str) -> None:
    text = _read(name)
    if API_LOCATIONS_INCLUDE not in text:
        pytest.skip(f"{name} does not proxy the API")
    # api-locations.inc references this zone; nginx fails to start if it is not declared.
    assert "limit_conn_zone $binary_remote_addr zone=bunnyland_api_conn:" in text
    assert "limit_req_zone $binary_remote_addr zone=bunnyland_api:" in text


@pytest.mark.parametrize("name", SERVER_CONFIGS)
def test_content_serving_blocks_include_the_shared_security_headers(name: str) -> None:
    text = _read(name)
    # Every block that serves content (rather than only redirecting to https) must carry the
    # headers. Counting roots is a proxy for "this block returns a body".
    serving_blocks = text.count("root /usr/share/nginx/")
    if not serving_blocks:
        pytest.skip(f"{name} serves no content directly")
    assert text.count(SECURITY_HEADERS_INCLUDE) >= serving_blocks


@pytest.mark.parametrize("name", SERVER_CONFIGS)
def test_no_config_sets_security_headers_inline(name: str) -> None:
    text = _read(name)
    # Inline copies drift. Strict-Transport-Security is deliberately excluded: it varies by
    # deployment shape (see security-headers.inc) and is asserted per server block.
    for header in (
        "add_header Content-Security-Policy",
        "add_header X-Content-Type-Options",
        "add_header X-Frame-Options",
    ):
        assert header not in text, f"{name} should include security-headers.inc instead"


@pytest.mark.parametrize("name", SERVER_CONFIGS)
def test_frontends_compress_text_and_apply_content_aware_cache_policy(name: str) -> None:
    text = _read(name)

    assert "gzip on;" in text
    assert (
        "gzip_types application/javascript application/json image/svg+xml text/css text/plain;"
        in text
    )
    assert "map $uri $bunnyland_cache_control {" in text
    assert '/config.json "no-store";' in text
    assert (
        '"~^/(?:[^/]+/)*assets/.*-[A-Za-z0-9_-]{8,}\\.[^/]+$" '
        '"public, max-age=31536000, immutable";'
        in text
    )
    assert '"public, max-age=31536000, immutable"' in text
    assert 'default "no-cache";' in text
    assert "add_header Cache-Control $bunnyland_cache_control always;" in text


def test_api_location_caps_concurrent_connections_and_request_rate() -> None:
    text = _read("api-locations.inc")

    assert "limit_conn bunnyland_api_conn ${BUNNYLAND_EDGE_API_CONNECTIONS};" in text
    assert "limit_req zone=bunnyland_api burst=${BUNNYLAND_EDGE_API_BURST}" in text
    assert "limit_conn_status 429;" in text
    assert "limit_req_status 429;" in text


def test_rate_limited_location_restates_the_security_headers() -> None:
    # add_header replaces rather than extends per level, so a location with its own
    # add_header drops every inherited one. The 429 response must not ship bare.
    text = _read("api-locations.inc")
    body = _block_body(text, "location @bunnyland_rate_limited {")

    assert "Retry-After" in body
    for header in (
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "X-Frame-Options",
    ):
        assert header in body


def test_config_json_locations_restate_the_security_headers() -> None:
    for name in SERVER_CONFIGS:
        text = _read(name)
        if "location = /config.json {" not in text:
            continue
        body = _block_body(text, "location = /config.json {")
        if "add_header" not in body:
            # No own add_header, so the server block's headers are inherited unchanged.
            continue
        assert SECURITY_HEADERS_INCLUDE in body, name


def test_edge_body_size_is_configurable_rather_than_pinned_below_the_app_limit() -> None:
    # A hard-coded 10m sat below the app's own cap (a 10MiB image plus multipart framing),
    # so a legitimate maximum-size upload was rejected at the edge first.
    text = _read("api-locations.inc")

    assert "client_max_body_size ${BUNNYLAND_EDGE_MAX_BODY_SIZE};" in text


def _referenced_includes(text: str) -> set[str]:
    return {
        line.split("/etc/nginx/conf.d/", 1)[1].rstrip(";").strip()
        for line in text.splitlines()
        if "include /etc/nginx/conf.d/" in line
    }


def test_every_included_file_exists() -> None:
    for path in NGINX.glob("*"):
        for include in _referenced_includes(path.read_text()):
            assert (NGINX / include).exists(), f"{path.name} includes missing {include}"


def test_compose_files_mount_every_include_the_config_they_use_needs() -> None:
    # nginx refuses to start on a missing include, and the frontend mounts config files one
    # by one, so adding an include without adding its mount breaks the deploy. That is not
    # visible from the nginx files alone.
    root = NGINX.parents[1]
    compose_files = [
        path
        for path in root.glob("compose*.yml")
        if "/etc/nginx/templates/" in path.read_text()
    ]
    assert compose_files, "expected at least one compose file to mount nginx templates"

    for compose in compose_files:
        text = compose.read_text()
        mounted = {
            line.split("./deploy/nginx/", 1)[1].split(":", 1)[0]
            for line in text.splitlines()
            if "./deploy/nginx/" in line
        }
        server_configs = mounted & set(SERVER_CONFIGS)
        for name in server_configs:
            for include in _referenced_includes(_read(name)):
                assert include in mounted, (
                    f"{compose.name} mounts {name}, which includes {include}, "
                    "but does not mount it"
                )
