# Bunnyland Experience Implementation Checklist

This checklist turns `bunnyland_experience.md` into implementable milestones. The
experience doc is the vision and backlog. This file is the practical execution checklist
for engineers.

The goal is not to copy aspirational phrasing into acceptance criteria. The goal is to
translate it into Bunnyland-shaped work: ECS state, component-owned prompt fragments,
projections, command handlers, scripts, plugin-owned mechanics, validated worldgen, and
deterministic harnesses.

## How to Use This Checklist

- Treat each checklist item as a focused PR or short PR sequence.
- Mark an item complete only when its acceptance check and verification pass.
- Prefer deterministic worlds and scripted scenarios for experience validation.
- Use scripts for scenario glue. Promote behavior to mechanics when it needs durable
  validation, commands, systems, prompt fragments, or reusable state.
- Do not add new sim packs until Stages 1-3 are fun in one polished scenario during
  dev/admin play.

## Translation Rules

- ECS remains the source of truth.
- Component rendering, visibility checks, and projections provide the reliable POV layer.
- LLM narration may summarize, stylize, and propose, but it must not be the only source
  of state visibility.
- DM/narrator world control is allowed as validated proposals through existing
  worldgen/admin patch/instantiation boundaries.
- Durable state changes must be validated by core and plugins before they enter the ECS.
- Prompt text should expose real state. It should not invent facts that the engine cannot
  inspect later.
- Costly model work must have a deterministic fallback path for tests and dev play.

## First Recommended Slice

- [x] **Read-only event narration over one deterministic scenario**
  - **Goal:** produce room/POV narration from existing domain events and projections.
  - **Depends on:** current domain event bus, room summaries, prompt fragments, and at
    least one deterministic demo world.
  - **Implementation notes:** start with a non-mutating narration pipeline that clusters
    tick events by room and viewer; use component/projection text as facts and treat LLM
    prose as presentation.
  - **Acceptance check:** after a scripted action sequence, each controlled character gets
    narration that references only visible, real state and omits hidden/remote state.
  - **Verification:** prompt/narration snapshot tests on a deterministic scenario, plus a
    contradiction check in the harness.

---

## Stage 1 - Narration and DM Presentation

- [x] **Narration boundary and runtime contract**
  - **Goal:** define where narration plugs into the actor tick without owning truth.
  - **Depends on:** `WorldActor` after-tick hooks, domain events, projections.
  - **Implementation notes:** narration reads events/projections and emits presentation
    messages; world edits from the DM are separate validated proposals.
  - **Acceptance check:** narration can run or fail without mutating ECS state or blocking
    command handling.
  - **Verification:** unit tests around no-op/failing narration plus actor tick tests.

- [x] **Programmatic POV assembly**
  - **Goal:** make each viewer's scene facts come from visibility-aware component
    rendering and projections before any prose styling happens.
  - **Depends on:** prompt fragments, viewer-scoped context, visibility/event privacy.
  - **Implementation notes:** treat "per-POV narration" as a rendering/projection problem
    first; LLM prose consumes the assembled facts.
  - **Acceptance check:** two characters in different perceptual positions receive
    different fact sets for the same world tick.
  - **Verification:** prompt-fragment and narration input tests that assert hidden state
    does not leak.

- [x] **Event-to-scene clustering**
  - **Goal:** convert raw tick events into coherent per-room/per-viewer scene inputs.
  - **Depends on:** event visibility levels, room containment, recent context.
  - **Implementation notes:** group events by room, actor, viewer, and salience; keep raw
    event ids available for audit.
  - **Acceptance check:** multiple low-level events from one action produce one coherent
    scene input rather than repeated stat lines.
  - **Verification:** deterministic event sequence tests.

- [x] **Dramatic salience scoring**
  - **Goal:** prioritize events that matter emotionally or mechanically.
  - **Depends on:** typed events, affect/relationship deltas where available, incident
    state where available.
  - **Implementation notes:** start with deterministic weights by event type and severity;
    add plugin-provided weights later.
  - **Acceptance check:** high-impact events are retained and low-impact repetitive events
    are compressed in the narration input.
  - **Verification:** table-driven salience tests.

- [x] **Scenario register and voice controls**
  - **Goal:** let narration style reflect scenario tone without changing facts.
  - **Depends on:** scenario/world metadata or tags.
  - **Implementation notes:** keep style tags separate from factual context; style can
    alter diction, not visibility or state.
  - **Acceptance check:** the same fact set can render in two scenario voices while
    preserving the same factual claims.
  - **Verification:** deterministic renderer tests or mocked narrator prompt tests.

- [x] **Validated DM world proposals**
  - **Goal:** allow DM-authored world edits without granting direct unvalidated mutation.
  - **Depends on:** worldgen proposal validation, admin patch pipeline, plugin type
    registries.
  - **Implementation notes:** the DM may propose rooms, items, NPCs, notes, incidents, or
    patches; core/plugins validate and instantiate.
  - **Acceptance check:** valid proposals instantiate through existing paths; invalid
    proposals fail without partial ECS mutation.
  - **Verification:** worldgen/admin patch validation tests.

- [x] **Non-blocking narration delivery**
  - **Goal:** narration latency does not stall world ticks.
  - **Depends on:** async task management and websocket/event delivery.
  - **Implementation notes:** queue narration jobs from tick facts; emit fallback
    deterministic text if model prose is unavailable.
  - **Acceptance check:** world ticks proceed when narration is slow or unavailable.
  - **Verification:** async timeout/fallback tests.

- [x] **Narration quality harness**
  - **Goal:** evaluate whether narration is grounded, POV-correct, and useful.
  - **Depends on:** deterministic scenarios and mocked model output.
  - **Implementation notes:** check factual grounding before literary quality.
  - **Acceptance check:** harness reports contradiction, hidden-state leakage, missing
    high-salience events, and style drift.
  - **Verification:** harness tests with seeded scenarios.

---

## Stage 2 - Character Identity, Autonomy, and True Recall

- [x] **Persistent persona prompt surface**
  - **Goal:** consistently feed each LLM controller its identity, voice, relationships,
    boundaries, and current role.
  - **Depends on:** prompt builder, identity/persona components, relationship components.
  - **Implementation notes:** persona facts are programmatic prompt inputs, not free-form
    memory guesses.
  - **Acceptance check:** prompt construction includes stable identity facts across
    sessions and model swaps.
  - **Verification:** prompt-builder tests.

- [x] **Persona contradiction guard**
  - **Goal:** detect when controller output contradicts stable identity facts.
  - **Depends on:** decision logging and persona prompt surface.
  - **Implementation notes:** start with deterministic checks for names, known
    relationships, and impossible self-claims.
  - **Acceptance check:** harness flags contradictory outputs without blocking normal
    valid actions.
  - **Verification:** mocked controller output tests.

- [x] **True recall gate: memory surfacing**
  - **Goal:** relevant past memories are retrieved and injected into character prompts at
    the right time.
  - **Depends on:** memory store, note/memory entries, `RecentContext`, prompt builder,
    deterministic test scenarios.
  - **Implementation notes:** combine vector or keyword retrieval with recency and
    relevance filters; include enough source metadata to audit why a memory appeared.
  - **Acceptance check:** a character prompt includes a relevant past memory when a later
    situation calls for it and excludes irrelevant/noisy memories.
  - **Verification:** prompt-builder tests plus one deterministic scenario where a past
    event becomes available for later recall.
  - **Gate:** this must pass before advanced autonomy, conversation memory, narrator
    callbacks, reputation references, legacy beats, or "they remembered" behavior can be
    marked complete.

- [x] **Memory hygiene and bounded context**
  - **Goal:** keep recall useful as worlds accumulate notes and events.
  - **Depends on:** true recall gate, memory store, note/forget or pruning flow.
  - **Implementation notes:** summarize or prune low-value memory noise; preserve durable
    high-salience memories with source references.
  - **Acceptance check:** prompts stay within configured context budgets while retaining
    important memories.
  - **Verification:** memory retrieval tests with noisy corpora.

- [x] **Goal-directed autonomy**
  - **Goal:** background LLM or behavior controllers choose actions from goals,
    aspirations, needs, relationships, and memory rather than random movement.
  - **Depends on:** persona prompt surface, true recall gate, available action definitions.
  - **Implementation notes:** start with explicit scoring inputs and deterministic
    fallbacks; do not require full LLM control for every NPC.
  - **Acceptance check:** an autonomous character repeatedly chooses plausible actions
    tied to current goals and recalled context.
  - **Verification:** deterministic controller tests and scenario harness checks.

- [x] **Cheap background controllers**
  - **Goal:** populate worlds without full LLM cost for every character.
  - **Depends on:** controller model, action definitions, persona/goals.
  - **Implementation notes:** provide behavior/script controller profiles for timid,
    social, aggressive, worker, and idle background roles.
  - **Acceptance check:** non-LLM background characters perform coherent low-cost actions.
  - **Verification:** controller dispatch tests.

- [x] **Social-cue perception**
  - **Goal:** characters notice nearby social facts: arrivals, silence, distress,
    ignored speech, and relationship-relevant changes.
  - **Depends on:** event clustering, prompt fragments, social/affect mechanics.
  - **Implementation notes:** expose cues as structured prompt facts before prose.
  - **Acceptance check:** a character prompt changes when someone meaningful enters,
    leaves, speaks, or is visibly upset.
  - **Verification:** prompt-fragment tests.

- [x] **Relationship-driven behavior**
  - **Goal:** relationships and sentiment influence dialogue, cooperation, avoidance, and
    memory salience.
  - **Depends on:** social bonds, affect, true recall gate.
  - **Implementation notes:** use relationship state as an input to both prompts and
    behavior scoring.
  - **Acceptance check:** two characters with different relationships to the same actor
    receive different behavior cues and likely actions.
  - **Verification:** social prompt and controller tests.

- [ ] **Reflection loop**
  - **Goal:** characters periodically synthesize recent experience into durable insights.
  - **Depends on:** true recall gate, memory hygiene, notes, affect/social state.
  - **Implementation notes:** reflection writes validated memory/note state, not hidden
    prompt-only lore.
  - **Acceptance check:** after a meaningful sequence, a concise reflection appears in
    memory and can be retrieved later.
  - **Verification:** memory persistence and retrieval tests.

- [ ] **Offline life mechanism**
  - **Goal:** characters continue limited needs/goals/social activity while players are
    away.
  - **Depends on:** cheap background controllers, persistence, autonomy scoring.
  - **Implementation notes:** start bounded and deterministic; avoid model-heavy
    simulation for every absent interval.
  - **Acceptance check:** returning players can observe real persisted changes caused by
    offline character activity.
  - **Verification:** save/reload and elapsed-time simulation tests.

---

## Stage 3 - Conversation and Social Interpretation

- [ ] **Threaded conversation micro-loop**
  - **Goal:** support immediate back-and-forth conversation without consuming a full world
    tick per line.
  - **Depends on:** command lanes, speech handlers, controller dispatch.
  - **Implementation notes:** treat this as a Focus-lane micro-loop with explicit
    turn-taking, participant list, timeout, and exit conditions.
  - **Acceptance check:** two or more characters can exchange several lines and return to
    normal world ticks cleanly.
  - **Verification:** direct handler tests and E2E conversation test.

- [ ] **Speech intent and approach metadata**
  - **Goal:** speech carries intent and social approach, not just text.
  - **Depends on:** existing speech command surface and action definitions.
  - **Implementation notes:** allow explicit intent when provided and deterministic
    inference when omitted.
  - **Acceptance check:** speech events include intent/approach metadata used by later
    systems.
  - **Verification:** speech handler and action metadata tests.

- [ ] **Social interpretation system**
  - **Goal:** listeners interpret speech through mood, traits, relationship, and context.
  - **Depends on:** speech intent, affect, relationships, true recall gate.
  - **Implementation notes:** interpretation drives affect/relationship deltas; raw text
    alone should not decide outcomes.
  - **Acceptance check:** the same sentence can land differently for two listeners with
    different relationship/mood state.
  - **Verification:** social/affect tests.

- [ ] **Conversation memory**
  - **Goal:** conversations leave durable, retrievable traces.
  - **Depends on:** true recall gate, speech interpretation, memory store.
  - **Implementation notes:** record who said what, who heard it, and how it landed using
    structured memory or linked entities.
  - **Acceptance check:** later prompts can surface a relevant prior conversation with
    speaker/listener context.
  - **Verification:** memory retrieval scenario tests.

- [ ] **Multi-party scene support**
  - **Goal:** several characters can participate in one coherent conversation scene.
  - **Depends on:** conversation micro-loop, social interpretation.
  - **Implementation notes:** turn order and interruptions must be explicit and bounded.
  - **Acceptance check:** a three-person conversation produces coherent events,
    memories, and narration inputs.
  - **Verification:** E2E or direct conversation loop tests.

- [ ] **Gossip propagation**
  - **Goal:** overheard or relayed information can spread through the social graph.
  - **Depends on:** conversation memory, relationships, reputation hooks.
  - **Implementation notes:** propagate structured claims with source/confidence, not
    arbitrary prose blobs.
  - **Acceptance check:** a character who was not present can later learn a degraded or
    attributed version of a conversation.
  - **Verification:** social memory tests.

- [ ] **Silence and presence as social acts**
  - **Goal:** watching, brooding, ignoring, or pointed silence is legible to nearby
    characters and narration.
  - **Depends on:** social-cue perception, conversation loop.
  - **Implementation notes:** expose silence/presence as events or projections before
    using model prose.
  - **Acceptance check:** nearby characters receive prompt cues for significant silence or
    nonverbal reactions.
  - **Verification:** prompt/projection tests.

---

## Stage 4 - Legacy, Persistence, and Consequence

- [ ] **World history projection**
  - **Goal:** notable deeds become queryable world history independent of one character's
    memory.
  - **Depends on:** domain events, persistence, salience scoring.
  - **Implementation notes:** store structured history records with actors, locations,
    time, tags, and source event ids.
  - **Acceptance check:** narrator and prompts can cite a persisted notable deed after
    reload.
  - **Verification:** persistence and prompt tests.

- [ ] **Physical marks and authored artifacts**
  - **Goal:** writing, carving, created artifacts, claimed spaces, and damage persist and
    remain discoverable.
  - **Depends on:** existing write/use/property/crafting mechanics.
  - **Implementation notes:** make marks normal ECS state; do not leave them as narration
    only.
  - **Acceptance check:** a later player can inspect the mark/artifact after autosave and
    reload.
  - **Verification:** persistence tests and player-command tests.

- [ ] **Creator signatures**
  - **Goal:** crafted or authored objects remember who made them and under what notable
    circumstances.
  - **Depends on:** crafting/authorship mechanics and world history projection.
  - **Implementation notes:** use components or edges for creator links; avoid multiple
    same-type components on one entity.
  - **Acceptance check:** inspecting an artifact exposes maker/lore when visible.
  - **Verification:** direct mechanic and prompt-fragment tests.

- [ ] **Reputation and deed references**
  - **Goal:** factions, regions, services, and NPC behavior can react to known deeds.
  - **Depends on:** world history, gossip propagation, social memory, daggersim-style
    reputation hooks.
  - **Implementation notes:** reputation state must be explicit ECS/plugin state, not
    inferred only by narration.
  - **Acceptance check:** a deed changes service/guard/dialogue behavior in a later scene.
  - **Verification:** mechanic tests and deterministic scenario test.

- [ ] **Death and consequence presentation**
  - **Goal:** death and major loss are narrated, remembered, and mechanically
    consequential.
  - **Depends on:** lifecycle/death mechanics, narrator, history, memory.
  - **Implementation notes:** respect suspended-character safety; separate event
    correctness from prose presentation.
  - **Acceptance check:** a death produces durable history/memory and visible consequence
    without killing suspended characters.
  - **Verification:** lifecycle tests, persistence tests, narration input tests.

- [ ] **Inheritance and lineage**
  - **Goal:** property, items, money, names, and relationships can pass through family or
    household structures.
  - **Depends on:** lifesim family/household/property mechanics.
  - **Implementation notes:** use explicit ECS state for lineage and ownership transfer.
  - **Acceptance check:** after death or transition, heirs receive appropriate links and
    surviving characters can reference them.
  - **Verification:** lifesim/persistence tests.

- [ ] **Tracked obligations and branching consequences**
  - **Goal:** promises, threats, agreements, failures, and debts become state that later
    systems can inspect.
  - **Depends on:** speech intent, conversation memory, reputation.
  - **Implementation notes:** store obligations as entities or edges with parties,
    conditions, deadlines, and status.
  - **Acceptance check:** failing or fulfilling an obligation changes later prompts,
    relationships, or services.
  - **Verification:** social/reputation tests.

- [ ] **Cross-player impact**
  - **Goal:** one player's actions visibly change the world another player later
    inhabits.
  - **Depends on:** persistence, history, marks, reputation, prompt rendering.
  - **Implementation notes:** validate through real shared world state, not scripted
    narration only.
  - **Acceptance check:** Player B can observe a durable consequence caused by Player A
    after save/reload.
  - **Verification:** E2E multi-controller scenario.

---

## Stage 5 - Onboarding, Scenarios, and Admin Packaging

- [ ] **Valid actions endpoint**
  - **Goal:** expose currently relevant verbs for a character and world state.
  - **Depends on:** action definitions, reachability/query helpers, loaded plugins.
  - **Implementation notes:** do not decide AP/FP affordability here; clients can disable
    unaffordable actions separately.
  - **Acceptance check:** endpoint returns core actions and plugin actions relevant to the
    current room and character.
  - **Verification:** server API and plugin parity tests.

- [ ] **Valid targets endpoint**
  - **Goal:** expose reachable/selectable targets per action.
  - **Depends on:** valid actions, reachability, containment, doors/items/characters.
  - **Implementation notes:** target resolution should use the same helpers handlers use
    where possible.
  - **Acceptance check:** a player can choose targets without guessing names or ids.
  - **Verification:** server API tests and web/TUI smoke checks.

- [ ] **Tiered verb reveal**
  - **Goal:** new players start with a small action surface and discover advanced verbs.
  - **Depends on:** valid actions endpoint, client UI state, scenario metadata.
  - **Implementation notes:** reveal should hide presentation, not remove server-side
    command validity.
  - **Acceptance check:** new character UI starts with core verbs and reveals more from
    context/use.
  - **Verification:** frontend or API tests depending on implementation layer.

- [ ] **Context-aware help and nudges**
  - **Goal:** stalled or failed players receive specific in-context guidance.
  - **Depends on:** command rejection reasons, recent context, onboarding state.
  - **Implementation notes:** use exact handler rejection reasons and visible state; avoid
    generic manuals as primary help.
  - **Acceptance check:** after a failed action or idle window, help references the
    current room/action and suggests a valid next step.
  - **Verification:** command/API tests and playtest script.

- [ ] **New-player safe window**
  - **Goal:** first-session players have a safe spawn and gentler early pressure.
  - **Depends on:** scenario metadata, incident/needs systems.
  - **Implementation notes:** implement as explicit scenario/player state, not hidden
    narrator mercy.
  - **Acceptance check:** early incidents/needs respect configured safe-window rules.
  - **Verification:** incident and needs tests.

- [ ] **Scenario manifest**
  - **Goal:** define a shareable scenario package with world snapshot/shorthand, cast,
    hook, opening beat, packs, difficulty, player count, and tone tags.
  - **Depends on:** worldgen examples, scripting engine, plugin ids.
  - **Implementation notes:** keep manifest schema minimal until one scenario is proven.
  - **Acceptance check:** a manifest can load a scenario with claimable characters and an
    opening beat.
  - **Verification:** manifest validation and scenario load tests.

- [ ] **Opening beat via scripts**
  - **Goal:** scenarios start with something immediate to react to.
  - **Depends on:** scripting engine, scenario manifest.
  - **Implementation notes:** use `submit_command` and `patch_world` only for scenario
    glue; durable mechanics remain plugin-owned.
  - **Acceptance check:** first few ticks produce a visible inciting event in the loaded
    scenario.
  - **Verification:** scripting scenario tests.

- [ ] **Scenario picker**
  - **Goal:** players/admins can choose a curated scenario, claim a character, and enter
    the opening beat.
  - **Depends on:** scenario manifest, claim flow, web/admin UI.
  - **Implementation notes:** keep sandbox generation available but secondary.
  - **Acceptance check:** user can select one curated scenario and reach playable state
    without manual admin patching.
  - **Verification:** Playwright or server/web smoke tests.

- [ ] **Scenario wizard**
  - **Goal:** admins can scaffold premise, cast, opening beat, arc triggers, and package
    output.
  - **Depends on:** scenario manifest, worldgen validation, scripting.
  - **Implementation notes:** emit valid manifest plus scripts; do not bypass plugin
    validation.
  - **Acceptance check:** wizard output loads as a playable scenario package.
  - **Verification:** admin API/UI tests.

- [ ] **Scenario authoring guide**
  - **Goal:** creators know how to build and share scenario packages.
  - **Depends on:** scenario manifest and at least one curated scenario.
  - **Implementation notes:** document the validated boundaries for scripts, worldgen,
    plugin packs, and opening beats.
  - **Acceptance check:** guide includes a minimal template and one complete example.
  - **Verification:** doc review and link check.

---

## Cross-Cutting Milestones

- [ ] **Model budget and latency tiering**
  - **Goal:** narration, character decisions, reflection, and background behavior stay
    affordable and responsive.
  - **Depends on:** LLM provider abstraction, controller dispatch, narration runtime.
  - **Implementation notes:** support premium narrator, cheaper background behavior,
    batched reflection, and cached persona/memory context.
  - **Acceptance check:** configured budgets cap per-tick model work and expose fallback
    behavior.
  - **Verification:** provider/mock tests and load-oriented harness checks.

- [ ] **Deterministic experience harness**
  - **Goal:** test fun-adjacent quality without relying on live model nondeterminism.
  - **Depends on:** deterministic worlds, scripts, mocked controller/narrator output.
  - **Implementation notes:** evaluate grounding, recall, persona consistency,
    conversation coherence, and scenario opening quality.
  - **Acceptance check:** harness can fail a scenario for contradiction, missing recall,
    hidden-state leakage, or incoherent conversation.
  - **Verification:** harness unit/E2E tests.

- [ ] **Story-moment capture**
  - **Goal:** make memorable moments easy to save and share.
  - **Depends on:** narration delivery, event ids, Discord/web clients.
  - **Implementation notes:** capture should include enough event/source metadata to avoid
    sharing invented or ungrounded text as fact.
  - **Acceptance check:** a user can capture a grounded moment with scene text and source
    context.
  - **Verification:** client/API tests.

- [ ] **Persistence and restore audit**
  - **Goal:** experience features survive autosave/reload without state drift.
  - **Depends on:** memory, history, scenario scripts, world persistence.
  - **Implementation notes:** document what is ECS persisted, what is script state, and
    what must be restored together for deterministic scenarios.
  - **Acceptance check:** a scenario can save, reload, and continue with memory/history/
    obligations intact.
  - **Verification:** persistence tests and scenario replay tests.

- [ ] **Public checklist maintenance**
  - **Goal:** keep this checklist aligned with implementation status.
  - **Depends on:** all experience milestones.
  - **Implementation notes:** update this file when a milestone ships or when architecture
    changes invalidate an item.
  - **Acceptance check:** completed items link to tests/docs or name the implemented
    surface.
  - **Verification:** doc review during related PRs.
