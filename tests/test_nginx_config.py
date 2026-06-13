from pathlib import Path

NGINX_TEMPLATES = (
    Path("deploy/nginx/frontend-http.conf"),
    Path("deploy/nginx/frontend-tls.conf"),
    Path("deploy/nginx/frontend-tls-home.conf"),
)
STATIC_NGINX_TEMPLATES = (
    Path("deploy/nginx/frontend-http-static.conf"),
    Path("deploy/nginx/frontend-tls-static.conf"),
    Path("deploy/nginx/frontend-tls-home-static.conf"),
)
COMPOSE_FILES = (
    Path("compose.yml"),
    Path("compose.tls.yml"),
    Path("compose.tls-home.yml"),
)


def _proxying_server_blocks(template: str) -> list[str]:
    blocks: list[str] = []
    offset = 0
    marker = "server {"
    while True:
        start = template.find(marker, offset)
        if start < 0:
            return blocks

        depth = 0
        for index in range(start, len(template)):
            char = template[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    block = template[start : index + 1]
                    if "location /api/" in block:
                        blocks.append(block)
                    offset = index + 1
                    break
        else:
            raise AssertionError("unterminated nginx server block")


def test_nginx_api_proxy_locations_use_runtime_dns_resolution() -> None:
    for template_path in NGINX_TEMPLATES:
        template = template_path.read_text()
        proxying_blocks = _proxying_server_blocks(template)
        assert proxying_blocks, f"{template_path} should include an API proxying server block"

        for block in proxying_blocks:
            assert "resolver ${NGINX_LOCAL_RESOLVERS} valid=10s ipv6=off;" in block
            assert "resolver 127.0.0.11" not in block
            assert "BUNNYLAND_NGINX_RESOLVER" not in block
            assert "set $api_upstream ${BUNNYLAND_API_UPSTREAM};" in block
            assert "proxy_pass $api_upstream;" in block
            assert "proxy_pass ${BUNNYLAND_API_UPSTREAM}" not in block
            assert "rewrite ^/api/(.*)$ /$1 break;" in block
            assert "rewrite ^/api(/admin/.*)$ $1 break;" in block
            assert "rewrite ^/api(/mcp)$ $1 break;" in block
            assert "rewrite ^/api(/mcp/.*)$ $1 break;" in block


def test_compose_enables_nginx_local_resolver_discovery() -> None:
    for compose_path in COMPOSE_FILES:
        compose = compose_path.read_text()
        assert 'NGINX_ENTRYPOINT_LOCAL_RESOLVERS: "1"' in compose

    setup_script = Path("scripts/vps-docker-setup").read_text()
    assert "NGINX_ENTRYPOINT_LOCAL_RESOLVERS" in setup_script
    assert "BUNNYLAND_NGINX_RESOLVER" not in setup_script
    assert '"$selected_runtime" == "docker"' in setup_script
    assert '-static.conf' in setup_script


def test_static_nginx_templates_keep_literal_proxy_pass_for_non_docker_runtimes() -> None:
    for template_path in STATIC_NGINX_TEMPLATES:
        template = template_path.read_text()
        assert "${NGINX_LOCAL_RESOLVERS}" not in template
        assert "set $api_upstream" not in template
        assert "proxy_pass ${BUNNYLAND_API_UPSTREAM}/;" in template
        assert "proxy_pass ${BUNNYLAND_API_UPSTREAM}/admin/;" in template
        assert "proxy_pass ${BUNNYLAND_API_UPSTREAM}/mcp;" in template
        assert "proxy_pass ${BUNNYLAND_API_UPSTREAM}/mcp/;" in template
