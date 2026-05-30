# Discord bot

The Discord front-end lets a person drive a character through the same verbs an LLM uses. A
message like `!take marsh journal` becomes a validated command routed to that user's
character. The bot only translates input and relays results — it never touches the world
directly.

> **Status:** the bot is an MVP front-end that exposes the world-lane verbs (`!move`,
> `!say`, `!take`) and shares the LLM's name resolver. In production, run it with
> `bunnyland serve --discord` so it shares the same `WorldActor` as the simulation and API.

## 1. Install the extra

```bash
uv sync --extra discord
```

## 2. Create the bot in Discord

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) →
   **New Application**.
2. **Bot** tab → **Add Bot** → copy the **token**.
3. Under **Privileged Gateway Intents**, enable **Message Content Intent** (the bot reads
   `!` command text).
4. **OAuth2 → URL Generator**: scope `bot`; permissions **Read Messages/View Channels** and
   **Send Messages**. Open the generated URL to invite the bot to your server.

## 3. Provide the token

Keep the token out of source control — put it in `.env` (git-ignored) and read it in your
launch script:

```
DISCORD_TOKEN=...
```

## 4. Wire a user to a character

A Discord user controls a character through a controller entity carrying a
`DiscordControllerComponent`. You assign it the same way any controller is assigned (see
[admin & controllers](admin.md)):

```python
from bunnyland.core import SuspendedComponent, WorldActor, spawn_entity
from bunnyland.core.controllers import DiscordControllerComponent
from bunnyland.plugins import apply_plugins, bunnyland_plugins
from bunnyland.worldgen import StubWorldBuilder, instantiate

actor = WorldActor()
apply_plugins(bunnyland_plugins(), actor)
world = await instantiate(actor, StubWorldBuilder().propose("a quiet marsh"))

# Hand the claimable character (Juniper) to a Discord user.
character_id = world.characters["juniper"]
controller = spawn_entity(
    actor.world,
    [DiscordControllerComponent(discord_user_id=YOUR_DISCORD_ID, default_channel_id=CHANNEL_ID)],
)
actor.assign_controller(character_id, controller.id)
character = actor.world.get_entity(character_id)
if character.has_component(SuspendedComponent):
    character.remove_component(SuspendedComponent)   # or use a control verb (see admin docs)
```

`discord_user_id` is the numeric Discord user id (enable Developer Mode in Discord, then
right-click a user → *Copy User ID*).

## 5. Run the bot

For the server process, prefer `bunnyland serve --discord`:

```bash
DISCORD_TOKEN=... \
BUNNYLAND_DISCORD_USER_ID=123 \
BUNNYLAND_DISCORD_CHANNEL_ID=456 \
BUNNYLAND_DISCORD_CHARACTER=Juniper \
uv run --extra server --extra llm --extra discord bunnyland serve \
  --llm \
  --discord \
  --load worlds/main.json \
  --save worlds/main.json \
  --ticks 0 \
  --api-host 127.0.0.1 \
  --api-port 8765
```

If `BUNNYLAND_DISCORD_USER_ID` is set, startup creates a Discord controller for that user
and assigns it to `BUNNYLAND_DISCORD_CHARACTER`; if no character name is set, the first
suspended claimable character is used.

For embedded tools or tests, you can still construct the bot directly:

```python
import os
from bunnyland.discord import DiscordBot

bot = DiscordBot(actor, token=os.environ["DISCORD_TOKEN"])
bot.run()   # blocking; runs the Discord client
```

`DiscordBot` does not advance the simulation by itself — the host process must run the game
loop on the same `actor` so ticks process the commands users submit.

## Player commands

| Command            | Action                                            |
|--------------------|---------------------------------------------------|
| `!move <direction>`| Move through an exit, e.g. `!move north`.          |
| `!take <name>`     | Pick up an item, e.g. `!take marsh journal`.       |
| `!say <text>`      | Speak to everyone in the room.                     |

### Names, not ids

Players refer to things by name. The bot resolves names to entities exactly as the LLM
dispatch does: case-insensitive, with a prefix match (so `!take mar` finds the *marsh
journal*). If a name can't be resolved, the bot replies with a suggestion instead of queuing
a doomed command:

```
> !take jurnal
I don't see 'jurnal' (item) here. Did you mean: marsh journal?
```

This is the same `did_you_mean` helper the LLM agents get as a prompt hint — humans and
agents are coached identically.
