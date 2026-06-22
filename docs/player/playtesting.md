# Playtesting checklist

Use this guide during a hosted Bunnyland playtest. It is a timed pass through the public
site, sandbox, clients, character sheet, admin world generation, world inspection, and
final feedback.

The whole pass takes about 45 to 60 minutes. Spend longer anywhere you find confusing,
broken, or especially promising behavior.

## 1. Public site

Start at [bunnyland.dev/#world](https://bunnyland.dev/#world). Read the current world and
sandbox entry point before opening any clients.

What to try:

- Check whether the page explains what the sandbox is and where to begin.
- Find the current world description, sandbox link, and any guide links.
- Note what you expect to happen before you open the sandbox.

What to report:

- Anything that made the sandbox purpose unclear.
- Any dead, misleading, or surprising links.
- Any wording that set the wrong expectation before play began.

## 2. Sandbox client chooser

Open [sandbox.bunnyland.dev](https://sandbox.bunnyland.dev/) and note the available
clients and admin tools.

What to try:

- Identify the Web TUI, Toon client, Web REPL, character sheet, world generator, and
  inspector links.
- Check whether one client looks like the recommended starting point.
- Confirm whether the page mentions the API server it will use.

What to report:

- Missing, duplicate, or surprising client links.
- Tools that look player-facing but require admin access.
- Any page text that does not match the clients you can actually open.

## 3. Guide index

Open [bunnyland.dev/guides](https://bunnyland.dev/guides/). Skim
[Getting started](getting-started.md), [Client guides](clients/README.md), and the guide
for the client you plan to try first.

What to try:

- Find the basic actions for looking, moving, speaking, taking items, and using items.
- Compare the client guide list with the client links on the sandbox page.
- Keep the guides open so you can check commands while playing.

What to report:

- Missing links between guides and live clients.
- Places where a guide assumes too much prior knowledge.
- Any command examples that do not match what the client accepts.

## 4. Web clients

Spend about 5 minutes each with the browser clients before trying terminal clients.

What to try:

- In [Web TUI](https://sandbox.bunnyland.dev/web-tui.html), choose or claim a character,
  read the room, search for an action, choose a target, submit it, and watch the queue.
- In [Toon client](https://sandbox.bunnyland.dev/toon-client.html), identify your sprite,
  move around, click nearby sprites or objects, and try an action menu command.
- In [Web REPL](https://sandbox.bunnyland.dev/web-repl.html), use `who`, `look`,
  `inventory`, `points`, `queued`, and one action you already tried elsewhere.
- Move to another room and return in at least one web client.

What to report:

- Whether you could tell what was clickable and what was only informational.
- Any action form that lacked enough labels, targets, or feedback.
- Any sprite, room, or door that was hard to identify.
- Whether command output, queued results, and rejection messages matched across clients.
- Commands that were hard to discover without reading the guide.

## 5. Terminal clients

Try terminal clients after the browser clients. Connect to the sandbox server when the
playtest instructions provide a command or server URL; otherwise run them locally and note
that you could not reach the hosted sandbox from the terminal.

What to try:

- Run the Terminal TUI and compare its panels with the Web TUI.
- Run the Terminal REPL and compare command entry with the Web REPL.
- Use the same character and repeat one action sequence from a browser client if possible.

What to report:

- Whether the setup instructions were enough to connect to the sandbox.
- Any difference in available actions, targets, or command results.
- Terminal layout, keyboard, or color issues that made play harder.

## 6. Character sheet

Open [Character Sheet](https://sandbox.bunnyland.dev/character-sheet.html) from a client
button or direct link.

What to try:

- Inspect portrait, identity, description, status, needs, and profile details.
- Check current room, visible characters, exits, inventory, relationships, and actions.
- Open sheets for another visible character if the client allows it.

What to report:

- Missing or stale character data after moving or acting.
- Any section whose label was unclear.
- Any portrait, relationship, inventory, or action detail that contradicted the client.

## 7. Optional Discord play

Use Discord only when the guide says the current playtest has a live channel and
bot available.

What to try:

- Claim or control a character using the channel instructions.
- Try the same basic sequence from [Getting started](getting-started.md).
- Compare Discord responses with the web or terminal client output.

What to report:

- Any message syntax that was not obvious.
- Bot responses that were delayed, missing, too noisy, or missing useful links.
- Any Discord-only blocker that prevented normal play.

## 8. Admin password

Ask the guide for the admin password when the playtest reaches the admin portion.
Do not publish, paste into notes, or hard-code the password in any feedback.

What to try:

- Confirm which username, password, and sandbox URL the guide wants you to use.
- Sign in only on the deployed admin pages for this playtest.

What to report:

- Any login prompt or authentication failure that blocked the admin steps.
- Any place where the password appeared visible after submission.

## 9. World Generator

Open [World Generator](https://sandbox.bunnyland.dev/world-generator.html). Create a new
world for the sandbox after confirming with the guide that replacing the current
world is expected.

What to try:

- Pick a generator and enter a short seed or prompt.
- Set a small room budget for a quick test.
- Use the required reset confirmation, start generation, and watch progress.
- Wait for the generator to finish before inspecting or playing the new world.

What to report:

- Any generator option whose purpose was unclear.
- Progress states that got stuck, skipped useful details, or failed silently.
- Generated-world failures, partial resets, or confusing completion messages.

## 10. World Inspector

Open [World Inspector](https://sandbox.bunnyland.dev/inspector.html) and inspect the world
you generated.

What to try:

- Check rooms, exits, characters, inventory, containers, and obvious interactable items.
- Follow edges between rooms and characters.
- Look for broken links, missing names, empty rooms, unreachable exits, or orphaned items.
- Toggle the event feed if available and watch whether activity appears while you play.

What to report:

- Rooms with no useful exits or no clear reason to exist.
- Characters without enough identity, location, or playable actions.
- Items that looked important but had no apparent use.
- Any graph, inspector panel, or event feed display that contradicted player-client output.

## 11. Play the generated world

Open [Web TUI](https://sandbox.bunnyland.dev/web-tui.html) again and explore the newly
generated world as a player.

What to try:

- Claim a character in the generated world.
- Move through several rooms and interact with at least two objects or characters.
- Check whether the generated setting gives you a reason to keep exploring.
- Open a character sheet again after playing for a few turns.

What to report:

- The first point where you felt blocked or unsure what to do.
- Whether generated rooms, exits, characters, and objects supported actual play.
- Any difference between what the inspector suggested and what the player client allowed.

## 12. Submit feedback

Submit feedback in the form, issue, thread, or document the guide provides.

Include:

- Bugs, crashes, broken links, and error messages.
- Confusing moments and the exact client or page where they happened.
- Which client you preferred and why.
- Missing affordances, labels, buttons, shortcuts, or feedback.
- Generated-world quality: rooms, exits, characters, objects, goals, and broken links.
- Anything that blocked play or required guide help.
