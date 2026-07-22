# Ollama tutorial-ladder benchmark

`scripts/benchmark-tutorials` measures how Ollama models reason through the three public
tutorial worlds with Bunnyland's ordinary character prompts, action tools, command
validation, receipts, and authoritative ECS state:

- Apple Crossing / Hungry Courier as Juniper.
- Bell Green orientation as Bram Hollow.
- Clover City orientation as Ada Warden.

The default run creates ten fresh worlds for every model/tutorial pair. Sessions run
sequentially so provider contention does not distort comparative timing. Every session also
gets a fresh controller, Ollama agent, and conversation history. Ollama's `show` endpoint
preflights each model without downloading it and records the parameter size, family, and
quantization when the provider supplies them.

## Running locally

Install the `llm` extra and make sure each requested model already exists in Ollama. A local
run defaults to `http://127.0.0.1:11434`:

```bash
scripts/benchmark-tutorials \
  --model qwen3:4b \
  --model qwen3:8b
```

Use `OLLAMA_HOST` or `--host` for another endpoint. `--model` and `--tutorial` are
repeatable; omitting `--tutorial` runs `apple`, `bell`, and `clover`.

```bash
OLLAMA_HOST=http://model-host:11434 scripts/benchmark-tutorials \
  --model qwen3:8b \
  --tutorial bell \
  --tutorial clover \
  --sessions 10
```

The wall-clock session limit defaults to 600 seconds, but reasoning models can need much
longer. Set it in seconds with `--session-timeout`; the configured value becomes the pass
deadline and is recorded in the manifest. `--turn-limit` remains an independent action-loop
safety limit.

```bash
scripts/benchmark-tutorials \
  --model deep-reasoner:32b \
  --session-timeout 3600 \
  --turn-limit 90
```

Use `--thinking low|medium|high` and `--temperature` to pin Ollama reasoning and sampling
settings. Unspecified sampling options retain each model's provider or model-profile
defaults, which is useful when families recommend different `top_p` or `top_k` values.
Every raw Ollama response is recorded with its content, tool calls, token counts, and timing
fields. Thinking text is omitted by default; add `--log-thinking` to retain Ollama's
`message.thinking` field in `responses.jsonl`.

Use `--repeat-command-guard` to bound exact repetition without prescribing a tutorial
solution. After five consecutive identical tool-and-argument calls, the next prompt warns
the agent to choose a different action. A tenth identical call ends that session with
`repeat_limit`; tutorial outcomes remain report-only.

## Running with Ollama Cloud

Set the credential only in the environment. It is used for requests but never written to
benchmark artifacts.

```bash
export OLLAMA_CLOUD_API_KEY='...'
scripts/benchmark-tutorials \
  --provider ollama-cloud \
  --model deepseek-v4-flash \
  --session-timeout 1800
```

Ollama Cloud defaults to `https://ollama.com`; `--host` can override it.

## Objectives and scoring

The model receives a high-level tester objective, not a route or scripted solution. Apple
uses Juniper's existing Hungry Courier goal. Bell asks Bram to orient himself, read the
notice board, visit the documented destinations, interact with a resident, and carry an
item between rooms. Clover asks Ada to read the bulletin, inspect major facilities, and
observe city activity.

A tutorial result never changes the process exit code. Configuration, provider, or artifact
write failures return nonzero; a low tutorial score remains report data.

Per-tutorial and full-ladder rankings consider, in order:

1. Sessions completed within the configured wall-clock limit and pass rate.
2. Median completion time and turns.
3. Milestone completion.
4. Valid actions, rejections, and recovery within two later decisions.

The summary also identifies the smallest model with a known parameter count that reaches at
least 8/10 on each tutorial. When all three tutorials are selected, it also reports the
smallest model reaching 8/10 independently on Apple, Bell, and Clover.

Milestones are evaluated from command result events and authoritative state. For example,
Apple does not complete until the delivery ledger contains the Hungry Courier mark, and
Bell's carry milestone requires the item to remain in Bram's inventory after crossing a
room boundary. Tool selection alone is not success.

The Clover missing-parcel, rooftop-water-shortage, and elevator/noise experiments are not
part of this model-size benchmark. Continue to use the fixed-snapshot controller experiment
for those systemic stories.

## Artifacts

The default output directory is `artifacts/benchmarks/tutorials`; change it with `--output`.

- `manifest.json` records the provider endpoint, model metadata, tutorials, session count,
  wall-clock limit, turn limit, simulated seconds per turn, version, and commit.
- `summary.json` contains per-tutorial and complete-ladder rankings plus the 8/10 parameter
  threshold results.
- `sessions.jsonl` contains one result per fresh world, including status, milestones,
  action/rejection/recovery counts, first confusion signal, and repeated blocker groups.
- `traces.jsonl` contains each visible prompt, tool and arguments, decision latency,
  candidates, decision summary, policy rejection codes, submission outcome, command receipt,
  provider error, consecutive-repeat count, guard warning, result events, and milestone
  state. It does not contain or request hidden reasoning.
- `responses.jsonl` contains the complete JSON response returned by Ollama for each turn,
  correlated by session and turn. It contains thinking text only with `--log-thinking`.
- `benchmark.log` contains timestamped lifecycle, turn, session, retry, warning, and error
  messages from the run.
- `report.md` is a human-readable model and per-tutorial comparison with instructions for
  rerunning the matrix with additional repeatable `--model` options.

If a long matrix is resumed into more than one output directory, combine completed batches
without copying or rewriting their full trace evidence:

```bash
scripts/compare-tutorial-benchmarks \
  --input artifacts/benchmarks/tutorials/first-batch \
  --input artifacts/benchmarks/tutorials/resumed-batch \
  --output artifacts/benchmarks/tutorials/comparison
```

Add later batches with more repeatable `--input` options. The comparison command rejects
missing or unequal model/tutorial cells and incompatible provider settings rather than
silently producing an unfair ranking. Its report links each source directory, where full
prompts, responses, thinking fields, traces, and logs remain unchanged. Traced attempts
without a completed session row are listed as interrupted evidence and excluded from scores.
If a mixed source contains superseded trials, select only one model from it with repeatable
`--input-model 'model-name=artifact-directory'` options.
When interrupted/resumed sources contain more completed attempts than intended, use
`--sessions-per-cell N` to keep the first N attempts per model/tutorial in source order.
Excluded completed attempts remain listed in `summary.json` and the source evidence stays
unchanged.

Trace rows are flushed and synced after every completed turn. Session rows, the partial
summary, and the report are checkpointed after every completed session, so an interruption
retains all completed evidence instead of losing the whole matrix.

This is a character-tool reasoning benchmark. It does not test whether a human can discover
controls, read browser layout, interpret rendering, claim a character, or keep state aligned
across clients. Use the [player playtesting guide](../player/playtesting.md) for browser,
Discord, multi-client, and human-usability acceptance.
