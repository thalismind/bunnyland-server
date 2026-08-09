# Server setup

This series takes a community host from a loopback-only Bunnyland process to a secure,
recoverable public service. Start locally even if the final destination is a VPS: it separates
application problems from DNS, TLS, proxy, and firewall problems.

The primary path uses a native Python environment, `systemd`, and nginx. Published server and
web containers are a supported packaging alternative, but the same boundaries still apply:
the Bunnyland API stays private, nginx exposes one TLS origin, credentials stay outside source
control, and server and web versions move together. The retired generic VPS installer is not
part of this sequence.

## The sequence

1. **Server setup overview** — choose a topology and establish the safety rules on this page.
2. **[Install and run your first server](running-a-server.md)** — prove the game loop and API
   locally.
3. **[Config wizard](config-wizard.md)** — create and validate durable configuration.
4. **[Authentication, permissions, and moderation](authentication-permissions-moderation.md)**
   — create human and automation principals with the smallest useful scopes.
5. **[Hosting the web client securely](hosting-web-client.md)** — run the service with
   `systemd`, serve the web client and API from one nginx origin, add TLS, and close the
   application port.
6. **[Worlds, plugins, persistence, and snapshots](worlds-plugins-persistence.md)** — choose
   mechanics, save state, and practice snapshot handling.
7. **[LLM providers and character controllers](llm-providers-controllers.md)** — add provider
   credentials and choose which actors may spend model budget.
8. **[Discord bot](discord-bot.md)** — safely connect a community Discord server.
9. **[MCP server and local agents](mcp-local-agent.md)** — give local agent clients scoped
   access without embedding bearer tokens in prompts or tool arguments.
10. **[Image generation](image-generation.md)** — add ComfyUI, OpenRouter, storage, and public
    media URLs deliberately.
11. **[Backups, upgrades, observability, and recovery](backups-upgrades-observability.md)** —
    encrypt backups, restore on a clean host, upgrade server and web together, and monitor the
    service without turning expensive audits into a hot-path cost.

Follow the order for a new public host. Existing operators can enter at the relevant page, but
should still complete the recovery drill before calling a deployment production-ready.

## Recommended topology

```text
browser / Discord / MCP client
             |
        HTTPS :443
             |
            nginx  ── static Bunnyland web files
             |
       /api/ on the same origin
             |
      127.0.0.1:8765
             |
      Bunnyland server ── private data, snapshots, token database, media
```

Use a dedicated unprivileged operating-system account. Bind Bunnyland to `127.0.0.1`; only
nginx should listen publicly. The public browser configuration should use `/api/`, not a
second cross-origin hostname. That preserves secure cookies, WebSocket origin checks, and the
single authorization model.

For a home server behind a router, forward only TCP 80 and 443 to nginx. Do not forward 8765,
the OpenTelemetry exporter, a local model server, ComfyUI, or a database port. If your ISP
uses carrier-grade NAT, use a reputable tunnel or a VPS reverse proxy with equivalent TLS and
origin controls; do not make the application listener public to work around it.

## Security rules used throughout

- Put passwords, bearer tokens, provider keys, Discord tokens, TLS private keys, and backup
  keys in files readable only by the service account. Never put them in Git, command history,
  URLs, screenshots, world snapshots, or MCP arguments.
- Give players `world:play`. Give `world:admin` only to operators and tightly controlled
  automation. Client-ID allowlists are an extra policy check, not authentication.
- Keep snapshots, the token SQLite database, persistent memory, controller definitions, and
  generated media on durable storage. Back them up as one consistency set.
- Terminate TLS at the reverse proxy and forward `Authorization`, cookies,
  `X-Bunnyland-Client-Id`, and WebSocket upgrade headers unchanged.
- Test changes on a copy of the world. Keep the previous server/web pair and a verified
  pre-upgrade backup until the new pair has passed login, play, admin-denial, WebSocket, and
  persistence checks.

## Native or containers?

The native path is easiest to understand and debug: a checked-out release, a locked `uv`
environment, a `systemd` unit, and static web files behind nginx. It also makes every path in
the following examples explicit.

Published images at `ghcr.io/thalismind/bunnyland-server` and
`ghcr.io/thalismind/bunnyland-web` are an alternative when you already operate Docker,
Podman, or containerd. Pin immutable image digests, mount the data and credential paths, keep
the server container off public ports, and upgrade both images as one release. The repository
Compose files are useful examples; review them and supply your own host policy instead of
running the retired generic VPS installer.

## Before continuing

You need a supported Linux host, Python 3.12–3.14, `git`, and
[`uv`](https://docs.astral.sh/uv/). Public hosting additionally needs a DNS name, nginx (or an
equivalent reverse proxy), a TLS certificate path, and an operator who can test restores.

**Next:** [Install and run your first server →](running-a-server.md)
