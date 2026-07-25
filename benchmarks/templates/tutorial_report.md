# {{TITLE}}

Completed sessions: **{{COMPLETED}}**

Authoritative passes: **{{PASSES}}**

## Evidence sources

{{SOURCES}}

## Runtime and token use

{{RUNTIME_SUMMARY}}

Output tokens include thinking tokens when the provider reports them. Token efficiency is
completed milestones per million total provider-reported input plus output tokens. Speed is
the median session-level seconds per turn. Timing is comparable only within panels with the
same provider and reasoning settings. These are logical provider-reported tokens, not billed
tokens; cached prompt tokens may still be included.

{{TOKEN_TABLE}}

## Model comparison

{{COMPARISON_TABLE}}

## Difficulty distribution

Possible pass means at least 1/5, likely pass at least 3/5, and consistent pass at least
4/5. Only complete five-session model/tutorial cells are classified.

{{DIFFICULTY_TABLE}}

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
