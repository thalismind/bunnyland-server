from pathlib import Path

NGINX_TEMPLATES = (
    Path("deploy/nginx/frontend-http.conf"),
    Path("deploy/nginx/frontend-tls.conf"),
    Path("deploy/nginx/frontend-tls-home.conf"),
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
            assert "resolver 127.0.0.11 valid=10s ipv6=off;" in block
            assert "set $api_upstream ${BUNNYLAND_API_UPSTREAM};" in block
            assert "proxy_pass $api_upstream;" in block
            assert "proxy_pass ${BUNNYLAND_API_UPSTREAM}" not in block
            assert "rewrite ^/api/(.*)$ /$1 break;" in block
            assert "rewrite ^/api(/admin/.*)$ $1 break;" in block
