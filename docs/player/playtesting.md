# Playtesting

Use this guide for the public-preview first-session pass. The pass starts at the welcome
page, uses the Toon client as the canonical first-user path, and validates the working
quest: **The Hungry Courier**.

The product goal is that a fresh tester can finish the demo in under 10 minutes and say:

> The NPC wanted to do something, but had to solve the same world problems I did.

## Product success metrics

- New user can start the Toon client without help.
- New user can complete Hungry Courier in under 10 minutes.
- New user can explain the core mechanic: agents act through the same world rules.
- User sees at least one visible consequence: delivery, memory, history, activity, or reply.

## Technical readiness metrics

- Hosted deployment acceptance checklist passes.
- Backup/restore drill passes.
- Non-admin player path passes.
- Discord path passes if enabled.
- Feature flags match public disclosure.
- Release manifest exists.
- Known issues are classified.

## Tester setup

Start a timer before opening the public welcome page. Do not read source code or admin
tools first.

Record:

- Tester name or initials.
- Date and hosted URL tested.
- Browser and device.
- Time to first successful Toon connection.
- Time to character claim.
- Time to courier delivery consequence.
- The first moment of confusion, quoted as closely as possible.
- The tester's explanation of the core mechanic after the run.

## 1. Welcome page

Open the sandbox welcome page.

What to try:

- Identify the primary first step without help.
- Confirm that **Play in Toon Client** is the obvious primary action.
- Read the "Start here" actions before opening a client.

Pass criteria:

- Tester opens Toon first without being told.
- Tester can name the first action they expect to take.

Report:

- Any equal-weight client-choice confusion.
- Any wording that makes the demo sound like a scripted movie instead of a live world.

## 2. Toon client start

Open the Toon client from the welcome page.

What to try:

- Connect to the hosted server if it does not auto-connect.
- Claim Juniper or the obvious available player character.
- Find the current goal, checklist, suggested actions, AP/FP, inventory, actions, and
  activity feed.

Pass criteria:

- Tester can claim a character without synchronous help.
- Checklist shows progress or can be reset for another run.

Report:

- Any claim, controller, auth, or reconnect issue.
- Any first-run guidance that is hidden below too much UI.

## 3. Hungry Courier golden path

Complete the golden path without using admin tools.

Expected beats:

1. Postmaster Wren introduces Moss and the delivery problem.
2. Player looks around in Clover Post Office.
3. Player goes east to Market Lane.
4. Player takes the red market apple.
5. Player returns west.
6. Player drops or otherwise leaves food where Moss can reach it.
7. Moss eats through the normal `eat` action.
8. Moss takes the courier letter.
9. Moss moves through exits toward Moss Kiosk.
10. Moss writes to the delivery ledger or creates an equivalent visible consequence.
11. Player checks activity, history, memory, ledger, or another consequence surface.

Pass criteria:

- Completion time is under 10 minutes.
- Moss visibly acts through normal validated actions.
- The tester can explain that Moss wanted to deliver, but could not bypass hunger.

Report:

- The exact step where the tester hesitated.
- Any action that lacked a clear target, unavailable reason, or useful result.
- Whether the visible consequence was obvious enough.

## 4. Branch checks

Run these as short follow-up passes after the golden path has been tested.

Player eats the food:

- Take the apple and eat it before Moss can.
- Moss should remain hungry and ask, adapt, or fail visibly.

Player takes the letter:

- Take the courier letter before Moss can.
- Moss should notice it is not reachable and react.

Player ignores the quest:

- Wait or explore without helping.
- The world should continue; Moss should not declare success without state support.

Player follows Moss:

- After feeding Moss, follow room by room.
- Moss should move through real exits and remain observable.

Pass criteria:

- Branches fail or adapt through normal command validation, not silent script breaks.
- Rejections or stalled behavior produce understandable feedback.

## 5. Multiclient check

Open Web REPL or Web TUI as a second client during or after the run.

What to try:

- Inspect the same character, room, inventory, or ledger state.
- Confirm the courier consequence is visible outside Toon.
- Submit one harmless command from the second client if using a separate claimed character.

Pass criteria:

- Both clients show the same world state.
- No client claims impossible state or hides the consequence.

## 6. Optional Discord check

Run this section only if Discord is enabled for the release manifest.

What to try:

- Claim or play from a non-admin Discord account.
- Reconnect after leaving and returning.
- Compare Discord command output with Toon or Web REPL state.

Pass criteria:

- Non-admin claim/play/reconnect works.
- Discord feature state matches public disclosure.

## 7. Release acceptance record

Attach this result to the release manifest.

Record:

- Hosted deployment URL.
- Release manifest id/tag.
- Feature flags observed: LLM, imagegen, Discord, MCP.
- Non-admin path result.
- Discord path result, if enabled.
- Save/restart/reload result.
- Backup/restore drill result.
- Known issues discovered or reclassified.

Overall pass requires the golden path, non-admin path, release manifest, feature-flag
disclosure, and known-issues classification to be complete.
