# Shared /api/* proxy locations, included by every frontend-*.conf server block so the
# admin auth rules live in exactly one place. Rendered by the nginx image's envsubst (it is
# mounted as a *.template into /etc/nginx/templates and emitted to /etc/nginx/conf.d as a
# .inc, so nginx's conf.d/*.conf autoload does not load it as a standalone server).
#
# Admin surfaces share ONE Basic-auth realm ("Bunnyland admin") so a single browser login
# carries to every admin path -- including the same-origin /world/updates WebSocket, whose
# handshake replays the cached credentials. After Basic auth passes, nginx injects the single
# X-Bunnyland-Admin-Token the app checks; clients can never supply their own (proxy_set_header
# overrides any inbound value). Player-facing /api/ paths stay open.

location = /api/world/snapshot {
    auth_basic "Bunnyland admin";
    auth_basic_user_file /etc/nginx/bunnyland/world-editor.htpasswd;

    proxy_pass ${BUNNYLAND_API_UPSTREAM}/world/snapshot;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Bunnyland-Admin-Token "${BUNNYLAND_ADMIN_TOKEN}";
}

location = /api/world/overview {
    auth_basic "Bunnyland admin";
    auth_basic_user_file /etc/nginx/bunnyland/world-editor.htpasswd;

    proxy_pass ${BUNNYLAND_API_UPSTREAM}/world/overview;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Bunnyland-Admin-Token "${BUNNYLAND_ADMIN_TOKEN}";
}

location ^~ /api/world/dm/ {
    auth_basic "Bunnyland admin";
    auth_basic_user_file /etc/nginx/bunnyland/world-editor.htpasswd;

    proxy_pass ${BUNNYLAND_API_UPSTREAM}/world/dm/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Bunnyland-Admin-Token "${BUNNYLAND_ADMIN_TOKEN}";
}

location = /api/world/updates {
    auth_basic "Bunnyland admin";
    auth_basic_user_file /etc/nginx/bunnyland/world-editor.htpasswd;

    proxy_pass ${BUNNYLAND_API_UPSTREAM}/world/updates;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header X-Bunnyland-Admin-Token "${BUNNYLAND_ADMIN_TOKEN}";
    proxy_read_timeout 3600s;
}

location /api/admin/ {
    auth_basic "Bunnyland admin";
    auth_basic_user_file /etc/nginx/bunnyland/world-editor.htpasswd;

    proxy_pass ${BUNNYLAND_API_UPSTREAM}/admin/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Bunnyland-Admin-Token "${BUNNYLAND_ADMIN_TOKEN}";
}

location = /api/mcp {
    auth_basic "Bunnyland admin";
    auth_basic_user_file /etc/nginx/bunnyland/world-editor.htpasswd;

    proxy_pass ${BUNNYLAND_API_UPSTREAM}/mcp;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_set_header Host 127.0.0.1:8765;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Bunnyland-Admin-Token "${BUNNYLAND_ADMIN_TOKEN}";
    proxy_read_timeout 3600s;
}

location /api/mcp/ {
    auth_basic "Bunnyland admin";
    auth_basic_user_file /etc/nginx/bunnyland/world-editor.htpasswd;

    proxy_pass ${BUNNYLAND_API_UPSTREAM}/mcp/;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_set_header Host 127.0.0.1:8765;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Bunnyland-Admin-Token "${BUNNYLAND_ADMIN_TOKEN}";
    proxy_read_timeout 3600s;
}

# Grafana Tempo query API (optional; only reachable when compose.tempo.yml is running).
# Shares the "Bunnyland admin" realm so a remote Grafana authenticates with the same admin
# password as every other admin surface. The upstream is resolved at request time via
# Docker's embedded DNS, so this block is harmless (502 on use) when the Tempo container is
# not deployed. Point a Grafana Tempo datasource at https://<host>/tempo/ with the admin
# Basic-auth credentials.
location /tempo/ {
    auth_basic "Bunnyland admin";
    auth_basic_user_file /etc/nginx/bunnyland/world-editor.htpasswd;

    resolver 127.0.0.11 valid=30s;
    set $tempo_upstream tempo;
    rewrite ^/tempo/(.*)$ /$1 break;
    proxy_pass http://$tempo_upstream:3200;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 3600s;
}

location /api/ {
    proxy_pass ${BUNNYLAND_API_UPSTREAM}/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_read_timeout 3600s;
}
