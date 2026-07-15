# Shared Bunnyland API proxy. FastAPI owns authentication and authorization for every
# HTTP, WebSocket, plugin, and MCP surface; nginx retains only transport and overload
# controls. Authorization and Cookie are forwarded explicitly so all clients use the same
# opaque bearer-token verifier.

limit_req_status 429;
error_page 429 = @bunnyland_rate_limited;

location @bunnyland_rate_limited {
    add_header Retry-After "${BUNNYLAND_EDGE_RETRY_AFTER}" always;
    return 429;
}

# Optional Tempo query API. Its included location retains a dedicated, unrelated Basic
# credential file and is never part of Bunnyland application authentication.
include /etc/nginx/conf.d/tempo-location.inc*;

location = /api/public/health {
    proxy_pass ${BUNNYLAND_API_UPSTREAM}/public/health;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /api/ {
    limit_req zone=bunnyland_api burst=${BUNNYLAND_EDGE_API_BURST} nodelay;
    client_max_body_size 10m;

    proxy_pass ${BUNNYLAND_API_UPSTREAM}/;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header Cookie $http_cookie;
    proxy_set_header X-Bunnyland-Client-Id $http_x_bunnyland_client_id;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_read_timeout 3600s;
}
