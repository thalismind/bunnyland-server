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
  favicon mounts, loads an existing world when requested, and injects LLM/Discord
  secrets for the full deployment;
- `deploy/nginx/frontend-tls.conf` and `deploy/nginx/frontend-tls-home.conf` are the TLS
  nginx templates mounted by the generated `compose.user.yml`.

The Compose service names are deliberately `server` and `frontend`. The frontend nginx
config proxies to `http://server:8765/`, which is Docker DNS for the server service. The
container images are `ghcr.io/thalismind/bunnyland-server` and
`ghcr.io/thalismind/bunnyland-web`.

## Before you start

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
   deployments also need a Discord bot token. Creating the Discord application is described in
   [Full Bunnyland Deployment](#2-full-bunnyland-deployment) below.

You also choose an admin username and password during setup; these protect the world
editor. There is no recovery if you forget them — you simply rerun setup to reset them.

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

## 1. Container Smoke Test

This starts the same server and frontend containers with deterministic/offline generation
and waiting controllers. It is only for proving that containers, routing, TLS, admin auth,
and persistence work before adding external services. It does not need
`OLLAMA_CLOUD_API_KEY`, `OPENROUTER_API_KEY`, or `DISCORD_TOKEN`.

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

To serve a separate static homepage from the same frontend nginx container, add
`BUNNYLAND_HOME_DOMAIN` and `BUNNYLAND_HOME_DIR`. The homepage directory must contain its
own `index.html`. The setup script requests or reuses a separate Let's Encrypt certificate
for that domain and mounts the homepage nginx template in `compose.user.yml`:

```bash
BUNNYLAND_HOME_DOMAIN='example.com' \
BUNNYLAND_HOME_CERT_NAME='example.com' \
BUNNYLAND_HOME_DIR='/opt/bunnyland/home' \
```

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

After the smoke test, open `https://sandbox.example.com/`. The frontend image ships a
default `/config.json` that points the browser at same-origin `/api/`, so the web UI and
API proxy come up together.

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

## 2. Full Bunnyland Deployment

Create the Discord application:

1. Open the Discord Developer Portal and create an application.
2. Open the **Bot** tab, use **Reset Token**, and copy the new token.
3. Enable **Message Content Intent**.
4. Generate an OAuth2 URL with scope `bot` and permissions **View Channels**,
   **Read Message History**, and **Send Messages**.
5. Invite the bot to your server.

Then run one full setup command with the required external service credentials. The wizard
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
OLLAMA_CLOUD_API_KEY='sk-...' \
OLLAMA_HOST='https://ollama.com' \
BUNNYLAND_WORLDGEN_MODEL='deepseek-v4-pro' \
BUNNYLAND_CHARACTER_MODEL='deepseek-v4-flash' \
BUNNYLAND_ENABLE_DISCORD=1 \
DISCORD_TOKEN='...' \
  scripts/vps-docker-setup
```

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
BUNNYLAND_WORLDGEN_PROVIDER='openrouter' \
BUNNYLAND_LLM_PROVIDER='openrouter' \
OPENROUTER_API_KEY='sk-or-...' \
BUNNYLAND_WORLDGEN_MODEL='openai/gpt-4.1' \
BUNNYLAND_CHARACTER_MODEL='openai/gpt-4.1-mini' \
BUNNYLAND_ENABLE_DISCORD=1 \
DISCORD_TOKEN='...' \
  scripts/vps-docker-setup
```

If you are loading an existing world, keep `BUNNYLAND_WORLD_SAVE` in that command so setup
continues to point Compose at that save file.

To assign a Discord user to a character at startup, add the numeric user id, channel id,
and character name to the same full setup command. If these are omitted, the bot still
starts and users can claim from Discord with `!claim`.

```bash
BUNNYLAND_DOMAIN='sandbox.example.com' \
BUNNYLAND_DATA_DIR='/var/lib/bunnyland' \
BUNNYLAND_ADMIN_USER='editor' \
BUNNYLAND_ADMIN_PASSWORD='change-this' \
BUNNYLAND_CERT_EMAIL='admin@example.com' \
BUNNYLAND_ENABLE_LLM=1 \
OLLAMA_CLOUD_API_KEY='sk-...' \
BUNNYLAND_ENABLE_DISCORD=1 \
DISCORD_TOKEN='...' \
BUNNYLAND_DISCORD_USER_ID='123' \
BUNNYLAND_DISCORD_CHANNEL_ID='456' \
BUNNYLAND_DISCORD_CHARACTER='Juniper' \
  scripts/vps-docker-setup
```

At this point the VPS is running the full Bunnyland deployment: web client, private server
API, LLM-backed character controllers, and optionally the Discord bot.

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

The script starts the checked-in Compose files:

- `compose.yml`;
- generated `compose.user.yml`, rendered from `compose.user.yml.template`.

The base `compose.yml` is the basic offline web/API deployment. User-specific settings,
secrets, image tags, bind mounts, TLS/homepage/favicon settings, world loading, LLM
provider, and Discord are written into `compose.user.yml`.

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
source control. Change the public domain, admin username/password, data directory, favicon,
homepage, world save, LLM provider/key, optional provider endpoint, or Discord token by
rerunning setup with the new value. The setup script rewrites `compose.user.yml`.

`scripts/vps-docker-setup` requires `BUNNYLAND_ADMIN_USER` and `BUNNYLAND_ADMIN_PASSWORD` on
every run and regenerates the world-editor htpasswd from them. To rerun without resupplying
the password and keep the existing login, set `BUNNYLAND_REUSE_ADMIN=1` and omit both admin
variables. Reuse keeps the stored htpasswd as-is and cannot validate it, so run
`scripts/vps-docker-verify` afterward to confirm the admin login still works.

To renew Let's Encrypt certificates with the same standalone method, stop the frontend
while certbot binds port `80`, then start it again:

```bash
sudo nerdctl compose --env-file /dev/null -p bunnyland -f compose.yml -f compose.user.yml stop frontend
sudo certbot renew --standalone
sudo nerdctl compose --env-file /dev/null -p bunnyland -f compose.yml -f compose.user.yml up -d frontend
```

The published containers are tagged by branch. For normal VPS installs, keep
`BUNNYLAND_SERVER_TAG=main` and `BUNNYLAND_WEB_TAG=main`; use another branch name only when
testing a branch-specific deployment.

If TLS terminates somewhere else, rerun setup with `BUNNYLAND_TLS=0` and
`BUNNYLAND_HTTP_BIND=127.0.0.1:8080`. Setup then skips certbot, omits the `443`
listener and cert mounts, publishes only `127.0.0.1:8080:80`, and you point the outer proxy
at the frontend container. Keep the `/api/` proxy in the frontend nginx config so the
browser always loads the web page and API from the same external origin.

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
