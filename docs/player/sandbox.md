# Crossroads sandbox

The `bunnyland-sandbox` generator creates a shared Crossroads world from the plugins that
the server actually loaded. It always includes Crossroads Arrival, four claimable New
Arrival characters, Crossroads Commons, and the optional After Dark district.

Each loaded bundled simpack adds one region to the Commons. An unloaded simpack contributes
nothing: no room, exit, object, character, or guidance. The entities in each region use the
simpack's ordinary generation intents and enrichment, so its normal actions and projected
state work in every player client.

From Crossroads Arrival, look around and move east:

```text
look
inspect target_id=<arrival-guide-id>
move direction=east
inspect target_id=<commons-map-id>
```

The Commons map describes the regions present in this particular world. Follow their
ordinary exits and use the actions exposed for nearby enriched entities.

## Enter and leave After Dark

After Dark is an optional adults-only district. Entry acknowledgement controls entry only;
it does not grant consent for romance, sexual content, violence, or any other independently
gated interaction.

Read the entrance warning, explicitly acknowledge it, and enter through the nearby marker:

```text
inspect target_id=<after-dark-entrance-id>
accept-after-dark-warning acknowledged=true
enter-after-dark entrance_id=<after-dark-entrance-id>
```

Leave at any time without a consent check:

```text
leave-after-dark exit_id=<after-dark-exit-id>
```

Withdraw future entry consent from anywhere:

```text
withdraw-after-dark-consent
```

Withdrawal never traps a character inside. Use the exit action normally, then acknowledge
the warning again later if you decide to return. A character-level `adult` denial or a
world-policy disablement always blocks entry and is never overridden by the sandbox.

## Launch with LLM representatives

The sandbox gives its five regional representatives deterministic behavioral controllers by
default and leaves the four New Arrivals suspended for players to claim. To generate the
world in memory and play it entirely inside the offline terminal TUI, run:

```bash
scripts/launch-sandbox-tui-llm \
  --chat-provider ollama-local \
  --chat-model MODEL
```

This starts no HTTP server and writes no world file. The TUI hosts and ticks the world in
its own process. `--llm` makes the sandbox generator assign LLM controllers to the regional
representatives, while the New Arrivals remain available to claim. The representative
controllers use the same provider, model, and endpoint as terminal character chat.

For OpenRouter instead:

```bash
export OPENROUTER_API_KEY_FILE=/absolute/path/to/openrouter.key
scripts/launch-sandbox-tui-llm \
  --chat-provider openrouter \
  --chat-model PROVIDER/MODEL
```

You can omit the provider flags after saving terminal LLM settings on an earlier local TUI
run. The generic equivalent is `uv run --extra tui --extra llm bunnyland tui --generator
bunnyland-sandbox --llm`.
