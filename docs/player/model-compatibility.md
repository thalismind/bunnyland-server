# Model compatibility

Bunnyland asks models to act through validated character tools. A model only passes when
the world reaches the tutorial's authoritative completion state; describing or claiming
success does not count.

The three tutorials represent increasing levels of play:

- **Apple Crossing:** basic quests and object use.
- **Bell Green:** town navigation, readable fixtures, and NPC interaction.
- **Clover City:** complex navigation, multiple facilities and residents, and recurring
  world activity.

Each result below is a five-session cell. **Consistent** means 4--5/5, **likely** means
3/5, **possible** means 1--2/5, and **not demonstrated** means 0/5. A recommendation
requires at least a likely pass at that level. A 0/5 result means no pass was observed in
five trials, not that success is impossible.

## Compatibility at a glance

The recommended level is the hardest tutorial where the model reached at least 3/5.
The pass rate shown is for that level, so readers do not need to compare all three
tutorial columns.

| Model | Size | Runs on | Best demonstrated level | Pass rate |
| --- | ---: | --- | --- | ---: |
| DeepSeek V4 Pro | 1.6T | Cloud | Complex worlds | 5/5 |
| Gemma 4 | 31B | Cloud | Complex worlds | 5/5 |
| Kimi K2.6 | 1T | Cloud | Complex worlds | 5/5 |
| Kimi K2.7 Code | 1T | Cloud | Complex worlds | 5/5 |
| DeepSeek V4 Flash | 284B | Cloud | Complex worlds | 4/5 |
| GLM-5.2 | 753B | Cloud | Complex worlds | 4/5 |
| Qwen 3.5 | 397B-A17B | Cloud | Complex worlds | 4/5 |
| Qwen 3.6 Genesis Hermes V5 Q8 | 35B-A3B | Local | Complex worlds | 4/5 |
| Qwen 3.6 Q4 | 35B-A3B | Local | Complex worlds | 4/5 |
| MiniMax M2.7 | 230B | Cloud | Complex worlds | 3/5 |
| Qwen 3.6 Q6 | 35B-A3B | Local | Complex worlds | 3/5 |
| Qwen 3.6 Q8 | 35B-A3B | Local | Complex worlds | 3/5 |
| GPT-OSS 120B | 117B | Cloud | Town and NPCs | 5/5 |
| GPT-OSS 20B | 21B | Cloud | Town and NPCs | 5/5 |
| Laguna XS 2.1 | 33B | Local | Town and NPCs | 5/5 |
| MiniMax M3 | 428B | Cloud | Town and NPCs | 5/5 |
| Nemotron 3 Nano | 31.6B-A3B | Cloud | Town and NPCs | 5/5 |
| Nemotron 3 Ultra | 550B-A55B | Cloud | Town and NPCs | 5/5 |
| Qwen 3.5 4B HauhauCS | 4B | Local | Town and NPCs | 5/5 |
| Qwen 3.5 9B | 9B | Local | Town and NPCs | 5/5 |
| Qwen 3.5 9B Defiant Fable | 9B | Local | Town and NPCs | 5/5 |
| Qwen 3.6 Bahushruth v4 Q4 | 35B-A3B | Local | Town and NPCs | 5/5 |
| Mistral Large 3 | 675B | Cloud | Town and NPCs | 4/5 |
| Nemotron 3 Super | 120B-A12B | Cloud | Town and NPCs | 4/5 |
| Qwen 3.5 4B | 4B | Local | Town and NPCs | 4/5 |

## Recommended top five

These recommendations balance demonstrated gameplay, latency, token or cost efficiency,
deployment practicality, and strength of evidence. They are not simply the five highest
pass counts.

| Rank | Model | Deployment | Best for | Evidence and tradeoff |
| ---: | --- | --- | --- | --- |
| 1 | [GPT-5.6 Luna](https://openrouter.ai/openai/gpt-5.6-luna) | OpenRouter | Best hosted value | 14/16 passes and the highest measured token efficiency; two-session cells |
| 2 | [Kimi K2.7 Code](https://ollama.com/library/kimi-k2.7-code%3Acloud) | Ollama Cloud | Proven cloud reliability | Clover 5/5, fastest overall at 1.51 seconds per decision, and strong token efficiency |
| 3 | [Qwen 3.6 35B-A3B Q4](https://ollama.com/library/qwen3.6%3A35b-a3b) | Local Ollama | Practical local hosting | Clover 4/5 and current Bell 5/5 on one 24 GB-class GPU |
| 4 | [DeepSeek V4 Flash](https://ollama.com/library/deepseek-v4-flash%3Acloud) | Ollama Cloud | Fast open-weight cloud play | Clover 4/5 and third-fastest overall at 1.81 seconds per decision |
| 5 | [Qwen 3.6 Genesis Hermes V5 Q8](https://huggingface.co/LuffyTheFox/Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-V5-GGUF) | Local Ollama from Hugging Face | High-end local roleplay | Clover 4/5; needs roughly 41 GB with the benchmark context and is an uncensored derivative |

For a cloud-only list, replace Genesis Hermes with
[DeepSeek V4 Pro](https://ollama.com/library/deepseek-v4-pro%3Acloud), which reached
Clover 5/5 and a 1.99-second median decision latency but uses a much larger architecture.

No rated model stopped at basic gameplay: every model reached at least a likely pass on
Bell Green.

For local town and NPC play, Qwen 3.5 4B is the smallest recommendation, while Qwen 3.5
9B provides more headroom. For local complex worlds, Qwen 3.6 Genesis Hermes V5 Q8 had
the strongest tested completion rate. It needs roughly 41 GB of GPU memory with the
benchmark's 262K context; the Q4 base model is the more practical 24 GB-class option.

For cloud complex-world play, DeepSeek V4 Flash is the efficiency-oriented
recommendation. Kimi K2.6, Kimi K2.7 Code, and DeepSeek V4 Pro were the most consistent,
but are much larger models.

## Frontier API preview

Four newly released hosted models received a breadth-first, two-session evaluation across
the applicable `v1`--`v4` tutorials. These cells do not meet the five-session threshold
used by the compatibility table above.

| Model | Observed level | Overall passes | Milestones | Estimated API cost | Player guidance |
| --- | --- | ---: | ---: | ---: | --- |
| GPT-5.6 Luna | Complex worlds | 14/16 | 166/172 | $2.50 | Recommended hosted frontier option |
| GPT-5.6 Sol | Complex worlds | 14/16 | 166/172 | $15.11 | Capable, but costlier than Luna |
| Claude Haiku 4.5 | Complex worlds | 10/16 | 160/172 | $7.60 | Promising; needs a full cell |
| Claude Opus 5 | Town and NPCs | 12/16 | 155/172 | $46.19 | Avoid for routine gameplay |

For hosted play, **GPT-5.6 Luna is the recommendation**. It passed more sessions and
completed more milestones than Claude Opus 5 while costing dramatically less. Across all
retained frontier runs it delivered about 22 times as many authoritative passes per dollar;
the `v2` and `v4` comparison was about 28 times. In practical terms, Luna appears **about
25 times better per dollar** for Bunnyland. We recommend avoiding Opus for routine gameplay
because its cost/performance ratio is poor here, even though it may remain useful for
different long-horizon workloads.

Costs cover all 16 retained sessions for each model and are reconstructed from OpenRouter
usage records and list prices, including observed prompt caching. They are estimates, not
per-session prices or invoice totals.

## Local Ollama model IDs

Admins can use these exact tested identifiers:

| Model | Ollama model ID |
| --- | --- |
| Qwen 3.5 4B | `qwen3.5:4b` |
| Qwen 3.5 4B HauhauCS | `hf.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive:Q4_K_M` |
| Qwen 3.5 9B | `qwen3.5:9b` |
| Qwen 3.5 9B Defiant Fable | `hf.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF:Q4_K_M` |
| Laguna XS 2.1 | `laguna-xs-2.1:latest` |
| Qwen 3.6 Q4 | `qwen3.6:35b-a3b` |
| Qwen 3.6 Q6 | `hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K` |
| Qwen 3.6 Q8 | `hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:Q8_0` |
| Qwen 3.6 Bahushruth v4 Q4 | `hf.co/Bahushruth/Qwen3.6-35B-A3B-abliterated-v4-GGUF:Q4_K_M` |
| Qwen 3.6 Genesis Hermes V5 Q8 | `hf.co/LuffyTheFox/Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-V5-GGUF:Q8_0` |

The local Gemma 4 31B HauhauCS Q4 variant is not rated. It does not expose the benchmark's
high-thinking option, and a provider-default diagnostic was stopped after 14 Apple turns:
it still carried the apple, had completed 6/13 milestones, and was taking 35--90 seconds
per decision. The separate `gemma4:cloud` result above completed its full rated cells.

Uncensored and abliterated derivatives remove or weaken model safeguards. Their gameplay
results are not a recommendation to expose them directly to untrusted public prompts;
server operators remain responsible for appropriate policy controls.

## Test conditions and detailed results

The established models use the latest applicable complete cells: Apple and Clover from
`v2` (`3a662413`) and Bell from `v4` (`0abb32b`). The four rated derivatives ran against
`c3f2729`, whose gameplay code retains the same latest tutorial semantics. Runs used five
fresh worlds per model/tutorial pair, provider-default temperature, and high thinking where
the model supported it.

See the [tutorial benchmark methodology](../developer/tutorial-benchmark.md) for scoring,
artifacts, latency, milestone completion, and turn-efficiency analysis.
