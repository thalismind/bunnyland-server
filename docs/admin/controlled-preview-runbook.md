# Controlled preview operations

Use this runbook for the 20-player Clover City preview and its 40-client validation.

## Before opening access

Run `scripts/test-all`, the exact focused regressions changed for the release, web
`scripts/playwright-all --coverage`, and the 3D integration checks. Push only after local
aggregate checks pass; wait for CI before deployment. Record the deployed git hashes,
world ID, checkpoint checksum, enabled plugins, memory namespace, and provider models.

Make a manual checkpoint and load it in a separate restore process. Confirm its checksum,
room graph, controller claims, known maps, memory checkpoint epoch, and Clover City story
consequences. Keep `.bak.1` and its checksum together.

Create a media checksum manifest and the versioned recovery manifest from the exact saved
world. Every `--pin` must be the deployed commit, not a branch name or a local dirty tree:

```bash
bunnyland recovery-manifest \
  /data/worlds/main.json \
  /data/media/manifest.sha256 \
  /data/recovery/bunnyland-ecs-agent-preview-2026-07.json \
  --release bunnyland-ecs-agent-preview-2026-07 \
  --pin server=SERVER_COMMIT \
  --pin web=WEB_COMMIT \
  --pin ui=UI_COMMIT \
  --pin homepage=HOME_COMMIT \
  --pin 3d=THREE_D_COMMIT \
  --pin media=MEDIA_COMMIT \
  --pin vps=VPS_COMMIT \
  --rollback-checkpoint main.json.bak.1
```

The command verifies the saved-world checksum and writes a checksum beside the recovery
manifest. Preserve the world snapshot and sidecar, memory directory or JSON store, media
tree and manifest, recovery manifest and sidecar, journal, and rollback checkpoint as one
restore boundary.

## Remote backup and clean-host restore drill

Remote backup must cover the complete durable data directory, not only `worlds/`. In the
VPS inventory, set `bunnyland_backup_enabled: true`, configure an access-controlled rclone
destination, apply Ansible, run `/usr/local/sbin/bunnyland-world-backup`, and verify the
remote contains world, memory, media, recovery, and checksum files. Record the remote
object version or immutable checkpoint in the release validation record.

For the clean-host drill, provision a host from the pinned VPS configuration without
reusing the active data volume. Stop the fresh server before it can mutate the target
directory, restore the remote boundary, and validate every checksum in the recovery and
media manifests. Start the pinned server with external model calls and image generation
disabled first. Verify world ID and epoch, room graph, claims, memory namespace and
watermark, media reads, the three Clover City consequences, and absence of quarantined
future memory from active collections. Then enable the release provider configuration and
perform one perspective-scoped action. Do not point the clone at the active world's memory
collections.

The drill passes only when the clean host reaches the recorded checksum and projections
without copying state from a sibling checkout or the running server. Afterward, rehearse
rollback to the recorded checkpoint and repeat checksum, namespace, projection, and story
aftermath verification.

## Stuck ticks or runaway agents

Pause the runtime. Capture health, recent traces, queue depths, the operational journal,
and a snapshot before changing state. Suspend the affected controller claim; do not edit
the character around validation. Resume for one tick and verify receipts and projections.
If the tick still fails, restore the last verified checkpoint and quarantine memory newer
than its epoch.

## Corruption

Stop mutation, preserve the corrupt file and sidecar, and verify the checksum. Try the
newest backup whose data and sidecar agree. Load it offline before replacing the live
path. Quarantine journal and memory records above the restored checkpoint epoch. Never
"fix" a checksum to match unexplained data.

## Provider failure

Leave the world authoritative and available to human/scripted controllers. Suspend or
handoff failing LLM controllers, apply provider/model rate limits, and retain rejected
decision traces without private memory text. Image generation failures are presentation
failures and must not block world ticks.

## Reconnect storm

Watch connection count, reconnect rate, subscriber depth, dropped frames, resync count,
and projection latency. Rate-limit new handshakes before command traffic. Clients that
receive `resync` fetch a new projection; do not enlarge queues until memory impact is
measured. Revoke compromised claims and confirm the socket closes before reassignment.

## Moderation or privacy incident

Suspend involved claims, preserve access-controlled receipts and redacted traces, rotate
affected credentials, and export/delete character memory through the authorized admin
surface. Do not place private memory text or secrets in tickets, broad traces, bulletins,
or player-facing explanations.

Release remains blocked by any critical security, privacy, moderation, credential,
restore, stream-gap, projection-isolation, or hosted-acceptance issue.
