# Playtesting

Use this guide to test the public demo ladder:

> Apple Crossing -> Bell Green -> Clover City

The goal is to confirm that a new player can learn the rules in Apple Crossing, then
understand Bell Green as the shared small-town sandbox, and Clover City as the larger
dense-world showcase.

The ladder uses layered guidance rather than a forced walkthrough. Room summaries name exit
destinations, fixed boards provide route information, and hub guides answer spoken direction
questions through normal validated speech actions. Players can ignore those hints and explore.

For model reasoning through these same tutorial objectives, see the
[model compatibility list](model-compatibility.md) and
[Ollama tutorial-ladder benchmark](../developer/tutorial-benchmark.md). The harness measures
validated character-tool decisions in fresh worlds; it does not replace the browser,
Discord, multi-client, or human-usability checks in this guide.

## Shared setup

Record for every pass:

- Tester name or initials.
- Date, build, hosted URL, and generator name.
- Browser and device.
- Time to first connection.
- Time to character claim.
- First moment of confusion, quoted as closely as possible.
- Whether Discord, LLM, imagegen, and MCP were enabled.

Pass criteria for every world:

- Non-admin player can claim, look, move, inspect, and speak.
- Toon, Web REPL/TUI, and Discord show the same world state when those clients are enabled.
- Suggested actions and visible room contents point to the next useful action.
- No NPC or system declares success without matching world state.

## 1. Apple Crossing: Hungry Courier

Generator: `apple-crossing`

Apple Crossing is the first-run tutorial. The quest is **Hungry Courier**: help Pip eat,
then watch him deliver a letter to Mira's Cottage through normal world actions.

### Start

What to try:

- Open the welcome page and start the Toon client.
- Connect to the hosted server if it does not auto-connect.
- Claim Juniper.
- Find the current goal, checklist, suggested actions, inventory, actions, AP/FP, and
  activity feed.

Pass criteria:

- Tester can claim Juniper without help.
- The current goal mentions helping Pip deliver the courier letter.
- The suggested action points toward Apple Hedge when the player has no apple.

### Golden path

Expected beats:

1. Pippa Bramble introduces Pip and the delivery problem.
2. Player receives the Apple Crossing room view and can reread the notice board or ask Pippa.
3. Player identifies Pip, Pippa, the courier letter, and exits from that view.
4. Player goes east to Apple Hedge.
5. Player takes the red crossing apple.
6. Player returns west to Apple Crossing.
7. Player drops the apple beside Pip, puts it in the open courier basket, or gives it to Pip.
8. Player leaves Pip's courier letter on the post table, or drops it back in Apple Crossing
   if they picked it up.
9. Pip retrieves basket food if necessary and eats through normal `take` and `eat` actions.
10. Pip takes the courier letter.
11. Pip moves through Old Footbridge and Mira's Cottage Lane.
12. Pip reaches Mira's Cottage and writes the delivery ledger consequence.
13. Player confirms the consequence in activity, history, memory, or the ledger.

Pass criteria:

- Completion time is under 10 minutes.
- Pip visibly acts through normal validated actions: eat, take, move, write or drop.
- Tester can explain that Pip wanted to deliver the letter, but could not bypass hunger.

### Branch checks

Run these after the golden path:

- Player eats the apple before Pip can: Pip should remain hungry and ask or stall visibly.
- Player takes the courier letter: Pip should notice it is not reachable.
- Player ignores the quest: the world should continue without fake completion.
- Player follows Pip: Pip should move through real exits and remain observable.

Report:

- The exact step where the tester hesitated.
- Any action with unclear targeting, unavailable reason, or result text.
- Whether the delivery consequence was obvious enough.

## 2. Bell Green

Generator: `bell-green`

Bell Green is the small-town sandbox. It should feel like the next step after Apple
Crossing: more rooms, more residents, and more shared-town context without becoming dense.

### Town orientation

What to try:

- Claim Bram Hollow, Pippa Bramble, or another obvious resident.
- Orient from the initial Bell Green room view.
- Inspect the central notice board for the required orientation circuit; optional errands
  are listed separately.
- Ask Tansy Bell for directions or which required stop remains.
- Read the fixed shrine signs at Garden Walk or River Footbridge if needed.
- Visit Bell Green Post Office, Garden Walk, Hearthwick Inn, and Old Bell Shrine.

Pass criteria:

- Tester can identify Bell Green as a town center.
- Notice board text distinguishes the required circuit from optional goals.
- Tansy's authored answer identifies the main routes and remaining required stops without
  using an LLM provider.
- Exits are readable enough to navigate back to Bell Green.
- The post office, garden, store/workshop/inn, pet yard, and shrine feel distinct.

### Sandbox behavior

What to try:

- Inspect the community mailbox or sorted letters.
- Carry a harmless item between two rooms.
- Speak to one resident.
- Use a second client to observe the same room or item state.

Pass criteria:

- Shared-state changes are visible from another client.
- The town has enough readable hooks to suggest errands without requiring a linear quest.
- Discord output, if enabled, can claim a resident and inspect the notice board.

Report:

- Any room that feels redundant or hard to distinguish.
- Any resident whose role is unclear from name, room, or nearby objects.
- Any online/shared-state mismatch between clients.

## 3. Clover City

Generator: `clover-city`

Clover City is the advanced dense-world showcase. It should feel larger than Bell Green,
with shared facilities, routines, and overlapping tensions.

### City orientation

What to try:

- Claim Ada Warden.
- Orient from the initial Clover City Lobby room view.
- Inspect the daily bulletin.
- Inspect the directory board or ask Cleo Clover for directions.
- Visit Mailroom, Elevator, Laundry Room, Community Kitchen, Rooftop Garden, Security
  Office, and Street Stop.

Pass criteria:

- Tester can identify the lobby as the navigation hub.
- The daily bulletin clearly lists city-block tensions.
- The directory maps every shared facility from the lobby and its branch hubs.
- Shared facilities feel distinct from private apartments.
- The map feels denser than Bell Green without losing basic navigability.

### Dense-world behavior

What to try:

- Inspect the parcel locker or incident log.
- Move through elevator apartment exits.
- Observe at least three residents in different facilities.
- Use ordinary movement, inspection, and conversation while routines advance.
- At Street Stop, inspect the timetable and witness Rook move or hear a route report.
- Use a second client or Discord account to compare room and bulletin state.

Pass criteria:

- Tester understands Clover City as a larger social simulation, not a first-run tutorial.
- Residents, shared resources, and bulletin text imply overlapping needs or conflicts.
- Multi-client or Discord observation matches the same world state.

### Systemic story seeds

Use the same save and seed for each controller under evaluation. These are unresolved
world conditions, not scripted outcomes; intervene with ordinary actions and record what
actually happens.

- **Missing parcel:** find the misrouted parcel outside the mailroom, question or inform a
  witness, return or keep it, then write the result in the incident log. A completed report
  must identify the missing parcel as resolved. Fulfill Pip's open obligation and check its
  relationship consequence before and after restart.
- **Rooftop water shortage:** inspect the rationed rain barrel and limited community
  pantry, respond to the need pressure through sharing, replenishment, or theft, and check
  the Wick/Saffron obligation and persistent resource state after restart.
- **Elevator/noise dispute:** inspect the elevator incident and music-room complaint,
  involve Jun or Orla, perform available repair/social work, and write the outcome in the
  incident log. Confirm routines and explanations reflect disruption after restart.

Each run passes only if normal validated verbs drive it, at least three systems become
observable, a human can change the trajectory, state survives checkpoint/reload, and the
outcome remains recoverable rather than being forced by narration. Capture the bulletin,
incident log, known-room map, obligations/relationships, recent activity, and player/admin
explanations as evidence.

Report:

- Any navigation label that is confusing.
- Any facility that lacks an obvious purpose.
- Any performance, rendering, or output problem caused by the larger cast.

## Release acceptance

Attach results to the release manifest.

Record:

- Generator tested: `apple-crossing`, `bell-green`, or `clover-city`.
- Hosted deployment URL.
- Release manifest id/tag.
- Feature flags observed.
- Toon result.
- Web REPL/TUI result.
- Discord result, if enabled.
- Save/restart/reload result.
- Known issues discovered or reclassified.

Overall pass requires Apple Crossing golden path, Bell Green orientation, Clover City
orientation, non-admin claim/play, feature-flag disclosure, and known-issues classification.
The controlled preview additionally requires three reproducible systemic-story runs and a
passing 40-client stream rehearsal; neither a focused green check nor later green legs can
override a failed aggregate runner.

## Concurrent LLM players

Use the multiplayer harness when the players themselves should be LLM agents sharing one
live world. Each roster entry has its own player identity, character claim, system prompt,
provider client, bounded conversation history, and harness memory. `provider` and `model`
may be set per player; omitted values inherit `shared_provider` and `shared_model`.

Copy `examples/playtests/multiplayer-llm.yml`, expand `players` to any roster size, and keep
credentials in environment variables named by `access_token_env` or `password_env`. The
configuration file and result artifact must not contain bearer tokens, passwords, provider
keys, or claim secrets. Ollama Local, Ollama Cloud, and OpenRouter are supported. Provider
keys use the normal `OLLAMA_CLOUD_API_KEY` and `OPENROUTER_API_KEY` environment variables;
`ollama_host` and `openrouter_server_url` optionally override their endpoints.

Run an opt-in live test against Ollama Cloud first, then run the roster:

```bash
BUNNYLAND_LIVE_LLM=1 uv run --extra llm -m pytest \
  tests/test_live_multiplayer.py -m live_llm
scripts/run-multiplayer-llm examples/playtests/multiplayer-llm.yml \
  --output artifacts/playtests/multiplayer-llm.json
```

For the ten-player release exercise, configure ten distinct player credentials and ten
distinct claimable characters, set `max_concurrency: 10`, retain the 600-second per-player
timeout, and attach the JSON artifact to the canonical release checklist. The generic
harness reports `completed` only when supplied a scenario completion probe; its default
run is exploratory and ends at the turn limit. Release acceptance still requires the
Apple Crossing-specific aggregate: at least eight of ten fresh sessions complete within
ten minutes.
