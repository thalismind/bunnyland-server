# VPS admin setup guide

This guide covers a production-style Bunnyland install on a Linux VPS:

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

# Required only for the Discord bot.
# DISCORD_TOKEN=...
```

Keep this file readable only by root and the service user:

```bash
sudo chown root:bunnyland /etc/bunnyland/server.env
sudo chmod 0640 /etc/bunnyland/server.env
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
Required dependencies are checked and ordered, but they are not auto-loaded yet.

Common builtin plugin ids:

| Plugin id               | Use it for                                      |
|-------------------------|-------------------------------------------------|
| `bunnyland.core_verbs`  | movement, items, speech, sleeping, writing      |
| `bunnyland.worldgen`    | `oneshot` and `recursive` world generators      |
| `bunnyland.lifesim`     | hunger, thirst, relationships, pregnancy, birth |
| `bunnyland.memory`      | private notes and recall                        |
| `bunnyland.environment` | calendar, time of day, weather                  |
| `bunnyland.social`      | social bond updates from speech                 |
| `bunnyland.policy`      | boundaries and consent checks                   |
| `bunnyland.persona`     | traits, preferences, goals                      |
| `bunnyland.colonysim`   | jobs, reservations, ownership, crafting         |
| `bunnyland.barbariansim` | combat and fortification                       |
| `bunnyland.gardensim`   | crops, watering, fertilizer, harvesting         |
| `bunnyland.dragonsim`   | quests, factions, discovery                     |

Create a new long-running world with the defaults:

```bash
cd /opt/bunnyland/server
sudo -u bunnyland /opt/bunnyland/.local/bin/uv run --extra server --extra llm bunnyland serve \
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
```

Create a smaller curated server surface:

```bash
sudo -u bunnyland /opt/bunnyland/.local/bin/uv run --extra server --extra llm bunnyland serve \
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
```

Load an external plugin module and select one of its plugins:

```bash
sudo -u bunnyland /opt/bunnyland/.local/bin/uv run --extra server bunnyland serve \
  --import module_foo \
  --plugin bar \
  --plugin bunnyland.core_verbs \
  --plugin bunnyland.worldgen \
  --ticks 0 \
  --api-host 127.0.0.1 \
  --api-port 8765
```

Imported plugin ids are namespaced by module for world metadata, so
`--import module_foo --plugin bar` is recorded as `module_foo.bar`.

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
ExecStart=/opt/bunnyland/.local/bin/uv run --extra server --extra llm bunnyland serve --llm --generator recursive --max-rooms 8 --ticks 0 --tick-seconds 30 --time-scale 1800 --api-host 127.0.0.1 --api-port 8765 --save /var/lib/bunnyland/worlds/main.json --autosave-every 20
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
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

Create the editor password file:

```bash
sudo install -d -o root -g www-data -m 0750 /etc/nginx/bunnyland
sudo htpasswd -c /etc/nginx/bunnyland/world-editor.htpasswd editor
sudo chown root:www-data /etc/nginx/bunnyland/world-editor.htpasswd
sudo chmod 0640 /etc/nginx/bunnyland/world-editor.htpasswd
```

Add these `map`s once in nginx's `http` block. A clean way on Ubuntu is a file such as
`/etc/nginx/conf.d/bunnyland-upgrade-map.conf`:

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}
```

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

    location /api/admin/ {
        auth_basic "Bunnyland world editor";
        auth_basic_user_file /etc/nginx/bunnyland/world-editor.htpasswd;

        proxy_pass http://127.0.0.1:8765/admin/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8765/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
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

In the web client's **Server** field:

- use `https://sandbox.example.com/api/` when nginx proxies the API under `/api`;
- use `http://localhost:8765` when running both pieces locally;
- use `https://api.example.com` if you expose the API on a separate hostname.

Click **Connect Live**. The client first requests:

```text
GET /world/snapshot
```

through the configured base URL, then opens:

```text
WS /world/updates
```

for the initial snapshot and later typed events. If nginx is mounted at `/api`, those become
`/api/world/snapshot` and `/api/world/updates` externally.

Useful checks:

```bash
curl -fsS https://example.com/
curl -fsS -I https://home.example.com/
curl -fsS https://sandbox.example.com/config.json
curl -fsS https://sandbox.example.com/api/health
curl -fsS https://sandbox.example.com/api/world/snapshot
curl -i -X PATCH https://sandbox.example.com/api/admin/world
curl -fsS -u editor:YOUR_PASSWORD -X PATCH https://sandbox.example.com/api/admin/world \
  -H 'Content-Type: application/json' \
  --data '{"operations":[]}'
curl -i -X POST https://sandbox.example.com/api/admin/world/save
curl -fsS -u editor:YOUR_PASSWORD -X POST https://sandbox.example.com/api/admin/world/save
curl -fsS -u editor:YOUR_PASSWORD -X POST https://sandbox.example.com/api/admin/pause
curl -fsS -u editor:YOUR_PASSWORD -X POST https://sandbox.example.com/api/admin/resume
cd /opt/bunnyland/server
/opt/bunnyland/.local/bin/uv run --extra server python - <<'PY'
import asyncio
import json
import websockets

async def main():
    async with websockets.connect("wss://sandbox.example.com/api/world/updates") as ws:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(message["type"])

asyncio.run(main())
PY
```

The unauthenticated `PATCH` and save checks should return `401 Unauthorized`. The
authenticated empty patch should return JSON with the current `world_epoch`, and the
authenticated save should include the server-side save path.

If the page loads but **Connect Live** fails, check:

- the Server field includes `/api` when using the nginx config above;
- nginx has the websocket `Upgrade` and `Connection` headers;
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
curl -fsS http://127.0.0.1:8765/health
curl -fsS https://sandbox.example.com/api/health
curl --connect-timeout 5 http://YOUR_VPS_PUBLIC_IP:8765/health || true
```

The last command should time out or fail. The public API should be available only through
`https://sandbox.example.com/api/`.

## 8. Optional Docker deployment

The repository does not require Docker, but the server can run in a container. One simple
server image is:

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --extra server --extra llm --extra discord

CMD ["uv", "run", "bunnyland", "serve", "--ticks", "0", "--api-host", "0.0.0.0", "--api-port", "8765", "--save", "/data/worlds/main.json", "--autosave-every", "20"]
```

Example compose file:

```yaml
services:
  server:
    build: /opt/bunnyland/server
    env_file: /etc/bunnyland/server.env
    command:
      - uv
      - run
      - bunnyland
      - serve
      - --llm
      - --generator
      - recursive
      - --ticks
      - "0"
      - --api-host
      - 0.0.0.0
      - --api-port
      - "8765"
      - --save
      - /data/worlds/main.json
      - --autosave-every
      - "20"
    volumes:
      - /var/lib/bunnyland:/data
    ports:
      - "127.0.0.1:8765:8765"
    restart: unless-stopped

  web:
    image: nginx:alpine
    volumes:
      - /opt/bunnyland/web:/usr/share/nginx/html:ro
    ports:
      - "127.0.0.1:8080:80"
    restart: unless-stopped
```

You can keep the host nginx config above and change its web `root` to proxy or serve the
containerized web service, depending on how you prefer to manage static assets.

## 9. Connect Discord as a bot

The Discord frontend is an embedded MVP: run it from the same `bunnyland serve` process that
owns the game loop and API by adding `--discord`.

Create the Discord application:

1. Open the Discord Developer Portal and create an application.
2. Add a bot and copy its token.
3. Enable **Message Content Intent**.
4. Generate an OAuth2 URL with scope `bot` and permissions to read and send messages.
5. Invite the bot to your server.
6. Put the token in `/etc/bunnyland/server.env` as `DISCORD_TOKEN=...`.
7. Optionally set the startup claim:
   `BUNNYLAND_DISCORD_USER_ID=...`, `BUNNYLAND_DISCORD_CHANNEL_ID=...`, and
   `BUNNYLAND_DISCORD_CHARACTER=Juniper`.

Then add `--discord` to the existing `bunnyland.service` `ExecStart`. Keep only one process
responsible for advancing a given world file at a time.

If you skip the startup claim, a player can claim from Discord with `!claim [character]`.

Player commands currently exposed by the bot:

| Command             | Effect                  |
|---------------------|-------------------------|
| `!claim [name]`     | claim a suspended character |
| `!look`             | describe the current room and exits |
| `!move <direction>` | queue a move command    |
| `!take <name>`      | queue a take command    |
| `!say <text>`       | queue room speech       |
| `!help [topic]`     | help for humans, agents, or a specific verb |

## 10. Operating checklist

Before inviting players:

1. `systemctl status bunnyland` is healthy.
2. `curl -fsS http://127.0.0.1:8765/health` works on the VPS.
3. `curl -fsS https://sandbox.example.com/api/health` works through nginx.
4. The websocket returns an initial `snapshot` from `wss://sandbox.example.com/api/world/updates`.
5. The web client connects live with `https://sandbox.example.com/api/`.
6. `curl --connect-timeout 5 http://YOUR_VPS_PUBLIC_IP:8765/health` does not connect.
7. `sudo ufw status verbose` shows SSH, HTTP, HTTPS allowed and the app port denied.
8. `https://example.com/` serves the homepage, if deployed.
9. `https://home.example.com/` redirects to `https://example.com/`, if deployed.
10. `https://sandbox.example.com/config.json` contains the production server URL and `autoConnect`.
11. `/var/lib/bunnyland/worlds/main.json` is being autosaved.
12. Only one server process writes that world file.
13. If Discord is enabled, the bot responds and its Discord user ids are assigned to
   character controllers.
