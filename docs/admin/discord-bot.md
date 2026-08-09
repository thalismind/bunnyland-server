# Discord bot

The Discord front-end lets a person drive a character through the same verbs an LLM uses. A
message like `!take marsh journal` becomes a validated command routed to that user's
character. The bot only translates input and relays results — it never touches the world
directly.

> **Status:** the bot is an MVP front-end that exposes the world-lane verbs (`!move`,
> `!say`, `!take`) and shares the LLM's name resolver. In production, run it with
> `bunnyland serve --discord` so it shares the same `WorldActor` as the simulation and API.

## Prerequisites and boundary

Complete [LLM providers and character controllers](llm-providers-controllers.md) even if
your Discord-driven characters do not use an LLM. The server should already run under a
dedicated account with durable world/auth state and a working HTTPS web client.

Discord is an ingress adapter, not a separate game server. Keep it in the Bunnyland process
that owns the `WorldActor`, restrict the guild/channel/DM sources it accepts, and configure
moderation separately. A Discord identity is not automatically linked to a Bunnyland web or
MCP identity.

## 1. Install the extra

```bash
uv sync --extra discord
```

## 2. Create the bot in Discord

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) →
   **New Application**.
2. **Bot** tab → **Reset Token** → copy the new **token**.
3. Under **Privileged Gateway Intents**, enable **Message Content Intent** (the bot reads
   `!` command text).
4. **OAuth2 → URL Generator**: scope `bot`; permissions **View Channels**,
   **Read Message History**, and **Send Messages**. Open the generated URL to invite the
   bot to your server.

## 3. Provide the token

Keep the token out of source control — put it in `.env` (git-ignored) and read it in your
launch script:

```
DISCORD_TOKEN=...
```

For a public native service, prefer a mode-`0600` credential file referenced by
`DISCORD_TOKEN_FILE=/etc/bunnyland/discord.token`. Do not set both `DISCORD_TOKEN` and
`DISCORD_TOKEN_FILE`. Never put the token in `bunnyland.yml` stored in Git, a command line,
chat, screenshots, world snapshots, or logs. Rotate it immediately in the Developer Portal
if it is exposed.

## 4. Wire a user to a character

A Discord user controls a character through a controller entity carrying a
`DiscordControllerComponent`. You assign it the same way any controller is assigned (see
[admin & controllers](./)):

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

Child life-stage characters are not claimable by default. Start the server with
`--discord-allow-child-claims` only if that world intentionally allows players to control
child characters.

By default, the bot ignores non-command messages but accepts `!` commands from any guild
channel or DM it can read. To restrict inbound commands, set one or more allowlists:

```bash
BUNNYLAND_DISCORD_ALLOWED_GUILD_IDS=111,222 \
BUNNYLAND_DISCORD_ALLOWED_CHANNEL_IDS=333,444 \
BUNNYLAND_DISCORD_ALLOWED_DM_USER_IDS=123,456 \
uv run --extra server --extra discord bunnyland serve --discord
```

The matching rules are:

| Filter                           | Effect                                                  |
|----------------------------------|---------------------------------------------------------|
| `--discord-allowed-guild-id`     | Accept guild messages only from these guilds.           |
| `--discord-allowed-channel-id`   | Accept guild messages only from these channels.         |
| `--discord-allowed-dm-user-id`   | Accept DMs only from these users.                       |
| `--discord-allowed-bot-user-id`  | Accept commands from this bot user id.                  |

Repeat the CLI flags to allow more than one id. If both guild and channel filters are set,
a guild message must match both. DM messages are accepted only when the author is listed in
`--discord-allowed-dm-user-id` or `BUNNYLAND_DISCORD_ALLOWED_DM_USER_IDS`.

The bot normally ignores Discord bot authors to prevent bot-to-bot loops and accidental
commands from integrations. To allow a specific bot actor, set
`BUNNYLAND_DISCORD_ALLOWED_BOT_USER_IDS` or repeat `--discord-allowed-bot-user-id`, and
keep the normal guild/channel allowlists restricted to the channels where bot-authored
commands are expected.

## Moderator configuration and commands

Discord moderation affects Bunnyland identities and sessions only. It never kicks, times
out, or bans anyone from a Discord guild. Authorize moderators by explicit Discord user ID,
guild role ID, or both:

```bash
BUNNYLAND_DISCORD_MODERATOR_USER_IDS=123,456 \
BUNNYLAND_DISCORD_MODERATOR_ROLE_IDS=789,987 \
uv run --extra server --extra discord bunnyland serve --discord
```

The equivalent repeatable flags are `--discord-moderator-user-id` and
`--discord-moderator-role-id`. In guild channels, either a configured user ID or one of the
caller's configured roles authorizes `!mod`. In DMs, only a configured user ID authorizes
moderation. Unauthorized calls and self-targeting are rejected before the target is acted
on.

```text
!mod kick <target> <reason>
!mod suspend <target> <duration> <reason>
!mod ban <target> <reason>
!mod lift <target> <reason>
!mod status <target>
!mod history <target>
```

Discord mentions and bare snowflakes select a Discord user. Explicit targets may use
`discord:<snowflake>`, `web:<auth-subject>`, or `client:<client-id>`. Durations accept
positive whole `s`, `m`, `h`, `d`, and `w` units, such as `30s`, `15m`, `2h`, `7d`, or
`4w`; there is no configured product maximum. The existing player-owned `!suspend` command
is separate and unchanged.

Every action requires a reason and creates an append-only audit entry. Kick releases every
current claim, applies each claim's fallback controller, clears queued work, revokes web
sessions, and closes player sockets, but permits immediate sign-in. Suspend adds a finite
UTC wall-clock restriction; ban has no expiration. Lift removes either restriction, but
does not restore sessions or claims.

Discord, web, and unauthenticated client identities are separate; Bunnyland does not link
accounts. `client:` restrictions are only a best-effort embedding control because an
unauthenticated caller can choose a new client ID.

If you do not know the numeric user id yet, omit `BUNNYLAND_DISCORD_USER_ID` and claim from
Discord instead:

```text
!claim Juniper
```

Character names can be shortened when the prefix is unique. With no character name,
`!claim` assigns the first suspended claimable character. Use `!characters` to list the
current world's character names.

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
| `!claim [name]`    | Claim a character for your Discord user.           |
| `!release`         | Release your character claim.                      |
| `!suspend`         | Idle your character until your next command.       |
| `!characters`      | List character names in the current world.         |
| `!look`            | Show the current room summary and exits.           |
| `!help [topic]`    | Help for humans, agents, or a specific verb.       |

`!suspend` transfers control to an idle controller but keeps your claim; your next command
resumes Discord control automatically. `!release` removes your claim entirely. Neither command
pauses or resumes the whole world.

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

## Troubleshooting

### The bot is online but ignores commands

Confirm **Message Content Intent** is enabled, the bot can view/read/send in the channel,
and the guild/channel/DM allowlists match numeric IDs. If both guild and channel lists are
configured, a guild command must match both.

### Startup says the Discord token is missing

Check that exactly one of `DISCORD_TOKEN` and `DISCORD_TOKEN_FILE` is visible to the service
account. A credential file must contain only the token and be readable by that account.

### `!claim` cannot find a character

Run `!characters`, use an unambiguous name prefix, and confirm a claimable character is
suspended. Child characters require the explicit `--discord-allow-child-claims` policy.

### Moderator commands return unauthorized

Guild commands require an allowed moderator user ID or role ID; DMs require an allowed user
ID. Discord administrator permission alone does not grant Bunnyland moderation.

### The bot reconnects but the world does not advance

The shared server process must still run the game loop. Check the Bunnyland service and its
provider/controller errors rather than restarting a separate Discord-only process.

[← LLM providers and character controllers](llm-providers-controllers.md) ·
[MCP server and local agents →](mcp-local-agent.md)
