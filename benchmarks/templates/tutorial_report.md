# {{TITLE}}

Completed sessions: **{{COMPLETED}}**

Authoritative passes: **{{PASSES}}**

{{COVERAGE_GAPS}}

## Runtime and token use

{{RUNTIME_SUMMARY}}

Output tokens include thinking tokens when the provider reports them. Token efficiency is
completed milestones per million total provider-reported input plus output tokens. Speed is
the median session-level seconds per turn. Timing is comparable only within panels with the
same provider and reasoning settings. These are logical provider-reported tokens, not billed
tokens; cached prompt tokens may still be included.

{{TOKEN_TABLE}}

## Performance leaders

{{PERFORMANCE_LEADERBOARDS}}

## Latency distribution

Decision latency is measured from the benchmark's scored turn traces. Provider and hardware
panels are reported separately because local and cloud timing are not directly interchangeable.

{{LATENCY_SECTION}}

## Model comparison

{{COMPARISON_TABLE}}

{{FRONTIER_COST_SECTION}}

## Tutorial acceptance policy

These are calibration goals, not changes to per-session milestone scoring. “Strong” models
are selected before results are read, using a reproducible public popularity or usage
metric.

{{ACCEPTANCE_POLICY}}

## Difficulty distribution

Possible pass means at least 1/5, likely pass at least 3/5, and consistent pass at least
4/5. Only complete five-session model/tutorial cells are classified.

{{DIFFICULTY_TABLE}}

## Cohort charts

The success chart uses authoritative session pass rate. The threshold chart uses the share
of complete five-session model/tutorial cells reaching possible (1/5), likely (3/5), and
consistent (4/5) pass. Missing tutorial/version combinations are shown as gaps, not zeroes.

{{SUMMARY_CHARTS}}

## Model size and milestone completion

Each scatter plot uses the latest supplied cohort containing that tutorial. The logarithmic
X-axis shows total upstream architecture parameters; the Y-axis shows completed milestone
checks divided by possible milestone checks across the model's sessions. Each numbered point
is one exact model identifier. Circles are local models and diamonds are cloud models.
Overlapping points are offset slightly. MoE models are plotted by total, not active,
parameters. Closed models without a published parameter count are omitted rather than assigned
an inferred size.

{{PARAMETER_SCATTER_PLOTS}}

## Kimi family comparison

This chart compares aggregate capability, decision latency, and logical-token efficiency
across the tested Kimi family. Kimi K2.7 Code is a code-specialized branch rather than a
direct general-purpose successor. K3 used OpenRouter while the K2 models used Ollama Cloud,
so the latency panel includes provider infrastructure differences; capability and token
efficiency are the more portable comparisons.

{{KIMI_FAMILY_CHART}}

## Cohort deltas

Deltas compare consecutive cohorts in the supplied order. Missing model/cohort cells are
shown as an em dash and are not treated as failures. Tutorial totals reflect each cohort's
tested model mix; matching model/tutorial rows provide the like-for-like comparison.

{{COHORT_DELTAS}}

## Additional analytical questions

### How broadly were cohort gains shared?

Counts compare pass-rate changes for exact model/tutorial cells present in both cohorts,
separating improvements, ties, and regressions.

{{CHANGE_BREADTH_TABLE}}

### Where does tutorial progress break?

The table lists the three lowest-completion exact milestone identifiers in each
tutorial/cohort. Historical and replacement identifiers remain separate.

{{MILESTONE_BOTTLENECKS}}

### Are failures mostly invalid actions?

Action validity measures accepted actions among all submitted actions. Rejection recovery
measures rejected actions followed by recovery within the benchmark's existing window.

{{BEHAVIOR_TABLE}}

### How sensitive is Qwen 3.6 35B to quantization?

These are like-for-like pass counts for the tested Q4, Q6, and Q8 identifiers. The table does
not infer monotonic quantization quality from a single five-session cell.

{{QUANTIZATION_TABLE}}

## Tutorial maps and milestone heatmaps

Heatmap cells show completed sessions per model. The first row shows how many tested models
reached each milestone at least once, which identifies shared onboarding bottlenecks.
Five-session cells use the six-class
[ColorBrewer RdYlGn](https://colorbrewer2.org/#type=diverging&scheme=RdYlGn&n=6) scale so
0, 1, 2, 3, 4, and 5 completions each have a distinct color.

{{DIAGRAMS}}

## Interpretation checklist

- Separate provider/tool-format failures from world-navigation and clue failures.
- Treat character notes and completion claims as diagnostic evidence, not authoritative state.
- Flag milestones missed by most models before attributing the result to model size.
- Prefer persistent, repeatable, diegetic clues over pop-ups, hidden commands, or repeated waits.
- Report the smallest parameter band reaching every milestone at least once and reliably.
