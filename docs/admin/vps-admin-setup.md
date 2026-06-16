# VPS Docker setup guide

For a ready-to-run container deployment, keep the public edge in one frontend container and
keep the Bunnyland API private on the Compose network:

- `server`: runs `bunnyland serve` on `0.0.0.0:8765`, with no host port published;
- `frontend`: runs nginx, serves the static web checkout, and proxies `/api/` to
  `http://server:8765/`.

This avoids SNI/hostname ambiguity because only nginx binds public `80`/`443`. TLS SNI and
HTTP `Host` routing both happen in that frontend container. The server container only sees
plain HTTP from nginx over Docker DNS (`server:8765`).

The server repo owns the Compose files:

- `compose.yml` runs `ghcr.io/thalismind/bunnyland-server` and
  `ghcr.io/thalismind/bunnyland-web` with private service ports only;
- `compose.user.yml.template` is rendered by setup into `compose.user.yml`, which publishes
  the frontend port, sets the domain, binds the data directory, configures TLS/homepage and
  favicon mounts, loads an existing world when requested, and injects LLM, Discord, and
  optional MCP secrets for the full deployment;
- `deploy/nginx/frontend-tls.conf` and `deploy/nginx/frontend-tls-home.conf` are the TLS
  nginx templates mounted by the generated `compose.user.yml`.

The Compose service names are deliberately `server` and `frontend`. The frontend nginx
config proxies to `http://server:8765/`, which is Docker DNS for the server service. The
container images are `ghcr.io/thalismind/bunnyland-server` and
`ghcr.io/thalismind/bunnyland-web`.

## Requirements

Have these ready before running anything. The wizard requests a real Let's Encrypt
certificate partway through, and that step fails if your domain does not already point at
this server:

1. **A VPS or mini PC** running Ubuntu 24 or 26 with a public IP, where you log in as a user
   with `sudo` (the default `ubuntu` user on most cloud images is fine). Size it with **at
   least 2 CPU cores and 4 GB RAM** (the reasonable minimum); **4 cores / 8 GB is
   recommended**. Shared/managed hosting that cannot run your own containers will not work;
   most mini PCs do, though ChromaDB vector searches may be slower on low-end hardware.
2. **A domain name with a DNS A record** pointing at the VPS's public IP (add an `AAAA`
   record too if the VPS has IPv6). Create this first and wait for it to propagate —
   `getent ahosts your.domain` from the VPS should return the VPS's public IP before you
   continue.
3. **Inbound port 443 open** in your cloud provider's firewall / security group for normal
   HTTPS traffic, plus **port 22** for SSH (this is separate from the host firewall the
   setup configures). **Port 80** only needs to be reachable from the internet while certbot
   issues or renews the certificate — the standalone HTTP-01 challenge binds it briefly. A
   rerun that reuses an existing certificate does not need port 80.
4. **A container runtime with Compose support installed:** Docker, nerdctl, or Podman.
   On Ubuntu, install Docker Engine from Docker's external apt repository by following
   Docker's [Install using the repository](https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository)
   guide. Do not rely on the older Ubuntu `docker.io` package for this setup.
5. **For the full deployment only:** an [Ollama Cloud](https://ollama.com) API key, an
   OpenRouter API key, or both, depending on the LLM providers you choose. Discord
   deployments also need a Discord bot token; create and invite the bot with the
   [Discord bot guide](discord-bot.md#2-create-the-bot-in-discord).

You also choose an admin username and password during setup; these protect the world
editor. There is no recovery if you forget them — you simply rerun setup to reset them.

## Setup wizard

The fastest path is the setup wizard. It supports Debian and Ubuntu, detects an installed
Docker, nerdctl, or Podman runtime with Compose support, prompts for the required values,
lets you choose Ollama or OpenRouter for world generation and character controllers, writes
`compose.user.yml`, and starts the checked-in Compose files. If existing Bunnyland
containers are present, it asks before removing those containers. It does not delete bind
mounts or named volumes, and the lower-level setup script backs up the selected world save
before starting containers. The wizard also prompts for an optional non-default Ollama or
OpenRouter endpoint.

```bash
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y git
sudo install -d -m 0755 -o "$USER" -g "$USER" /opt/bunnyland
cd /opt/bunnyland
if [ ! -d server ]; then
  git clone https://github.com/thalismind/bunnyland-server.git server
fi
cd server
git pull --ff-only
scripts/vps-docker-wizard
```

The rest of this section shows the same setup in copy-pasteable steps. Start with a
container/routing smoke test if you need to isolate DNS, TLS, firewall, and admin auth.
That smoke test is not a complete Bunnyland deployment. The full deployment requires both
the LLM provider key and the Discord bot token.

## Offline smoke test

This starts the same server and frontend containers with deterministic/offline generation
and waiting controllers. It is only for proving that containers, routing, TLS, admin auth,
and persistence work before adding external services. It does not need
`OLLAMA_CLOUD_API_KEY`, `OPENROUTER_API_KEY`, or `DISCORD_TOKEN`.

### Run the smoke setup

Copy this block, change the values in the first section, and paste it into the VPS:

```bash
BUNNYLAND_DOMAIN='sandbox.example.com'
BUNNYLAND_DATA_DIR='/var/lib/bunnyland'
BUNNYLAND_ADMIN_USER='editor'
BUNNYLAND_ADMIN_PASSWORD='change-this'
BUNNYLAND_CERT_EMAIL='admin@example.com'

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y git
sudo install -d -m 0755 -o "$USER" -g "$USER" /opt/bunnyland
sudo install -d -m 0755 "$BUNNYLAND_DATA_DIR"
cd /opt/bunnyland
if [ ! -d server ]; then
  git clone https://github.com/thalismind/bunnyland-server.git server
fi
cd server
git pull --ff-only

BUNNYLAND_DOMAIN="$BUNNYLAND_DOMAIN" \
BUNNYLAND_DATA_DIR="$BUNNYLAND_DATA_DIR" \
BUNNYLAND_ADMIN_USER="$BUNNYLAND_ADMIN_USER" \
BUNNYLAND_ADMIN_PASSWORD="$BUNNYLAND_ADMIN_PASSWORD" \
BUNNYLAND_CERT_EMAIL="$BUNNYLAND_CERT_EMAIL" \
BUNNYLAND_ENABLE_LLM=0 \
BUNNYLAND_ENABLE_DISCORD=0 \
  scripts/vps-docker-setup
```

### Optional setup inputs

To start from an existing saved world, add `BUNNYLAND_WORLD_SAVE` to the setup command. If
the file is already under `BUNNYLAND_DATA_DIR`, the script loads it in place; otherwise it
copies the save into `$BUNNYLAND_DATA_DIR/worlds/` first. Before starting containers, the
script creates a timestamped backup next to the selected save file.

```bash
BUNNYLAND_WORLD_SAVE='/var/lib/bunnyland/worlds/main.json' \
```

To use a custom favicon, add `BUNNYLAND_FAVICON_FILE` to the setup command:

```bash
BUNNYLAND_FAVICON_FILE='/opt/bunnyland/favicon.png' \
```

To show a Discord invite on the web welcome page and in every client's menu, add
`BUNNYLAND_DISCORD_URL`. It must be empty or an `http(s)` URL. The frontend renders it into
`config.json` at container start, so changing it later only needs a rerun (or a
`compose.user.yml` edit) and a frontend restart — no image rebuild. Leave it unset and no
Discord link is shown anywhere.

```bash
BUNNYLAND_DISCORD_URL='https://discord.gg/your-invite' \
```

To serve a separate static homepage from the same frontend nginx container, add
`BUNNYLAND_HOME_DOMAIN` and `BUNNYLAND_HOME_DIR`. The homepage directory must contain its
own `index.html`. The setup script requests or reuses a separate Let's Encrypt certificate
for that domain and mounts the homepage nginx template in `compose.user.yml`:

```bash
BUNNYLAND_HOME_DOMAIN='example.com' \
BUNNYLAND_HOME_CERT_NAME='example.com' \
BUNNYLAND_HOME_DIR='/opt/bunnyland/home' \
```

### TLS and firewall behavior

The script uses only Let's Encrypt for public TLS certificate issuance. It never generates
self-signed certificates for the VPS Docker deployment. If matching certificates already
exist under `/etc/letsencrypt/live/`, the script reuses them; otherwise it stops the
frontend container and runs certbot's standalone authenticator for the app domain and,
when configured, the homepage domain. Port `80` must be reachable by Let's Encrypt while
certbot runs.

The script also configures UFW rules for the containerized deployment. It allows SSH, HTTP,
and HTTPS as normal inbound rules, denies direct public access to `8765`, and adds routed
`ALLOW FWD` rules for ports `80` and `443`. Those routed rules are required with
nerdctl/containerd because published container ports traverse the container bridge; without
them, `ufw status` can show `443/tcp ALLOW IN` while public HTTPS still times out.

The script does **not** enable UFW itself. If UFW is already active the new rules apply
immediately; otherwise they are staged and you turn the firewall on when ready with
`sudo ufw enable`. SSH on port `22` is allowed first, so enabling will not drop your
session. To skip the UFW step entirely (for example when the host firewall is managed
elsewhere), rerun setup with `BUNNYLAND_CONFIGURE_FIREWALL=0`.

### Verify the smoke test

After the smoke test, open `https://sandbox.example.com/`. The frontend renders
`/config.json` from its environment at container start; by default it points the browser at
same-origin `/api/` (and carries the optional `discordUrl`), so the web UI and API proxy
come up together.

Verify the public route and admin auth:

```bash
BUNNYLAND_DOMAIN='sandbox.example.com' \
BUNNYLAND_ADMIN_USER='editor' \
BUNNYLAND_ADMIN_PASSWORD='change-this' \
  scripts/vps-docker-verify
```

The verifier checks the web client, world editor, `/config.json`, `/api/health`,
`/api/world/snapshot`, websocket upgrades through `/api/world/updates`, admin rejection
with bad credentials (`401`), and admin success with the supplied credentials (`200`).

## Full deployment

### Ollama provider

Run one full setup command with the required external service credentials. The wizard
prompts for the same provider choice. Ollama is the default provider and uses one
`OLLAMA_CLOUD_API_KEY` for both world generation and LLM character controllers. World
generation defaults to `deepseek-v4-pro`; character controllers default to
`deepseek-v4-flash`.

Keep the same domain, data directory, admin credentials, and any
world/homepage/favicon settings you used in the smoke test. The setup script formats
`compose.user.yml` from `compose.user.yml.template`; after that, `compose.user.yml` is the
only deployment-specific Compose file an admin should edit.

```bash
BUNNYLAND_DOMAIN='sandbox.example.com' \
BUNNYLAND_DATA_DIR='/var/lib/bunnyland' \
BUNNYLAND_ADMIN_USER='editor' \
BUNNYLAND_ADMIN_PASSWORD='change-this' \
BUNNYLAND_CERT_EMAIL='admin@example.com' \
BUNNYLAND_ENABLE_LLM=1 \
BUNNYLAND_STARTER_PACK='peaceful' \
OLLAMA_CLOUD_API_KEY='sk-...' \
OLLAMA_HOST='https://ollama.com' \
BUNNYLAND_WORLDGEN_MODEL='deepseek-v4-pro' \
BUNNYLAND_CHARACTER_MODEL='deepseek-v4-flash' \
BUNNYLAND_ENABLE_DISCORD=1 \
DISCORD_TOKEN='...' \
  scripts/vps-docker-setup
```

### OpenRouter provider

To drive world generation and character controllers through OpenRouter, choose OpenRouter
in the wizard or set `BUNNYLAND_WORLDGEN_PROVIDER=openrouter`,
`BUNNYLAND_LLM_PROVIDER=openrouter`, and `OPENROUTER_API_KEY`.

```bash
BUNNYLAND_DOMAIN='sandbox.example.com' \
BUNNYLAND_DATA_DIR='/var/lib/bunnyland' \
BUNNYLAND_ADMIN_USER='editor' \
BUNNYLAND_ADMIN_PASSWORD='change-this' \
BUNNYLAND_CERT_EMAIL='admin@example.com' \
BUNNYLAND_ENABLE_LLM=1 \
BUNNYLAND_GENERATOR='recursive' \
BUNNYLAND_STARTER_PACK='fantastic' \
BUNNYLAND_WORLDGEN_PROVIDER='openrouter' \
BUNNYLAND_LLM_PROVIDER='openrouter' \
OPENROUTER_API_KEY='sk-or-...' \
BUNNYLAND_WORLDGEN_MODEL='openai/gpt-4.1' \
BUNNYLAND_CHARACTER_MODEL='openai/gpt-4.1-mini' \
BUNNYLAND_ENABLE_DISCORD=1 \
DISCORD_TOKEN='...' \
  scripts/vps-docker-setup
```

### Discord startup assignment

If you are loading an existing world, keep `BUNNYLAND_WORLD_SAVE` in that command so setup
continues to point Compose at that save file.

Both full setup examples start the Discord bot with `DISCORD_TOKEN`. To assign a Discord
user to a character at startup, add the numeric user id, channel id, and character name to
the same setup command:

```bash
BUNNYLAND_DISCORD_USER_ID='123' \
BUNNYLAND_DISCORD_CHANNEL_ID='456' \
BUNNYLAND_DISCORD_CHARACTER='Juniper' \
```

If these are omitted, the bot still starts and users can claim from Discord with `!claim`.

At this point the VPS is running the full Bunnyland deployment: web client, private server
API, LLM-backed character controllers, and optionally the Discord bot.

### Optional MCP endpoint

The MCP server is disabled by default. To expose it on the VPS, set both the enable flag
and a strong MCP admin token when running setup:

```bash
BUNNYLAND_ENABLE_MCP=1 \
BUNNYLAND_ADMIN_TOKEN='change-this-long-random-token' \
  scripts/vps-docker-setup
```

The setup wizard can also prompt for these values. When enabled, setup writes
`BUNNYLAND_ENABLE_MCP=1` and `BUNNYLAND_ADMIN_TOKEN` into the private `compose.user.yml`
(on both the server and the frontend, since nginx injects the token), starts `bunnyland
serve` with `--mcp`, and keeps the server on the same private `8765` service port. The same
token gates the admin world projections and the `/world/updates` map stream: nginx Basic-auth
protects those paths under one realm and injects `X-Bunnyland-Admin-Token` after login, so a
single browser login also authorizes the same-origin WebSocket.

The public MCP URL is:

```text
https://sandbox.example.com/api/mcp
```

The checked-in nginx templates protect `/api/mcp` with the same htpasswd file as the world
editor before proxying to the backend `/mcp` endpoint. MCP admin tools still require the
MCP admin token as a tool argument. See [MCP server](mcp-server.md) for client setup,
tools, resources, and event notifications.

### Verify Discord

Test through Discord:

1. In the invited channel, send `!characters`.
2. Claim a suspended character with `!claim Character Name`, or just `!claim` to claim the
   first claimable character.
3. Send `!look`.
4. Send a small command such as `!say hello`.

Check the server logs if the bot does not respond:

```bash
sudo nerdctl logs bunnyland-server-1
```

If you used Docker or Podman instead of nerdctl, use `sudo docker logs bunnyland-server-1`
or `sudo podman logs bunnyland-server-1`.

## Operations

The setup script starts `compose.yml` plus generated `compose.user.yml`. User-specific
settings, secrets, image tags, bind mounts, TLS/homepage/favicon settings, world loading,
LLM provider, Discord, and MCP settings are written into `compose.user.yml`.

If the same frontend container also serves a static homepage, include the homepage domain
and expected text:

```bash
BUNNYLAND_DOMAIN='sandbox.example.com' \
BUNNYLAND_ADMIN_USER='editor' \
BUNNYLAND_ADMIN_PASSWORD='change-this' \
BUNNYLAND_HOME_DOMAIN='example.com' \
BUNNYLAND_HOME_EXPECT_TEXT='A social simulation sandbox built as an ECS graph.' \
  scripts/vps-docker-verify
```

The generated `compose.user.yml` contains deployment knobs and secrets. Keep it out of
source control.

### Update deployment

To update an existing VPS deployment to the latest checked-in Compose and nginx templates,
pull the server repo and rerun the restart script:

```bash
cd /opt/bunnyland/server
git pull --ff-only
scripts/vps-docker-restart
```

The restart script pulls updated container images before applying the deployment, so this is
the normal update path for new server/web images and checked-in deployment script changes.

### Reapply config changes

To change LLM provider keys, optional provider endpoints, Discord token, MCP token, image
tags, tick timing, or similar settings that already exist in `compose.user.yml`, edit that
file and then reapply the Compose deployment:

```bash
scripts/vps-docker-restart
```

Set `BUNNYLAND_CONTAINER_RUNTIME` if you want to force the same runtime used during setup:

```bash
BUNNYLAND_CONTAINER_RUNTIME=nerdctl scripts/vps-docker-restart
```

The restart script validates `compose.user.yml`, pulls updated images, and runs Compose
`up -d` with the checked-in `compose.yml` plus the generated `compose.user.yml`. It
intentionally does not run a plain Compose `restart`, because `restart` can keep old
container configuration after secrets or environment values change. If you use Docker or
Podman instead of nerdctl, set
`BUNNYLAND_CONTAINER_RUNTIME=docker` or `BUNNYLAND_CONTAINER_RUNTIME=podman`.

### Rerun setup for generated files

Rerun `scripts/vps-docker-setup` instead when changing values that need generated files or
host-side setup: public domain, admin username/password, data directory, favicon, homepage,
world save, TLS settings, or firewall setup. The setup script rewrites `compose.user.yml`.

`scripts/vps-docker-setup` requires `BUNNYLAND_ADMIN_USER` and `BUNNYLAND_ADMIN_PASSWORD` on
every run and regenerates the world-editor htpasswd from them. To rerun without resupplying
the password and keep the existing login, set `BUNNYLAND_REUSE_ADMIN=1` and omit both admin
variables. Reuse keeps the stored htpasswd as-is and cannot validate it, so run
`scripts/vps-docker-verify` afterward to confirm the admin login still works.

### Renew TLS certificates

To renew Let's Encrypt certificates with the same standalone method, stop the frontend
while certbot binds port `80`, then start it again:

```bash
sudo nerdctl compose --env-file /dev/null -p bunnyland -f compose.yml -f compose.user.yml stop frontend
sudo certbot renew --standalone
sudo nerdctl compose --env-file /dev/null -p bunnyland -f compose.yml -f compose.user.yml up -d frontend
```

### Image tags

The published containers are tagged by branch. For normal VPS installs, keep
`BUNNYLAND_SERVER_TAG=main` and `BUNNYLAND_WEB_TAG=main`; use another branch name only when
testing a branch-specific deployment.

### External TLS termination

If TLS terminates somewhere else, rerun setup with `BUNNYLAND_TLS=0` and
`BUNNYLAND_HTTP_BIND=127.0.0.1:8080`. Setup then skips certbot, omits the `443`
listener and cert mounts, publishes only `127.0.0.1:8080:80`, and you point the outer proxy
at the frontend container. Keep the `/api/` proxy in the frontend nginx config so the
browser always loads the web page and API from the same external origin.

### Public bot traffic

Assume that bots will start probing and scraping the site shortly after it has a public IP
address or DNS record. If you want a free front-door mitigation, one common option is to put
the domain behind Cloudflare DNS in proxied mode and enable
[Bot Fight Mode](https://developers.cloudflare.com/bots/get-started/bot-fight-mode/). Bot
Fight Mode protects the whole domain, so test the web client, websocket, and admin routes
after enabling it; if it challenges legitimate API traffic, disable it or move to a more
configurable bot-management setup.

### Clear CDN cache

If the domain is proxied through Cloudflare and a deploy appears to serve stale JavaScript,
CSS, images, or `config.json`, clear Cloudflare's cache before debugging the containers.
Use Cloudflare's cache purge option for the affected URL when you know the stale asset, or
purge everything after broad frontend/static-asset changes. This clears Cloudflare's edge
cache, but visitors may still need to refresh their browser cache.

## Operating checklist

Before inviting players:

1. Your selected runtime shows `bunnyland-server-1` and `bunnyland-frontend-1` running:
   `sudo nerdctl ps`, `sudo docker ps`, or `sudo podman ps`.
2. `curl -fsS https://sandbox.example.com/api/health` works through the frontend container.
3. The websocket returns an initial `snapshot` from `wss://sandbox.example.com/api/world/updates`.
4. The web client connects live with `https://sandbox.example.com/api/`.
5. `curl --connect-timeout 5 http://YOUR_VPS_PUBLIC_IP:8765/health` does not connect.
6. `sudo ufw status verbose` shows SSH, HTTP, HTTPS allowed, `80/tcp` and `443/tcp`
   allowed for forwarded traffic, and the app port denied. If it reports `Status: inactive`,
   the rules are staged but the firewall is off — enable it with `sudo ufw enable`.
7. `https://example.com/` serves the homepage, if deployed.
8. `https://sandbox.example.com/config.json` contains the production server URL and `autoConnect`.
9. The selected world save under `BUNNYLAND_DATA_DIR` is being autosaved.
10. Only one server container writes that world file.
11. If Discord is enabled, the bot responds and its Discord user ids are assigned to
    character controllers.
