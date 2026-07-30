# Shared Bunnyland API proxy. FastAPI owns authentication and authorization for every
# HTTP, WebSocket, plugin, and MCP surface; nginx retains only transport and overload
# controls. Authorization and Cookie are forwarded explicitly so all clients use the same
# opaque bearer-token verifier.

limit_req_status 429;
limit_conn_status 429;
error_page 429 = @bunnyland_rate_limited;

location @bunnyland_rate_limited {
    # add_header here replaces, rather than extends, the server block's headers, so the
    # security headers have to be restated or a 429 would ship without any of them.
    add_header Retry-After "${BUNNYLAND_EDGE_RETRY_AFTER}" always;
    # Origin-only: this file is shared by every deployment shape, and the self-hosted
    # TLS shapes deliberately do not assert includeSubDomains.
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header X-Frame-Options "DENY" always;
    return 429;
}

location = /api/v1/public/health {
    proxy_pass ${BUNNYLAND_API_UPSTREAM}/v1/public/health;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $bunnyland_forwarded_proto;
}

location /api/ {
    limit_req zone=bunnyland_api burst=${BUNNYLAND_EDGE_API_BURST} nodelay;
    # limit_req bounds how fast connections are opened, not how many are held. A websocket
    # is one request that then lives for up to proxy_read_timeout, so without limit_conn a
    # single address could accumulate sockets until nginx ran out of worker connections --
    # which would take the home site down with the API, since one nginx serves both.
    limit_conn bunnyland_api_conn ${BUNNYLAND_EDGE_API_CONNECTIONS};
    # Matches the app's own body cap (BUNNYLAND_MAX_REQUEST_BODY_BYTES) so a legitimate
    # maximum-size upload plus multipart framing is not rejected at the edge first.
    client_max_body_size ${BUNNYLAND_EDGE_MAX_BODY_SIZE};

    proxy_pass ${BUNNYLAND_API_UPSTREAM}/;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $bunnyland_forwarded_proto;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header Cookie $http_cookie;
    proxy_set_header X-Bunnyland-Client-Id $http_x_bunnyland_client_id;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_read_timeout 3600s;
}
