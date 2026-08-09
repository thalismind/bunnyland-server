# Hosting the web client securely

Public Bunnyland should have one HTTPS origin. nginx serves the static web client and proxies
`/api/` to a loopback-only server. This keeps cookies, browser origin checks, HTTP, WebSocket,
MCP, and media on one authorization boundary.

## Prerequisites

- The local health check from [the first-server guide](running-a-server.md) passes.
- Human accounts and private auth files exist.
- A dedicated Linux service account owns the checkout and data.
- Your DNS name resolves to the host.
- nginx and your TLS certificate tool are installed.

The examples use `play.example.com`. Replace it everywhere, including the browser origin in
your Bunnyland config.

## Install the native service

Place a reviewed server release at `/opt/bunnyland/server`, create its locked environment,
and keep durable state under `/var/lib/bunnyland`:

```bash
sudo useradd --system --home /var/lib/bunnyland --create-home bunnyland
sudo install -d -o bunnyland -g bunnyland -m 0700 \
  /etc/bunnyland /var/lib/bunnyland/worlds /var/lib/bunnyland/media
sudo -u bunnyland uv sync --directory /opt/bunnyland/server --locked \
  --extra server
```

Copy the validated config and user inventory into `/etc/bunnyland`, set their owner to
`bunnyland`, and set mode `0600`. Put provider or Discord secrets in separate files in the
same directory when those integrations are enabled.

Create `/etc/systemd/system/bunnyland.service`:

```ini
[Unit]
Description=Bunnyland server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=bunnyland
Group=bunnyland
WorkingDirectory=/opt/bunnyland/server
EnvironmentFile=-/etc/bunnyland/server.env
ExecStart=/opt/bunnyland/server/.venv/bin/bunnyland serve --config /etc/bunnyland/bunnyland.yml --api-host 127.0.0.1 --api-port 8765 --auth-users-file /etc/bunnyland/users.yml --token-db /var/lib/bunnyland/tokens.sqlite3
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Enable and verify it locally:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bunnyland
sudo systemctl status bunnyland
curl -i http://127.0.0.1:8765/v1/public/health
```

Use the virtual environment's `bunnyland` executable in `ExecStart`; a service should not
run a dependency sync on every restart.

## Build and place the web client

Check out the matching Bunnyland web release on a build machine:

```bash
git clone https://github.com/thalismind/bunnyland-web.git
cd bunnyland-web
npm ci
npm run check
```

Publish the resulting `dist/` directory to `/var/www/bunnyland-web` as read-only files. Its
`config.json` should contain a same-origin API URL:

```json
{
  "serverUrl": "/api/v1/",
  "autoConnect": true,
  "playerAuthRequired": true
}
```

Never place `bunnyland.yml`, provider credentials, auth users, token databases, or world
snapshots in the web directory.

## Configure same-origin nginx proxying

Define the WebSocket connection map once inside nginx's `http` context (commonly a file under
`/etc/nginx/conf.d/`):

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}
```

Create a site for the hostname:

```nginx
server {
    listen 80;
    server_name play.example.com;

    root /var/www/bunnyland-web;
    index index.html;

    location = /config.json {
        add_header Cache-Control "no-store" always;
        try_files $uri =404;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8765/;
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

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

The trailing slash on both `location /api/` and `proxy_pass .../` intentionally removes the
public `/api/` prefix before forwarding. Keep `server.forwarded_allow_ips` restricted to the
actual proxy address (`127.0.0.1` in this native topology).

Validate nginx, obtain a certificate with Certbot or your normal ACME client, and redirect
HTTP to HTTPS:

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d play.example.com \
  --agree-tos -m admin@example.com --redirect
```

Re-run `nginx -t` after certificate automation changes the site. Verify that the HTTPS server
still contains the `/api/` proxy and WebSocket headers.

## Configure the firewall

Allow your administration path before enabling a deny-by-default firewall. A typical UFW host
allows SSH, HTTP for ACME/redirects, and HTTPS, while explicitly keeping 8765 private:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 8765/tcp
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw --force enable
sudo ufw status verbose
```

If SSH uses a custom port, allow that exact port before enabling UFW. Cloud security groups or
router rules must enforce the same policy.

## Verify the public path

```bash
curl -i http://127.0.0.1:8765/v1/public/health
curl -i https://play.example.com/api/v1/public/health
curl --connect-timeout 5 http://PUBLIC_IP:8765/v1/public/health
```

The first two requests should return `204`; the direct public-port request should fail. Then
open the HTTPS site and verify login, character selection, a normal action, reconnect, and an
admin page with both a play-only and an admin account. A play-only account must receive `403`
for admin operations.

## Published-container alternative

The server and web images are published at:

```text
ghcr.io/thalismind/bunnyland-server
ghcr.io/thalismind/bunnyland-web
```

Use immutable `@sha256:...` references, not floating tags, for a durable deployment. Mount
the same private config, auth, world, token, memory, and media paths described above. Put both
containers on a private network, expose only the web/nginx container on 80/443, and point its
`BUNNYLAND_API_UPSTREAM` at the server container. The server repository's Compose files show
the wiring; review and adapt them manually. Do not run the retired generic VPS installer.

## Troubleshooting

### The page loads but live connection fails

Check that `config.json` uses `/api/v1/`, nginx forwards upgrade headers, `proxy_buffering` is
off, and the browser console has no mixed-content or origin error.

### Public health returns 502

Check `systemctl status bunnyland`, then request the loopback health URL. A failed loopback
request is an application/service issue; a successful loopback request with public 502 is an
nginx upstream or host-policy issue.

### Login loops or cookies disappear

Confirm the browser is using HTTPS and the API is same-origin. Do not add Basic auth at nginx
or proxy the API through a second hostname.

### WebSockets disconnect after one minute

Increase `proxy_read_timeout`, verify the connection map is in nginx's `http` context, and
ensure intermediate load balancers permit long-lived WebSockets.

[← Authentication, permissions, and moderation](authentication-permissions-moderation.md) ·
[Worlds, plugins, persistence, and snapshots →](worlds-plugins-persistence.md)
