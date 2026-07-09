# Shared /api/* proxy locations, included by every frontend-*.conf server block so the
# admin auth rules live in exactly one place. Rendered by the nginx image's envsubst (it is
# mounted as a *.template into /etc/nginx/templates and emitted to /etc/nginx/conf.d as a
# .inc, so nginx's conf.d/*.conf autoload does not load it as a standalone server).
#
# Admin surfaces share ONE Basic-auth realm ("Bunnyland admin") so a single browser login
# carries to every admin path -- including the same-origin /world/updates WebSocket, whose
# handshake replays the cached credentials. After Basic auth passes, nginx injects the single
# X-Bunnyland-Admin-Secret the app checks. X-Bunnyland-Client-Id is an application
# client identity header, not a Basic-auth username, so nginx forwards it when a client
# provides it. Generic player-facing /api/ paths use a separate Basic-auth file.

location = /api/world/snapshot {
    auth_basic "Bunnyland admin";
    auth_basic_user_file /etc/nginx/bunnyland/world-editor.htpasswd;

    proxy_pass ${BUNNYLAND_API_UPSTREAM}/world/snapshot;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Bunnyland-Admin-Secret "${BUNNYLAND_ADMIN_TOKEN}";
    proxy_set_header X-Bunnyland-Client-Id $http_x_bunnyland_client_id;
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
    proxy_set_header X-Bunnyland-Admin-Secret "${BUNNYLAND_ADMIN_TOKEN}";
    proxy_set_header X-Bunnyland-Client-Id $http_x_bunnyland_client_id;
}

location = /api/world/events/recent {
    auth_basic "Bunnyland admin";
    auth_basic_user_file /etc/nginx/bunnyland/world-editor.htpasswd;

    proxy_pass ${BUNNYLAND_API_UPSTREAM}/world/events/recent;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Bunnyland-Admin-Secret "${BUNNYLAND_ADMIN_TOKEN}";
    proxy_set_header X-Bunnyland-Client-Id $http_x_bunnyland_client_id;
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
    proxy_set_header X-Bunnyland-Admin-Secret "${BUNNYLAND_ADMIN_TOKEN}";
    proxy_set_header X-Bunnyland-Client-Id $http_x_bunnyland_client_id;
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
    proxy_set_header X-Bunnyland-Admin-Secret "${BUNNYLAND_ADMIN_TOKEN}";
    proxy_set_header X-Bunnyland-Client-Id $http_x_bunnyland_client_id;
    proxy_read_timeout 3600s;
}

location /api/admin/ {
    client_max_body_size 10m;

    auth_basic "Bunnyland admin";
    auth_basic_user_file /etc/nginx/bunnyland/world-editor.htpasswd;

    proxy_pass ${BUNNYLAND_API_UPSTREAM}/admin/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Bunnyland-Admin-Secret "${BUNNYLAND_ADMIN_TOKEN}";
    proxy_set_header X-Bunnyland-Client-Id $http_x_bunnyland_client_id;
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
    proxy_set_header X-Bunnyland-Admin-Secret "${BUNNYLAND_ADMIN_TOKEN}";
    proxy_set_header X-Bunnyland-Client-Id $http_x_bunnyland_client_id;
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
    proxy_set_header X-Bunnyland-Admin-Secret "${BUNNYLAND_ADMIN_TOKEN}";
    proxy_set_header X-Bunnyland-Client-Id $http_x_bunnyland_client_id;
    proxy_read_timeout 3600s;
}

# Optional Grafana Tempo query API. The /tempo/ location lives in tempo-location.inc, which
# the compose.tempo.yml fragment mounts into the frontend only when Tempo is deployed; this
# wildcard include is a harmless no-op otherwise (so nginx never tries to resolve the tempo
# upstream when it is absent). It shares the "Bunnyland admin" Basic-auth realm, so a remote
# Grafana authenticates with the same admin password.
include /etc/nginx/conf.d/tempo-location.inc*;

location = /api/health {
    proxy_pass ${BUNNYLAND_API_UPSTREAM}/health;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /api/ {
    auth_basic "Bunnyland player";
    auth_basic_user_file /etc/nginx/bunnyland/players.htpasswd;

    proxy_pass ${BUNNYLAND_API_UPSTREAM}/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Bunnyland-Client-Id $http_x_bunnyland_client_id;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_read_timeout 3600s;
}
