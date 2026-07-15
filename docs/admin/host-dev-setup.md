# Host dev setup guide

This guide captures the older non-container host setup for development and debugging:

1. run the server API;
2. serve the web client from `../bunnyland-web`;
3. choose plugins and create or resume a world;
4. connect a browser client;
5. connect Discord as a bot.
6. optionally serve a project homepage from `../bunnyland-home`.

The examples assume:

- Debian/Ubuntu paths and service commands;
- homepage domain `example.com`;
- web client domain `sandbox.example.com`;
- optional homepage redirect domain `home.example.com`;
- server checkout at `/opt/bunnyland/server`;
- web checkout at `/opt/bunnyland/web`;
- homepage checkout at `/opt/bunnyland/home`;
- public web client config at `/var/www/bunnyland/config.json`;
- world state at `/var/lib/bunnyland/worlds/main.json`;
- Bunnyland API bound to `127.0.0.1:8765`.

Adjust names and paths for your host.

## 1. Server install

Install host packages. Use Python 3.12 on Ubuntu 24.04 and older:

```bash
sudo apt update
sudo apt install -y \
  git curl nginx apache2-utils ufw certbot python3-certbot-nginx \
  python3.12 python3.12-venv
```

On Ubuntu 26.04 and newer, the Python 3.12 packages are no longer present, so use
Python 3.14 instead:

```bash
sudo apt update
sudo apt install -y \
  git curl nginx apache2-utils ufw certbot python3-certbot-nginx \
  python3.14 python3.14-venv
```

Create a service account and directories:

```bash
sudo useradd --system --create-home --home-dir /opt/bunnyland --shell /usr/sbin/nologin bunnyland
sudo install -d -o bunnyland -g bunnyland /opt/bunnyland/server
sudo install -d -o bunnyland -g bunnyland /opt/bunnyland/web
sudo install -d -o bunnyland -g bunnyland /opt/bunnyland/home
sudo install -d -o bunnyland -g bunnyland /var/lib/bunnyland/worlds
sudo install -d -m 0750 -o bunnyland -g bunnyland /etc/bunnyland
sudo install -d -o www-data -g www-data /var/www/bunnyland
```

Install `uv` for the service account:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sudo -u bunnyland sh
```

Clone and install the server:

```bash
sudo -u bunnyland git clone https://github.com/thalismind/bunnyland-server.git /opt/bunnyland/server
cd /opt/bunnyland/server
sudo -u bunnyland /opt/bunnyland/.local/bin/uv sync --python 3.12 --extra server --extra llm --extra discord
```

On Ubuntu 26.04 and newer, use Python 3.14 for the virtual environment:

```bash
sudo -u bunnyland /opt/bunnyland/.local/bin/uv sync --python 3.14 --extra server --extra llm --extra discord
```

Use the SSH deployment remote instead if your VPS needs deploy-key access.

Create `/etc/bunnyland/server.env`:

```dotenv
# Required only when using --llm.
OLLAMA_CLOUD_API_KEY=sk-...

# Optional for local Ollama.
# OLLAMA_HOST=http://127.0.0.1:11434

# Optional for OpenRouter-backed character controllers.
# OPENROUTER_API_KEY=sk-or-...
# OPENROUTER_SERVER_URL=https://openrouter.ai/api/v1

# Required only for the Discord bot.
# DISCORD_TOKEN=...
```

Keep this file readable only by root and the service user:

```bash
sudo chown root:bunnyland /etc/bunnyland/server.env
sudo chmod 0640 /etc/bunnyland/server.env
```

The systemd service below loads this file with `EnvironmentFile=...`; ad hoc shell
commands do not. If you run `bunnyland serve --llm` manually, source the file in that
command before starting the process. Keep the file to simple `KEY=value` lines so it works
for both systemd and shell sourcing.

The `bunnyland` account is created with `/usr/sbin/nologin` for security. That means
`sudo su - bunnyland` is expected to fail with `This account is currently not available`.
Use `sudo -u bunnyland <command>` instead.

The account may also have a locked password because it was created as a system user. That
does not stop systemd or `sudo -u bunnyland ...` from working. Check both the shell and
password state with:

```bash
getent passwd bunnyland
sudo passwd -S bunnyland
```

For temporary interactive maintenance, give the account a real shell and unlock it:

```bash
sudo usermod --shell /bin/bash bunnyland
sudo passwd bunnyland
sudo passwd -u bunnyland
sudo su - bunnyland
```

When you are done, restore the service-account posture:

```bash
sudo usermod --shell /usr/sbin/nologin bunnyland
sudo passwd -l bunnyland
```

## 2. Web client install

The current web client is a static snapshot/live inspector. It has no build step.

```bash
sudo -u bunnyland git clone https://github.com/thalismind/bunnyland-web.git /opt/bunnyland/web
```

Deploy-specific web client settings should live outside the web checkout so `git pull` stays
clean:

```bash
sudo tee /var/www/bunnyland/config.json >/dev/null <<'JSON'
{
  "serverUrl": "https://sandbox.example.com/api/",
  "autoConnect": true
}
JSON
sudo chown www-data:www-data /var/www/bunnyland/config.json
sudo chmod 0644 /var/www/bunnyland/config.json
```

For a local smoke test without nginx:

```bash
cd /opt/bunnyland/web
sudo -u bunnyland ./serve.sh 8080
```

## 2.1 Optional homepage install

The project homepage is also static and has no build step:

```bash
sudo -u bunnyland git clone https://github.com/thalismind/bunnyland-home.git /opt/bunnyland/home
```

The example nginx config below serves this at `https://example.com/` and redirects
`https://home.example.com/` to the apex domain.

## 3. Choose plugins and create a world

By default, `bunnyland serve` loads every builtin plugin whose `default_enabled` flag is
set. To restrict the surface, pass every plugin you want with repeated `--plugin` flags.
Required dependencies are checked and ordered, but they are not auto-loaded yet. See
[admin & controllers](./#plugins) for the canonical plugin list and
[world creation](../developer/world-creation.md) for generator names.

Create a new long-running world with the defaults:

```bash
sudo -u bunnyland bash -lc '
cd /opt/bunnyland/server
set -a
. /etc/bunnyland/server.env
set +a
exec /opt/bunnyland/.local/bin/uv run --extra server --extra llm bunnyland serve \
  --llm \
  --generator recursive \
  --seed "a mossy rabbit village under an old observatory" \
  --max-rooms 8 \
  --ticks 0 \
  --tick-seconds 30 \
  --time-scale 1800 \
  --api-host 127.0.0.1 \
  --api-port 8765 \
  --save /var/lib/bunnyland/worlds/main.json \
  --autosave-every 20
'
```

To use OpenRouter for character controllers or world generation, keep `OPENROUTER_API_KEY`
in `/etc/bunnyland/server.env` and add the OpenRouter provider flags.

```bash
sudo -u bunnyland bash -lc '
cd /opt/bunnyland/server
set -a
. /etc/bunnyland/server.env
set +a
exec /opt/bunnyland/.local/bin/uv run --extra server --extra llm bunnyland serve \
  --llm \
  --generator recursive \
  --llm-provider openrouter \
  --worldgen-provider openrouter \
  --worldgen-model openai/gpt-4.1 \
  --character-model openai/gpt-4.1-mini \
  --ticks 0 \
  --api-host 127.0.0.1 \
  --api-port 8765 \
  --save /var/lib/bunnyland/worlds/main.json \
  --autosave-every 20
'
```

Create a smaller curated server surface:

```bash
sudo -u bunnyland bash -lc '
cd /opt/bunnyland/server
set -a
. /etc/bunnyland/server.env
set +a
exec /opt/bunnyland/.local/bin/uv run --extra server --extra llm bunnyland serve \
  --plugin bunnyland.core_verbs \
  --plugin bunnyland.worldgen \
  --plugin bunnyland.lifesim \
  --plugin bunnyland.memory \
  --plugin bunnyland.social \
  --plugin bunnyland.policy \
  --llm \
  --generator recursive \
  --seed "a quiet burrow commons" \
  --ticks 0 \
  --api-host 127.0.0.1 \
  --api-port 8765 \
  --save /var/lib/bunnyland/worlds/main.json \
  --autosave-every 20
'
```

Install an external plugin wheel, then select one of its entry-point plugins:

```bash
sudo -u bunnyland /opt/bunnyland/.local/bin/uv pip install \
  --python /opt/bunnyland/server/.venv/bin/python /path/to/module-foo.whl
sudo -u bunnyland /opt/bunnyland/server/.venv/bin/bunnyland serve \
  --plugin module_foo.bar \
  --plugin bunnyland.core_verbs \
  --plugin bunnyland.worldgen \
  --ticks 0 \
  --api-host 127.0.0.1 \
  --api-port 8765
```

The wheel must declare `module_foo.bar` in the `bunnyland.plugins` entry-point group.
The server never imports a sibling checkout or invents a namespace from a module alias.

Resume an existing world:

```bash
sudo -u bunnyland /opt/bunnyland/.local/bin/uv run --extra server --extra llm bunnyland serve \
  --load /var/lib/bunnyland/worlds/main.json \
  --save /var/lib/bunnyland/worlds/main.json \
  --ticks 0 \
  --api-host 127.0.0.1 \
  --api-port 8765
```

## 4. Run the server with systemd

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
EnvironmentFile=/etc/bunnyland/server.env
ExecStart=/opt/bunnyland/.local/bin/uv run --extra server --extra llm bunnyland serve --llm --generator recursive --max-rooms 8 --ticks 0 --tick-seconds 30 --time-scale 1800 --api-host 127.0.0.1 --api-port 8765 --save /var/lib/bunnyland/worlds/main.json --autosave-every 20 --auth-users-file /etc/bunnyland/auth-users.yml --token-db /var/lib/bunnyland/auth-tokens.sqlite3
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Create the application user inventory before starting the service. Generate the Argon2 hash
with `bunnyland auth hash-password`, then place it in the private YAML file:

```bash
sudo install -d -o bunnyland -g bunnyland -m 0700 /etc/bunnyland
sudo -u bunnyland /opt/bunnyland/.local/bin/uv run --directory /opt/bunnyland/server \
  bunnyland auth hash-password
sudoedit /etc/bunnyland/auth-users.yml
sudo chown bunnyland:bunnyland /etc/bunnyland/auth-users.yml
sudo chmod 0600 /etc/bunnyland/auth-users.yml
```

```yaml
users:
  - username: editor
    password_hash: '$argon2id$...'
    enabled: true
    scopes: [world:play, world:admin]
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bunnyland
sudo systemctl status bunnyland
curl -fsS http://127.0.0.1:8765/health
```

## 5. Configure nginx

Serve the homepage at the apex domain, serve the web client at the sandbox domain, and proxy
the Bunnyland API under `/api` on the sandbox domain.

Create the websocket upgrade map before enabling the site config. On Ubuntu, files in
`/etc/nginx/conf.d/*.conf` are included from nginx's `http` block, so this defines
`$connection_upgrade` for the proxy headers below:

```bash
sudo tee /etc/nginx/conf.d/bunnyland-upgrade-map.conf >/dev/null <<'NGINX'
map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}
NGINX
```

`$connection_upgrade` is not a built-in nginx variable; this `map` creates it. The map is
needed on any nginx version when the site config uses
`proxy_set_header Connection $connection_upgrade;`. If your distro or custom nginx config
does not include `/etc/nginx/conf.d/*.conf` from the `http` block, add the `map` directly
inside `http { ... }` instead.

Create `/etc/nginx/sites-available/bunnyland`:

```nginx
server {
    listen 80;
    server_name example.com;

    root /opt/bunnyland/home;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}

server {
    listen 80;
    server_name home.example.com;
    return 301 https://example.com$request_uri;
}

server {
    listen 80;
    server_name sandbox.example.com;

    root /opt/bunnyland/web;
    index index.html;

    location = /config.json {
        alias /var/www/bunnyland/config.json;
        default_type application/json;
        add_header Cache-Control "no-store" always;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8765/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Cookie $http_cookie;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 3600s;
    }
}
```

Enable and reload:

```bash
sudo ln -s /etc/nginx/sites-available/bunnyland /etc/nginx/sites-enabled/bunnyland
sudo nginx -t
sudo systemctl reload nginx
```

Add TLS with certbot or your normal certificate automation:

```bash
sudo certbot --nginx \
  -d example.com \
  -d home.example.com \
  -d sandbox.example.com \
  --agree-tos \
  -m admin@example.com \
  --redirect
```

After TLS is enabled, verify that the certbot-managed HTTPS server for
`sandbox.example.com` still contains the `/api/` proxy block and the `/config.json` alias.

## 6. Connect through the web client

Open `https://sandbox.example.com`.

Use `/api/` in the web client's **Server** field. Hosted browser clients require the API,
WebSocket, media, and configuration surfaces to share the page origin. Local development
should proxy `/api/` to a loopback server rather than configure a cross-origin API URL.

Sign in through the shared login dialog. The browser keeps the resulting secure HttpOnly
cookie and rotates it while active. Player clients use only the play zone; editors and
inspectors use the admin zone and its global stream. Run `scripts/vps-docker-verify` for
the exact anonymous, play, admin, and WebSocket checks. Use the deployed OpenAPI document
as the endpoint and payload reference.

If the page loads but **Connect Live** fails, check:

- the Server field includes `/api` when using the nginx config above;
- `https://sandbox.example.com/` serves the web checkout rather than the homepage or a 404;
- nginx has the websocket `Upgrade` and `Connection` headers;
- `/etc/nginx/conf.d/bunnyland-upgrade-map.conf` exists before running `nginx -t`;
- `bunnyland.service` is listening on `127.0.0.1:8765`;
- browser devtools do not show mixed-content errors from using `http://` on an HTTPS page.

## 7. Enable the firewall

Bind Bunnyland to localhost (`--api-host 127.0.0.1`) and expose it only through nginx.
Then allow SSH, HTTP, and HTTPS before enabling UFW:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 8765/tcp
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw --force enable
sudo ufw status verbose
```

Expected policy:

```text
Default: deny (incoming), allow (outgoing)
22/tcp ALLOW IN
80/tcp ALLOW IN
443/tcp ALLOW IN
8765/tcp DENY IN
```

Verify that nginx still reaches the app locally, but the app port is not public:

```bash
curl -fsS http://127.0.0.1:8765/public/health
curl -fsS https://sandbox.example.com/api/public/health
curl --connect-timeout 5 http://YOUR_VPS_PUBLIC_IP:8765/public/health || true
```

The last command should time out or fail. The public API should be available only through
`https://sandbox.example.com/api/`.
