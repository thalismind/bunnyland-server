# bunnyland Implementation Plan

Plan for completing `bunnyland_specification.md`. Sequenced to reach a **playable MVP**
(spec §28) first, then add depth.

**Locked decisions**
- Optimize ordering for a playable human + LLM Discord loop as early as possible.
- LLM (controllers §25, worldgen DM §22): **Ollama Cloud**, behind a generic LLM-client
  interface; stubbed in tests.
- Vector memory (§15): **ChromaDB**, behind a `MemoryStore` interface; in-memory/keyword
  backend first, ChromaDB adapter as an optional extra.
- Heavy/optional deps (`chromadb`, `discord.py`, `ollama`) live behind extras.
- One branch per phase, merged to `main` as each lands.

## Status

**Done (31 tests, ruff clean):** world actor + tick pipeline (§5), Action/Focus (§6),
controller handoff/generation/suspend (§7), Contains/Holding/Wearing (§10), two-lane
queues, typed events + bus (subset §18); verbs `move`/`take`/`drop`/`put`/`eat`/`drink`/
`say`/`tell`; hunger & thirst with shared `Meter` (§11.11, §27.1); `SpeechIntent` (§14.2).

## Phases (MVP path = 1–8)

### Phase 1 — Close core verb & lifecycle gaps (§8, §13)
- Verbs: `sleep`/`wake`, `wait`/`yield`, `use` (affordance dispatch §13.6), `write`
  (physical, §13.11). Control verbs (`take-control`/`release-to-llm`/`resume`) as real
  `SubmittedCommand`s over the existing actor methods.
- Systems: downed/recovery (§8.4, §23.4) and death (§8.3), excluding suspended.
- Components needed: `SleepNeed`/`Sleeping`, `Readable`/`Writable`, mechanism components
  for `use` targets as needed (`Door`/`Lockable`).
- **Done when:** sleep/wake works; a lethal event downs then kills only active
  characters; all control transitions flow through the command lane with generation bumps.

### Phase 2 — Projections & perception (§17, §19, §23.8–23.9)
- Event-driven `RoomSummary` projection: dirty-on-change, semantic bands
  (light/temp/moisture/cleanliness), structured facts vs prose, lazy rebuild.
- `RecentContext` projection; a perception/observation pass (who sees what).
- **Done when:** mutating a room marks its summary dirty and a deterministic rebuild
  reflects occupants/exits/objects/bands.

### Phase 3 — Notes & memory (§15, §11.16)
- Focus-lane verbs `take note` and `remember`/`search` (first focus-lane commands).
- `MemoryStore` interface; in-memory + keyword backend, then ChromaDB adapter. Private
  per-character collections; private results.
- **Done when:** notes cost Focus, are non-discoverable, and recent/keyword/vector
  search returns them privately.

### Phase 4 — Affect, thought, environment bands (§11.12–11.13, §23.5, §23.7)
- `AffectVector`, thought creation/decay, affect aggregation → mood labels.
- Basic weather/temperature/moisture/light systems with semantic bands.
- Wire speech/eat/needs into thought + affect deltas (closes the §14.3 reaction gap).
- **Done when:** events produce thoughts that shift affect and surface as feeling labels.

### Phase 5 — Prompt builder (§16)
- Per-mechanic prompt fragments assembled by a central builder into the foundation
  prompt; identical context for humans and LLMs.
- **Done when:** a character renders the §16.2 example prompt from live ECS state.

### Phase 6 — Plugin architecture (§21)
- `Plugin` / `*Contribution` models; installed entry-point discovery and `--plugin`
  selection with dependency ordering.
- Refactor `mechanics.install_needs` and core registration into plugins.
- **Done when:** core/memory/lifesim load as plugins via CLI; disabling a plugin removes
  its components/systems/verbs.

### Phase 7 — World generation (§22)
- Generator interface → structured proposal → schema + policy validation → actor
  instantiation. Stub generator first, then Ollama Cloud DM. LLM never mutates ECS.
- **Done when:** a seed prompt yields a validated multi-room world hitting the §28.2
  checklist (rooms, controllable + LLM character, food, water, container, notes, writing,
  speech, suspend/resume).

### Phase 8 — Controllers & integration → playable MVP (§24, §25)
- LLM controller provider (Ollama Cloud): tool schemas mapping 1:1 to verbs, decision
  logging (§25.4, no hidden chain-of-thought).
- Discord integration: slash commands, buttons/selects, DM focus actions, ready
  notifications; actor runs as a background task fed by Discord/LLM via `submit()`.
- **Done when:** a human on Discord and an LLM share a generated world, take/release
  control, and play the full loop.

## Post-MVP

### Phase 9 — Persistence (§26)
World snapshots, typed event log, command audit log, vector collections; volatile queues
not persisted; clean restart restores state with empty queues.

### Phase 10 — Policy & boundaries (§20)
`BoundaryTag`, `CharacterBoundary`, `WorldPolicy`, the allow/deny gate (denied always
wins; admins can't override), PvP gating.

### Phase 11 — Simulation bundles (§21.4, §20.5–20.6)
`lifesim` (romance/family/pregnancy incl. suspended-progression rules), `colonysim`
(jobs/reservations/crafting), `barbariansim` (combat/raids) — each as plugins.

### Phase 12 — v2 deferred (§28.3)
NL command parser, shared notes, advanced stealth/overhearing, full crafting/colony/
combat, web client, LLM prose room summaries.

## Cross-cutting concerns
- **Async ↔ blocking Relics under Discord:** actor owns the tick loop as a background
  task; `discord.py`/LLM input is funneled through `submit()`; never touch ECS directly.
- **Secrets/outbound:** Discord token + Ollama Cloud host/key injected and configurable;
  stubbed in tests.
- **Optional deps behind extras:** core stays importable without chromadb/discord/ollama.
- **Tuning vs architecture:** point/regen/need numbers stay tuning data (§29); tests
  assert behavior, not magic constants.
