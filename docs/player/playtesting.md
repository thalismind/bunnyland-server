# Playtesting

Use this guide to test the public demo ladder:

> Apple Crossing -> Bell Green -> Clover City

The goal is to confirm that a new player can learn the rules in Apple Crossing, then
understand Bell Green as the shared small-town sandbox, and Clover City as the larger
dense-world showcase.

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
2. Player looks around in Apple Crossing.
3. Player sees Pip, Pippa, the courier letter, and exits.
4. Player goes east to Apple Hedge.
5. Player takes the red crossing apple.
6. Player returns west to Apple Crossing.
7. Player drops or otherwise leaves the apple where Pip can reach it.
8. Pip eats through the normal `eat` action.
9. Pip takes the courier letter.
10. Pip moves through Old Footbridge and Mira's Cottage Lane.
11. Pip reaches Mira's Cottage and writes the delivery ledger consequence.
12. Player confirms the consequence in activity, history, memory, or the ledger.

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
- Look in Bell Green.
- Inspect the central notice board.
- Visit Bell Green Post Office, Garden Walk, Hearthwick Inn, and Old Bell Shrine.

Pass criteria:

- Tester can identify Bell Green as a town center.
- Notice board text gives several possible goals.
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
- Look in Clover City Lobby.
- Inspect the daily bulletin.
- Visit Mailroom, Elevator, Laundry Room, Community Kitchen, Rooftop Garden, Security
  Office, and Street Stop.

Pass criteria:

- Tester can identify the lobby as the navigation hub.
- The daily bulletin clearly lists city-block tensions.
- Shared facilities feel distinct from private apartments.
- The map feels denser than Bell Green without losing basic navigability.

### Dense-world behavior

What to try:

- Inspect the parcel locker or incident log.
- Move through elevator apartment exits.
- Observe at least three residents in different facilities.
- Wait or tick long enough to see routines or activity feed changes.
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
