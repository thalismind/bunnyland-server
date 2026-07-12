# Bunnyland — Experience & Storytelling Checklist

The goal of this work is not more mechanics. It's making the world *legible, dramatic, and alive*: the layer that turns the simulation into a game people screenshot and tell their friends about. Five stages plus the cross-cutting glue. Items are roughly dependency-ordered within each stage.

The chosen order is **build the magic first, package it last**: get the narration and the minds genuinely good (Stages 1–2), make scenes sing (Stage 3), give actions lasting weight (Stage 4), and only then polish the front door that presents it to newcomers and admins (Stage 5). The tradeoff to stay honest about: you need a way to playtest *quality* before onboarding exists — that's dev/admin direct play plus the deterministic harness, not new-player flow.

Design invariants to hold throughout:
- The narrator **reads and renders; it never mutates truth**. New content is introduced only through the existing worldgen/validation pipeline (the daggersim/worldgen pattern). Plugins keep owning components, systems, enrichment, and generators.
- Everything stays on the right side of read-broadly / write-narrowly. Story lives in projections; state lives in ECS.
- Deterministic worlds remain the substrate for testing fun, not just correctness.

---

## Stage 1 — Make the DM a writer and narrator (plugin enrichment preserved)

### Architecture — keep the boundary clean
- [ ] Split the DM into two layers: **(a) mechanics & world enrichment owned by plugins** (unchanged — components, systems, generators, typed events) and **(b) a narration layer** that subscribes to events + projections and produces prose. The narrator interprets; plugins produce.
- [ ] Lock the rule: **the narrator never writes world state directly.** It renders, and when it wants to introduce content (room, NPC, item) it routes through the existing worldgen → validation → instantiation pipeline. The narrator *proposes*; plugins + core validate. (Decide deliberately whether to grant a privileged direct-patch channel — default is no.)
- [ ] Build on "specify a different DM model": give the narrator its **own model, prompt, and token/latency budget**, independent of character controllers.

### Make it write, not dispatch
- [ ] **Event-to-prose pipeline**: cluster the tick's typed events per room and per POV (using existing event-visibility levels) into composed scene narration, not stat readouts.
- [ ] **Dramatic salience scoring**: weight events for narrative importance (a death ≫ a watering). Linger on high-salience moments; compress or omit low ones. Drive weighting from affect/relationship deltas and incident state.
- [ ] **Per-POV narration**: leverage the multi-POV fragment work so each player sees the scene from their character's vantage (what they perceive), never an omniscient dump.
- [ ] **Register/voice by scenario**: the narrator adapts tone to genre via scenario tags (cozy vs grim vs noir vs comedic). A horror world must not read like garden-sim.

### Story-arc awareness & continuity
- [ ] Evolve the storyteller from a **threat budget** into a **narrative budget**: a tension/arc projection (rising → climax → falling) the narrator reads to know when to escalate, breathe, or pay off. Reuse the incident machinery rather than replacing it.
- [ ] **Callbacks/continuity**: give the narrator a queryable "notable beats" projection over the event timeline + memory so it can reference the past ("the third time this week the well ran dry").
- [ ] **Narrate incidents as beats**: wire storyteller incidents through the narrator so they arrive as story, not as numbers (kaiju arrival, raid, betrayal land as scenes).

### Safety, cost, quality
- [ ] **Async, non-blocking narration**: ticks must not wait on the narrator (realtime-ish, queued). Stream narration over websocket with graceful fallback.
- [ ] **Narration eval** in the harness on deterministic worlds: does the narrator reference real state, avoid contradictions, hold voice, respect POV/visibility?

---

## Stage 2 — Make the LLM characters act and think like people

### Stable identity
- [ ] **Persistent persona injection**: consistently feed each LLM controller its traits, voice/style, biography, preferences, and boundaries so voice survives across sessions and model swaps.
- [ ] **Persona-drift / contradiction guards**: detect when a character forgets its own name, backstory, or relationships; flag in the eval harness.

### Wants of their own
- [ ] **Goal-directed autonomy**: the "LLMs move every N turns" behavior should pursue whims/goals/aspirations (lifesim WhimGeneration/GoalScoring), not act randomly.
- [ ] Ship the **behavior controller** with profiles (timid, aggressive, …) and the **script controller** as cheap alternatives for background characters, so worlds feel populated without full-LLM cost on every NPC.
- [ ] **Surprise budget**: occasionally allow grounded against-expectation actions (driven by trait + affect + memory) so characters aren't predictable — but never ungrounded.

### Memory, notes, reflection (self-improvement)
- [ ] **Habitual note-taking**: prompt LLM controllers to record what matters via the Focus-lane note system (NoteEntryComponent); notes then shape future behavior, not just sit there.
- [ ] **Reflection loop**: periodic synthesis (ReflectionTriggerSystem) where a character distills recent observations into higher-level insights/sentiment — the self-improvement substrate (generative-agents style).
- [ ] **Memory surfacing**: vector-search relevant memories into the prompt (RecentContext + MemoryProfile) so the right past moment recalls itself at the right time — the source of "they remembered!" magic.
- [ ] **Memory hygiene**: summarize/prune old notes and clean noise entities (your existing TODOs: forget action + noise cleanup) so context stays relevant and token cost stays bounded.

### Reading the room
- [ ] **Social-cue perception**: characters notice who's present, who's upset, who ignored them, who entered (PerceptionComponent / AttentionComponent) and react to it.
- [ ] **Relationship-driven behavior**: SocialBond + sentiment gate cooperation, warmth, and dialogue — grudges and fondness actually change how a character treats each person.
- [ ] **Emotional continuity**: affect/moodlets persist across sessions and color behavior (a character who lost a friend stays grieving).

### Growth
- [ ] **Learning by use**: skills-by-use + preference formation — characters improve at what they do and form likes/dislikes from experience, changing future choices.
- [ ] **Self-narrative revision**: bounded, validated aspiration/goal shifts after major life events (driven by reflections).
- [ ] **Offline life (mechanism)**: characters keep living — needs, goals, relationships, conversations — while players are away. (The *payoff* of this is world impact; see Stage 4.)

---

## Stage 3 — Depth of storytelling & conversation

### The conversation sub-loop (your open TODO)
- [ ] Implement a **threaded, immediate back-and-forth** conversation loop that doesn't burn a full world tick per line — a Focus-lane micro-loop nested under the existing tick model. Decide turn-taking and exit conditions explicitly. (This is the item with the most open design questions — prototype it early within the stage.)
- [ ] Support **multi-party scenes**: several characters in a room conversing, with turn-taking, resolving back into one coherent narrated passage.
- [ ] **Interruption / reaction**: characters can interject, gasp, or react mid-scene without consuming a full turn.

### Make speech carry weight
- [ ] Implement the **speech-intent enum** (inform, question, request, offer, joke, insult, threat, comfort, apology, praise, flirt, confession, promise, gossip) plus the daggersim **approach axis** (casual, polite, formal, blunt, deferential, courtly, underworld…). Infer intent when unspecified; let players set it explicitly when they want.
- [ ] **Social interpretation system**: how a line *lands* depends on the listener's mood, traits, and relationship — interpretation, not raw text, drives affect/relationship deltas. This is the "speech is world state" promise made real.
- [ ] **Conversation memory**: who said what, how it was interpreted, who overheard (SocialMemoryComponent). Conversations leave durable traces.
- [ ] **Gossip propagation**: overheard/relayed info spreads through the social graph, degrading into rumor (feeds daggersim's rumor → expansion loop, and Stage 4 reputation).

### Texture
- [ ] DM renders **subtext, tone, body language, pauses** — not just quoted dialogue (overlaps Stage 1).
- [ ] Make **silence/presence legible**: watching, brooding, or pointedly not speaking is also a social act and should read as one.

---

## Stage 4 — Real impact on the world: legacy & lasting actions

This is the most *ownable* stakes engine you have. No other text game has both the persistence and the population to make "what you did echoes" literally true. The job is to make consequence durable, visible, and emotional.

### Actions leave permanent marks
- [ ] **Physical persistence**: writing/carving on objects (exists), built structures, claimed homes/property, damage, and named/created artifacts persist in saves and remain discoverable later.
- [ ] **World history record**: notable deeds recorded into a queryable history projection (fortress-sim WorldHistory pattern) — the world keeps a memory independent of any single character, and the narrator can cite it (Stage 1 callbacks).
- [ ] **Creator signatures**: crafted artifacts carry maker/lore (fortress-sim Craftsmanship/Creator) — "made by X," "the blade Hazel forged the winter the well froze."

### Other minds carry your consequences
- [ ] **NPCs reference your deeds**: characters recall and act on what you did, in dialogue and behavior (built on Stage 2 memory, framed here as *your* footprint).
- [ ] **Reputation that reacts**: civic/regional/institutional reputation (daggersim) shifts services, ranks, prices, and guard response based on deeds; gossip (Stage 3) carries your name beyond the room.

### Legacy & generations
- [ ] **Death that lands**: meaningful, narrated, consequential — never a silent stat flip. (Respect the safety rules: suspended characters cannot die.)
- [ ] **Inheritance**: property, items, money, name, and relationships pass on (lifesim family + household funds + property deeds).
- [ ] **Generational memory**: a child grows up hearing about a parent; surviving characters remember and reference the dead. Lineage/family tree is durable world state across deaths.
- [ ] **Legacy / epilogue beats**: at a life's end or a scenario's resolution, surface what the character left behind — the seed for the next session or generation.

### Choices with teeth
- [ ] **Failure matters everywhere**: extend daggersim's ethos (quest failure → reputation loss, debt, rivals, follow-up quests) across packs. Decisions should cost something.
- [ ] **Tracked branching**: choices and their consequences are world state, not narration. Promises, threats, and agreements from Stage 3 become binding, tracked obligations.

### The world moves with and without you
- [ ] **Impact payoff of offline life**: the living world (Stage 2 mechanism) means a returning player finds it genuinely changed — relationships shifted, conflicts resolved or escalated, marks left by others.
- [ ] **Cross-player impact**: one player's actions visibly change the world another player inhabits — the shared-world promise made tangible.
- [ ] **Consequence survives restart**: verify all of the above persists through autosave/reload; mind the scripting-state vs world-state drift caveat when restoring scenarios.

---

## Stage 5 — Onboarding & packaging: present scenarios, ship a ready world

Two audiences: the **new player** who must not drown or face an empty room, and the **admin** who must be able to stand up a populated, scenario-ready world fast.

### New-player onboarding
- [x] Build a **valid-actions projection**: character views serialize registry-derived
  actions with per-character availability, costs, requirements, and unavailable reasons;
  action search progressively exposes the larger catalogue.
- [x] Build **valid-targets** resolution per action: `target_groups` contains the reachable
  exits, items, inventory, characters, and other entities named by each argument schema.
- [ ] **Tiered verb reveal**: start with the core five (move, look, take, use, say); reveal more as the player uses adjacent ones or the scenario calls for them.
- [x] **Progressive disclosure of detail**: component-owned facts carry numeric detail
  scores (`0` most important); standard turns use cutoff `10` and detailed status/inspection
  use cutoff `30`. First/second/third-person grammar remains separate from admin access,
  privacy, perception, and reachability.
- [ ] Collapse/hide advanced prompt sections (policy wall, deep needs, AP/FP accounting) for new characters until relevant.
- [ ] **Contextual nudges**: if a new player stalls for N ticks, the DM offers a gentle in-fiction prompt.
- [ ] **Context-aware help** in the existing threaded reply, keyed to the action just tried, not a generic manual.
- [ ] **New-player safe window**: safe spawn room, incident exemption for the first N epochs, gentler needs decay.
- [ ] Verify acted/moved/queued notifications fire consistently across web, TUI, and Discord.
- [ ] Onboarding telemetry: time-to-first-command, first-failure point, drop-off epoch → feed the harness.

### Scenario presentation (the default front door)
- [ ] Define a **scenario manifest**: world snapshot + cast + one-line hook + opening beat + arc/goal conditions + recommended pack set + difficulty + suggested player count + tone/genre tags.
- [ ] **Welcome-page scenario picker** for both players and admins: choose scenario → claim a character → drop into the opening beat. Sandbox stays available but secondary.
- [ ] Curate **3–6 headline scenarios** (small casts, clear dramatic pressure) polished to showcase quality: angel/devil debate, the apartment building, a mystery, a cozy one, one genre showpiece.
- [ ] Each scenario: sharp hook; distinct voice + goal + relationship per claimable character; ≥1 **arc condition** via scripting triggers (`epoch_at_least`, `event_type`, `event_fields`).
- [ ] **Opening beat via scripting**: stage an inciting incident in the first few ticks (`submit_command` / `patch_world`) so there's something to react to immediately.
- [ ] **Resolution / epilogue beat** wired to the Stage 4 legacy system.

### Admin: a world that's ready to go
- [ ] One-step world stand-up: extend the world-gen wizard into a **scenario wizard** that scaffolds premise → cast → opening beat → arc triggers and emits a valid manifest + scripts.
- [ ] Pack-aware setup: surface available plugins/packs and the starter bundles (peaceful / futuristic / fantastic) in the setup flow (worldgen is already plugin-aware).
- [ ] Bundle scenarios as one shareable artifact: world shorthand/snapshot + scripts + manifest, so admins and creators can publish and import them.
- [ ] Scenario-authoring guide + template, parallel to the world-generation guide.
- [ ] **Arc/progress projection** (acts → beats → climax) the DM reads to know where in the story it is (shared with Stage 1).

---

## Cross-cutting glue

- [ ] **Cost & latency tiering**: narrator + characters + reflection is a lot of inference. Tiered models (premium narrator, cheap background characters), batched reflection, cached personas. OpenRouter is wired; build budgeting on top.
- [ ] **Fun-focused playtest harness**: extend the existing harness (deterministic worlds, mocked at the Discord/MCP adapter) with quality checks — narration coherence, character consistency, conversation quality — not just correctness. The recurring question every session: *"was that a story I'd tell a friend?"*
- [ ] **Story-moment capture**: make great moments easy to capture and share (Discord-native). Word of mouth is how text games win.
- [ ] **Determinism preserved**: narration and character reflection must be reproducible on seeded worlds for testing (respect the scripting engine's determinism contract).

---

## Notes on this ordering

Stages 1–2 are the moat and the perceived-quality lever, so they come first; you'll playtest them through dev/admin direct play, not new-player flow. Stage 3 only pays off once narration and characters are good. Stage 4 turns "good sessions" into "stories people retell" — it leans almost entirely on systems you already have (family, death, property, reputation, history), so it's more wiring than invention. Stage 5 is last on purpose: don't polish the front door until the house is worth entering — but it's also the gate on *external* players, so it can't be skipped, only deferred.

**Add no new sim packs until Stages 1–3 are genuinely fun in a single polished scenario during dev play.**
