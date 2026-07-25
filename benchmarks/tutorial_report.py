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
    cohort: str | None
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
class DifficultyRow:
    cohort: str | None
    tutorial: str
    complete_cells: int
    possible_passes: int
    likely_passes: int
    consistent_passes: int


@dataclass(frozen=True)
class CohortDeltaRow:
    before_cohort: str
    after_cohort: str
    tutorial: str
    model: str | None
    before_passes: int | None
    before_sessions: int | None
    after_passes: int | None
    after_sessions: int | None

    @property
    def delta_percentage_points(self) -> float | None:
        if (
            self.before_passes is None
            or self.before_sessions is None
            or not self.before_sessions
            or self.after_passes is None
            or self.after_sessions is None
            or not self.after_sessions
        ):
            return None
        before_rate = self.before_passes / self.before_sessions
        after_rate = self.after_passes / self.after_sessions
        return 100 * (after_rate - before_rate)


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


@dataclass(frozen=True)
class CohortInput:
    label: str
    path: Path


@dataclass(frozen=True)
class LabeledResult:
    cohort: str | None
    result: SessionResult


TUTORIAL_MAPS: dict[str, TutorialMap] = {
    "apple": TutorialMap(
        "Apple Crossing / Hungry Courier",
        (
            MapNode(
                "crossing",
                "Apple Crossing",
                360,
                190,
                ("introduction", "orientation", "courier scene", "food access"),
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
                ("orientation", "notice", "mail", "resident"),
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
                ("orientation", "bulletin"),
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


def _model_usage(
    sources: Sequence[tuple[str | None, LoadedSource]],
) -> dict[tuple[str | None, str], ModelUsage]:
    usage: dict[tuple[str | None, str], ModelUsage] = defaultdict(ModelUsage)
    for cohort, source in sources:
        for evidence in _evidence_slices(source):
            model_by_session = {
                result.session_id: result.model for result in evidence.results
            }
            for row in _read_responses(evidence.path):
                model = model_by_session.get(row.session_id)
                if model is None:
                    continue
                key = (cohort, model)
                previous = usage[key]
                tokens = _response_usage(row.response)
                usage[key] = ModelUsage(
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
    results: Sequence[LabeledResult],
    usage: dict[tuple[str | None, str], ModelUsage],
) -> tuple[ModelRow, ...]:
    grouped: dict[tuple[str | None, str], list[SessionResult]] = defaultdict(list)
    for labeled in results:
        grouped[(labeled.cohort, labeled.result.model)].append(labeled.result)
    rows = []
    for (cohort, model), sessions in grouped.items():
        model_usage = usage.get((cohort, model), ModelUsage())
        rows.append(
            ModelRow(
                cohort=cohort,
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
    cohort_rank = {
        cohort: index
        for index, cohort in enumerate(
            dict.fromkeys(labeled.cohort for labeled in results)
        )
    }

    def sort_key(row: ModelRow) -> tuple[str, str, int]:
        return (
            row.model.casefold(),
            row.model,
            cohort_rank[row.cohort],
        )

    return tuple(sorted(rows, key=sort_key))


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
    results: Sequence[LabeledResult],
    tutorial: str,
    replacements: dict[str, str],
) -> tuple[tuple[str, ...], dict[str, dict[str, tuple[int, int]]]]:
    selected = [item for item in results if item.result.tutorial == tutorial]
    milestone_order = list(
        dict.fromkeys(
            name
            for item in selected
            for name, _complete in item.result.milestone_results
        )
    )
    for old, new in replacements.items():
        if old not in milestone_order or new not in milestone_order:
            continue
        milestone_order.remove(new)
        milestone_order.insert(milestone_order.index(old) + 1, new)
    milestones = tuple(milestone_order)
    models: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for item in selected:
        row_name = (
            f"{item.result.model} / {item.cohort}"
            if item.cohort is not None
            else item.result.model
        )
        for name, complete in item.result.milestone_results:
            models[row_name][name].append(complete)
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


COLORBREWER_RDYLGN_6 = (
    "#d73027",
    "#fc8d59",
    "#fee08b",
    "#d9ef8b",
    "#91cf60",
    "#1a9850",
)


def _heat_color(hit: int, total: int) -> str:
    palette_index = round(5 * hit / total) if total else 0
    return COLORBREWER_RDYLGN_6[palette_index]


def render_heatmap_svg(
    results: Sequence[LabeledResult],
    tutorial: str,
    replacements: dict[str, str],
) -> str:
    milestones, matrix = _milestone_matrix(results, tutorial, replacements)
    models = tuple(sorted(matrix))
    cell_width, cell_height, label_width = 82, 34, 230
    width = max(720, label_width + cell_width * len(milestones) + 24)
    visible_replacements = tuple(
        (old, new)
        for old, new in replacements.items()
        if old in milestones and new in milestones
    )
    replacement_legend_height = (
        26 + 18 * len(visible_replacements) if visible_replacements else 0
    )
    scale_legend_height = 48
    legend_height = replacement_legend_height + scale_legend_height
    height = 118 + cell_height * (len(models) + 1) + legend_height
    lines = _svg_start(width, height, f"{tutorial.title()} milestone completion")
    lines.insert(
        2,
        ".replaced-column{opacity:.72;filter:saturate(.35)}"
        ".replacement-column{stroke:#1971c2;"
        "stroke-width:4}.not-applicable{fill:#adb5bd}",
    )
    model_reach = {
        milestone: (
            sum(matrix[model][milestone][0] > 0 for model in models),
            sum(matrix[model][milestone][1] > 0 for model in models),
        )
        for milestone in milestones
    }
    for column, milestone in enumerate(milestones):
        x = label_width + column * cell_width
        short = milestone.replace("visited_", "").replace("inspected_", "").replace("_", " ")
        css = " replaced-column" if milestone in replacements else ""
        suffix = " (replaced)" if milestone in replacements else ""
        lines.append(
            f'<text class="small{css}" transform="translate({x + 14},104) rotate(-48)">'
            f"{escape((short + suffix)[:34])}</text>"
        )
    all_rows = (("Models reaching milestone", None), *((model, model) for model in models))
    for row, (label, model) in enumerate(all_rows):
        y = 112 + row * cell_height
        lines.append(f'<text class="label" x="12" y="{y + 23}">{escape(label)}</text>')
        for column, milestone in enumerate(milestones):
            x = label_width + column * cell_width
            if model is None:
                hit, total = model_reach[milestone]
            else:
                hit, total = matrix[model][milestone]
            classes = []
            if milestone in replacements:
                classes.append("replaced-column")
            if milestone in replacements.values():
                classes.append("replacement-column")
            if not total:
                classes.append("not-applicable")
            class_attr = f' class="{" ".join(classes)}"' if classes else ""
            fill = "#adb5bd" if not total else _heat_color(hit, total)
            lines.append(
                f'<rect{class_attr} x="{x}" y="{y}" width="{cell_width - 2}" '
                f'height="{cell_height - 2}" fill="{fill}"/>'
            )
            cell_text = f"{hit}/{total}" if total else "—"
            palette_index = round(5 * hit / total) if total else 0
            text_fill = "#17202a" if total and palette_index in (2, 3, 4) else "white"
            lines.append(
                f'<text x="{x + cell_width // 2}" y="{y + 22}" text-anchor="middle" '
                f'style="font-family:sans-serif;font-size:12px;font-weight:700;'
                f'fill:{text_fill}">'
                f"{cell_text}</text>"
            )
    legend_y = 124 + cell_height * (len(models) + 1)
    if visible_replacements:
        lines.append(
            f'<text class="label" x="12" y="{legend_y}">Milestone replacements</text>'
        )
        for index, (old, new) in enumerate(visible_replacements, 1):
            lines.append(
                f'<text class="small" x="12" y="{legend_y + index * 18}">'
                f"{escape(old)} → {escape(new)}</text>"
            )
    scale_y = legend_y + replacement_legend_height
    lines.append(
        f'<text class="label" x="12" y="{scale_y}">'
        "Completed sessions · ColorBrewer RdYlGn</text>"
    )
    for count, color in enumerate(COLORBREWER_RDYLGN_6):
        x = 12 + count * 62
        lines.append(
            f'<rect x="{x}" y="{scale_y + 8}" width="32" height="20" fill="{color}"/>'
        )
        lines.append(
            f'<text class="small" x="{x + 39}" y="{scale_y + 23}">{count}</text>'
        )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _comparison_table(rows: Sequence[ModelRow]) -> str:
    cohort_mode = any(row.cohort is not None for row in rows)
    lines = (
        [
            "| Cohort | Model | Passes | Milestones | Validity | Milestones/turn |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
        if cohort_mode
        else [
            "| Model | Passes | Milestones | Validity | Milestones/turn |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        attempted = row.valid_actions + row.rejected_actions
        validity = row.valid_actions / attempted if attempted else 1
        progress = row.milestone_hits / row.turns if row.turns else 0
        prefix = f"| `{row.cohort}` | `{row.model}`" if cohort_mode else f"| `{row.model}`"
        lines.append(
            f"{prefix} | {row.passes}/{row.sessions} | "
            f"{row.milestone_hits}/{row.milestone_possible} | {validity:.1%} | "
            f"{progress:.3f} |"
        )
    return "\n".join(lines)


def _difficulty_rows(results: Sequence[LabeledResult]) -> tuple[DifficultyRow, ...]:
    cohort_rank = {
        cohort: index
        for index, cohort in enumerate(
            dict.fromkeys(item.cohort for item in results)
        )
    }
    tutorial_rank = {name: index for index, name in enumerate(TUTORIAL_MAPS)}
    cells: dict[tuple[str | None, str, str], list[SessionResult]] = defaultdict(list)
    for item in results:
        cells[(item.cohort, item.result.tutorial, item.result.model)].append(item.result)
    grouped: dict[tuple[str | None, str], list[int]] = defaultdict(list)
    for (cohort, tutorial, _model), sessions in cells.items():
        if len(sessions) < 5:
            continue
        grouped[(cohort, tutorial)].append(sum(result.passed for result in sessions))
    rows = (
        DifficultyRow(
            cohort=cohort,
            tutorial=tutorial,
            complete_cells=len(pass_counts),
            possible_passes=sum(count >= 1 for count in pass_counts),
            likely_passes=sum(count >= 3 for count in pass_counts),
            consistent_passes=sum(count >= 4 for count in pass_counts),
        )
        for (cohort, tutorial), pass_counts in grouped.items()
    )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                tutorial_rank.get(row.tutorial, len(tutorial_rank)),
                row.tutorial,
                cohort_rank[row.cohort],
            ),
        )
    )


def _difficulty_table(rows: Sequence[DifficultyRow]) -> str:
    if not rows:
        return "No complete five-session model/tutorial cells were available."
    cohort_mode = any(row.cohort is not None for row in rows)
    lines = (
        [
            "| Cohort | Tutorial | Complete cells | Possible pass ≥1/5 | "
            "Likely pass ≥3/5 | Consistent pass ≥4/5 |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
        if cohort_mode
        else [
            "| Tutorial | Complete cells | Possible pass ≥1/5 | Likely pass ≥3/5 | "
            "Consistent pass ≥4/5 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        prefix = (
            f"| `{row.cohort}` | `{row.tutorial}`"
            if cohort_mode
            else f"| `{row.tutorial}`"
        )
        lines.append(
            f"{prefix} | {row.complete_cells} | "
            f"{row.possible_passes}/{row.complete_cells} | "
            f"{row.likely_passes}/{row.complete_cells} | "
            f"{row.consistent_passes}/{row.complete_cells} |"
        )
    return "\n".join(lines)


def _cohort_delta_rows(
    results: Sequence[LabeledResult],
    cohort_order: Sequence[str],
) -> tuple[tuple[CohortDeltaRow, ...], tuple[CohortDeltaRow, ...]]:
    cells: dict[tuple[str, str, str], list[SessionResult]] = defaultdict(list)
    tutorials_by_cohort: dict[str, set[str]] = defaultdict(set)
    for item in results:
        if item.cohort is None:
            continue
        key = (item.cohort, item.result.tutorial, item.result.model)
        cells[key].append(item.result)
        tutorials_by_cohort[item.cohort].add(item.result.tutorial)

    aggregate_rows: list[CohortDeltaRow] = []
    model_rows: list[CohortDeltaRow] = []
    tutorial_rank = {name: index for index, name in enumerate(TUTORIAL_MAPS)}
    for before, after in zip(cohort_order, cohort_order[1:], strict=False):
        shared_tutorials = tutorials_by_cohort[before].intersection(
            tutorials_by_cohort[after]
        )
        for tutorial in sorted(
            shared_tutorials,
            key=lambda name: (tutorial_rank.get(name, len(tutorial_rank)), name),
        ):
            before_cells = {
                model: sessions
                for (cohort, cell_tutorial, model), sessions in cells.items()
                if cohort == before and cell_tutorial == tutorial
            }
            after_cells = {
                model: sessions
                for (cohort, cell_tutorial, model), sessions in cells.items()
                if cohort == after and cell_tutorial == tutorial
            }
            before_sessions = tuple(
                result for sessions in before_cells.values() for result in sessions
            )
            after_sessions = tuple(
                result for sessions in after_cells.values() for result in sessions
            )
            aggregate_rows.append(
                CohortDeltaRow(
                    before_cohort=before,
                    after_cohort=after,
                    tutorial=tutorial,
                    model=None,
                    before_passes=sum(result.passed for result in before_sessions),
                    before_sessions=len(before_sessions),
                    after_passes=sum(result.passed for result in after_sessions),
                    after_sessions=len(after_sessions),
                )
            )
            for model in sorted(before_cells.keys() | after_cells.keys()):
                before_model = before_cells.get(model)
                after_model = after_cells.get(model)
                model_rows.append(
                    CohortDeltaRow(
                        before_cohort=before,
                        after_cohort=after,
                        tutorial=tutorial,
                        model=model,
                        before_passes=(
                            sum(result.passed for result in before_model)
                            if before_model is not None
                            else None
                        ),
                        before_sessions=(
                            len(before_model) if before_model is not None else None
                        ),
                        after_passes=(
                            sum(result.passed for result in after_model)
                            if after_model is not None
                            else None
                        ),
                        after_sessions=(
                            len(after_model) if after_model is not None else None
                        ),
                    )
                )
    cohort_rank = {cohort: index for index, cohort in enumerate(cohort_order)}
    ordered_aggregate_rows = sorted(
        aggregate_rows,
        key=lambda row: (
            tutorial_rank.get(row.tutorial, len(tutorial_rank)),
            row.tutorial,
            cohort_rank[row.before_cohort],
        ),
    )
    ordered_model_rows = sorted(
        model_rows,
        key=lambda row: (
            (row.model or "").casefold(),
            row.model or "",
            tutorial_rank.get(row.tutorial, len(tutorial_rank)),
            row.tutorial,
            cohort_rank[row.before_cohort],
        ),
    )
    return tuple(ordered_aggregate_rows), tuple(ordered_model_rows)


def _pass_rate_cell(passes: int | None, sessions: int | None) -> str:
    if passes is None or sessions is None or not sessions:
        return "—"
    return f"{passes}/{sessions} ({passes / sessions:.1%})"


def _delta_cell(row: CohortDeltaRow) -> str:
    delta = row.delta_percentage_points
    if delta is None:
        return "—"
    return f"{delta:+.1f} pp"


def _cohort_delta_table(
    aggregate_rows: Sequence[CohortDeltaRow],
    model_rows: Sequence[CohortDeltaRow],
) -> str:
    if not aggregate_rows:
        return "At least two cohorts with a shared tutorial are required."
    lines = [
        "### Tutorial totals",
        "",
        "| Transition | Tutorial | Before | After | Δ pass rate |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in aggregate_rows:
        lines.append(
            f"| `{row.before_cohort} → {row.after_cohort}` | `{row.tutorial}` | "
            f"{_pass_rate_cell(row.before_passes, row.before_sessions)} | "
            f"{_pass_rate_cell(row.after_passes, row.after_sessions)} | "
            f"{_delta_cell(row)} |"
        )
    lines.extend(
        (
            "",
            "### Matching model/tutorial cells",
            "",
            "| Transition | Model | Tutorial | Before | After | Δ pass rate |",
            "| --- | --- | --- | ---: | ---: | ---: |",
        )
    )
    for row in model_rows:
        lines.append(
            f"| `{row.before_cohort} → {row.after_cohort}` | `{row.model}` | "
            f"`{row.tutorial}` | "
            f"{_pass_rate_cell(row.before_passes, row.before_sessions)} | "
            f"{_pass_rate_cell(row.after_passes, row.after_sessions)} | "
            f"{_delta_cell(row)} |"
        )
    return "\n".join(lines)


def _token_table(rows: Sequence[ModelRow]) -> str:
    cohort_mode = any(row.cohort is not None for row in rows)
    lines = (
        [
            "| Cohort | Model | Input tokens | Output tokens | Total tokens | "
            "Usage coverage | Median sec/turn | Milestones/M tokens |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        if cohort_mode
        else [
            "| Model | Input tokens | Output tokens | Total tokens | "
            "Usage coverage | Median sec/turn | Milestones/M tokens |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        prefix = f"| `{row.cohort}` | `{row.model}`" if cohort_mode else f"| `{row.model}`"
        lines.append(
            f"{prefix} | {row.input_tokens:,} | {row.output_tokens:,} | "
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
    def label(row: ModelRow) -> str:
        return f"{row.cohort} / {row.model}" if row.cohort is not None else row.model

    return "\n".join(
        (
            f"Recorded provider usage totals **{input_tokens + output_tokens:,} tokens**: "
            f"{input_tokens:,} input and {output_tokens:,} output tokens across "
            f"{covered:,}/{response_rows:,} retained response rows.",
            "",
            f"- Fastest median decision pace: `{label(fastest)}` at "
            f"{fastest.median_seconds_per_turn:.2f} seconds/turn.",
            f"- Slowest median decision pace: `{label(slowest)}` at "
            f"{slowest.median_seconds_per_turn:.2f} seconds/turn.",
            f"- Most token-efficient: `{label(most_efficient)}` at "
            f"{most_efficient.token_efficiency:,.2f} completed milestones per million tokens.",
            f"- Least token-efficient: `{label(least_efficient)}` at "
            f"{least_efficient.token_efficiency:,.2f} completed milestones per million tokens.",
        )
    )


def _typst_text(value: str) -> str:
    return f"#text({json.dumps(value, ensure_ascii=False)})"


def _typst_report(
    title: str,
    rows: Sequence[ModelRow],
    difficulty_rows: Sequence[DifficultyRow],
    aggregate_deltas: Sequence[CohortDeltaRow],
    model_deltas: Sequence[CohortDeltaRow],
    diagrams: Sequence[str],
    sources: Sequence[str],
) -> str:
    cohort_mode = any(row.cohort is not None for row in rows)
    cells = [
        *(["[*Cohort*]"] if cohort_mode else []),
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
            *((row.cohort or "",) if cohort_mode else ()),
            row.model,
            f"{row.passes}/{row.sessions}",
            f"{row.milestone_hits}/{row.milestone_possible}",
            f"{validity:.1%}",
            f"{progress:.3f}",
        )
        cells.extend(f"[{_typst_text(value)}]" for value in values)
    token_cells = [
        *(["[*Cohort*]"] if cohort_mode else []),
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
            *((row.cohort or "",) if cohort_mode else ()),
            row.model,
            f"{row.input_tokens:,}",
            f"{row.output_tokens:,}",
            f"{row.total_tokens:,}",
            f"{row.token_response_rows}/{row.response_rows}",
            f"{row.median_seconds_per_turn:.2f}",
            f"{row.token_efficiency:,.2f}",
        )
        token_cells.extend(f"[{_typst_text(value)}]" for value in values)
    difficulty_cohort_mode = any(row.cohort is not None for row in difficulty_rows)
    difficulty_cells = [
        *(["[*Cohort*]"] if difficulty_cohort_mode else []),
        "[*Tutorial*]",
        "[*Complete cells*]",
        "[*Possible ≥1/5*]",
        "[*Likely ≥3/5*]",
        "[*Consistent ≥4/5*]",
    ]
    for row in difficulty_rows:
        values = (
            *((row.cohort or "",) if difficulty_cohort_mode else ()),
            row.tutorial,
            str(row.complete_cells),
            f"{row.possible_passes}/{row.complete_cells}",
            f"{row.likely_passes}/{row.complete_cells}",
            f"{row.consistent_passes}/{row.complete_cells}",
        )
        difficulty_cells.extend(f"[{_typst_text(value)}]" for value in values)
    difficulty_block = (
        (
            "#table(",
            (
                "  columns: (1.2fr, 1fr, 1fr, 1fr, 1fr, 1fr),"
                if difficulty_cohort_mode
                else "  columns: (1fr, 1fr, 1fr, 1fr, 1fr),"
            ),
            "  inset: 5pt,",
            '  stroke: 0.5pt + rgb("ccd3dc"),',
            "  " + ",\n  ".join(difficulty_cells),
            ")",
        )
        if difficulty_rows
        else (_typst_text("No complete five-session model/tutorial cells were available."),)
    )
    delta_block: tuple[str, ...]
    if aggregate_deltas:
        aggregate_cells = [
            "[*Transition*]",
            "[*Tutorial*]",
            "[*Before*]",
            "[*After*]",
            "[*Delta*]",
        ]
        for row in aggregate_deltas:
            values = (
                f"{row.before_cohort} → {row.after_cohort}",
                row.tutorial,
                _pass_rate_cell(row.before_passes, row.before_sessions),
                _pass_rate_cell(row.after_passes, row.after_sessions),
                _delta_cell(row),
            )
            aggregate_cells.extend(f"[{_typst_text(value)}]" for value in values)
        model_cells = [
            "[*Transition*]",
            "[*Model*]",
            "[*Tutorial*]",
            "[*Before*]",
            "[*After*]",
            "[*Delta*]",
        ]
        for row in model_deltas:
            values = (
                f"{row.before_cohort} → {row.after_cohort}",
                row.model or "",
                row.tutorial,
                _pass_rate_cell(row.before_passes, row.before_sessions),
                _pass_rate_cell(row.after_passes, row.after_sessions),
                _delta_cell(row),
            )
            model_cells.extend(f"[{_typst_text(value)}]" for value in values)
        delta_block = (
            "=== Tutorial totals",
            "#table(",
            "  columns: (1.2fr, 1fr, 1fr, 1fr, 1fr),",
            "  inset: 5pt,",
            '  stroke: 0.5pt + rgb("ccd3dc"),',
            "  " + ",\n  ".join(aggregate_cells),
            ")",
            "#pagebreak()",
            "=== Matching model/tutorial cells",
            "#set text(size: 7pt)",
            "#table(",
            "  columns: (1.2fr, 2fr, 1fr, 1fr, 1fr, 1fr),",
            "  inset: 3pt,",
            '  stroke: 0.5pt + rgb("ccd3dc"),',
            "  " + ",\n  ".join(model_cells),
            ")",
            "#set text(size: 9pt)",
        )
    else:
        delta_block = (
            _typst_text("At least two cohorts with a shared tutorial are required."),
        )
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
            (
                "  columns: (1.2fr, 2fr, 1fr, 0.8fr, 1fr, 0.8fr, 0.8fr, 1fr),"
                if cohort_mode
                else "  columns: (2fr, 1fr, 0.8fr, 1fr, 0.8fr, 0.8fr, 1fr),"
            ),
            "  inset: 3pt,",
            "  stroke: 0.5pt + rgb(\"ccd3dc\"),",
            "  " + ",\n  ".join(token_cells),
            ")",
            "#set text(size: 9pt)",
            "",
            "== Model comparison",
            "",
            "#table(",
            (
                "  columns: (1.2fr, 2.2fr, 1fr, 1fr, 1fr, 1fr),"
                if cohort_mode
                else "  columns: (2.2fr, 1fr, 1fr, 1fr, 1fr),"
            ),
            "  inset: 5pt,",
            "  stroke: 0.5pt + rgb(\"ccd3dc\"),",
            "  " + ",\n  ".join(cells),
            ")",
            "",
            "== Difficulty distribution",
            "",
            "Possible pass means at least 1/5, likely pass at least 3/5, and consistent "
            "pass at least 4/5. Incomplete cells are excluded.",
            "",
            *difficulty_block,
            "",
            "== Cohort deltas",
            "",
            "Deltas compare consecutive cohorts in the supplied order. Missing model/cohort "
            "cells are not treated as failures. Tutorial totals reflect each cohort's "
            "tested model mix; matching model/tutorial rows are like-for-like.",
            "",
            *delta_block,
            *images,
            "",
        )
    )


def _replacement_mapping(sources: Sequence[LoadedSource]) -> dict[str, str]:
    replacements: dict[str, str] = {}
    for source in sources:
        for old, new in source.manifest.milestone_replacements.items():
            previous = replacements.get(old)
            if previous is not None and previous != new:
                raise ValueError(
                    f"report sources disagree on replacement for {old}: {previous} vs {new}"
                )
            replacements[old] = new
    return replacements


def build_report(
    inputs: Sequence[Path],
    output: Path,
    *,
    title: str,
    cohorts: Sequence[CohortInput] = (),
) -> None:
    if inputs and cohorts:
        raise ValueError("use either --input or --cohort, not both")
    if cohorts:
        if any(not cohort.label.strip() for cohort in cohorts):
            raise ValueError("cohort labels must not be empty")
        labeled_sources = tuple(
            (cohort.label, load_source(SourceSelection(cohort.path.resolve())))
            for cohort in cohorts
        )
    else:
        labeled_sources = tuple(
            (None, load_source(SourceSelection(path.resolve()))) for path in inputs
        )
    if not labeled_sources:
        raise ValueError("at least one --input or --cohort is required")
    sources = tuple(source for _cohort, source in labeled_sources)
    schema_versions = {source.manifest.schema_version for source in sources}
    if not cohorts and len(schema_versions) > 1:
        versions = ", ".join(map(str, sorted(schema_versions)))
        raise ValueError(
            f"report inputs mix schema versions ({versions}); use --cohort LABEL=PATH "
            "for explicit cross-version analysis"
        )
    results = tuple(
        LabeledResult(cohort, result)
        for cohort, source in labeled_sources
        for result in source.results
    )
    if not results:
        raise ValueError("report inputs contain no completed sessions")
    replacements = _replacement_mapping(sources)
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
        heatmap_path.write_text(
            render_heatmap_svg(results, tutorial, replacements),
            encoding="utf-8",
        )
        diagram_paths.extend(
            (
                str(tabletop_path.relative_to(output)),
                str(map_path.relative_to(output)),
                str(heatmap_path.relative_to(output)),
            )
        )
    rows = _model_rows(results, _model_usage(labeled_sources))
    difficulty_rows = _difficulty_rows(results)
    cohort_order = tuple(
        dict.fromkeys(
            cohort for cohort, _source in labeled_sources if cohort is not None
        )
    )
    aggregate_deltas, model_deltas = _cohort_delta_rows(results, cohort_order)
    template = (Path(__file__).parent / "templates" / "tutorial_report.md").read_text(
        encoding="utf-8"
    )
    markdown = (
        template.replace("{{TITLE}}", title)
        .replace("{{COMPLETED}}", str(len(results)))
        .replace("{{PASSES}}", str(sum(item.result.passed for item in results)))
        .replace(
            "{{SOURCES}}",
            "\n".join(
                "- "
                + (f"`{cohort}` / " if cohort is not None else "")
                + f"`{source.path.name}` — "
                f"{len(source.results)} completed sessions"
                for cohort, source in labeled_sources
            ),
        )
        .replace("{{RUNTIME_SUMMARY}}", _runtime_summary(rows))
        .replace("{{TOKEN_TABLE}}", _token_table(rows))
        .replace("{{COMPARISON_TABLE}}", _comparison_table(rows))
        .replace("{{DIFFICULTY_TABLE}}", _difficulty_table(difficulty_rows))
        .replace(
            "{{COHORT_DELTAS}}",
            _cohort_delta_table(aggregate_deltas, model_deltas),
        )
        .replace(
            "{{DIAGRAMS}}",
            "\n\n".join(f"![{Path(path).stem}]({path})" for path in diagram_paths),
        )
    )
    (output / "report.md").write_text(markdown, encoding="utf-8")
    (output / "report.typ").write_text(
        _typst_report(
            title,
            rows,
            difficulty_rows,
            aggregate_deltas,
            model_deltas,
            diagram_paths,
            tuple(
                f"{cohort} / {source.path.name}" if cohort is not None else source.path.name
                for cohort, source in labeled_sources
            ),
        ),
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
    parser.add_argument("--input", action="append", default=[], type=Path)
    parser.add_argument(
        "--cohort",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="label a report input cohort; repeat and reuse labels for multiple paths",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--title", default="Bunnyland tutorial-ladder benchmark")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cohorts = []
    for value in args.cohort:
        if "=" not in value:
            raise SystemExit("--cohort must use LABEL=PATH")
        label, path = value.split("=", 1)
        if not label or not path:
            raise SystemExit("--cohort must use LABEL=PATH")
        cohorts.append(CohortInput(label, Path(path)))
    build_report(args.input, args.output, title=args.title, cohorts=cohorts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
