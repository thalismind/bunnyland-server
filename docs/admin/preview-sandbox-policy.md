# Controlled preview rules, privacy, and incident contact

This notice applies to the hosted Bunnyland sandbox. It is an experimental, best-effort
service, not a production platform. Access may be paused or withdrawn to
protect players, world consistency, privacy, or operating cost.

## Sandbox rules

- Treat other players and the operator respectfully. Do not harass, threaten, impersonate,
  dox, or deliberately evade moderation.
- Do not probe another character's claim, private memory, direct messages, credentials, or
  hidden world state. Report an accidental disclosure without redistributing it.
- Do not submit secrets, sensitive personal information, or material you do not have the
  right to share. Bunnyland is a persistent world, so ordinary play can remain visible in
  world history and snapshots.
- Do not automate high-rate commands, reconnect loops, scraping, or model calls outside a
  coordinated test. Respect HTTP `429` responses, `Retry-After`, and Discord cooldowns.
- Do not treat autonomous-character output as professional advice or as a statement from a
  real person. Models can be wrong, repetitive, or inappropriate.

## What is stored

The sandbox can store account and claim identifiers, character actions, command receipts,
room-visible speech, direct-message events, character-scoped memories, relationships,
world history, uploaded or generated media, moderation records, and operational logs.
Credentials and claim secrets are authentication data and must not appear in ordinary
traces or public evidence.

World snapshots, memories, and media persist so the world can continue and be restored.
They are retained for the life of the controlled preview unless they are removed through
an operator action or restore. Operational tracing currently uses a 72-hour default where
Tempo is enabled. Backup retention depends on the configured remote and is documented in
the release recovery record.

To request access to, export of, or deletion of a character's private memory, contact the
operator with the character and claim details. Deleting memories does not retroactively
erase room-visible speech, command consequences, incident reports, or backups that must be
retained temporarily for recovery or abuse investigation.

## Model-provider disclosure

The active preview uses Ollama Cloud for autonomous character and world-generation calls.
The provider receives the bounded prompt needed for a call, which can include the
character's current perspective, persona and needs, relevant private memory excerpts,
recent visible events, conversation text, and available actions. It should not receive the
full admin snapshot, another character's private memory, claim secrets, or server
credentials through the normal controller path.

The open-source server also supports local or remote Ollama and OpenRouter. A self-hosted
operator is responsible for that deployment's provider, retention, and privacy choices.
Image generation is optional and may be disabled; a disabled or failed image provider must
not block world actions.

## Security contact

Report a vulnerability privately through the
[bunnyland-server GitHub security advisory form](https://github.com/thalismind/bunnyland-server/security/advisories/new).
Do not include live credentials, private memory text, or exploit details in a public issue.
For non-sensitive defects, use the repository issue tracker.

## Operator incident procedure

The operator may pause the world, freeze autonomous controllers, suspend or revoke claims,
disable LLM, chat, MCP, image, or write surfaces, and restore the last verified checkpoint.
During an incident the operator preserves access-controlled receipts and redacted traces,
rotates affected credentials, and checks perspective isolation before reopening.

The preview remains closed when there is an unexplained restart, hidden-state disclosure,
undetected stream gap, inconsistent projection, unrecoverable world state, failed backup,
or unresolved critical safety, privacy, moderation, or cost issue. The operational response
steps are in the [controlled preview runbook](controlled-preview-runbook.md).
