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

