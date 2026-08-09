# LLM providers and character controllers

Bunnyland can use Ollama or OpenRouter for world generation and LLM-controlled characters.
Provider access is optional: deterministic, scripted, behavioral, suspended, Discord, and MCP
controllers do not require a model call.

## Prerequisites

Complete the [world and persistence guide](worlds-plugins-persistence.md). Decide separately:

- whether a new world needs LLM generation;
- which characters need live model decisions;
- the maximum acceptable latency and spend;
- where provider credentials will be stored and rotated.

Install the LLM extra in the same environment as the service:

```bash
uv sync --locked --extra server --extra llm
```

## Keep credentials out of commands and config history

For Ollama Cloud:

```text
OLLAMA_CLOUD_API_KEY_FILE=/etc/bunnyland/ollama.key
OLLAMA_HOST=https://ollama.com
```

For OpenRouter:

```text
OPENROUTER_API_KEY_FILE=/etc/bunnyland/openrouter.key
```

Each key file should be owned by the service account and mode `0600`. Never expose a local
Ollama listener publicly. Do not put keys in world seeds, controller prompts, browser config,
logs, screenshots, or shell command arguments.

## Select providers and models

Ollama example:

```bash
uv run bunnyland serve \
  --llm \
  --llm-provider ollama \
  --worldgen-provider ollama \
  --worldgen-model deepseek-v4-pro \
  --character-model deepseek-v4-flash \
  --generator recursive \
  --max-rooms 6 \
  --save data/worlds/main.json
```

OpenRouter example:

```bash
uv run bunnyland serve \
  --llm \
  --llm-provider openrouter \
  --worldgen-provider openrouter \
  --worldgen-model PROVIDER/WORLDGEN_MODEL \
  --character-model PROVIDER/CHARACTER_MODEL \
  --generator recursive \
  --max-rooms 6 \
  --save data/worlds/main.json
```

Model names change more often than Bunnyland's CLI. Use a model currently available to your
provider account and test structured tool calling before inviting players. World generation
can use a stronger model than routine character turns. Loading an existing world does not
need the world-generation provider, but LLM-controlled characters still need their configured
character provider.

## Choose controllers by role

- **LLM** controllers make provider calls and act autonomously.
- **Behavioral** controllers evaluate a named behavior tree without a model call.
- **Scripted** controllers replay a fixed sequence of normal commands.
- **Discord** and **MCP** controllers let a person or external agent drive a claim.
- **Suspended** controllers take no action while world systems continue.

Use cheap deterministic controllers for background population and reserve LLM controllers for
characters whose judgment materially improves play. Controller handoff changes who proposes
actions; it does not bypass normal command validation.

When persistent behavior/script definitions are loaded by editors, store them with
`--controller-definitions` and include the file in the backup set.

## Control cost and failure impact

- Set a bounded `--max-rooms` for recursive generation.
- Test one or two characters before enabling a large autonomous population.
- Use provider-side budgets and alerts in addition to Bunnyland logs.
- Keep rejected text-tool-call protection enabled unless a compatibility test proves the
  selected provider requires otherwise.
- Do not silently fall back from one provider to another. A visible failed turn is safer than
  an unexpected provider, model, price, or data-processing boundary.

Character and world prompts may contain community-authored content. Review the provider's
retention and data-use terms and disclose the integration to players.

## Verify before long-running use

Start a disposable world with one tick and verbose logging:

```bash
uv run bunnyland serve \
  --llm \
  --llm-provider openrouter \
  --worldgen-provider openrouter \
  --worldgen-model PROVIDER/WORLDGEN_MODEL \
  --character-model PROVIDER/CHARACTER_MODEL \
  --generator recursive \
  --max-rooms 2 \
  --ticks 1 \
  --verbose
```

Confirm generation, a native structured tool call, normal command validation, and provider
usage reporting. Do not use production world paths for this test.

## Troubleshooting

### Bunnyland says a provider key is required

Confirm the matching literal or `_FILE` environment variable is visible to the service user.
Do not set both forms. Check file permissions from the service account, not only from your
interactive shell.

### A provider returns prose instead of a tool call

Use a model with reliable native structured tool calling. Keep rejection/retry protection
enabled and inspect bounded verbose logs without enabling prompt-content capture in production.

### Generation works but character turns fail

Worldgen and character providers/models can differ. Verify `--llm-provider` and
`--character-model`, and confirm the character provider key remains valid after startup.

### Costs rise unexpectedly

Reduce LLM-controlled population, move background actors to behavioral/scripted controllers,
lower generation room budgets, and inspect provider/model labels in telemetry. Do not solve a
budget issue by disabling command safety or authentication.

[← Worlds, plugins, persistence, and snapshots](worlds-plugins-persistence.md) ·
[Discord bot →](discord-bot.md)
