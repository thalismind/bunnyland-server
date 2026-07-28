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

The harness deliberately uses the standard `ControllerDispatch`, Ollama/OpenRouter agents,
prompt projection, event buffering, tool-result history, command validation, and receipts.
Provider and per-character scheduling fixes belong to those shared gameplay paths, with
standard game-loop regression coverage; the harness owns only session orchestration,
scoring, safety limits, and artifacts.

## Five-session difficulty rubric

Use complete five-session cells for tutorial-difficulty decisions:

- **Possible pass:** at least 1/5 sessions pass.
- **Likely pass:** at least 3/5 sessions pass.
- **Consistent pass:** at least 4/5 sessions pass.

Preselect one representative for each target parameter class before reading its tutorial
results. Prefer a strong, commonly used model and record a reproducible public metric such as
Hugging Face downloads or likes, the source model id, and the retrieval date. The
Apple and Bell representatives carry the consistent-pass target, with 5/5 desirable but not
required. Many or most models should reach likely pass on those two tutorials. Clover is the
filter point: its spread across possible, likely, and consistent pass is the result, and it
does not impose a blanket 4/5 gate on every strong model. Other models describe the
difficulty distribution rather than being required to succeed.

For the server-`5b33e2a69301` research round, the representatives use the Hugging Face
`downloads` field retrieved 2026-07-24:

- 3--4B: [`Qwen/Qwen3.5-4B`](https://huggingface.co/Qwen/Qwen3.5-4B), 6,665,403 downloads.
- 7--9B: [`Qwen/Qwen3.5-9B`](https://huggingface.co/Qwen/Qwen3.5-9B), 10,929,128 downloads.
- 20--35B: [`Qwen/Qwen3.6-35B-A3B`](https://huggingface.co/Qwen/Qwen3.6-35B-A3B),
  6,460,680 downloads. The tested
  [`unsloth/Qwen3.6-35B-A3B-GGUF`](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF)
  distribution had another 793,190 downloads.

Download counters change over time; the dated values explain selection and are not permanent
rankings.

## Candidate model backlog

Do not start scored sessions from a catalogue badge alone. Before adding any model below,
require both:

1. Ollama reports `tools` in the model capabilities.
2. A minimal `/api/chat` request with tools returns a non-empty
   `message.tool_calls`.

If either check fails, record the attempt as a serving-compatibility diagnostic and exclude
it from gameplay rankings. This gate prevents plain-text action names from being mistaken
for structured tool calls.

Primary local queue, in suggested order:

- [ ] [`hermes3:8b-llama3.1-q8_0`](https://ollama.com/library/hermes3) — 8B
  Llama 3.1 roleplaying/function-calling control.
- [ ] [`NousResearch/Hermes-4-14B`](https://huggingface.co/NousResearch/Hermes-4-14B)
  at Q8 — 14B roleplaying, function-calling, and structured-JSON model; queued
  2026-07-28.
- [x] [`subsectmusic/qwriko3-4b-instruct-2507`](https://huggingface.co/subsectmusic/qwriko3-4b-instruct-2507)
  at Q8 — excluded by the 2026-07-28 compatibility gate. Ollama advertised `tools`,
  but both provider-default and thinking-disabled calls returned tool-shaped text
  without a non-empty `message.tool_calls`.
- [ ] [`llmfan46/Qwythos-9B-Claude-Mythos-5-1M-uncensored-heretic-GGUF`](https://huggingface.co/llmfan46/Qwythos-9B-Claude-Mythos-5-1M-uncensored-heretic-GGUF)
  at Q8 — uncensored 9B conversational model with a documented tool harness.
- [ ] [`LESSTHANSUPER/THE_OMEGA_DIRECTIVE-Mistral_Small3.2-24b:Q6_K`](https://ollama.com/LESSTHANSUPER/THE_OMEGA_DIRECTIVE-Mistral_Small3.2-24b)
  — 24B multi-turn roleplaying model.
- [ ] [`LESSTHANSUPER/RP-INK-Qwen2.5-32b:Q5_K_S`](https://ollama.com/LESSTHANSUPER/RP-INK-Qwen2.5-32b)
  — 32B roleplaying and creative-writing model; queued 2026-07-28.
- [ ] [`gemma4:26b`](https://ollama.com/library/gemma4:26b) — official Gemma 4
  function-calling control for comparison with incompatible community Gemma builds.

Secondary local candidates:

- [ ] [`R4C3R/qwen3-8b-heretic:q8_0`](https://ollama.com/R4C3R/qwen3-8b-heretic)
  — 8B uncensored roleplaying model.
- [ ] [`R4C3R/qwen2.5-14b-instruct-heretic:q8_0`](https://ollama.com/R4C3R/qwen2.5-14b-instruct-heretic)
  — 14B uncensored creative-writing control.
- [ ] [`RootMonsteR/Qwen3-14B-Abliterated-GGUF`](https://huggingface.co/RootMonsteR/Qwen3-14B-Abliterated-GGUF)
  at Q5_K_M — 14B abliterated structured-output control.
- [ ] [`limloop/MN-12B-Runeweaver-RP-RU-GGUF`](https://huggingface.co/limloop/MN-12B-Runeweaver-RP-RU-GGUF)
  at Q6_K — bilingual long-form roleplaying model; tool support needs stronger
  preflight evidence.
- [ ] [`jatayulabs/Qwen3-32B-ToolCall-GGUF`](https://huggingface.co/jatayulabs/Qwen3-32B-ToolCall-GGUF)
  at Q4_K_M — tool-specialist 32B control.
- [ ] [`nemotron-mini:4b`](https://ollama.com/library/nemotron-mini) — small
  roleplaying/function-calling control.
- [ ] [`lfm2.5:8b`](https://ollama.com/library/lfm2.5) — local tool-calling
  latency and efficiency control.

Official Qwen family comparison, using local Ollama Q4_K_M packages:

- [ ] [`qwen2:7b-instruct-q4_K_M`](https://ollama.com/library/qwen2:7b-instruct-q4_K_M)
  — 7.62B dense Qwen2 checkpoint.
- [ ] [`qwen2.5:7b-instruct-q4_K_M`](https://ollama.com/library/qwen2.5:7b-instruct-q4_K_M)
  — 7.62B dense Qwen2.5 checkpoint.
- [ ] [`qwen3:8b-q4_K_M`](https://ollama.com/library/qwen3:8b-q4_K_M)
  — 8.19B dense Qwen3 checkpoint.
- [x] [`qwen3.5:9b`](https://ollama.com/library/qwen3.5:9b) — existing 9.65B
  dense Qwen3.5 matrix.

Keep that dense 7--10B lineage separate from the small-active-parameter MoE lineage:

- [ ] [`qwen3:30b-a3b-instruct-2507-q4_K_M`](https://ollama.com/library/qwen3:30b-a3b-instruct-2507-q4_K_M)
  — 30.5B total / 3.3B active.
- [ ] [`qwen3.5:35b-a3b-q4_K_M`](https://ollama.com/library/qwen3.5:35b-a3b-q4_K_M)
  — 35B total / 3B active.
- [x] [`qwen3.6:35b-a3b`](https://ollama.com/library/qwen3.6:35b-a3b) —
  existing 35B total / 3B active matrix.

Qwen 1.5 has no structured-tools surface in the official Ollama package. Record it as
not applicable rather than scoring it as a gameplay failure. Apply the same two-stage
compatibility gate to every unchecked Qwen entry before running scored sessions.

Cloud comparison candidates:

- [x] [`qwen/qwen3.7-plus`](https://openrouter.ai/qwen/qwen3.7-plus) — inexpensive
  hosted Qwen 3.7 agent model; full OpenRouter matrix started 2026-07-28.
- [x] [`qwen/qwen3.7-flash`](https://openrouter.ai/qwen/qwen3.7-flash) — low-cost,
  low-latency Qwen 3.7 control; full OpenRouter matrix started 2026-07-28.
- [ ] [`minimax-m2.7:cloud`](https://ollama.com/library/minimax-m2.7) — tool-capable
  model emphasizing character consistency, emotional intelligence, and scene interaction.
- [ ] [`mistral-large-3:675b-cloud`](https://ollama.com/library/mistral-large-3) —
  large function-calling and system-adherence control.

Alibaba exposes Qwen 3.8 Max Preview through Model Studio, but no Qwen 3.8 fast or
flash endpoint is currently available in the live OpenRouter catalogue. Do not substitute
the preview into the low-cost comparison unless a fast endpoint becomes available.

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
deadline, bounds each Ollama provider request so a stuck HTTP call cannot bypass that
deadline, and is recorded in the manifest. `--turn-limit` remains an independent
action-loop safety limit.

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

Use `--provider-session-retries N` for long research cohorts where an exhausted transient
provider request must not become model behavior. The default is zero. When enabled, the
harness discards the affected session attempt, creates a fresh agent and world from the same
seed, and retries up to `N` times. The final scored artifacts contain only the successful
attempt; the benchmark log retains explicit warnings for discarded infrastructure attempts.

Use `--seed-helpful-memory` to add three authored, tutorial-specific notes to the controlled
character's private memory before the first decision. The default is off. Seeded and
unseeded runs are different experimental conditions, and the manifest and report record
which condition was used.

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
item between rooms. Bell's board names the required orientation circuit separately from
optional errands, and Tansy's authored response reports the required stops Bram has not yet
visited. Clover asks Ada to read the bulletin, inspect major facilities, and observe city
activity.

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

The benchmark captures the initial full-room prompt projection once with the gameplay
room-fact renderer. That projection, later movement arrival summaries, and optional explicit
`look` results all count as room perception. Resident perception also accepts inspecting or
speaking with the resident. Apple food access accepts a room drop, an open same-room
container, a gift to Pip, or Pip's eventual consumption; carrying the apple nearby does not
count. Clover activity requires witnessing Rook move through Street Stop or hearing one of
his co-located route reports, so repeated no-op waits are unnecessary.

Artifact schema 6 records the old-to-new milestone identifier mapping in every manifest.
Schema-5 baseline artifacts remain immutable and keep their original identifiers and
completion counts.

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
  `receipt_reason`; it is never counted as a wait. Completely empty Ollama and OpenRouter
  responses receive up to three retries after the original response. Retries do not advance
  the world or enter conversation history; if all four attempts are empty, the final empty
  response is recorded and rejected through the same policy path.
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
silently producing an unfair ranking. Schema versions must also match; fair-ranking
comparisons never mix schema-5 and schema-6 sessions. Its report links each source directory, where full
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

For an explicit before/after analysis across schema versions, use repeatable cohort inputs.
Multiple paths may share a label and are aggregated under that cohort:

```bash
scripts/build-tutorial-report \
  --cohort baseline=artifacts/benchmarks/tutorials/schema-5-baseline \
  --cohort post-fix=artifacts/benchmarks/tutorials/schema-6-part-one \
  --cohort post-fix=artifacts/benchmarks/tutorials/schema-6-part-two \
  --output artifacts/benchmarks/tutorials/before-after \
  --title "Bunnyland tutorial playability: baseline and post-fix"
```

Cohort mode groups comparison and token rows by cohort and model. Its heatmaps label and sort
rows by model then cohort so the same model's commit history stays adjacent. They keep old
and replacement milestone columns separate, show unavailable cohort cells as em dashes, fade
the replaced column, outline the replacement, and print the exact identifier mapping.

The generated directory contains:

- `report.md`, the source-linked narrative and embedded SVG diagrams.
- `comparison-table.md`, the compact model, passes, milestones, validity, and
  milestones-per-turn table suitable for a README or server document.
- `token-stats.md`, the provider-reported input/output totals, response-row coverage,
  median seconds per turn, and completed milestones per million total tokens for every
  model.
- `report.typ`, the deterministic print layout.
- `diagrams/tutorial-success-trend-chart.svg`, authoritative session success by cohort and
  tutorial.
- `diagrams/threshold-attainment-chart.svg`, the share of complete model/tutorial cells
  reaching possible, likely, and consistent pass.
- `diagrams/*-parameter-milestone-scatter-chart.svg`, one plot per tutorial comparing total
  upstream architecture parameters on a logarithmic scale with milestone completion in the
  latest supplied cohort containing that tutorial.
- `diagrams/*-tabletop.png`, illustrated top-down world maps in Bunnyland's visual style.
- `diagrams/*-map.svg`, exact tutorial topology with milestone locations and persistent clue
  notes.
- `diagrams/*-milestones.svg`, heatmaps whose first row counts models that reached each
  milestone at least once and whose remaining rows show session reliability by model.
- The difficulty-distribution table counts complete cells reaching possible pass (1/5),
  likely pass (3/5), and consistent pass (4/5) for each cohort and tutorial.
- The tutorial-acceptance table treats Apple and Bell as broad-playability checks and Clover
  as the model-discrimination filter. These calibration goals do not alter milestone scoring.

Install [Typst](https://typst.app/open-source/) and render the PDF with:

```bash
scripts/build-tutorial-report-pdf \
  artifacts/benchmarks/tutorials/full-report/report.typ \
  artifacts/benchmarks/tutorials/full-report/report.pdf
```

Package the rendered report for external sharing:

```bash
scripts/package-tutorial-report \
  artifacts/benchmarks/tutorials/full-report \
  artifacts/benchmarks/tutorials/bunnyland-tutorial-report.zip
```

The ZIP uses a report-only allowlist: Markdown, PDF, copy-ready tables, findings when
present, and diagrams. It deliberately excludes raw prompts, provider responses, thinking,
traces, manifests, logs, and the Typst source. Generated reports identify evidence sources
by artifact directory name instead of recording local absolute paths.

This is a character-tool reasoning benchmark. It does not test whether a human can discover
controls, read browser layout, interpret rendering, claim a character, or keep state aligned
across clients. Use the [player playtesting guide](../player/playtesting.md) for browser,
Discord, multi-client, and human-usability acceptance.

When benchmark results show a shared milestone bottleneck, review the
[diegetic guidance and recoverable world design](diegetic-world-guidance.md) standard before
assuming the intended model-size difficulty ramp is working. Tutorial difficulty should come
from increasingly rich planning, not one-time pop-ups, hidden command rituals, repeated
no-op waits, or clues that cannot be consulted again.
