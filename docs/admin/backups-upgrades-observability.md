# Backups, upgrades, observability, and recovery

Production readiness means you can lose the host, rebuild it, restore the world, and explain
what version is running. A backup is not proven until a clean-host restore has passed.

## Prerequisites

Complete [image generation](image-generation.md), or record that image generation is disabled.
Identify every durable path from the world/persistence guide and the exact server and web
revisions currently deployed. Install an authenticated encryption tool such as
[`age`](https://age-encryption.org/) and keep its private recovery key off the server.

## Back up one consistency set

Quiesce writes with a maintenance window and clean service stop:

```bash
sudo systemctl stop bunnyland
sudo tar -C /var/lib -czf - bunnyland \
  | age -r AGE_RECIPIENT \
  > bunnyland-$(date -u +%Y%m%dT%H%M%SZ).tar.gz.age
sudo systemctl start bunnyland
curl -i https://play.example.com/api/v1/public/health
```

Store alongside the encrypted archive:

- a SHA-256 checksum of the encrypted file;
- the server commit/package version and web commit/package version;
- enabled plugins/add-ons and their versions;
- a redacted copy of non-secret configuration;
- the UTC backup time and whether the final save completed.

Back up at least the world snapshot, token SQLite database, persistent memory, controller
definitions, and generated media. Back up the private user inventory and service config in a
separate encrypted operator bundle. Never put the backup decryption key in either archive.

Keep multiple generations and an off-host copy. Test retention by deleting an expired backup
from a disposable backup bucket, not by experimenting on the only copy.

## Restore on a clean host

Practice this before an emergency:

1. Build a new host with the same OS-level service account and directory permissions.
2. Install the exact recorded server and web revisions without starting them.
3. Verify the encrypted archive checksum.
4. Decrypt and restore into an empty staging directory.
5. Check file ownership, mode, available disk space, and expected durable paths.
6. Start Bunnyland on loopback with the restored world and `--load-paused`.
7. Verify health, login, a play-scoped action, admin denial for that player, admin access for
   an operator, WebSocket reconnect, token metadata, memory, and media.
8. Resume ticks, make one disposable state change, save, restart, and verify the change.
9. Only then switch DNS/proxy traffic or declare the restore usable.

Example decryption into an empty staging directory:

```bash
install -d -m 0700 restore
age --decrypt -i /secure/off-host/recovery.key backup.tar.gz.age \
  | tar -C restore -xzf -
```

Do not restore over a running data directory. Preserve the failed/current directory until the
restored copy is independently verified.

## Upgrade server and web as a pair

The server owns the API contract and the web client consumes it. Treat them as one tested
release even when only one repository changed.

1. Read both release diffs and migration notes.
2. Build/test the candidate server and web revisions on a copy of production state.
3. Create and verify an encrypted pre-upgrade backup.
4. Stop the service and retain the previous server environment, previous web `dist/`, and
   previous immutable container digests.
5. Install the candidate server and web together.
6. Migrate a copy of an older snapshot when required; never overwrite the backup source.
7. Start on loopback, run the restore checks, then reload nginx.
8. Keep the previous pair and backup until the new pair survives a save/restart cycle.

For containers, update both immutable `@sha256:` references in one reviewed change and pull
before the maintenance window. For native installs, create a new environment or release
directory instead of mutating the only working environment in place.

## Roll back safely

If the candidate fails before writing new state, stop it and restore the previous server/web
pair. If it saved or migrated state, restore the verified pre-upgrade data set as well; an old
binary may not understand a newly written schema. Never point both old and new servers at the
same writable data directory.

After rollback, repeat health, authentication, least-privilege, WebSocket, save/restart,
memory, and media checks. Record what was rolled back and which backup was restored.

## Logs and health

For a native `systemd` service:

```bash
sudo journalctl -u bunnyland --since "30 minutes ago"
sudo journalctl -u bunnyland -f
curl -i http://127.0.0.1:8765/v1/public/health
curl -i https://play.example.com/api/v1/public/health
```

Bound log retention at the host and central collector. Do not record credentials, cookies,
claim secrets, bearer headers, private memory, or full prompts. Health returning `204` proves
the HTTP process is ready; it does not prove login, authorization, WebSocket, providers,
persistence, or backups, so schedule those narrower synthetic checks separately.

For containers, collect the runtime's bounded service logs and inspect restart counts, health,
disk usage, and exact image digests. Avoid unbounded debug logging on a public server.

## Optional OpenTelemetry

Install the extra, then opt in explicitly:

```bash
uv sync --locked --extra server --extra otel
```

```text
BUNNYLAND_OTEL_ENABLED=1
OTEL_SERVICE_NAME=bunnyland
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4317
```

Standard `OTEL_*` variables configure OTLP protocol and protected exporter headers. Keep the
collector private. Content capture is off by default; leave it off unless you have a specific,
disclosed diagnostic need and protected retention.

To expose metrics to a private local Prometheus scrape:

```text
OTEL_METRICS_EXPORTER=prometheus
OTEL_EXPORTER_PROMETHEUS_HOST=127.0.0.1
OTEL_EXPORTER_PROMETHEUS_PORT=9464
```

Do not add this listener to nginx or the public firewall.

## Expensive world-health metrics

The optional world-health plugin walks entities, relationships, controllers, claims, and
queued commands when its observable metric is collected. Cost is proportional to world size,
so it is disabled by default and does not run every tick.

Enable the plugin without replacing the normal plugin set:

```bash
uv run bunnyland serve --extra-plugin bunnyland.world_health
```

Enable the separate orphan audit only when required:

```text
BUNNYLAND_OTEL_WORLD_AUDIT_ENABLED=1
BUNNYLAND_OTEL_ORPHAN_GRACE_SECONDS=300
```

Scrape these audits infrequently, measure collection duration on a production-sized copy, and
disable them if collector pressure affects play. Prefer ordinary bounded counters and health
checks for frequent monitoring.

## Troubleshooting

### The backup is encrypted but cannot be restored

Verify the recovery key and archive on a separate host immediately. An unreadable encrypted
file is not a backup; create a new verified generation before changing production.

### The restored server is healthy but players cannot sign in

Confirm the user inventory and token database were restored with correct ownership. Health is
anonymous and does not validate authentication state.

### The web client behaves differently after an upgrade

Confirm nginx serves the intended web revision, `config.json` is not stale, and server/web
versions are the tested pair. Roll back both, not just the more visible side.

### Telemetry increases latency

Disable content capture and expensive world audits first, reduce scrape frequency, and check
collector backpressure. The game service must remain useful when telemetry is unavailable.

[← Image generation](image-generation.md) · [Back to server setup](server-setup.md)
