# Plan: Finish the daggersim package (7.10 + 7.13)

## Context

The mechanics catalogue (`bunnyland_mechanics.md`) defines nine sim packages. Eight are
built; `daggersim` (section 7) is the current one and is nearly complete — its plugin
(`daggersim_plugin` in `src/bunnyland/plugins/builtin.py`) already wires 7.1–7.9, 7.11,
7.12, 7.14 and 7.15. Two subsections remain unimplemented:

- **7.10 Procedural dungeons** — no dungeon components/handlers anywhere.
- **7.13 Etiquette, streetwise, social approach** — no dialogue-approach mechanics
  (`social.py` only has relationship bonds).

(7.16 "How daggersim uses worldgen" is design intent already satisfied by the existing
`ExpansionHookComponent` / `ExpansionRequestedEvent` flow — nothing to build.)

`voidsim` (Phase 8) and `fortresssim` (Phase 9) are explicitly **out of scope** for now.

Goal: close the two daggersim gaps so the package is feature-complete against section 7,
**one subsection per commit** (matching the existing commit cadence). Build 7.10 first,
then 7.13.

## Conventions to follow (from existing daggersim code)

All new code lives in the single module `src/bunnyland/mechanics/daggersim.py` and is
wired through `daggersim_plugin()` in `src/bunnyland/plugins/builtin.py`. Match the
established patterns:

- **Components/edges/events:** frozen `@dataclass` (pydantic) subclassing
  `Component` / `Edge` / `DomainEvent`. See `ProceduralSiteComponent` (daggersim.py:23)
  and `ExpansionRequestedEvent` (daggersim.py:272).
- **Handlers:** zero-arg class with `command_type` + `execute(self, ctx, command)`,
  returning `ok(...)` / `rejected(...)`. Validate ids with `parse_entity_id`, reachability
  with `reachable_ids`, mutate via `replace_component`, build events with
  `ctx.event_base(...)`. See `ExpandSiteHandler` (daggersim.py:465).
- **Time-driven effects:** consequence classes registered in `install_daggersim`
  (daggersim.py:1886), e.g. `TravelCompletionConsequence` (daggersim.py:725).
- **Prompt surface:** extend `daggersim_fragments` (daggersim.py:1803).
- **Plugin wiring:** add new components/edges to `EcsContribution`, handlers +
  events to `CommandContribution`, consequences to `install_daggersim`. Add every new
  public symbol to daggersim.py `__all__` and to the import list in `builtin.py`.
- **Pragmatic scope:** daggersim deliberately tracks state and *delegates content
  generation to worldgen* rather than implementing every catalogue "system" as a full ECS
  system. Keep that altitude — do not build heavyweight generators inline.

## Unit A — 7.10 Procedural dungeons (commit 1)

Dungeon *room generation* reuses the existing expansion flow (a dungeon is an unrealized
site that worldgen fills in); daggersim owns the dungeon graph state, exploration,
secrets, recall, and rest risk.

**Components** (keep the set lean; fold the catalogue's overlapping ones together):
- `DungeonComponent` — dungeon id, theme/seed, level count, objective summary, `entered`.
- `DungeonRoomComponent` — dungeon id, depth, `discovered`, `is_objective`,
  `danger` band. (Covers DungeonNode/DungeonRoom/DungeonLevel.)
- `DungeonObjectiveComponent` — objective kind + `found` flag.
- `SecretDoorComponent` — `found` flag, difficulty, leads-to hint.
- `LockedDoorComponent` — `key_id`, `locked` flag (reuse existing `mechanisms.py` door
  idiom if it fits; otherwise local).
- `AutomapComponent` (on the character) — discovered room ids, marked breadcrumbs.
- `RecallAnchorComponent` (on the character) — anchored room id.
- `RestRiskComponent` — ambush probability band for a room.

**Handlers** (the 9 actions): `enter dungeon`, `search room` (rolls vs `SecretDoorComponent`),
`open secret door`, `mark path` (breadcrumb on automap), `view map` (returns automap as
event/prompt, no mutation), `set recall`, `use recall` (move to anchor room), `rest`
(triggers rest-ambush check), `leave dungeon`. Movement reuses core containment/`move`
semantics; recall/use moves the character via the same containment edges core uses.

**Consequence:** `RestAmbushConsequence` — on rest, consults `RestRiskComponent` and may
emit an ambush event (no combat system here; emit the event and let combat-capable
packages/observers react, per the "systems read broadly, write narrowly" warning).

**Dungeon creation:** add a `request dungeon` path that emits `DungeonRequestedEvent` and
reuses the `ExpansionRequestedEvent` mechanism so worldgen instantiates rooms — do **not**
generate room graphs inline.

**Events:** `DungeonRequestedEvent`, `DungeonGeneratedEvent`, `DungeonEnteredEvent`,
`DungeonRoomDiscoveredEvent`, `SecretDoorFoundEvent`, `RecallAnchorSetEvent`,
`RecallUsedEvent`, `DungeonObjectiveFoundEvent`, `DungeonExitedEvent`.

**Prompt fragments:** in `daggersim_fragments`, surface current dungeon, discovered/
objective rooms, known secret doors, recall anchor, and rest risk for the current room.

## Unit B — 7.13 Etiquette, streetwise, social approach (commit 2)

7.13 "extends say/tell with an approach." Keep daggersim decoupled: do **not** add
daggersim verbs that duplicate speech. Instead:

1. **Minimal additive core touch** (mirror how `intent` is already handled): accept an
   optional `approach` payload key in `SayHandler`/`TellHandler`
   (`src/bunnyland/core/handlers/speech.py`) and carry it on `SpeechSaidEvent` /
   `SpeechToldEvent` (`src/bunnyland/core/events.py`) as an optional `approach` field
   (default `None`, so existing behavior/tests are unchanged). This is the only file
   outside daggersim that changes; ~6 lines, matching the `author_intent` pattern.
2. **daggersim components:** `DialogueApproachComponent` (allowed approaches / last used),
   `EtiquetteSkillComponent`, `StreetwiseSkillComponent`, `SocialRegisterComponent`
   (a character/NPC's expected register, folding in `NPCSocialClassComponent`),
   `ConversationToneComponent` (running tone state on a listener).
3. **`SocialRegisterReactionConsequence`** — observes `SpeechSaidEvent`/`SpeechToldEvent`,
   reads the speaker's etiquette/streetwise skill and the listener's
   `SocialRegisterComponent`, decides whether the `approach` fits, updates the listener's
   `ConversationToneComponent`, and emits an outcome event. Covers DialogueApproach/
   Etiquette/Streetwise/SocialRegisterReaction/CourtSpeech as one event-driven reaction
   (don't build six separate systems — keep altitude consistent with daggersim).
4. **Events:** `ApproachUsedEvent`, `EtiquetteCheckEvent`, `StreetwiseCheckEvent`,
   `SocialRegisterReactionEvent` (faux-pas vs. well-received).
5. **Prompt fragments:** surface the character's etiquette/streetwise skill, available
   approaches, and any nearby NPC's expected social register.

The catalogue lists `casual/polite/formal/deferential/blunt/threatening/underworld/
courtly/commercial` — define these as a small string set/enum used for validation and
the skill-check mapping (e.g. underworld→streetwise, courtly/formal→etiquette).

## Files to modify

- `src/bunnyland/mechanics/daggersim.py` — all new components/edges/events/handlers/
  consequences/fragments (+ `__all__`).
- `src/bunnyland/plugins/builtin.py` — extend `daggersim_plugin()` (`EcsContribution`,
  `CommandContribution`, `install_daggersim`) and the daggersim import block.
- `src/bunnyland/core/handlers/speech.py` + `src/bunnyland/core/events.py` — Unit B only,
  minimal additive `approach` field.
- `tests/test_daggersim.py` — new tests per unit (see below).

## Verification

Per unit, before committing:

1. **Tests** — add cases to `tests/test_daggersim.py` using `build_scenario` +
   `build_submitted_command` (existing helpers; see test file head and `_site`/`_rumor`
   helpers). Cover:
   - 7.10: enter dungeon; search reveals a secret door; recall set→use relocates the
     character; rest triggers the ambush consequence; objective found event; rejections
     (not in a dungeon, room not reachable).
   - 7.13: each approach validated; an etiquette-fitting approach is well-received vs a
     faux-pas; streetwise covers the underworld register; speech with no `approach`
     behaves exactly as today (regression guard on core speech tests).
2. `uv run pytest` — full suite green (including existing `test_daggersim.py`,
   `test_speech.py`, `test_plugins.py`).
3. `uv run ruff check src tests` — clean.
4. Confirm the plugin still loads: a scenario with `daggersim_plugin()` applied registers
   the new handlers/components without dependency errors.

**Done when:** both subsections implemented, all new behavior covered by passing tests,
suite + ruff green, and daggersim section 7 is feature-complete. Two commits, one per
subsection (7.10 then 7.13), matching the existing one-mechanic-per-commit cadence.
