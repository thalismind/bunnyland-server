"""Build tutorial benchmark reports, maps, and milestone heatmaps."""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import zipfile
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path

from pydantic import TypeAdapter

from benchmarks.tutorial_comparison import LoadedSource, SourceSelection, load_source
from benchmarks.tutorials import JsonValue, ModelResponseTrace, SessionResult


@dataclass(frozen=True)
class MapNode:
    key: str
    label: str
    x: int
    y: int
    milestones: tuple[str, ...] = ()
    clues: tuple[str, ...] = ()


@dataclass(frozen=True)
class MapEdge:
    start: str
    end: str
    label: str


@dataclass(frozen=True)
class TutorialMap:
    title: str
    nodes: tuple[MapNode, ...]
    edges: tuple[MapEdge, ...]
    width: int = 800
    height: int = 650


@dataclass(frozen=True)
class ModelRow:
    model: str
    sessions: int
    passes: int
    milestone_hits: int
    milestone_possible: int
    valid_actions: int
    rejected_actions: int
    turns: int
    median_seconds_per_turn: float
    input_tokens: int
    output_tokens: int
    token_response_rows: int
    response_rows: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def token_efficiency(self) -> float:
        if not self.total_tokens:
            return 0
        return self.milestone_hits * 1_000_000 / self.total_tokens

    @property
    def token_coverage(self) -> float:
        if not self.response_rows:
            return 0
        return self.token_response_rows / self.response_rows


@dataclass(frozen=True)
class ResponseUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    token_response_rows: int = 0
    response_rows: int = 0


@dataclass(frozen=True)
class EvidenceSlice:
    path: Path
    results: tuple[SessionResult, ...]


TUTORIAL_MAPS: dict[str, TutorialMap] = {
    "apple": TutorialMap(
        "Apple Crossing / Hungry Courier",
        (
            MapNode(
                "crossing",
                "Apple Crossing",
                360,
                190,
                ("introduction", "look", "courier scene", "apple handoff"),
                ("notice board", "Pippa and Pip", "post table"),
            ),
            MapNode(
                "hedge",
                "Apple Hedge",
                650,
                190,
                ("visit", "take apple"),
                ("visible red apple",),
            ),
            MapNode("post", "Pippa's Post Hut", 360, 55),
            MapNode("bridge", "Old Footbridge", 360, 330, ("Pip visits",)),
            MapNode("lane", "Mira's Cottage Lane", 650, 330, ("Pip visits",), ("mailbox",)),
            MapNode(
                "cottage",
                "Mira's Cottage",
                650,
                455,
                ("Pip arrives", "ledger mark"),
                ("delivery ledger",),
            ),
        ),
        (
            MapEdge("crossing", "hedge", "east / west"),
            MapEdge("crossing", "post", "north / south"),
            MapEdge("crossing", "bridge", "south / north"),
            MapEdge("bridge", "lane", "west / east"),
            MapEdge("lane", "cottage", "in / out"),
        ),
    ),
    "bell": TutorialMap(
        "Bell Green orientation",
        (
            MapNode(
                "green",
                "Bell Green",
                500,
                230,
                ("look", "notice", "mail", "resident"),
                ("persistent route board", "Tansy"),
            ),
            MapNode(
                "post",
                "Bell Green Post Office",
                500,
                60,
                ("visit", "inspect mail"),
                ("Pippa", "sorted letters"),
            ),
            MapNode(
                "garden",
                "Garden Walk",
                820,
                230,
                ("visit", "carry item"),
                ("Saffron", "harvest basket"),
            ),
            MapNode("shed", "Saffron's Garden Shed", 1050, 230),
            MapNode("inn", "Hearthwick Inn", 500, 430, ("visit",), ("residents",)),
            MapNode("market", "Market Lane", 200, 230),
            MapNode("store", "Nettle's General Store", 120, 60),
            MapNode("workshop", "Jun's Workshop", 200, 430, clues=("Jun",)),
            MapNode("pet", "Pet Yard", 710, 430, clues=("Button",)),
            MapNode(
                "bridge",
                "River Footbridge",
                850,
                510,
                clues=("Shrine route junction",),
            ),
            MapNode(
                "shrine",
                "Old Bell Shrine",
                1060,
                510,
                ("visit",),
                ("most common missed destination",),
            ),
            MapNode("courier", "Courier Path", 850, 700),
        ),
        (
            MapEdge("green", "post", "north / south"),
            MapEdge("green", "garden", "east / west"),
            MapEdge("garden", "shed", "in / out"),
            MapEdge("green", "inn", "south / north"),
            MapEdge("green", "market", "west / east"),
            MapEdge("market", "store", "in / out"),
            MapEdge("market", "workshop", "south / north"),
            MapEdge("inn", "pet", "east / west"),
            MapEdge("garden", "bridge", "south / north"),
            MapEdge("bridge", "shrine", "east / west"),
            MapEdge("bridge", "courier", "south / north"),
        ),
        1180,
        800,
    ),
    "clover": TutorialMap(
        "Clover City orientation",
        (
            MapNode(
                "lobby",
                "Clover City Lobby",
                700,
                420,
                ("look", "bulletin"),
                ("directory", "Cleo concierge"),
            ),
            MapNode(
                "mail",
                "Mailroom",
                1040,
                420,
                ("visit", "city record"),
                ("Pip", "parcel locker"),
            ),
            MapNode("elevator", "Elevator", 700, 160, ("visit",), ("button panel",)),
            MapNode("stairs", "Stairwell", 360, 420, clues=("roof/workshop junction",)),
            MapNode("roof", "Rooftop Garden", 130, 320, ("visit",), ("Saffron", "rain barrel")),
            MapNode("workshop", "Basement Workshop", 130, 580, clues=("Jun",)),
            MapNode("court", "Courtyard", 700, 650, clues=("kitchen/laundry junction",)),
            MapNode("laundry", "Laundry Room", 390, 650, ("visit",), ("Tavi",)),
            MapNode("kitchen", "Community Kitchen", 1010, 650, ("visit",), ("Wick",)),
            MapNode(
                "security",
                "Security Office",
                1110,
                540,
                ("visit", "city record"),
                ("Orla", "incident log"),
            ),
            MapNode("clinic", "Clinic Room", 1050, 300, clues=("Kestrel",)),
            MapNode("music", "Music Room", 350, 300, clues=("Lark",)),
            MapNode(
                "street",
                "Street Stop",
                700,
                870,
                ("visit", "world activity"),
                ("replace repeated waits with recurring evidence",),
            ),
            MapNode("store", "Corner Store", 1010, 870, clues=("Nettle",)),
            MapNode("apt2a", "Apartment 2A: Mira", 260, 60),
            MapNode("apt2b", "Apartment 2B: Jun", 480, 60),
            MapNode("apt3a", "Apartment 3A: Lark", 920, 60),
            MapNode("apt3b", "Apartment 3B: Saffron", 1140, 60),
            MapNode("apt4a", "Apartment 4A: Nettle", 340, 180),
            MapNode("apt4b", "Apartment 4B: Empty", 1060, 180),
        ),
        (
            MapEdge("lobby", "mail", "east / west"),
            MapEdge("lobby", "elevator", "north / south"),
            MapEdge("lobby", "stairs", "west / east"),
            MapEdge("stairs", "roof", "up / down"),
            MapEdge("stairs", "workshop", "down / up"),
            MapEdge("lobby", "court", "south / north"),
            MapEdge("court", "laundry", "west / east"),
            MapEdge("court", "kitchen", "east / west"),
            MapEdge("lobby", "clinic", "northeast / southwest"),
            MapEdge("lobby", "music", "northwest / southeast"),
            MapEdge("lobby", "security", "southeast / northwest"),
            MapEdge("lobby", "street", "out / in"),
            MapEdge("street", "store", "east / west"),
            MapEdge("elevator", "apt2a", "2A / hall"),
            MapEdge("elevator", "apt2b", "2B / hall"),
            MapEdge("elevator", "apt3a", "3A / hall"),
            MapEdge("elevator", "apt3b", "3B / hall"),
            MapEdge("elevator", "apt4a", "4A / hall"),
            MapEdge("elevator", "apt4b", "4B / hall"),
        ),
        1400,
        980,
    ),
}

TABLETOP_MAPS: dict[str, Path] = {
    "apple": Path(__file__).parent.parent
    / "docs"
    / "assets"
    / "tutorial-benchmark"
    / "apple-crossing-tabletop.png",
    "bell": Path(__file__).parent.parent
    / "docs"
    / "assets"
    / "tutorial-benchmark"
    / "bell-green-tabletop.png",
    "clover": Path(__file__).parent.parent
    / "docs"
    / "assets"
    / "tutorial-benchmark"
    / "clover-city-tabletop.png",
}


def _json_int(value: JsonValue | None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _response_usage(response: dict[str, JsonValue]) -> ResponseUsage | None:
    prompt_tokens = _json_int(response.get("prompt_eval_count"))
    output_tokens = _json_int(response.get("eval_count"))
    if prompt_tokens is not None and output_tokens is not None:
        return ResponseUsage(prompt_tokens, output_tokens)
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt_tokens = _json_int(usage.get("prompt_tokens"))
    output_tokens = _json_int(usage.get("completion_tokens"))
    if prompt_tokens is None or output_tokens is None:
        return None
    return ResponseUsage(prompt_tokens, output_tokens)


def _source_path(parent: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else parent / path


def _evidence_slices(source: LoadedSource) -> tuple[EvidenceSlice, ...]:
    if source.manifest.benchmark != "ollama-tutorial-ladder-comparison":
        return (EvidenceSlice(source.path, source.results),)
    remaining = Counter(source.results)
    slices: list[EvidenceSlice] = []
    for entry in source.manifest.sources:
        child = load_source(
            SourceSelection(
                _source_path(source.path, entry.path),
                entry.selected_models,
            )
        )
        selected: list[SessionResult] = []
        for result in child.results:
            if remaining[result] <= 0:
                continue
            remaining[result] -= 1
            selected.append(result)
        if selected:
            for evidence in _evidence_slices(child):
                evidence_results = tuple(
                    result for result in evidence.results if result in selected
                )
                if evidence_results:
                    slices.append(EvidenceSlice(evidence.path, evidence_results))
    return tuple(slices)


def _read_responses(path: Path) -> tuple[ModelResponseTrace, ...]:
    response_path = path / "responses.jsonl"
    if not response_path.exists():
        return ()
    rows = []
    adapter = TypeAdapter(ModelResponseTrace)
    for line in response_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(adapter.validate_json(line))
    return tuple(rows)


def _model_usage(sources: Sequence[LoadedSource]) -> dict[str, ModelUsage]:
    usage: dict[str, ModelUsage] = defaultdict(ModelUsage)
    for source in sources:
        for evidence in _evidence_slices(source):
            model_by_session = {
                result.session_id: result.model for result in evidence.results
            }
            for row in _read_responses(evidence.path):
                model = model_by_session.get(row.session_id)
                if model is None:
                    continue
                previous = usage[model]
                tokens = _response_usage(row.response)
                usage[model] = ModelUsage(
                    input_tokens=previous.input_tokens
                    + (tokens.input_tokens if tokens is not None else 0),
                    output_tokens=previous.output_tokens
                    + (tokens.output_tokens if tokens is not None else 0),
                    token_response_rows=previous.token_response_rows
                    + (tokens is not None),
                    response_rows=previous.response_rows + 1,
                )
    return usage


def _model_rows(
    results: Sequence[SessionResult], usage: dict[str, ModelUsage]
) -> tuple[ModelRow, ...]:
    grouped: dict[str, list[SessionResult]] = defaultdict(list)
    for result in results:
        grouped[result.model].append(result)
    rows = []
    for model, sessions in grouped.items():
        model_usage = usage.get(model, ModelUsage())
        rows.append(
            ModelRow(
                model=model,
                sessions=len(sessions),
                passes=sum(result.passed for result in sessions),
                milestone_hits=sum(
                    sum(complete for _name, complete in result.milestone_results)
                    for result in sessions
                ),
                milestone_possible=sum(len(result.milestone_results) for result in sessions),
                valid_actions=sum(result.valid_actions for result in sessions),
                rejected_actions=sum(result.rejected_actions for result in sessions),
                turns=sum(result.turns for result in sessions),
                median_seconds_per_turn=statistics.median(
                    result.elapsed_seconds / result.turns
                    for result in sessions
                    if result.turns
                ),
                input_tokens=model_usage.input_tokens,
                output_tokens=model_usage.output_tokens,
                token_response_rows=model_usage.token_response_rows,
                response_rows=model_usage.response_rows,
            )
        )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                -row.passes,
                -(row.milestone_hits / row.milestone_possible if row.milestone_possible else 0),
                row.model,
            ),
        )
    )


def _svg_start(width: int, height: int, title: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
        "<style>",
        ".title{font-family:sans-serif;font-size:22px;font-weight:700;fill:#17202a}"
        ".node{fill:#fff;stroke:#425466;"
        "stroke-width:2}.milestone{fill:#fff3bf;stroke:#d97706;stroke-width:3}"
        ".label{font-family:sans-serif;font-size:13px;font-weight:700;fill:#17202a}"
        ".small{font-family:sans-serif;font-size:11px;fill:#425466}"
        ".edge{stroke:#718096;stroke-width:2}"
        ".edge-label{font-family:sans-serif;font-size:10px;fill:#59636e}"
        ".grid{stroke:#d7dde5;stroke-width:1}</style>",
        f'<rect width="{width}" height="{height}" fill="#f7f9fc"/>',
        f'<text class="title" x="24" y="22">{escape(title)}</text>',
    ]


def render_map_svg(spec: TutorialMap) -> str:
    width, height = spec.width, spec.height
    lines = _svg_start(width, height, spec.title)
    by_key = {node.key: node for node in spec.nodes}
    for edge in spec.edges:
        start, end = by_key[edge.start], by_key[edge.end]
        lines.append(
            f'<line class="edge" x1="{start.x}" y1="{start.y}" x2="{end.x}" y2="{end.y}"/>'
        )
        lines.append(
            f'<text class="edge-label" x="{(start.x + end.x) // 2 + 5}" '
            f'y="{(start.y + end.y) // 2 - 5}">{escape(edge.label)}</text>'
        )
    for node in spec.nodes:
        css = "milestone" if node.milestones else "node"
        lines.append(
            f'<rect class="{css}" x="{node.x - 92}" y="{node.y - 34}" '
            'width="184" height="68" rx="9"/>'
        )
        lines.append(
            f'<text class="label" text-anchor="middle" x="{node.x}" y="{node.y - 8}">'
            f"{escape(node.label)}</text>"
        )
        for offset, details in ((11, node.milestones), (25, node.clues)):
            detail = " · ".join(details)
            if not detail:
                continue
            fitting = ""
            if len(detail) > 38:
                fitting = ' style="font-size:7px"'
            elif len(detail) > 28:
                fitting = ' style="font-size:8.5px"'
            lines.append(
                f'<text class="small" text-anchor="middle" x="{node.x}" '
                f'y="{node.y + offset}"{fitting}>{escape(detail)}</text>'
            )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _milestone_matrix(
    results: Sequence[SessionResult], tutorial: str
) -> tuple[tuple[str, ...], dict[str, dict[str, tuple[int, int]]]]:
    selected = [result for result in results if result.tutorial == tutorial]
    milestones = tuple(
        dict.fromkeys(name for result in selected for name, _complete in result.milestone_results)
    )
    models: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for result in selected:
        for name, complete in result.milestone_results:
            models[result.model][name].append(complete)
    matrix = {
        model: {
            milestone: (
                sum(values.get(milestone, [])),
                len(values.get(milestone, [])),
            )
            for milestone in milestones
        }
        for model, values in models.items()
    }
    return milestones, matrix


def _heat_color(rate: float) -> str:
    if rate >= 0.8:
        return "#2f9e44"
    if rate >= 0.4:
        return "#f59f00"
    if rate > 0:
        return "#e8590c"
    return "#c92a2a"


def render_heatmap_svg(results: Sequence[SessionResult], tutorial: str) -> str:
    milestones, matrix = _milestone_matrix(results, tutorial)
    models = tuple(sorted(matrix))
    cell_width, cell_height, label_width = 82, 34, 230
    width = max(720, label_width + cell_width * len(milestones) + 24)
    height = 118 + cell_height * (len(models) + 1)
    lines = _svg_start(width, height, f"{tutorial.title()} milestone completion")
    model_reach = {
        milestone: sum(matrix[model][milestone][0] > 0 for model in models)
        for milestone in milestones
    }
    for column, milestone in enumerate(milestones):
        x = label_width + column * cell_width
        short = milestone.replace("visited_", "").replace("inspected_", "").replace("_", " ")
        lines.append(
            f'<text class="small" transform="translate({x + 14},104) rotate(-48)">'
            f"{escape(short[:24])}</text>"
        )
    all_rows = (("Models reaching milestone", None), *((model, model) for model in models))
    for row, (label, model) in enumerate(all_rows):
        y = 112 + row * cell_height
        lines.append(f'<text class="label" x="12" y="{y + 23}">{escape(label)}</text>')
        for column, milestone in enumerate(milestones):
            x = label_width + column * cell_width
            if model is None:
                hit, total = model_reach[milestone], len(models)
            else:
                hit, total = matrix[model][milestone]
            rate = hit / total if total else 0
            lines.append(
                f'<rect x="{x}" y="{y}" width="{cell_width - 2}" height="{cell_height - 2}" '
                f'fill="{_heat_color(rate)}"/>'
            )
            lines.append(
                f'<text x="{x + cell_width // 2}" y="{y + 22}" text-anchor="middle" '
                'style="font-family:sans-serif;font-size:12px;font-weight:700;fill:white">'
                f"{hit}/{total}</text>"
            )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _comparison_table(rows: Sequence[ModelRow]) -> str:
    lines = [
        "| Model | Passes | Milestones | Validity | Milestones/turn |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        attempted = row.valid_actions + row.rejected_actions
        validity = row.valid_actions / attempted if attempted else 1
        progress = row.milestone_hits / row.turns if row.turns else 0
        lines.append(
            f"| `{row.model}` | {row.passes}/{row.sessions} | "
            f"{row.milestone_hits}/{row.milestone_possible} | {validity:.1%} | "
            f"{progress:.3f} |"
        )
    return "\n".join(lines)


def _token_table(rows: Sequence[ModelRow]) -> str:
    lines = [
        "| Model | Input tokens | Output tokens | Total tokens | "
        "Usage coverage | Median sec/turn | Milestones/M tokens |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.model}` | {row.input_tokens:,} | {row.output_tokens:,} | "
            f"{row.total_tokens:,} | {row.token_response_rows}/{row.response_rows} "
            f"({row.token_coverage:.1%}) | {row.median_seconds_per_turn:.2f} | "
            f"{row.token_efficiency:,.2f} |"
        )
    return "\n".join(lines)


def _runtime_summary(rows: Sequence[ModelRow]) -> str:
    measured = tuple(row for row in rows if row.total_tokens and row.response_rows)
    if not measured:
        return "Provider token usage was not retained for these sessions."
    fastest = min(measured, key=lambda row: row.median_seconds_per_turn)
    slowest = max(measured, key=lambda row: row.median_seconds_per_turn)
    most_efficient = max(measured, key=lambda row: row.token_efficiency)
    least_efficient = min(measured, key=lambda row: row.token_efficiency)
    input_tokens = sum(row.input_tokens for row in measured)
    output_tokens = sum(row.output_tokens for row in measured)
    covered = sum(row.token_response_rows for row in measured)
    response_rows = sum(row.response_rows for row in measured)
    return "\n".join(
        (
            f"Recorded provider usage totals **{input_tokens + output_tokens:,} tokens**: "
            f"{input_tokens:,} input and {output_tokens:,} output tokens across "
            f"{covered:,}/{response_rows:,} retained response rows.",
            "",
            f"- Fastest median decision pace: `{fastest.model}` at "
            f"{fastest.median_seconds_per_turn:.2f} seconds/turn.",
            f"- Slowest median decision pace: `{slowest.model}` at "
            f"{slowest.median_seconds_per_turn:.2f} seconds/turn.",
            f"- Most token-efficient: `{most_efficient.model}` at "
            f"{most_efficient.token_efficiency:,.2f} completed milestones per million tokens.",
            f"- Least token-efficient: `{least_efficient.model}` at "
            f"{least_efficient.token_efficiency:,.2f} completed milestones per million tokens.",
        )
    )


def _typst_text(value: str) -> str:
    return f"#text({json.dumps(value, ensure_ascii=False)})"


def _typst_report(
    title: str,
    rows: Sequence[ModelRow],
    diagrams: Sequence[str],
    sources: Sequence[str],
) -> str:
    cells = [
        "[*Model*]",
        "[*Passes*]",
        "[*Milestones*]",
        "[*Validity*]",
        "[*Milestones / turn*]",
    ]
    for row in rows:
        attempted = row.valid_actions + row.rejected_actions
        validity = row.valid_actions / attempted if attempted else 1
        progress = row.milestone_hits / row.turns if row.turns else 0
        values = (
            row.model,
            f"{row.passes}/{row.sessions}",
            f"{row.milestone_hits}/{row.milestone_possible}",
            f"{validity:.1%}",
            f"{progress:.3f}",
        )
        cells.extend(f"[{_typst_text(value)}]" for value in values)
    token_cells = [
        "[*Model*]",
        "[*Input*]",
        "[*Output*]",
        "[*Total*]",
        "[*Coverage*]",
        "[*Sec / turn*]",
        "[*Milestones / M tokens*]",
    ]
    for row in rows:
        values = (
            row.model,
            f"{row.input_tokens:,}",
            f"{row.output_tokens:,}",
            f"{row.total_tokens:,}",
            f"{row.token_response_rows}/{row.response_rows}",
            f"{row.median_seconds_per_turn:.2f}",
            f"{row.token_efficiency:,.2f}",
        )
        token_cells.extend(f"[{_typst_text(value)}]" for value in values)
    images = []
    for path in diagrams:
        images.extend(
            (
                "#pagebreak()",
                f"= {_typst_text(Path(path).stem.replace('-', ' ').title())}",
                f'#image({json.dumps(path)}, width: 100%, height: 165mm, fit: "contain")',
            )
        )
    return "\n".join(
        (
            '#set page(paper: "a4", flipped: true, margin: 12mm)',
            "#set text(size: 9pt)",
            "#set heading(numbering: none)",
            f"= {_typst_text(title)}",
            "",
            "Generated from authoritative benchmark artifacts.",
            "",
            "== Evidence sources",
            "",
            *(_typst_text(path) for path in sources),
            "",
            "== Runtime and token use",
            "",
            _typst_text(_runtime_summary(rows)),
            "",
            "Provider-reported logical tokens are shown, not billed tokens. Output includes "
            "thinking where reported. Timing is comparable only within compatible panels.",
            "",
            "#set text(size: 6pt)",
            "#table(",
            "  columns: (2fr, 1fr, 0.8fr, 1fr, 0.8fr, 0.8fr, 1fr),",
            "  inset: 3pt,",
            "  stroke: 0.5pt + rgb(\"ccd3dc\"),",
            "  " + ",\n  ".join(token_cells),
            ")",
            "#set text(size: 9pt)",
            "",
            "== Model comparison",
            "",
            "#table(",
            "  columns: (2.2fr, 1fr, 1fr, 1fr, 1fr),",
            "  inset: 5pt,",
            "  stroke: 0.5pt + rgb(\"ccd3dc\"),",
            "  " + ",\n  ".join(cells),
            ")",
            *images,
            "",
        )
    )


def build_report(inputs: Sequence[Path], output: Path, *, title: str) -> None:
    sources = tuple(load_source(SourceSelection(path.resolve())) for path in inputs)
    results = tuple(result for source in sources for result in source.results)
    if not results:
        raise ValueError("report inputs contain no completed sessions")
    output.mkdir(parents=True, exist_ok=True)
    diagrams = output / "diagrams"
    diagrams.mkdir(exist_ok=True)
    diagram_paths: list[str] = []
    for tutorial, spec in TUTORIAL_MAPS.items():
        tabletop_path = diagrams / f"{tutorial}-tabletop.png"
        map_path = diagrams / f"{tutorial}-map.svg"
        heatmap_path = diagrams / f"{tutorial}-milestones.svg"
        shutil.copyfile(TABLETOP_MAPS[tutorial], tabletop_path)
        map_path.write_text(render_map_svg(spec), encoding="utf-8")
        heatmap_path.write_text(render_heatmap_svg(results, tutorial), encoding="utf-8")
        diagram_paths.extend(
            (
                str(tabletop_path.relative_to(output)),
                str(map_path.relative_to(output)),
                str(heatmap_path.relative_to(output)),
            )
        )
    rows = _model_rows(results, _model_usage(sources))
    template = (Path(__file__).parent / "templates" / "tutorial_report.md").read_text(
        encoding="utf-8"
    )
    markdown = (
        template.replace("{{TITLE}}", title)
        .replace("{{COMPLETED}}", str(len(results)))
        .replace("{{PASSES}}", str(sum(result.passed for result in results)))
        .replace(
            "{{SOURCES}}",
            "\n".join(
                f"- `{source.path.name}` — "
                f"{len(source.results)} completed sessions"
                for source in sources
            ),
        )
        .replace("{{RUNTIME_SUMMARY}}", _runtime_summary(rows))
        .replace("{{TOKEN_TABLE}}", _token_table(rows))
        .replace("{{COMPARISON_TABLE}}", _comparison_table(rows))
        .replace(
            "{{DIAGRAMS}}",
            "\n\n".join(f"![{Path(path).stem}]({path})" for path in diagram_paths),
        )
    )
    (output / "report.md").write_text(markdown, encoding="utf-8")
    (output / "report.typ").write_text(
        _typst_report(title, rows, diagram_paths, tuple(source.path.name for source in sources)),
        encoding="utf-8",
    )
    (output / "comparison-table.md").write_text(_comparison_table(rows) + "\n", encoding="utf-8")
    (output / "token-stats.md").write_text(_token_table(rows) + "\n", encoding="utf-8")


def package_report(report: Path, archive: Path) -> None:
    files = (
        "report.md",
        "report.pdf",
        "comparison-table.md",
        "token-stats.md",
        "findings.md",
    )
    diagrams = tuple(sorted((report / "diagrams").glob("*")))
    selected = tuple(report / name for name in files if (report / name).is_file()) + diagrams
    if not (report / "report.md").is_file() or not (report / "report.pdf").is_file():
        raise ValueError("shareable report needs report.md and report.pdf")
    archive.parent.mkdir(parents=True, exist_ok=True)
    root = report.name
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in selected:
            bundle.write(path, Path(root) / path.relative_to(report))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--title", default="Bunnyland tutorial-ladder benchmark")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    build_report(args.input, args.output, title=args.title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
