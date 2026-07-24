# LLM tutorial-ladder benchmark

`scripts/benchmark-tutorials` measures how provider-backed models reason through the three public
tutorial worlds with Bunnyland's ordinary character prompts, action tools, command
validation, receipts, and authoritative ECS state:

- Apple Crossing / Hungry Courier as Juniper.
- Bell Green orientation as Bram Hollow.
- Clover City orientation as Ada Warden.

The default run creates ten fresh worlds for every model/tutorial pair. Sessions run
sequentially so provider contention does not distort comparative timing. Every session also
gets a fresh controller, provider agent, and conversation history. Model preflight does not
download or invoke a model. Ollama records parameter size, family, and quantization when
available; OpenRouter records the catalogue metadata it exposes.

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

Session duration and response length are separate controls. Most models stop normally, so
Ollama's model-profile output setting is retained by default. If a model can enter runaway
reasoning, use `--max-output-tokens` to cap a single response without shortening the session:

```bash
scripts/benchmark-tutorials \
  --model deep-reasoner:32b \
  --session-timeout 3600 \
  --max-output-tokens 8192
```

`--max-output-tokens` maps to Ollama's `num_predict`, which includes both thinking and final
answer/tool-call tokens. Do not use it for comparative reasoning runs unless that shared
budget is intentional: a thinking-heavy model can exhaust the cap before emitting its tool
call. Prefer the wall-clock session limit for the normal tutorial benchmark, and reserve the
token cap for explicitly labeled runaway-generation diagnostics.

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

## Running with OpenRouter

Set `OPENROUTER_API_KEY` in the environment and use the exact OpenRouter model id. The key is
used only for requests and is never written to benchmark artifacts.

```bash
export OPENROUTER_API_KEY='...'
scripts/benchmark-tutorials \
  --provider openrouter \
  --model openai/gpt-5.6-terra \
  --model anthropic/claude-sonnet-5 \
  --thinking medium \
  --tutorial bell \
  --tutorial clover \
  --sessions 2
```

`--thinking low|medium|high` maps to OpenRouter reasoning effort. Leave `--temperature`
unset to preserve each model/provider default. OpenRouter defaults to
`https://openrouter.ai/api/v1`; `--host` can override it.

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
Bell's carry milestone requires the item to be in Bram's inventory after crossing a room
boundary. Once authoritatively observed, a milestone remains achieved even if Bram later
returns the item. Tool selection alone is not success.

The initial full-room prompt projection counts as looking in Bell Green or the Clover City
Lobby. Requiring a redundant `look` tool call after the character has already received that
projection would measure command ritual rather than orientation.

The Clover missing-parcel, rooftop-water-shortage, and elevator/noise experiments are not
part of this model-size benchmark. Continue to use the fixed-snapshot controller experiment
for those systemic stories. Benchmark preparation suppresses Ada's authored story obligation
before the first prompt without removing it from the normal Clover City generator.

## Artifacts

The default output directory is `artifacts/benchmarks/tutorials`; change it with `--output`.

- `manifest.json` records the provider endpoint, model metadata, tutorials, session count,
  wall-clock limit, per-response token limit (when configured), turn limit, simulated seconds
  per turn, version, and commit.
- `summary.json` contains per-tutorial and complete-ladder rankings plus the 8/10 parameter
  threshold results.
- `sessions.jsonl` contains one result per fresh world, including status, milestones,
  action/rejection/recovery counts, first confusion signal, and repeated blocker groups.
- `traces.jsonl` contains each visible prompt, tool and arguments, decision latency,
  candidates, decision summary, policy rejection codes, submission outcome, command receipt,
  provider error, consecutive-repeat count, guard warning, result events, prompt-visible event
  ids, event-buffer omission counts, and milestone state. It does not contain or request
  hidden reasoning. A provider response without structured `tool_calls` is recorded as an
  `invalid_agent_response` policy rejection, with its bounded content excerpt in
  `receipt_reason`; it is never counted as a wait.
- `responses.jsonl` contains the complete JSON response returned by the provider for each
  turn, correlated by session and turn. It contains thinking or reasoning fields only with
  `--log-thinking`.
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

## Building the illustrated report

Build a Markdown report, a copy-ready comparison table, a Typst source document, tutorial
maps, and milestone heatmaps from one or more benchmark artifact directories:

```bash
scripts/build-tutorial-report \
  --input artifacts/benchmarks/tutorials/local-batch \
  --input artifacts/benchmarks/tutorials/cloud-batch \
  --output artifacts/benchmarks/tutorials/full-report \
  --title "Bunnyland tutorial ladder"
```

The report builder accepts an in-progress artifact directory and includes only checkpointed
sessions. Rerun the same command after more sessions complete; it replaces the derived report
files without changing the source traces, responses, logs, or session evidence.

The generated directory contains:

- `report.md`, the source-linked narrative and embedded SVG diagrams.
- `comparison-table.md`, the compact model, passes, milestones, validity, and
  milestones-per-turn table suitable for a README or server document.
- `report.typ`, the deterministic print layout.
- `diagrams/*-tabletop.png`, illustrated top-down world maps in Bunnyland's visual style.
- `diagrams/*-map.svg`, exact tutorial topology with milestone locations and persistent clue
  notes.
- `diagrams/*-milestones.svg`, heatmaps whose first row counts models that reached each
  milestone at least once and whose remaining rows show session reliability by model.

Install [Typst](https://typst.app/open-source/) and render the PDF with:

```bash
scripts/build-tutorial-report-pdf \
  artifacts/benchmarks/tutorials/full-report/report.typ \
  artifacts/benchmarks/tutorials/full-report/report.pdf
```

This is a character-tool reasoning benchmark. It does not test whether a human can discover
controls, read browser layout, interpret rendering, claim a character, or keep state aligned
across clients. Use the [player playtesting guide](../player/playtesting.md) for browser,
Discord, multi-client, and human-usability acceptance.

When benchmark results show a shared milestone bottleneck, review the
[diegetic guidance and recoverable world design](diegetic-world-guidance.md) standard before
assuming the intended model-size difficulty ramp is working. Tutorial difficulty should come
from increasingly rich planning, not one-time pop-ups, hidden command rituals, repeated
no-op waits, or clues that cannot be consulted again.
