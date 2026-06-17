# Grafana Tempo query API. Mounted into the frontend by compose.tempo.yml (rendered to
# /etc/nginx/conf.d/tempo-location.inc and pulled in by the wildcard include in
# api-locations.inc) so the /tempo/ route exists only when Tempo is deployed.
#
# Shares the "Bunnyland admin" Basic-auth realm, so a remote Grafana authenticates with the
# same admin password as every other admin surface. The upstream resolves via the container
# /etc/hosts entry the compose runtime adds for the tempo service, so a static proxy_pass
# works on Docker and nerdctl alike (no embedded-DNS resolver needed). As with the server
# upstream, the frontend caches the resolved IP at config load, so restart the frontend
# after recreating the tempo container. Point a Grafana Tempo datasource at
# https://<host>/tempo/ with the admin Basic-auth credentials.
location /tempo/ {
    auth_basic "Bunnyland admin";
    auth_basic_user_file /etc/nginx/bunnyland/world-editor.htpasswd;

    rewrite ^/tempo/(.*)$ /$1 break;
    proxy_pass http://tempo:3200;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 3600s;
}
