"""Build tutorial benchmark reports, maps, and milestone heatmaps."""

from __future__ import annotations

import argparse
import json
import math
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
from benchmarks.tutorials import JsonValue, ModelResponseTrace, SessionResult, TurnTrace


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
    estimated_cost_usd: float

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def token_efficiency(self) -> float:
        if not self.total_tokens:
            return 0
        return self.milestone_hits * 1_000_000 / self.total_tokens

@dataclass(frozen=True)
class DifficultyRow:
    cohort: str | None
    tutorial: str
    complete_cells: int
    possible_passes: int
    likely_passes: int
    consistent_passes: int


@dataclass(frozen=True)
class TutorialAcceptancePolicy:
    tutorial: str
    cohort_expectation: str
    strong_model_expectation: str
    role: str


TUTORIAL_ACCEPTANCE_POLICIES = (
    TutorialAcceptancePolicy(
        tutorial="apple",
        cohort_expectation="Many or most models reach likely pass (at least 3/5).",
        strong_model_expectation=(
            "Preselected strong models reach consistent pass (at least 4/5); "
            "5/5 is desirable."
        ),
        role="Accessible onboarding, not a filter.",
    ),
    TutorialAcceptancePolicy(
        tutorial="bell",
        cohort_expectation="Many or most models reach likely pass (at least 3/5).",
        strong_model_expectation=(
            "Preselected strong models reach consistent pass (at least 4/5); "
            "5/5 is desirable."
        ),
        role="Reinforcement, not the primary filter.",
    ),
    TutorialAcceptancePolicy(
        tutorial="clover",
        cohort_expectation=(
            "Retain a meaningful spread across possible, likely, and consistent pass."
        ),
        strong_model_expectation=(
            "Compare preselected strong models without imposing a blanket 4/5 gate."
        ),
        role="Primary filter point.",
    ),
)


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
class ChangeBreadthRow:
    before_cohort: str
    after_cohort: str
    tutorial: str
    improved_models: int
    tied_models: int
    regressed_models: int

    @property
    def shared_models(self) -> int:
        return self.improved_models + self.tied_models + self.regressed_models


@dataclass(frozen=True)
class ResponseUsage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    token_response_rows: int = 0
    response_rows: int = 0
    estimated_cost_usd: float = 0


@dataclass(frozen=True)
class FrontierPricing:
    display_name: str
    input_per_million: float
    output_per_million: float
    cache_read_per_million: float
    cache_write_per_million: float


@dataclass(frozen=True)
class FrontierCostRow:
    model: str
    display_name: str
    sessions: int
    passes: int
    milestone_hits: int
    milestone_possible: int
    estimated_cost_usd: float

    @property
    def pass_rate(self) -> float:
        return self.passes / self.sessions if self.sessions else 0

    @property
    def passes_per_dollar(self) -> float:
        return self.passes / self.estimated_cost_usd if self.estimated_cost_usd else 0

    @property
    def milestones_per_dollar(self) -> float:
        if not self.estimated_cost_usd:
            return 0
        return self.milestone_hits / self.estimated_cost_usd


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


@dataclass(frozen=True)
class CoverageSummaryRow:
    cohort: str
    tutorials: tuple[str, ...]
    observed_sessions: int
    expected_sessions: int
    complete_cells: int
    partial_cells: int
    missing_cells: int
    not_applicable_cells: int


@dataclass(frozen=True)
class CoverageGapRow:
    cohort: str
    model: str
    observed_sessions: int
    expected_sessions: int
    missing_sessions: int
    incomplete_tutorials: tuple[str, ...]


@dataclass(frozen=True)
class CoverageAnalysis:
    reference_cohort: str
    reference_models: int
    target_sessions: int
    summary_rows: tuple[CoverageSummaryRow, ...]
    gap_rows: tuple[CoverageGapRow, ...]


@dataclass(frozen=True)
class LatencyRow:
    cohort: str | None
    model: str
    provider: str
    decisions: int
    median_seconds: float
    p95_seconds: float
    p99_seconds: float
    maximum_seconds: float
    token_decisions: int
    output_tokens: int
    token_seconds: float

    @property
    def output_tokens_per_second(self) -> float | None:
        if not self.token_seconds:
            return None
        return self.output_tokens / self.token_seconds


@dataclass(frozen=True)
class LatencyAnalysis:
    overall: LatencyRow
    cohort_rows: tuple[LatencyRow, ...]
    model_rows: tuple[LatencyRow, ...]
    aggregate_model_rows: tuple[LatencyRow, ...]


@dataclass(frozen=True)
class ModelEfficiencyRow:
    model: str
    milestone_hits: int
    milestone_possible: int
    total_tokens: int

    @property
    def token_efficiency(self) -> float:
        if not self.total_tokens:
            return 0
        return self.milestone_hits * 1_000_000 / self.total_tokens


@dataclass(frozen=True)
class KimiFamilyRow:
    model: str
    display_name: str
    provider: str
    sessions: int
    passes: int
    milestone_hits: int
    milestone_possible: int
    median_latency_seconds: float | None
    total_tokens: int

    @property
    def pass_rate(self) -> float:
        return self.passes / self.sessions if self.sessions else 0

    @property
    def milestone_rate(self) -> float:
        if not self.milestone_possible:
            return 0
        return self.milestone_hits / self.milestone_possible

    @property
    def token_efficiency(self) -> float:
        if not self.total_tokens:
            return 0
        return self.milestone_hits * 1_000_000 / self.total_tokens


@dataclass(frozen=True)
class LatencySample:
    cohort: str | None
    model: str
    provider: str
    seconds: float
    output_tokens: int | None


@dataclass(frozen=True)
class MilestoneBottleneckRow:
    cohort: str | None
    tutorial: str
    milestone: str
    completions: int
    sessions: int


@dataclass(frozen=True)
class BehaviorRow:
    cohort: str | None
    tutorial: str
    passes: int
    sessions: int
    valid_actions: int
    rejected_actions: int
    recovered_rejections: int

    @property
    def validity(self) -> float:
        attempted = self.valid_actions + self.rejected_actions
        return self.valid_actions / attempted if attempted else 1

    @property
    def recovery(self) -> float:
        return (
            self.recovered_rejections / self.rejected_actions
            if self.rejected_actions
            else 1
        )


@dataclass(frozen=True)
class QuantizationRow:
    cohort: str | None
    tutorial: str
    model: str
    quantization: str
    passes: int
    sessions: int


@dataclass(frozen=True)
class ModelArchitecture:
    display_name: str
    total_parameters: int


@dataclass(frozen=True)
class ParameterScatterMetadata:
    display_name: str
    parameter_count: int
    provider: str


@dataclass(frozen=True)
class ParameterScatterPoint:
    model: str
    display_name: str
    parameter_count: int
    provider: str
    milestone_hits: int
    milestone_possible: int

    @property
    def milestone_rate(self) -> float:
        if not self.milestone_possible:
            return 0
        return self.milestone_hits / self.milestone_possible


MODEL_ARCHITECTURES: dict[str, ModelArchitecture] = {
    "qwen3.5:4b": ModelArchitecture("Qwen 3.5 4B", 4_000_000_000),
    "bunnyland-rpmax-llama3.1-8b-q8-tools:latest": ModelArchitecture(
        "Llama 3.1 8B ArliAI RPMax v1.3 Q8",
        8_000_000_000,
    ),
    "bunnyland-stheno-llama3.1-8b-q8-tools:latest": ModelArchitecture(
        "Llama 3.1 8B Stheno v3.4 Q8",
        8_000_000_000,
    ),
    "qwen3.5:9b": ModelArchitecture("Qwen 3.5 9B", 9_000_000_000),
    "ornith:9b": ModelArchitecture("Ornith 1.0 9B", 9_000_000_000),
    "gpt-oss:20b-cloud": ModelArchitecture("GPT-OSS 20B", 21_000_000_000),
    "gemma4:cloud": ModelArchitecture("Gemma 4 31B", 30_700_000_000),
    "hf.co/HauhauCS/Gemma4-31B-QAT-Uncensored-HauhauCS-Balanced-MTP:Q4_K_M": (
        ModelArchitecture("Gemma 4 31B HauhauCS Q4", 30_700_000_000)
    ),
    "nemotron-3-nano:30b-cloud": ModelArchitecture(
        "Nemotron 3 Nano 30B-A3B",
        31_600_000_000,
    ),
    "laguna-xs-2.1:latest": ModelArchitecture("Laguna XS 2.1", 33_000_000_000),
    "ornith:35b": ModelArchitecture("Ornith 1.0 35B-A3B", 34_700_000_000),
    "qwen3.6:35b-a3b": ModelArchitecture(
        "Qwen 3.6 35B-A3B Q4",
        35_000_000_000,
    ),
    "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K": ModelArchitecture(
        "Qwen 3.6 35B-A3B Q6",
        35_000_000_000,
    ),
    "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:Q8_0": ModelArchitecture(
        "Qwen 3.6 35B-A3B Q8",
        35_000_000_000,
    ),
    "gpt-oss:120b-cloud": ModelArchitecture("GPT-OSS 120B", 117_000_000_000),
    "nemotron-3-super:cloud": ModelArchitecture(
        "Nemotron 3 Super 120B-A12B",
        120_000_000_000,
    ),
    "minimax-m2.7:cloud": ModelArchitecture("MiniMax M2.7", 230_000_000_000),
    "deepseek-v4-flash:cloud": ModelArchitecture(
        "DeepSeek V4 Flash",
        284_000_000_000,
    ),
    "qwen3.5:397b-cloud": ModelArchitecture(
        "Qwen 3.5 397B-A17B",
        397_000_000_000,
    ),
    "minimax-m3:cloud": ModelArchitecture("MiniMax M3", 428_000_000_000),
    "nemotron-3-ultra:cloud": ModelArchitecture(
        "Nemotron 3 Ultra 550B-A55B",
        550_000_000_000,
    ),
    "mistral-large-3:675b-cloud": ModelArchitecture(
        "Mistral Large 3",
        675_000_000_000,
    ),
    "glm-5.2:cloud": ModelArchitecture("GLM-5.2", 753_000_000_000),
    "kimi-k2.5": ModelArchitecture("Kimi K2.5", 1_042_000_000_000),
    "kimi-k2.6:cloud": ModelArchitecture("Kimi K2.6", 1_000_000_000_000),
    "kimi-k2.7-code:cloud": ModelArchitecture(
        "Kimi K2.7 Code",
        1_000_000_000_000,
    ),
    "deepseek-v4-pro:cloud": ModelArchitecture(
        "DeepSeek V4 Pro",
        1_600_000_000_000,
    ),
    "moonshotai/kimi-k3": ModelArchitecture("Kimi K3", 2_800_000_000_000),
}


KIMI_FAMILY_MODELS: dict[str, tuple[int, str, str]] = {
    "kimi-k2.5": (0, "Kimi K2.5", "Ollama Cloud"),
    "kimi-k2.6:cloud": (1, "Kimi K2.6", "Ollama Cloud"),
    "kimi-k2.7-code:cloud": (2, "Kimi K2.7 Code¹", "Ollama Cloud"),
    "moonshotai/kimi-k3": (3, "Kimi K3", "OpenRouter"),
}


FRONTIER_PRICING: dict[str, FrontierPricing] = {
    "anthropic/claude-haiku-4.5": FrontierPricing(
        "Claude Haiku 4.5",
        input_per_million=1,
        output_per_million=5,
        cache_read_per_million=0.1,
        cache_write_per_million=1.25,
    ),
    "anthropic/claude-opus-5": FrontierPricing(
        "Claude Opus 5",
        input_per_million=5,
        output_per_million=25,
        cache_read_per_million=0.5,
        cache_write_per_million=6.25,
    ),
    "openai/gpt-5.6-luna": FrontierPricing(
        "GPT-5.6 Luna",
        input_per_million=1,
        output_per_million=6,
        cache_read_per_million=0.1,
        cache_write_per_million=1.25,
    ),
    "openai/gpt-5.6-sol": FrontierPricing(
        "GPT-5.6 Sol",
        input_per_million=5,
        output_per_million=30,
        cache_read_per_million=0.5,
        cache_write_per_million=6.25,
    ),
}


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
    prompt_details = usage.get("prompt_tokens_details")
    cached_tokens = 0
    cache_write_tokens = 0
    if isinstance(prompt_details, dict):
        cached_tokens = _json_int(prompt_details.get("cached_tokens")) or 0
        cache_write_tokens = _json_int(prompt_details.get("cache_write_tokens")) or 0
    return ResponseUsage(
        prompt_tokens,
        output_tokens,
        cached_input_tokens=cached_tokens,
        cache_write_input_tokens=cache_write_tokens,
    )


def _estimated_response_cost(model: str, usage: ResponseUsage | None) -> float:
    pricing = FRONTIER_PRICING.get(model)
    if pricing is None or usage is None:
        return 0
    uncached_tokens = max(
        usage.input_tokens
        - usage.cached_input_tokens
        - usage.cache_write_input_tokens,
        0,
    )
    return (
        uncached_tokens * pricing.input_per_million
        + usage.cached_input_tokens * pricing.cache_read_per_million
        + usage.cache_write_input_tokens * pricing.cache_write_per_million
        + usage.output_tokens * pricing.output_per_million
    ) / 1_000_000


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


def _read_traces(path: Path) -> tuple[TurnTrace, ...]:
    trace_path = path / "traces.jsonl"
    if not trace_path.exists():
        return ()
    rows = []
    adapter = TypeAdapter(TurnTrace)
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(adapter.validate_json(line))
    return tuple(rows)


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _latency_row(
    samples: Sequence[LatencySample],
    *,
    cohort: str | None,
    model: str,
) -> LatencyRow:
    seconds = tuple(sample.seconds for sample in samples)
    token_samples = tuple(
        sample
        for sample in samples
        if sample.output_tokens is not None and sample.output_tokens > 0
    )
    return LatencyRow(
        cohort=cohort,
        model=model,
        provider=", ".join(sorted({sample.provider for sample in samples})),
        decisions=len(samples),
        median_seconds=statistics.median(seconds),
        p95_seconds=_percentile(seconds, 0.95),
        p99_seconds=_percentile(seconds, 0.99),
        maximum_seconds=max(seconds),
        token_decisions=len(token_samples),
        output_tokens=sum(sample.output_tokens or 0 for sample in token_samples),
        token_seconds=sum(sample.seconds for sample in token_samples),
    )


def _latency_analysis(
    sources: Sequence[tuple[str | None, LoadedSource]],
) -> LatencyAnalysis | None:
    samples: list[LatencySample] = []
    cohort_order = tuple(dict.fromkeys(cohort for cohort, _source in sources))
    for cohort, source in sources:
        for evidence in _evidence_slices(source):
            model_by_session = {
                result.session_id: result.model for result in evidence.results
            }
            usage_by_turn: dict[tuple[str, int], ResponseUsage] = {}
            for response in _read_responses(evidence.path):
                if response.session_id not in model_by_session:
                    continue
                usage = _response_usage(response.response)
                if usage is not None:
                    usage_by_turn[(response.session_id, response.turn)] = usage
            for trace in _read_traces(evidence.path):
                model = model_by_session.get(trace.session_id)
                if model is None:
                    continue
                usage = usage_by_turn.get((trace.session_id, trace.turn))
                samples.append(
                    LatencySample(
                        cohort=cohort,
                        model=model,
                        provider=source.manifest.provider,
                        seconds=trace.decision_latency_seconds,
                        output_tokens=usage.output_tokens if usage is not None else None,
                    )
                )
    if not samples:
        return None
    samples_by_cohort: dict[str | None, list[LatencySample]] = defaultdict(list)
    samples_by_model: dict[tuple[str | None, str], list[LatencySample]] = defaultdict(list)
    samples_by_exact_model: dict[str, list[LatencySample]] = defaultdict(list)
    for sample in samples:
        samples_by_cohort[sample.cohort].append(sample)
        samples_by_model[(sample.cohort, sample.model)].append(sample)
        samples_by_exact_model[sample.model].append(sample)
    cohort_rank = {cohort: index for index, cohort in enumerate(cohort_order)}
    cohort_rows = tuple(
        _latency_row(samples_by_cohort[cohort], cohort=cohort, model="All models")
        for cohort in cohort_order
        if samples_by_cohort[cohort]
    )
    model_rows = tuple(
        _latency_row(grouped, cohort=cohort, model=model)
        for (cohort, model), grouped in sorted(
            samples_by_model.items(),
            key=lambda item: (
                item[0][1].casefold(),
                item[0][1],
                cohort_rank[item[0][0]],
            ),
        )
    )
    aggregate_model_rows = tuple(
        _latency_row(grouped, cohort=None, model=model)
        for model, grouped in sorted(
            samples_by_exact_model.items(),
            key=lambda item: (item[0].casefold(), item[0]),
        )
    )
    return LatencyAnalysis(
        overall=_latency_row(samples, cohort=None, model="All models"),
        cohort_rows=cohort_rows,
        model_rows=model_rows,
        aggregate_model_rows=aggregate_model_rows,
    )


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
                    estimated_cost_usd=previous.estimated_cost_usd
                    + _estimated_response_cost(model, tokens),
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
                estimated_cost_usd=model_usage.estimated_cost_usd,
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

COLORBREWER_DARK2_3 = {
    "apple": "#1b9e77",
    "bell": "#d95f02",
    "clover": "#7570b3",
}

COLORBREWER_BLUES_3 = (
    "#9ecae1",
    "#4292c6",
    "#08519c",
)

SCATTER_PROVIDER_COLORS = {
    "Local": "#1f78b4",
    "Cloud": "#e66101",
}

COLORBREWER_DARK2_4 = (
    "#1b9e77",
    "#d95f02",
    "#7570b3",
    "#e7298a",
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
    models = tuple(sorted(matrix, key=lambda model: (model.casefold(), model)))
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


def _chart_cohorts(results: Sequence[LabeledResult]) -> tuple[str | None, ...]:
    return tuple(dict.fromkeys(item.cohort for item in results))


def _chart_x_positions(
    cohorts: Sequence[str | None],
    *,
    left: int,
    right: int,
) -> dict[str | None, float]:
    if len(cohorts) == 1:
        return {cohorts[0]: (left + right) / 2}
    step = (right - left) / (len(cohorts) - 1)
    return {cohort: left + index * step for index, cohort in enumerate(cohorts)}


def _cohort_label(cohort: str | None) -> str:
    return cohort if cohort is not None else "Unlabeled"


def render_success_trend_svg(results: Sequence[LabeledResult]) -> str:
    width, height = 1100, 600
    left, right, top, bottom = 90, 1040, 95, 500
    lines = _svg_start(width, height, "Tutorial success by version")
    lines.insert(
        2,
        ".axis{stroke:#425466;stroke-width:2}"
        ".trend-label{font-family:sans-serif;font-size:12px;font-weight:700}",
    )
    cohorts = _chart_cohorts(results)
    positions = _chart_x_positions(cohorts, left=left, right=right)
    grouped: dict[tuple[str | None, str], list[SessionResult]] = defaultdict(list)
    for item in results:
        grouped[(item.cohort, item.result.tutorial)].append(item.result)

    for percentage in range(0, 101, 20):
        y = bottom - (bottom - top) * percentage / 100
        lines.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}"/>')
        lines.append(
            f'<text class="small" text-anchor="end" x="{left - 12}" '
            f'y="{y + 4:.1f}">{percentage}%</text>'
        )
    lines.extend(
        (
            f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{bottom}"/>',
            f'<line class="axis" x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}"/>',
            (
                f'<text class="label" text-anchor="middle" '
                f'x="{(left + right) / 2:.1f}" y="{height - 28}">Version</text>'
            ),
            (
                f'<text class="label" text-anchor="middle" '
                f'transform="translate(24 {(top + bottom) / 2:.1f}) rotate(-90)">'
                "Session success rate</text>"
            ),
        )
    )
    for cohort in cohorts:
        x = positions[cohort]
        lines.append(
            f'<text class="label" text-anchor="middle" x="{x:.1f}" '
            f'y="{bottom + 30}">{escape(_cohort_label(cohort))}</text>'
        )

    for tutorial_index, tutorial in enumerate(TUTORIAL_MAPS):
        color = COLORBREWER_DARK2_3[tutorial]
        points: list[tuple[int, float, float, int, int]] = []
        for cohort_index, cohort in enumerate(cohorts):
            sessions = grouped.get((cohort, tutorial), ())
            if not sessions:
                continue
            passes = sum(session.passed for session in sessions)
            rate = passes / len(sessions)
            points.append(
                (
                    cohort_index,
                    positions[cohort],
                    bottom - (bottom - top) * rate,
                    passes,
                    len(sessions),
                )
            )
        for previous, current in zip(points, points[1:], strict=False):
            if current[0] != previous[0] + 1:
                continue
            lines.append(
                f'<line data-tutorial="{tutorial}" x1="{previous[1]:.1f}" '
                f'y1="{previous[2]:.1f}" x2="{current[1]:.1f}" '
                f'y2="{current[2]:.1f}" stroke="{color}" stroke-width="4"/>'
            )
        for _index, x, y, passes, total in points:
            rate = passes / total
            label_y = y - 12 if tutorial_index != 1 else y + 22
            lines.append(
                f'<circle data-tutorial="{tutorial}" cx="{x:.1f}" cy="{y:.1f}" '
                f'r="7" fill="{color}" stroke="white" stroke-width="2"/>'
            )
            lines.append(
                f'<text class="trend-label" text-anchor="middle" x="{x:.1f}" '
                f'y="{label_y:.1f}" fill="{color}">{rate:.1%}</text>'
            )

    legend_x = 710
    for index, tutorial in enumerate(TUTORIAL_MAPS):
        x = legend_x + index * 120
        color = COLORBREWER_DARK2_3[tutorial]
        lines.append(
            f'<line x1="{x}" y1="58" x2="{x + 28}" y2="58" stroke="{color}" stroke-width="4"/>'
        )
        lines.append(f'<circle cx="{x + 14}" cy="58" r="5" fill="{color}"/>')
        lines.append(f'<text class="small" x="{x + 36}" y="62">{escape(tutorial.title())}</text>')
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def render_threshold_chart_svg(rows: Sequence[DifficultyRow]) -> str:
    width, height = 1260, 650
    left, right, top, bottom = 80, 1220, 125, 535
    lines = _svg_start(width, height, "Five-session threshold attainment")
    lines.insert(
        2,
        ".axis{stroke:#425466;stroke-width:2}"
        ".bar-value{font-family:sans-serif;font-size:7.5px;font-weight:700;fill:#17202a}",
    )
    cohorts = tuple(dict.fromkeys(row.cohort for row in rows))
    if not rows or not cohorts:
        lines.append(
            '<text class="label" x="24" y="70">'
            "No complete five-session model/tutorial cells were available.</text>"
        )
        lines.append("</svg>")
        return "\n".join(lines) + "\n"

    thresholds = (
        ("Possible ≥1/5", "possible_passes", COLORBREWER_BLUES_3[0]),
        ("Likely ≥3/5", "likely_passes", COLORBREWER_BLUES_3[1]),
        ("Consistent ≥4/5", "consistent_passes", COLORBREWER_BLUES_3[2]),
    )
    lookup = {(row.cohort, row.tutorial): row for row in rows}
    panel_gap = 24
    panel_width = (right - left - panel_gap * 2) / 3
    plot_height = bottom - top

    for percentage in range(0, 101, 20):
        y = bottom - plot_height * percentage / 100
        lines.append(
            f'<text class="small" text-anchor="end" x="{left - 12}" '
            f'y="{y + 4:.1f}">{percentage}%</text>'
        )
    lines.append(
        f'<text class="label" text-anchor="middle" '
        f'transform="translate(22 {(top + bottom) / 2:.1f}) rotate(-90)">'
        "Share of complete model cells</text>"
    )

    for tutorial_index, tutorial in enumerate(TUTORIAL_MAPS):
        panel_left = left + tutorial_index * (panel_width + panel_gap)
        panel_right = panel_left + panel_width
        lines.append(
            f'<text class="label" text-anchor="middle" '
            f'x="{(panel_left + panel_right) / 2:.1f}" y="{top - 22}">'
            f"{escape(tutorial.title())}</text>"
        )
        for percentage in range(0, 101, 20):
            y = bottom - plot_height * percentage / 100
            lines.append(
                f'<line class="grid" x1="{panel_left:.1f}" y1="{y:.1f}" '
                f'x2="{panel_right:.1f}" y2="{y:.1f}"/>'
            )
        lines.extend(
            (
                f'<line class="axis" x1="{panel_left:.1f}" y1="{top}" '
                f'x2="{panel_left:.1f}" y2="{bottom}"/>',
                f'<line class="axis" x1="{panel_left:.1f}" y1="{bottom}" '
                f'x2="{panel_right:.1f}" y2="{bottom}"/>',
            )
        )
        group_width = panel_width / len(cohorts)
        bar_width = min(24.0, (group_width - 14) / len(thresholds))
        for cohort_index, cohort in enumerate(cohorts):
            center = panel_left + group_width * (cohort_index + 0.5)
            row = lookup.get((cohort, tutorial))
            if row is None:
                lines.append(
                    f'<text class="label" text-anchor="middle" x="{center:.1f}" '
                    f'y="{bottom - 8}">—</text>'
                )
            else:
                group_start = center - bar_width * len(thresholds) / 2
                threshold_hits = (
                    row.possible_passes,
                    row.likely_passes,
                    row.consistent_passes,
                )
                for threshold_index, (
                    (_label, field, color),
                    hits,
                ) in enumerate(zip(thresholds, threshold_hits, strict=True)):
                    rate = hits / row.complete_cells if row.complete_cells else 0
                    bar_height = plot_height * rate
                    x = group_start + threshold_index * bar_width
                    y = bottom - bar_height
                    lines.append(
                        f'<rect data-threshold="{field}" x="{x:.1f}" y="{y:.1f}" '
                        f'width="{bar_width - 2:.1f}" height="{bar_height:.1f}" '
                        f'fill="{color}"/>'
                    )
                    lines.append(
                        f'<text class="bar-value" text-anchor="middle" '
                        f'x="{x + (bar_width - 2) / 2:.1f}" y="{max(top + 10, y - 4):.1f}">'
                        f"{hits}/{row.complete_cells}</text>"
                    )
            lines.append(
                f'<text class="small" text-anchor="middle" x="{center:.1f}" '
                f'y="{bottom + 24}">{escape(_cohort_label(cohort))}</text>'
            )

    legend_x = 745
    for index, (label, _field, color) in enumerate(thresholds):
        x = legend_x + index * 165
        lines.append(f'<rect x="{x}" y="56" width="24" height="16" fill="{color}"/>')
        lines.append(f'<text class="small" x="{x + 32}" y="69">{escape(label)}</text>')
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _scatter_provider(provider: str) -> str:
    return "Local" if provider == "ollama-local" else "Cloud"


def _parameter_scatter_metadata(
    labeled_sources: Sequence[tuple[str | None, LoadedSource]],
) -> dict[tuple[str | None, str], ParameterScatterMetadata]:
    metadata: dict[tuple[str | None, str], ParameterScatterMetadata] = {}
    for cohort, source in labeled_sources:
        for item in source.manifest.models:
            architecture = MODEL_ARCHITECTURES.get(item.model)
            parameter_count = (
                architecture.total_parameters
                if architecture is not None
                else item.parameter_count
            )
            if parameter_count is None or parameter_count <= 0:
                continue
            current = ParameterScatterMetadata(
                display_name=(
                    architecture.display_name
                    if architecture is not None
                    else item.model
                ),
                parameter_count=parameter_count,
                provider=_scatter_provider(source.manifest.provider),
            )
            key = (cohort, item.model)
            previous = metadata.get(key)
            if previous is not None and previous != current:
                raise ValueError(
                    f"report sources disagree on scatter metadata for {item.model} "
                    f"in {_cohort_label(cohort)}"
                )
            metadata[key] = current
    return metadata


def _latest_tutorial_cohort(
    results: Sequence[LabeledResult],
    tutorial: str,
) -> tuple[bool, str | None]:
    selected = tuple(
        dict.fromkeys(
            item.cohort for item in results if item.result.tutorial == tutorial
        )
    )
    if not selected:
        return False, None
    return True, selected[-1]


def _parameter_scatter_points(
    results: Sequence[LabeledResult],
    tutorial: str,
    metadata: dict[tuple[str | None, str], ParameterScatterMetadata],
) -> tuple[str | None, tuple[ParameterScatterPoint, ...], int]:
    found, cohort = _latest_tutorial_cohort(results, tutorial)
    if not found:
        return None, (), 0
    grouped: dict[str, list[SessionResult]] = defaultdict(list)
    for item in results:
        if item.cohort == cohort and item.result.tutorial == tutorial:
            grouped[item.result.model].append(item.result)
    points = []
    missing_parameters = 0
    for model, sessions in grouped.items():
        item_metadata = metadata.get((cohort, model))
        if item_metadata is None:
            missing_parameters += 1
            continue
        points.append(
            ParameterScatterPoint(
                model=model,
                display_name=item_metadata.display_name,
                parameter_count=item_metadata.parameter_count,
                provider=item_metadata.provider,
                milestone_hits=sum(
                    complete
                    for session in sessions
                    for _milestone, complete in session.milestone_results
                ),
                milestone_possible=sum(
                    len(session.milestone_results) for session in sessions
                ),
            )
        )
    return (
        cohort,
        tuple(
            sorted(
                points,
                key=lambda point: (
                    point.parameter_count,
                    point.display_name.casefold(),
                    point.model,
                ),
            )
        ),
        missing_parameters,
    )


def _format_parameter_count(parameter_count: int) -> str:
    divisor, suffix = (
        (1_000_000_000_000, "T")
        if parameter_count >= 1_000_000_000_000
        else (1_000_000_000, "B")
    )
    value = parameter_count / divisor
    formatted = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{formatted}{suffix}"


def _scatter_key_name(display_name: str, maximum_length: int = 38) -> str:
    if len(display_name) <= maximum_length:
        return display_name
    available = maximum_length - 1
    prefix_length = available * 3 // 5
    suffix_length = available - prefix_length
    return f"{display_name[:prefix_length]}…{display_name[-suffix_length:]}"


def _scatter_marker(
    *,
    x: float,
    y: float,
    provider: str,
    color: str,
    size: float,
) -> str:
    if provider == "Local":
        return (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{size:.1f}" '
            f'fill="{color}" stroke="white" stroke-width="2"/>'
        )
    return (
        f'<path d="M {x:.1f} {y - size:.1f} L {x + size:.1f} {y:.1f} '
        f'L {x:.1f} {y + size:.1f} L {x - size:.1f} {y:.1f} Z" '
        f'fill="{color}" stroke="white" stroke-width="2"/>'
    )


def render_parameter_scatter_svg(
    results: Sequence[LabeledResult],
    tutorial: str,
    metadata: dict[tuple[str | None, str], ParameterScatterMetadata],
) -> str:
    width, height = 1400, 790
    left, right, top, bottom = 100, 1340, 95, 500
    cohort, points, missing_parameters = _parameter_scatter_points(
        results,
        tutorial,
        metadata,
    )
    cohort_label = _cohort_label(cohort)
    title = f"{tutorial.title()}: model size vs milestone completion ({cohort_label})"
    lines = _svg_start(width, height, title)
    lines.insert(
        2,
        ".axis{stroke:#425466;stroke-width:2}"
        ".point-number{font-family:sans-serif;font-size:9px;font-weight:700;fill:white}"
        ".key{font-family:sans-serif;font-size:11px;fill:#17202a}",
    )
    lines.append(
        f'<text class="small" x="24" y="52">Latest applicable cohort: '
        f"{escape(cohort_label)} · completed milestone checks / possible milestone checks"
        "</text>"
    )
    if not points:
        lines.append(
            '<text class="label" x="24" y="82">'
            "No models with known positive parameter counts were available.</text>"
        )
        lines.append("</svg>")
        return "\n".join(lines) + "\n"

    minimum = min(point.parameter_count for point in points)
    maximum = max(point.parameter_count for point in points)
    if minimum == maximum:
        log_min = math.log10(minimum / 2)
        log_max = math.log10(maximum * 2)
    else:
        log_min = math.log10(minimum / 1.35)
        log_max = math.log10(maximum * 1.35)

    def x_position(parameter_count: int) -> float:
        fraction = (math.log10(parameter_count) - log_min) / (log_max - log_min)
        return left + (right - left) * fraction

    def y_position(rate: float) -> float:
        return bottom - (bottom - top) * rate

    for percentage in range(0, 101, 20):
        y = y_position(percentage / 100)
        lines.append(
            f'<line class="grid" x1="{left}" y1="{y:.1f}" '
            f'x2="{right}" y2="{y:.1f}"/>'
        )
        lines.append(
            f'<text class="small" text-anchor="end" x="{left - 12}" '
            f'y="{y + 4:.1f}">{percentage}%</text>'
        )
    tick_counts = (
        1_000_000_000,
        3_000_000_000,
        10_000_000_000,
        30_000_000_000,
        100_000_000_000,
        300_000_000_000,
        1_000_000_000_000,
        3_000_000_000_000,
    )
    for parameter_count in tick_counts:
        log_count = math.log10(parameter_count)
        if not log_min <= log_count <= log_max:
            continue
        x = x_position(parameter_count)
        lines.append(
            f'<line class="grid" x1="{x:.1f}" y1="{top}" '
            f'x2="{x:.1f}" y2="{bottom}"/>'
        )
        lines.append(
            f'<text class="small" text-anchor="middle" x="{x:.1f}" '
            f'y="{bottom + 24}">{_format_parameter_count(parameter_count)}</text>'
        )
    lines.extend(
        (
            f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{bottom}"/>',
            f'<line class="axis" x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}"/>',
            (
                f'<text class="label" text-anchor="middle" '
                f'x="{(left + right) / 2:.1f}" y="{bottom + 52}">'
                "Total architecture parameters (log scale)</text>"
            ),
            (
                f'<text class="label" text-anchor="middle" '
                f'transform="translate(24 {(top + bottom) / 2:.1f}) rotate(-90)">'
                "Milestone completion rate</text>"
            ),
        )
    )

    collision_groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, point in enumerate(points):
        collision_groups[
            (point.parameter_count, round(point.milestone_rate * 1_000_000))
        ].append(index)
    offsets = (
        (0, 0),
        (-9, -7),
        (9, 7),
        (-9, 7),
        (9, -7),
        (0, 12),
        (0, -12),
    )
    point_offsets: dict[int, tuple[int, int]] = {}
    for indexes in collision_groups.values():
        for collision_index, point_index in enumerate(indexes):
            point_offsets[point_index] = offsets[collision_index % len(offsets)]

    for index, point in enumerate(points, start=1):
        offset_x, offset_y = point_offsets[index - 1]
        x = x_position(point.parameter_count) + offset_x
        y = y_position(point.milestone_rate) + offset_y
        color = SCATTER_PROVIDER_COLORS[point.provider]
        lines.append(
            f'<g data-model="{escape(point.model)}" '
            f'data-parameters="{point.parameter_count}" '
            f'data-milestone-rate="{point.milestone_rate:.6f}" '
            f'data-cohort="{escape(cohort_label)}" '
            f'data-provider="{escape(point.provider)}">'
        )
        lines.append(
            f"<title>{escape(point.display_name)}: "
            f"{_format_parameter_count(point.parameter_count)}, "
            f"{point.milestone_hits}/{point.milestone_possible} "
            f"({point.milestone_rate:.1%})</title>"
        )
        lines.append(
            _scatter_marker(
                x=x,
                y=y,
                provider=point.provider,
                color=color,
                size=9,
            )
        )
        lines.append(
            f'<text class="point-number" text-anchor="middle" '
            f'x="{x:.1f}" y="{y + 3.3:.1f}">{index}</text>'
        )
        lines.append("</g>")

    lines.append('<text class="label" x="24" y="574">Model key</text>')
    rows_per_column = 7
    column_count = math.ceil(len(points) / rows_per_column)
    column_width = (width - 48) / column_count
    for index, point in enumerate(points, start=1):
        column = (index - 1) // rows_per_column
        row = (index - 1) % rows_per_column
        x = 24 + column * column_width
        y = 604 + row * 24
        color = SCATTER_PROVIDER_COLORS[point.provider]
        lines.append(
            _scatter_marker(
                x=x + 8,
                y=y - 4,
                provider=point.provider,
                color=color,
                size=6,
            )
        )
        lines.append(
            f'<text class="key" x="{x + 20}" y="{y}">{index}. '
            f"{escape(_scatter_key_name(point.display_name))} · "
            f"{_format_parameter_count(point.parameter_count)} · "
            f"{point.milestone_rate:.1%}</text>"
        )
    legend_x = 1110
    for index, provider in enumerate(("Local", "Cloud")):
        x = legend_x + index * 115
        color = SCATTER_PROVIDER_COLORS[provider]
        lines.append(
            _scatter_marker(
                x=x,
                y=54,
                provider=provider,
                color=color,
                size=7,
            )
        )
        lines.append(f'<text class="small" x="{x + 12}" y="58">{provider}</text>')
    if missing_parameters:
        lines.append(
            f'<text class="small" x="24" y="{height - 12}">'
            f"{missing_parameters} model(s) omitted because no positive parameter count "
            "was available.</text>"
        )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _kimi_family_rows(
    rows: Sequence[ModelRow],
    latency: LatencyAnalysis | None,
) -> tuple[KimiFamilyRow, ...]:
    grouped: dict[str, list[ModelRow]] = defaultdict(list)
    for row in rows:
        if row.model in KIMI_FAMILY_MODELS:
            grouped[row.model].append(row)
    latency_by_model = (
        {row.model: row for row in latency.aggregate_model_rows}
        if latency is not None
        else {}
    )
    family_rows = []
    for model, model_rows in grouped.items():
        _rank, display_name, provider = KIMI_FAMILY_MODELS[model]
        latency_row = latency_by_model.get(model)
        family_rows.append(
            KimiFamilyRow(
                model=model,
                display_name=display_name,
                provider=provider,
                sessions=sum(row.sessions for row in model_rows),
                passes=sum(row.passes for row in model_rows),
                milestone_hits=sum(row.milestone_hits for row in model_rows),
                milestone_possible=sum(row.milestone_possible for row in model_rows),
                median_latency_seconds=(
                    latency_row.median_seconds if latency_row is not None else None
                ),
                total_tokens=sum(row.total_tokens for row in model_rows),
            )
        )
    return tuple(
        sorted(
            family_rows,
            key=lambda row: KIMI_FAMILY_MODELS[row.model][0],
        )
    )


def render_kimi_family_svg(rows: Sequence[KimiFamilyRow]) -> str:
    width, height = 1380, 700
    left, right, top, bottom = 90, 1335, 135, 510
    lines = _svg_start(width, height, "Kimi family gameplay comparison")
    lines.insert(
        2,
        ".axis{stroke:#425466;stroke-width:2}"
        ".value{font-family:sans-serif;font-size:10px;font-weight:700;fill:#17202a}",
    )
    if len(rows) < 2:
        lines.append(
            '<text class="label" x="24" y="70">'
            "At least two Kimi family models are required.</text>"
        )
        lines.append("</svg>")
        return "\n".join(lines) + "\n"

    lines.append(
        '<text class="small" x="24" y="52">'
        "All retained v1–v4 sessions · lower latency is better; higher capability and "
        "token efficiency are better.</text>"
    )
    lines.append(
        '<text class="small" x="24" y="72">'
        "K3 used OpenRouter; K2.5–K2.7 used Ollama Cloud, so latency includes provider "
        "infrastructure and is not a pure model comparison.</text>"
    )
    panel_gap = 30
    panel_width = (right - left - panel_gap * 2) / 3
    metrics: tuple[
        tuple[str, tuple[tuple[str, str, tuple[float, ...]], ...], float, str],
        ...,
    ] = (
        (
            "Capability",
            (
                (
                    "Session passes",
                    "#1b9e77",
                    tuple(row.pass_rate * 100 for row in rows),
                ),
                (
                    "Milestones",
                    "#7570b3",
                    tuple(row.milestone_rate * 100 for row in rows),
                ),
            ),
            100,
            "%",
        ),
        (
            "Median latency",
            (
                (
                    "Seconds / decision",
                    "#d95f02",
                    tuple(
                        row.median_latency_seconds or 0
                        for row in rows
                    ),
                ),
            ),
            max((row.median_latency_seconds or 0) for row in rows) * 1.15,
            "s",
        ),
        (
            "Token efficiency",
            (
                (
                    "Milestones / M tokens",
                    "#1f78b4",
                    tuple(row.token_efficiency for row in rows),
                ),
            ),
            max(row.token_efficiency for row in rows) * 1.15,
            "",
        ),
    )
    plot_height = bottom - top
    for panel_index, (title, series, maximum, suffix) in enumerate(metrics):
        panel_left = left + panel_index * (panel_width + panel_gap)
        panel_right = panel_left + panel_width
        safe_maximum = maximum if maximum > 0 else 1
        lines.append(
            f'<text class="label" text-anchor="middle" '
            f'x="{(panel_left + panel_right) / 2:.1f}" y="{top - 22}">'
            f"{escape(title)}</text>"
        )
        for step in range(0, 6):
            value = safe_maximum * step / 5
            y = bottom - plot_height * step / 5
            label = (
                f"{value:.0f}{suffix}"
                if suffix or value >= 10
                else f"{value:.1f}"
            )
            lines.append(
                f'<line class="grid" x1="{panel_left:.1f}" y1="{y:.1f}" '
                f'x2="{panel_right:.1f}" y2="{y:.1f}"/>'
            )
            lines.append(
                f'<text class="small" text-anchor="end" x="{panel_left - 8:.1f}" '
                f'y="{y + 4:.1f}">{label}</text>'
            )
        lines.extend(
            (
                f'<line class="axis" x1="{panel_left:.1f}" y1="{top}" '
                f'x2="{panel_left:.1f}" y2="{bottom}"/>',
                f'<line class="axis" x1="{panel_left:.1f}" y1="{bottom}" '
                f'x2="{panel_right:.1f}" y2="{bottom}"/>',
            )
        )
        x_step = panel_width / max(1, len(rows) - 1)
        for series_name, color, values in series:
            points = tuple(
                (
                    panel_left + index * x_step,
                    bottom - plot_height * value / safe_maximum,
                    value,
                )
                for index, value in enumerate(values)
            )
            for previous, current in zip(points, points[1:], strict=False):
                lines.append(
                    f'<line x1="{previous[0]:.1f}" y1="{previous[1]:.1f}" '
                    f'x2="{current[0]:.1f}" y2="{current[1]:.1f}" '
                    f'stroke="{color}" stroke-width="3"/>'
                )
            for row, (x, y, value) in zip(rows, points, strict=True):
                formatted = (
                    f"{value:.1f}{suffix}"
                    if suffix or value < 10
                    else f"{value:.0f}"
                )
                lines.append(
                    f'<g data-model="{escape(row.model)}" '
                    f'data-series="{escape(series_name)}">'
                )
                lines.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}" '
                    'stroke="white" stroke-width="2"/>'
                )
                lines.append(
                    f'<text class="value" text-anchor="middle" x="{x:.1f}" '
                    f'y="{max(top + 11, y - 10):.1f}">{formatted}</text>'
                )
                lines.append("</g>")
        for index, row in enumerate(rows):
            x = panel_left + index * x_step
            lines.append(
                f'<text class="small" text-anchor="middle" x="{x:.1f}" '
                f'y="{bottom + 24}">{escape(row.display_name)}</text>'
            )
        legend_x = panel_left
        for series_index, (series_name, color, _values) in enumerate(series):
            x = legend_x + series_index * 150
            lines.append(
                f'<line x1="{x:.1f}" y1="{top - 52}" x2="{x + 24:.1f}" '
                f'y2="{top - 52}" stroke="{color}" stroke-width="3"/>'
            )
            lines.append(
                f'<text class="small" x="{x + 31:.1f}" y="{top - 48}">'
                f"{escape(series_name)}</text>"
            )

    lines.append(
        '<text class="small" x="24" y="575">'
        "¹ Kimi K2.7 Code is a code-specialized branch, not a direct general-purpose "
        "successor. Each point aggregates the supplied model’s retained sessions.</text>"
    )
    for index, row in enumerate(rows):
        x = 24 + index * 330
        lines.append(
            f'<text class="small" x="{x}" y="610">{escape(row.display_name)} · '
            f"{escape(row.provider)} · {row.passes}/{row.sessions} passes · "
            f"{row.milestone_hits}/{row.milestone_possible} milestones</text>"
        )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _frontier_cost_rows(rows: Sequence[ModelRow]) -> tuple[FrontierCostRow, ...]:
    grouped: dict[str, list[ModelRow]] = defaultdict(list)
    for row in rows:
        if row.model in FRONTIER_PRICING and row.estimated_cost_usd:
            grouped[row.model].append(row)
    cost_rows = (
        FrontierCostRow(
            model=model,
            display_name=FRONTIER_PRICING[model].display_name,
            sessions=sum(row.sessions for row in model_rows),
            passes=sum(row.passes for row in model_rows),
            milestone_hits=sum(row.milestone_hits for row in model_rows),
            milestone_possible=sum(row.milestone_possible for row in model_rows),
            estimated_cost_usd=sum(row.estimated_cost_usd for row in model_rows),
        )
        for model, model_rows in grouped.items()
    )
    return tuple(
        sorted(
            cost_rows,
            key=lambda row: (row.display_name.casefold(), row.display_name),
        )
    )


def _frontier_cost_table(rows: Sequence[FrontierCostRow]) -> str:
    lines = [
        "| Model | Passes | Milestones | Estimated cost | "
        "Passes/$ | Milestones/$ |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.display_name}` | {row.passes}/{row.sessions} "
            f"({row.pass_rate:.1%}) | "
            f"{row.milestone_hits}/{row.milestone_possible} | "
            f"${row.estimated_cost_usd:.2f} | {row.passes_per_dollar:.2f} | "
            f"{row.milestones_per_dollar:.2f} |"
        )
    return "\n".join(lines)


def _frontier_ratio(
    rows: Sequence[ModelRow],
    *,
    cohorts: frozenset[str] | None = None,
) -> float | None:
    selected = tuple(
        row
        for row in rows
        if cohorts is None or row.cohort in cohorts
    )
    aggregated = {row.model: row for row in _frontier_cost_rows(selected)}
    luna = aggregated.get("openai/gpt-5.6-luna")
    opus = aggregated.get("anthropic/claude-opus-5")
    if (
        luna is None
        or opus is None
        or not luna.passes
        or not opus.passes
        or not luna.estimated_cost_usd
        or not opus.estimated_cost_usd
    ):
        return None
    return luna.passes_per_dollar / opus.passes_per_dollar


def _frontier_cost_section(
    rows: Sequence[ModelRow],
    chart_path: str | None,
) -> str:
    cost_rows = _frontier_cost_rows(rows)
    if not cost_rows:
        return ""
    by_model = {row.model: row for row in cost_rows}
    luna = by_model.get("openai/gpt-5.6-luna")
    opus = by_model.get("anthropic/claude-opus-5")
    recommendation = ""
    if luna is not None and opus is not None:
        overall_ratio = _frontier_ratio(rows)
        recent_ratio = _frontier_ratio(rows, cohorts=frozenset(("v2", "v4")))
        ratio_text = (
            f" Across all retained frontier runs, Luna delivered "
            f"**{overall_ratio:.1f}×** as many authoritative passes per dollar"
            if overall_ratio is not None
            else ""
        )
        if recent_ratio is not None:
            ratio_text += (
                f"; in the v2 and v4 cohorts the observed ratio was "
                f"**{recent_ratio:.1f}×**. That supports an operational summary of "
                "**about 25× better per dollar** across the current comparison."
            )
        else:
            ratio_text += "."
        recommendation = (
            f"**Recommendation:** use **GPT-5.6 Luna** when a hosted frontier model is "
            f"wanted, and avoid **Claude Opus 5** for routine Bunnyland play. Luna "
            f"passed {luna.passes}/{luna.sessions} sessions for an estimated "
            f"${luna.estimated_cost_usd:.2f}; Opus passed {opus.passes}/{opus.sessions} "
            f"for ${opus.estimated_cost_usd:.2f}.{ratio_text} Opus may still make sense "
            "for work outside this gameplay benchmark, but its cost/performance ratio "
            "here is poor."
        )
    chart = (
        f"\n\n![frontier API cost performance]({chart_path})"
        if chart_path is not None
        else ""
    )
    return (
        "## Frontier API cost and recommendation\n\n"
        "These four models were breadth-tested with two sessions per applicable "
        "model/version/tutorial cell and are not classified by the five-session "
        "possible/likely/consistent rubric. Costs are "
        "reconstructed from retained OpenRouter usage details and the model list prices "
        "for [Claude Opus 5](https://openrouter.ai/anthropic/claude-opus-5), "
        "[Claude Haiku 4.5](https://openrouter.ai/anthropic/claude-haiku-4.5), "
        "[GPT-5.6 Luna](https://openrouter.ai/openai/gpt-5.6-luna), and "
        "[GPT-5.6 Sol](https://openrouter.ai/openai/gpt-5.6-sol). They include observed "
        "cache reads and writes; they are estimates rather than invoice records.\n\n"
        f"{recommendation}\n\n"
        f"{_frontier_cost_table(cost_rows)}"
        f"{chart}"
    )


def render_frontier_cost_svg(rows: Sequence[FrontierCostRow]) -> str:
    width, height = 1100, 650
    left, right, top, bottom = 100, 1040, 90, 440
    lines = _svg_start(width, height, "Frontier API cost versus authoritative pass rate")
    lines.insert(
        2,
        ".axis{stroke:#425466;stroke-width:2}"
        ".point-number{font-family:sans-serif;font-size:11px;font-weight:700;fill:white}"
        ".key{font-family:sans-serif;font-size:12px;fill:#17202a}",
    )
    lines.append(
        '<text class="small" x="24" y="52">All retained v1–v4 frontier sessions · '
        "estimated billed cost uses observed prompt caching</text>"
    )
    if not rows:
        lines.append('<text class="label" x="24" y="82">No priced frontier rows.</text>')
        lines.append("</svg>")
        return "\n".join(lines) + "\n"
    maximum = max(row.estimated_cost_usd for row in rows)
    padded_maximum = maximum * 1.08
    magnitude = 10 ** math.floor(math.log10(padded_maximum))
    normalized_maximum = padded_maximum / magnitude
    nice_factor = (
        1
        if normalized_maximum <= 1
        else 2
        if normalized_maximum <= 2
        else 5
        if normalized_maximum <= 5
        else 10
    )
    axis_maximum = nice_factor * magnitude

    def x_position(cost: float) -> float:
        return left + (right - left) * cost / axis_maximum

    def y_position(rate: float) -> float:
        return bottom - (bottom - top) * rate

    for percentage in range(0, 101, 20):
        y = y_position(percentage / 100)
        lines.append(
            f'<line class="grid" x1="{left}" y1="{y:.1f}" '
            f'x2="{right}" y2="{y:.1f}"/>'
        )
        lines.append(
            f'<text class="small" text-anchor="end" x="{left - 12}" '
            f'y="{y + 4:.1f}">{percentage}%</text>'
        )
    for index in range(6):
        cost = axis_maximum * index / 5
        x = x_position(cost)
        cost_label = f"${cost:.2f}" if axis_maximum < 10 else f"${cost:g}"
        lines.append(
            f'<line class="grid" x1="{x:.1f}" y1="{top}" '
            f'x2="{x:.1f}" y2="{bottom}"/>'
        )
        lines.append(
            f'<text class="small" text-anchor="middle" x="{x:.1f}" '
            f'y="{bottom + 24}">{cost_label}</text>'
        )
    lines.extend(
        (
            f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{bottom}"/>',
            f'<line class="axis" x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}"/>',
            (
                f'<text class="label" text-anchor="middle" '
                f'x="{(left + right) / 2:.1f}" y="{bottom + 52}">'
                "Estimated cost for retained sessions (USD, linear scale)</text>"
            ),
            (
                f'<text class="label" text-anchor="middle" '
                f'transform="translate(24 {(top + bottom) / 2:.1f}) rotate(-90)">'
                "Authoritative session pass rate</text>"
            ),
        )
    )
    for index, row in enumerate(rows, start=1):
        x = x_position(row.estimated_cost_usd)
        y = y_position(row.pass_rate)
        color = COLORBREWER_DARK2_4[(index - 1) % len(COLORBREWER_DARK2_4)]
        outline = ' stroke="#17202a" stroke-width="4"' if "Luna" in row.display_name else ""
        lines.append(
            f'<g data-model="{escape(row.model)}" '
            f'data-cost="{row.estimated_cost_usd:.6f}" '
            f'data-pass-rate="{row.pass_rate:.6f}">'
        )
        lines.append(
            f"<title>{escape(row.display_name)}: ${row.estimated_cost_usd:.2f}, "
            f"{row.passes}/{row.sessions} ({row.pass_rate:.1%}), "
            f"{row.passes_per_dollar:.2f} passes/$</title>"
        )
        lines.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="13" fill="{color}"{outline}/>'
        )
        lines.append(
            f'<text class="point-number" text-anchor="middle" x="{x:.1f}" '
            f'y="{y + 4:.1f}">{index}</text>'
        )
        lines.append("</g>")
    lines.append('<text class="label" x="24" y="540">Model key</text>')
    for index, row in enumerate(rows, start=1):
        column = (index - 1) % 2
        table_row = (index - 1) // 2
        x = 32 + column * 530
        y = 575 + table_row * 28
        color = COLORBREWER_DARK2_4[(index - 1) % len(COLORBREWER_DARK2_4)]
        suffix = " · recommended" if "Luna" in row.display_name else ""
        lines.append(f'<circle cx="{x + 8}" cy="{y - 4}" r="7" fill="{color}"/>')
        lines.append(
            f'<text class="key" x="{x + 22}" y="{y}">{index}. '
            f"{escape(row.display_name)} · ${row.estimated_cost_usd:.2f} · "
            f"{row.passes}/{row.sessions}{escape(suffix)}</text>"
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


def _acceptance_policy_table() -> str:
    lines = [
        "| Tutorial | Cohort expectation | Strong-model expectation | Role |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| `{policy.tutorial}` | {policy.cohort_expectation} | "
        f"{policy.strong_model_expectation} | {policy.role} |"
        for policy in TUTORIAL_ACCEPTANCE_POLICIES
    )
    return "\n".join(lines)


def _milestone_bottleneck_rows(
    results: Sequence[LabeledResult],
) -> tuple[MilestoneBottleneckRow, ...]:
    counts: dict[tuple[str | None, str, str], list[bool]] = defaultdict(list)
    cohort_rank = {
        cohort: index
        for index, cohort in enumerate(
            dict.fromkeys(item.cohort for item in results)
        )
    }
    tutorial_rank = {tutorial: index for index, tutorial in enumerate(TUTORIAL_MAPS)}
    for item in results:
        for milestone, complete in item.result.milestone_results:
            counts[(item.cohort, item.result.tutorial, milestone)].append(complete)
    grouped: dict[tuple[str | None, str], list[MilestoneBottleneckRow]] = defaultdict(list)
    for (cohort, tutorial, milestone), completions in counts.items():
        grouped[(cohort, tutorial)].append(
            MilestoneBottleneckRow(
                cohort=cohort,
                tutorial=tutorial,
                milestone=milestone,
                completions=sum(completions),
                sessions=len(completions),
            )
        )
    selected = []
    for rows in grouped.values():
        selected.extend(
            sorted(
                rows,
                key=lambda row: (
                    row.completions / row.sessions,
                    row.milestone,
                ),
            )[:3]
        )
    return tuple(
        sorted(
            selected,
            key=lambda row: (
                tutorial_rank.get(row.tutorial, len(tutorial_rank)),
                row.tutorial,
                cohort_rank[row.cohort],
                row.completions / row.sessions,
                row.milestone,
            ),
        )
    )


def _milestone_bottleneck_table(rows: Sequence[MilestoneBottleneckRow]) -> str:
    lines = [
        "| Tutorial | Cohort | Milestone | Completed sessions | Completion rate |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.tutorial}` | `{row.cohort}` | `{row.milestone}` | "
            f"{row.completions}/{row.sessions} | {row.completions / row.sessions:.1%} |"
        )
    return "\n".join(lines)


def _behavior_rows(results: Sequence[LabeledResult]) -> tuple[BehaviorRow, ...]:
    grouped: dict[tuple[str | None, str], list[SessionResult]] = defaultdict(list)
    cohort_rank = {
        cohort: index
        for index, cohort in enumerate(
            dict.fromkeys(item.cohort for item in results)
        )
    }
    tutorial_rank = {tutorial: index for index, tutorial in enumerate(TUTORIAL_MAPS)}
    for item in results:
        grouped[(item.cohort, item.result.tutorial)].append(item.result)
    rows = (
        BehaviorRow(
            cohort=cohort,
            tutorial=tutorial,
            passes=sum(result.passed for result in sessions),
            sessions=len(sessions),
            valid_actions=sum(result.valid_actions for result in sessions),
            rejected_actions=sum(result.rejected_actions for result in sessions),
            recovered_rejections=sum(
                result.recovered_rejections for result in sessions
            ),
        )
        for (cohort, tutorial), sessions in grouped.items()
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


def _behavior_table(rows: Sequence[BehaviorRow]) -> str:
    lines = [
        "| Tutorial | Cohort | Pass rate | Valid actions | Rejected actions | "
        "Action validity | Rejection recovery |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        recovery = (
            f"{row.recovered_rejections}/{row.rejected_actions} "
            f"({row.recovery:.1%})"
            if row.rejected_actions
            else "—"
        )
        lines.append(
            f"| `{row.tutorial}` | `{row.cohort}` | "
            f"{row.passes}/{row.sessions} ({row.passes / row.sessions:.1%}) | "
            f"{row.valid_actions} | {row.rejected_actions} | {row.validity:.1%} | "
            f"{recovery} |"
        )
    return "\n".join(lines)


def _quantization_label(model: str, manifest_label: str | None) -> str:
    if model.endswith(":Q8_0"):
        return "Q8_0"
    if model.endswith(":UD-Q6_K"):
        return "UD-Q6_K"
    if model == "qwen3.6:35b-a3b":
        return manifest_label or "Q4_K_M"
    return manifest_label or "unknown"


def _quantization_rows(
    results: Sequence[LabeledResult],
    sources: Sequence[tuple[str | None, LoadedSource]],
) -> tuple[QuantizationRow, ...]:
    qwen_models = {
        "qwen3.6:35b-a3b",
        "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K",
        "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:Q8_0",
    }
    labels: dict[tuple[str | None, str], str] = {}
    for cohort, source in sources:
        for metadata in source.manifest.models:
            if metadata.model in qwen_models:
                labels[(cohort, metadata.model)] = _quantization_label(
                    metadata.model,
                    metadata.quantization,
                )
    grouped: dict[tuple[str | None, str, str], list[SessionResult]] = defaultdict(list)
    cohort_rank = {
        cohort: index
        for index, cohort in enumerate(
            dict.fromkeys(item.cohort for item in results)
        )
    }
    tutorial_rank = {tutorial: index for index, tutorial in enumerate(TUTORIAL_MAPS)}
    for item in results:
        if item.result.model in qwen_models:
            grouped[
                (item.cohort, item.result.tutorial, item.result.model)
            ].append(item.result)
    rows = (
        QuantizationRow(
            cohort=cohort,
            tutorial=tutorial,
            model=model,
            quantization=labels.get(
                (cohort, model),
                _quantization_label(model, None),
            ),
            passes=sum(result.passed for result in sessions),
            sessions=len(sessions),
        )
        for (cohort, tutorial, model), sessions in grouped.items()
    )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                tutorial_rank.get(row.tutorial, len(tutorial_rank)),
                row.tutorial,
                cohort_rank[row.cohort],
                row.quantization,
                row.model,
            ),
        )
    )


def _quantization_table(rows: Sequence[QuantizationRow]) -> str:
    lines = [
        "| Tutorial | Cohort | Quantization | Model | Passes |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.tutorial}` | `{row.cohort}` | `{row.quantization}` | "
            f"`{row.model}` | {row.passes}/{row.sessions} |"
        )
    return "\n".join(lines)


def _token_latency_cell(value: float | None) -> str:
    return "—" if value is None else f"{value:.4f}"


def _latency_section(analysis: LatencyAnalysis | None) -> str:
    if analysis is None:
        return "No retained turn-latency evidence was available."
    overall_rows = (analysis.overall, *analysis.cohort_rows)
    lines = [
        f"Across **{analysis.overall.decisions:,} scored decisions**, median end-to-end "
        f"decision latency was **{analysis.overall.median_seconds:.2f}s**, p95 was "
        f"**{analysis.overall.p95_seconds:.2f}s**, p99 was "
        f"**{analysis.overall.p99_seconds:.2f}s**, and the maximum was "
        f"**{analysis.overall.maximum_seconds:.2f}s**.",
        "",
        "Token-normalized figures divide complete end-to-end decision latency—including "
        "prompt evaluation, provider overhead, retries, and generation—by output tokens. "
        "They are not pure decoder throughput.",
        "",
        "### Overall and cohort latency",
        "",
        "| Scope | Provider(s) | Decisions | Median sec | P95 sec | P99 sec | Max sec | "
        "Output tokens/sec |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for index, row in enumerate(overall_rows):
        scope = "Overall" if index == 0 else row.cohort or "Unlabeled"
        lines.append(
            f"| `{scope}` | `{row.provider}` | {row.decisions:,} | "
            f"{row.median_seconds:.2f} | {row.p95_seconds:.2f} | "
            f"{row.p99_seconds:.2f} | {row.maximum_seconds:.2f} | "
            f"{_token_latency_cell(row.output_tokens_per_second)} |"
        )
    lines.extend(
        (
            "",
            "### Per-model latency",
            "",
            "| Model | Cohort | Provider | Decisions | Median sec | P95 sec | P99 sec | "
            "Output tokens/sec |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        )
    )
    for row in analysis.model_rows:
        lines.append(
            f"| `{row.model}` | `{row.cohort or 'Unlabeled'}` | `{row.provider}` | "
            f"{row.decisions:,} | {row.median_seconds:.2f} | {row.p95_seconds:.2f} | "
            f"{row.p99_seconds:.2f} | "
            f"{_token_latency_cell(row.output_tokens_per_second)} |"
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


def _change_breadth_rows(
    model_rows: Sequence[CohortDeltaRow],
) -> tuple[ChangeBreadthRow, ...]:
    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in model_rows:
        delta = row.delta_percentage_points
        if delta is not None:
            grouped[(row.before_cohort, row.after_cohort, row.tutorial)].append(delta)
    tutorial_rank = {name: index for index, name in enumerate(TUTORIAL_MAPS)}
    return tuple(
        ChangeBreadthRow(
            before_cohort=before,
            after_cohort=after,
            tutorial=tutorial,
            improved_models=sum(delta > 0 for delta in deltas),
            tied_models=sum(delta == 0 for delta in deltas),
            regressed_models=sum(delta < 0 for delta in deltas),
        )
        for (before, after, tutorial), deltas in sorted(
            grouped.items(),
            key=lambda item: (
                tutorial_rank.get(item[0][2], len(tutorial_rank)),
                item[0][2],
                item[0][0],
                item[0][1],
            ),
        )
    )


def _change_breadth_table(rows: Sequence[ChangeBreadthRow]) -> str:
    if not rows:
        return "At least two cohorts with shared model/tutorial cells are required."
    lines = [
        "| Tutorial | Transition | Shared models | Improved | Tied | Regressed |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.tutorial}` | `{row.before_cohort} → {row.after_cohort}` | "
            f"{row.shared_models} | {row.improved_models} | {row.tied_models} | "
            f"{row.regressed_models} |"
        )
    return "\n".join(lines)


def _coverage_analysis(
    results: Sequence[LabeledResult],
    sources: Sequence[tuple[str | None, LoadedSource]],
) -> CoverageAnalysis | None:
    cohort_order = tuple(
        dict.fromkeys(cohort for cohort, _source in sources if cohort is not None)
    )
    if not cohort_order:
        return None
    reference_cohort = cohort_order[-1]
    reference_sources = tuple(
        source for cohort, source in sources if cohort == reference_cohort
    )
    reference_models = tuple(
        dict.fromkeys(
            model
            for source in reference_sources
            for model in (
                source.selected_models
                or tuple(metadata.model for metadata in source.manifest.models)
            )
        )
    )
    if not reference_models:
        return None
    target_sessions = max(
        source.manifest.sessions_per_model_tutorial for source in reference_sources
    )
    tutorial_order = tuple(TUTORIAL_MAPS)
    cohort_tutorials = {
        cohort: tuple(
            tutorial
            for tutorial in tutorial_order
            if any(
                source_cohort == cohort and tutorial in source.manifest.tutorials
                for source_cohort, source in sources
            )
        )
        for cohort in cohort_order
    }
    counts = Counter(
        (item.cohort, item.result.model, item.result.tutorial)
        for item in results
        if item.cohort is not None
    )
    summary_rows: list[CoverageSummaryRow] = []
    gap_rows: list[CoverageGapRow] = []
    cohort_rank = {cohort: index for index, cohort in enumerate(cohort_order)}
    for cohort in cohort_order:
        tutorials = cohort_tutorials[cohort]
        observed_sessions = 0
        complete_cells = 0
        partial_cells = 0
        missing_cells = 0
        for model in reference_models:
            model_observed = 0
            incomplete_tutorials: list[str] = []
            for tutorial in tutorials:
                observed = min(counts[cohort, model, tutorial], target_sessions)
                observed_sessions += observed
                model_observed += observed
                if observed >= target_sessions:
                    complete_cells += 1
                elif observed:
                    partial_cells += 1
                    incomplete_tutorials.append(
                        f"{tutorial} {observed}/{target_sessions}"
                    )
                else:
                    missing_cells += 1
                    incomplete_tutorials.append(f"{tutorial} 0/{target_sessions}")
            model_expected = len(tutorials) * target_sessions
            if incomplete_tutorials:
                gap_rows.append(
                    CoverageGapRow(
                        cohort=cohort,
                        model=model,
                        observed_sessions=model_observed,
                        expected_sessions=model_expected,
                        missing_sessions=model_expected - model_observed,
                        incomplete_tutorials=tuple(incomplete_tutorials),
                    )
                )
        expected_sessions = len(reference_models) * len(tutorials) * target_sessions
        summary_rows.append(
            CoverageSummaryRow(
                cohort=cohort,
                tutorials=tutorials,
                observed_sessions=observed_sessions,
                expected_sessions=expected_sessions,
                complete_cells=complete_cells,
                partial_cells=partial_cells,
                missing_cells=missing_cells,
                not_applicable_cells=len(reference_models)
                * (len(tutorial_order) - len(tutorials)),
            )
        )
    gap_rows.sort(
        key=lambda row: (
            row.model.casefold(),
            row.model,
            cohort_rank[row.cohort],
        )
    )
    return CoverageAnalysis(
        reference_cohort=reference_cohort,
        reference_models=len(reference_models),
        target_sessions=target_sessions,
        summary_rows=tuple(summary_rows),
        gap_rows=tuple(gap_rows),
    )


def _coverage_gap_section(analysis: CoverageAnalysis | None) -> str:
    if analysis is None:
        return ""
    lines = [
        "## Data coverage gaps",
        "",
        f"Coverage uses the **{analysis.reference_models} exact model identifiers** in "
        f"the final supplied cohort, `{analysis.reference_cohort}`, as the reference "
        f"roster and targets **{analysis.target_sessions} sessions per in-scope cell**. "
        "Identifiers are not aliased across model names. Tutorials absent from a cohort's "
        "manifest are **not applicable (N/A)** rather than missing.",
        "",
        "### Cohort coverage",
        "",
        "| Cohort | In-scope tutorials | Session coverage | Complete cells | "
        "Partial cells | Missing cells | N/A cells |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in analysis.summary_rows:
        tutorials = ", ".join(f"`{tutorial}`" for tutorial in row.tutorials) or "—"
        lines.append(
            f"| `{row.cohort}` | {tutorials} | "
            f"{row.observed_sessions}/{row.expected_sessions} | "
            f"{row.complete_cells} | {row.partial_cells} | {row.missing_cells} | "
            f"{row.not_applicable_cells} |"
        )
    lines.extend(
        (
            "",
            "### Missing and partial in-scope coverage",
            "",
        )
    )
    if not analysis.gap_rows:
        lines.append("No in-scope coverage gaps remain.")
        return "\n".join(lines)
    lines.extend(
        (
            "| Model | Cohort | Coverage | Missing sessions | Incomplete tutorials |",
            "| --- | --- | ---: | ---: | --- |",
        )
    )
    for row in analysis.gap_rows:
        lines.append(
            f"| `{row.model}` | `{row.cohort}` | "
            f"{row.observed_sessions}/{row.expected_sessions} | "
            f"{row.missing_sessions} | "
            f"{', '.join(f'`{tutorial}`' for tutorial in row.incomplete_tutorials)} |"
        )
    return "\n".join(lines)


def _token_table(rows: Sequence[ModelRow]) -> str:
    cohort_mode = any(row.cohort is not None for row in rows)
    lines = (
        [
            "| Cohort | Model | Input tokens | Output tokens | Total tokens | "
            "Median sec/turn | Milestones/M tokens |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        if cohort_mode
        else [
            "| Model | Input tokens | Output tokens | Total tokens | "
            "Median sec/turn | Milestones/M tokens |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        prefix = f"| `{row.cohort}` | `{row.model}`" if cohort_mode else f"| `{row.model}`"
        lines.append(
            f"{prefix} | {row.input_tokens:,} | {row.output_tokens:,} | "
            f"{row.total_tokens:,} | {row.median_seconds_per_turn:.2f} | "
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
            f"- Fastest single-cohort session pace: `{label(fastest)}` at "
            f"{fastest.median_seconds_per_turn:.2f} seconds/turn.",
            f"- Slowest single-cohort session pace: `{label(slowest)}` at "
            f"{slowest.median_seconds_per_turn:.2f} seconds/turn.",
            f"- Highest single-cohort token efficiency: `{label(most_efficient)}` at "
            f"{most_efficient.token_efficiency:,.2f} completed milestones per million tokens.",
            f"- Lowest single-cohort token efficiency: `{label(least_efficient)}` at "
            f"{least_efficient.token_efficiency:,.2f} completed milestones per million tokens.",
        )
    )


def _fastest_models(analysis: LatencyAnalysis | None) -> tuple[LatencyRow, ...]:
    if analysis is None:
        return ()
    return tuple(
        sorted(
            analysis.aggregate_model_rows,
            key=lambda row: (
                row.median_seconds,
                row.p95_seconds,
                row.model.casefold(),
                row.model,
            ),
        )[:5]
    )


def _most_efficient_models(rows: Sequence[ModelRow]) -> tuple[ModelEfficiencyRow, ...]:
    grouped: dict[str, list[ModelRow]] = defaultdict(list)
    for row in rows:
        if row.total_tokens and row.response_rows:
            grouped[row.model].append(row)
    efficiency_rows = (
        ModelEfficiencyRow(
            model=model,
            milestone_hits=sum(row.milestone_hits for row in model_rows),
            milestone_possible=sum(row.milestone_possible for row in model_rows),
            total_tokens=sum(row.total_tokens for row in model_rows),
        )
        for model, model_rows in grouped.items()
    )
    return tuple(
        sorted(
            efficiency_rows,
            key=lambda row: (
                -row.token_efficiency,
                row.model.casefold(),
                row.model,
            ),
        )[:5]
    )


def _performance_leaderboards(
    rows: Sequence[ModelRow],
    latency: LatencyAnalysis | None,
) -> str:
    fastest = _fastest_models(latency)
    efficient = _most_efficient_models(rows)
    lines = [
        "### Top 5 fastest models",
        "",
        "Latency ranks aggregate all retained scored decisions for each exact model. "
        "Provider and hardware differ, so compare models within compatible deployment "
        "panels before making capacity decisions.",
        "",
    ]
    if fastest:
        lines.extend(
            (
                "| Rank | Model | Provider | Decisions | Median sec/decision | "
                "P95 sec/decision | Output tokens/sec |",
                "| ---: | --- | --- | ---: | ---: | ---: | ---: |",
            )
        )
        for rank, row in enumerate(fastest, start=1):
            lines.append(
                f"| {rank} | `{row.model}` | `{row.provider}` | "
                f"{row.decisions:,} | {row.median_seconds:.2f} | "
                f"{row.p95_seconds:.2f} | "
                f"{_token_latency_cell(row.output_tokens_per_second)} |"
            )
    else:
        lines.append("No retained decision-latency evidence was available.")
    lines.extend(
        (
            "",
            "### Top 5 most token-efficient models",
            "",
            "Efficiency ranks aggregate completed milestone checks per million logical "
            "provider-reported input plus output tokens across all supplied cohorts. "
            "Cached prompt tokens may be included.",
            "",
        )
    )
    if efficient:
        lines.extend(
            (
                "| Rank | Model | Milestones | Total tokens | Milestones/M tokens |",
                "| ---: | --- | ---: | ---: | ---: |",
            )
        )
        for rank, row in enumerate(efficient, start=1):
            lines.append(
                f"| {rank} | `{row.model}` | "
                f"{row.milestone_hits}/{row.milestone_possible} | "
                f"{row.total_tokens:,} | {row.token_efficiency:,.2f} |"
            )
    else:
        lines.append("No retained provider token usage was available.")
    return "\n".join(lines)


def _typst_text(value: str) -> str:
    return f"#text({json.dumps(value, ensure_ascii=False)})"


def _typst_table(
    columns: str,
    cells: Sequence[str],
    *,
    text_size: str | None = None,
) -> tuple[str, ...]:
    lines = []
    if text_size is not None:
        lines.append(f"#set text(size: {text_size})")
    lines.extend(
        (
            "#table(",
            f"  columns: {columns},",
            "  " + ",\n  ".join(cells),
            ")",
        )
    )
    if text_size is not None:
        lines.append("#set text(size: 9pt)")
    return tuple(lines)


def _typst_latency_block(analysis: LatencyAnalysis | None) -> tuple[str, ...]:
    if analysis is None:
        return (_typst_text("No retained turn-latency evidence was available."),)
    overall_cells = [
        "[*Scope*]",
        "[*Provider(s)*]",
        "[*Decisions*]",
        "[*Median sec*]",
        "[*P95 sec*]",
        "[*P99 sec*]",
        "[*Max sec*]",
        "[*Output tokens/sec*]",
    ]
    for index, row in enumerate((analysis.overall, *analysis.cohort_rows)):
        values = (
            "Overall" if index == 0 else row.cohort or "Unlabeled",
            row.provider,
            f"{row.decisions:,}",
            f"{row.median_seconds:.2f}",
            f"{row.p95_seconds:.2f}",
            f"{row.p99_seconds:.2f}",
            f"{row.maximum_seconds:.2f}",
            _token_latency_cell(row.output_tokens_per_second),
        )
        overall_cells.extend(f"[{_typst_text(value)}]" for value in values)
    model_cells = [
        "[*Model*]",
        "[*Cohort*]",
        "[*Provider*]",
        "[*Decisions*]",
        "[*Median sec*]",
        "[*P95 sec*]",
        "[*P99 sec*]",
        "[*Output tokens/sec*]",
    ]
    for row in analysis.model_rows:
        values = (
            row.model,
            row.cohort or "Unlabeled",
            row.provider,
            f"{row.decisions:,}",
            f"{row.median_seconds:.2f}",
            f"{row.p95_seconds:.2f}",
            f"{row.p99_seconds:.2f}",
            _token_latency_cell(row.output_tokens_per_second),
        )
        model_cells.extend(f"[{_typst_text(value)}]" for value in values)
    return (
        _typst_text(
            f"Across {analysis.overall.decisions:,} scored decisions, median end-to-end "
            f"decision latency was {analysis.overall.median_seconds:.2f}s, p95 was "
            f"{analysis.overall.p95_seconds:.2f}s, p99 was "
            f"{analysis.overall.p99_seconds:.2f}s, and the maximum was "
            f"{analysis.overall.maximum_seconds:.2f}s."
        ),
        _typst_text(
            "Token-normalized figures divide complete end-to-end decision latency by "
            "output tokens. They are not pure decoder throughput."
        ),
        "=== Overall and cohort latency",
        *_typst_table(
            "(0.8fr, 1.2fr, 0.8fr, 0.8fr, 0.8fr, 0.8fr, 0.8fr, 1fr)",
            overall_cells,
            text_size="6pt",
        ),
        "#pagebreak()",
        "=== Per-model latency",
        *_typst_table(
            "(2fr, 0.6fr, 0.9fr, 0.7fr, 0.7fr, 0.7fr, 0.7fr, 0.9fr)",
            model_cells,
            text_size="5.5pt",
        ),
    )


def _typst_performance_leaderboards(
    rows: Sequence[ModelRow],
    latency: LatencyAnalysis | None,
) -> tuple[str, ...]:
    fastest = _fastest_models(latency)
    efficient = _most_efficient_models(rows)
    fastest_cells = [
        "[*Rank*]",
        "[*Model*]",
        "[*Provider*]",
        "[*Decisions*]",
        "[*Median sec*]",
        "[*P95 sec*]",
        "[*Output tokens / sec*]",
    ]
    for rank, row in enumerate(fastest, start=1):
        values = (
            str(rank),
            row.model,
            row.provider,
            f"{row.decisions:,}",
            f"{row.median_seconds:.2f}",
            f"{row.p95_seconds:.2f}",
            _token_latency_cell(row.output_tokens_per_second),
        )
        fastest_cells.extend(f"[{_typst_text(value)}]" for value in values)
    efficient_cells = [
        "[*Rank*]",
        "[*Model*]",
        "[*Milestones*]",
        "[*Total tokens*]",
        "[*Milestones / M tokens*]",
    ]
    for rank, row in enumerate(efficient, start=1):
        values = (
            str(rank),
            row.model,
            f"{row.milestone_hits}/{row.milestone_possible}",
            f"{row.total_tokens:,}",
            f"{row.token_efficiency:,.2f}",
        )
        efficient_cells.extend(f"[{_typst_text(value)}]" for value in values)
    fastest_block = (
        _typst_table(
            "(0.5fr, 2fr, 1fr, 0.8fr, 0.9fr, 0.8fr, 1fr)",
            fastest_cells,
            text_size="7pt",
        )
        if fastest
        else (_typst_text("No retained decision-latency evidence was available."),)
    )
    efficient_block = (
        _typst_table(
            "(0.5fr, 2fr, 1fr, 1fr, 1.1fr)",
            efficient_cells,
            text_size="7pt",
        )
        if efficient
        else (_typst_text("No retained provider token usage was available."),)
    )
    return (
        "== Performance leaders",
        "",
        "=== Top 5 fastest models",
        _typst_text(
            "Latency ranks aggregate all retained scored decisions for each exact model. "
            "Provider and hardware differ; compare compatible deployment panels before "
            "making capacity decisions."
        ),
        *fastest_block,
        "",
        "=== Top 5 most token-efficient models",
        _typst_text(
            "Efficiency is completed milestone checks per million logical "
            "provider-reported input plus output tokens across all supplied cohorts. "
            "Cached prompt tokens may be included."
        ),
        *efficient_block,
        "#pagebreak()",
    )


def _typst_analysis_block(
    change_breadth_rows: Sequence[ChangeBreadthRow],
    bottlenecks: Sequence[MilestoneBottleneckRow],
    behavior_rows: Sequence[BehaviorRow],
    quantization_rows: Sequence[QuantizationRow],
) -> tuple[str, ...]:
    change_breadth_cells = [
        "[*Tutorial*]",
        "[*Transition*]",
        "[*Shared*]",
        "[*Improved*]",
        "[*Tied*]",
        "[*Regressed*]",
    ]
    for row in change_breadth_rows:
        values = (
            row.tutorial,
            f"{row.before_cohort} → {row.after_cohort}",
            str(row.shared_models),
            str(row.improved_models),
            str(row.tied_models),
            str(row.regressed_models),
        )
        change_breadth_cells.extend(f"[{_typst_text(value)}]" for value in values)
    bottleneck_cells = [
        "[*Tutorial*]",
        "[*Cohort*]",
        "[*Milestone*]",
        "[*Completed*]",
        "[*Rate*]",
    ]
    for row in bottlenecks:
        values = (
            row.tutorial,
            row.cohort or "Unlabeled",
            row.milestone,
            f"{row.completions}/{row.sessions}",
            f"{row.completions / row.sessions:.1%}",
        )
        bottleneck_cells.extend(f"[{_typst_text(value)}]" for value in values)
    behavior_cells = [
        "[*Tutorial*]",
        "[*Cohort*]",
        "[*Pass rate*]",
        "[*Valid*]",
        "[*Rejected*]",
        "[*Validity*]",
        "[*Recovery*]",
    ]
    for row in behavior_rows:
        recovery = (
            f"{row.recovered_rejections}/{row.rejected_actions} ({row.recovery:.1%})"
            if row.rejected_actions
            else "—"
        )
        values = (
            row.tutorial,
            row.cohort or "Unlabeled",
            f"{row.passes}/{row.sessions} ({row.passes / row.sessions:.1%})",
            str(row.valid_actions),
            str(row.rejected_actions),
            f"{row.validity:.1%}",
            recovery,
        )
        behavior_cells.extend(f"[{_typst_text(value)}]" for value in values)
    quantization_cells = [
        "[*Tutorial*]",
        "[*Cohort*]",
        "[*Quantization*]",
        "[*Model*]",
        "[*Passes*]",
    ]
    for row in quantization_rows:
        values = (
            row.tutorial,
            row.cohort or "Unlabeled",
            row.quantization,
            row.model,
            f"{row.passes}/{row.sessions}",
        )
        quantization_cells.extend(f"[{_typst_text(value)}]" for value in values)
    return (
        "== Additional analytical questions",
        "=== How broadly were cohort gains shared?",
        _typst_text(
            "Counts compare pass-rate changes for exact model/tutorial cells present "
            "in both cohorts, separating improvements, ties, and regressions."
        ),
        *_typst_table(
            "(0.8fr, 1.2fr, 0.8fr, 0.8fr, 0.8fr, 0.8fr)",
            change_breadth_cells,
            text_size="7pt",
        ),
        "=== Where does tutorial progress break?",
        _typst_text(
            "The table lists the three lowest-completion exact milestone identifiers "
            "in each tutorial/cohort. Historical and replacement identifiers remain separate."
        ),
        *_typst_table(
            "(0.8fr, 0.6fr, 2fr, 0.8fr, 0.8fr)",
            bottleneck_cells,
            text_size="7pt",
        ),
        "#pagebreak()",
        "=== Are failures mostly invalid actions?",
        _typst_text(
            "Action validity measures accepted actions among all submitted actions. "
            "Rejection recovery uses the benchmark's existing recovery window."
        ),
        *_typst_table(
            "(0.8fr, 0.6fr, 1fr, 0.8fr, 0.8fr, 0.8fr, 1fr)",
            behavior_cells,
            text_size="7pt",
        ),
        "=== How sensitive is Qwen 3.6 35B to quantization?",
        _typst_text(
            "These are like-for-like pass counts for the tested Q4, Q6, and Q8 "
            "identifiers; one five-session cell does not establish monotonic quality."
        ),
        *_typst_table(
            "(0.8fr, 0.6fr, 0.9fr, 2fr, 0.7fr)",
            quantization_cells,
            text_size="7pt",
        ),
    )


def _typst_frontier_cost_block(
    rows: Sequence[ModelRow],
    chart_path: str | None,
) -> tuple[str, ...]:
    cost_rows = _frontier_cost_rows(rows)
    if not cost_rows:
        return ()
    cells = [
        "[*Model*]",
        "[*Passes*]",
        "[*Milestones*]",
        "[*Estimated cost*]",
        "[*Passes / USD*]",
        "[*Milestones / USD*]",
    ]
    for row in cost_rows:
        values = (
            row.display_name,
            f"{row.passes}/{row.sessions} ({row.pass_rate:.1%})",
            f"{row.milestone_hits}/{row.milestone_possible}",
            f"${row.estimated_cost_usd:.2f}",
            f"{row.passes_per_dollar:.2f}",
            f"{row.milestones_per_dollar:.2f}",
        )
        cells.extend(f"[{_typst_text(value)}]" for value in values)
    by_model = {row.model: row for row in cost_rows}
    luna = by_model.get("openai/gpt-5.6-luna")
    opus = by_model.get("anthropic/claude-opus-5")
    recommendation = ""
    if luna is not None and opus is not None:
        overall_ratio = _frontier_ratio(rows)
        recent_ratio = _frontier_ratio(rows, cohorts=frozenset(("v2", "v4")))
        ratios = (
            f"Luna delivered {overall_ratio:.1f}× the authoritative passes per dollar "
            "across all retained frontier runs"
            if overall_ratio is not None
            else ""
        )
        if recent_ratio is not None:
            ratios += (
                f" and {recent_ratio:.1f}× in v2 and v4, supporting an operational "
                "summary of about 25× better per dollar."
            )
        recommendation = (
            "Recommendation: use GPT-5.6 Luna for hosted frontier gameplay and avoid "
            "Claude Opus 5 for routine Bunnyland play. "
            f"Luna passed {luna.passes}/{luna.sessions} for an estimated "
            f"${luna.estimated_cost_usd:.2f}; Opus passed {opus.passes}/{opus.sessions} "
            f"for ${opus.estimated_cost_usd:.2f}. {ratios} Opus may still suit work "
            "outside this gameplay benchmark, but its cost/performance ratio here is poor."
        )
    chart = (
        (
            f'#image({json.dumps(chart_path)}, width: 92%, height: 110mm, fit: "contain")',
        )
        if chart_path is not None
        else ()
    )
    return (
        "== Frontier API cost and recommendation",
        "",
        _typst_text(
            "These four models used two sessions per applicable cell and are not classified "
            "by the five-session threshold rubric. "
            "Costs are reconstructed from retained OpenRouter usage and list prices, "
            "including observed cache reads and writes; they are estimates, not invoices."
        ),
        "",
        _typst_text(recommendation),
        "",
        "#set text(size: 7pt)",
        "#table(",
        "  columns: (1.5fr, 1.1fr, 1fr, 1fr, 0.8fr, 0.9fr),",
        "  " + ",\n  ".join(cells),
        ")",
        "#set text(size: 9pt)",
        *chart,
        "#pagebreak()",
    )


def _typst_report(
    title: str,
    rows: Sequence[ModelRow],
    difficulty_rows: Sequence[DifficultyRow],
    aggregate_deltas: Sequence[CohortDeltaRow],
    model_deltas: Sequence[CohortDeltaRow],
    change_breadth_rows: Sequence[ChangeBreadthRow],
    coverage: CoverageAnalysis | None,
    latency: LatencyAnalysis | None,
    bottlenecks: Sequence[MilestoneBottleneckRow],
    behavior_rows: Sequence[BehaviorRow],
    quantization_rows: Sequence[QuantizationRow],
    frontier_chart_path: str | None,
    kimi_chart_path: str | None,
    diagrams: Sequence[str],
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
            "  " + ",\n  ".join(difficulty_cells),
            ")",
        )
        if difficulty_rows
        else (_typst_text("No complete five-session model/tutorial cells were available."),)
    )
    acceptance_policy_cells = [
        "[*Tutorial*]",
        "[*Cohort expectation*]",
        "[*Strong-model expectation*]",
        "[*Role*]",
    ]
    for policy in TUTORIAL_ACCEPTANCE_POLICIES:
        acceptance_policy_cells.extend(
            f"[{_typst_text(value)}]"
            for value in (
                policy.tutorial,
                policy.cohort_expectation,
                policy.strong_model_expectation,
                policy.role,
            )
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
            "  " + ",\n  ".join(aggregate_cells),
            ")",
            "#pagebreak()",
            "=== Matching model/tutorial cells",
            "#set text(size: 7pt)",
            "#table(",
            "  columns: (1.2fr, 2fr, 1fr, 1fr, 1fr, 1fr),",
            "  " + ",\n  ".join(model_cells),
            ")",
            "#set text(size: 9pt)",
        )
    else:
        delta_block = (
            _typst_text("At least two cohorts with a shared tutorial are required."),
        )
    coverage_block: tuple[str, ...] = ()
    if coverage is not None:
        summary_cells = [
            "[*Cohort*]",
            "[*In scope*]",
            "[*Sessions*]",
            "[*Complete*]",
            "[*Partial*]",
            "[*Missing*]",
            "[*N/A*]",
        ]
        for row in coverage.summary_rows:
            values = (
                row.cohort,
                ", ".join(row.tutorials) or "—",
                f"{row.observed_sessions}/{row.expected_sessions}",
                str(row.complete_cells),
                str(row.partial_cells),
                str(row.missing_cells),
                str(row.not_applicable_cells),
            )
            summary_cells.extend(f"[{_typst_text(value)}]" for value in values)
        gap_lines: tuple[str, ...]
        if coverage.gap_rows:
            gap_cells = [
                "[*Model*]",
                "[*Cohort*]",
                "[*Coverage*]",
                "[*Missing sessions*]",
                "[*Incomplete tutorials*]",
            ]
            for row in coverage.gap_rows:
                values = (
                    row.model,
                    row.cohort,
                    f"{row.observed_sessions}/{row.expected_sessions}",
                    str(row.missing_sessions),
                    ", ".join(row.incomplete_tutorials),
                )
                gap_cells.extend(f"[{_typst_text(value)}]" for value in values)
            gap_lines = (
                "=== Missing and partial in-scope coverage",
                "#set text(size: 7pt)",
                "#table(",
                "  columns: (2fr, 0.7fr, 0.8fr, 0.8fr, 2fr),",
                "  " + ",\n  ".join(gap_cells),
                ")",
                "#set text(size: 9pt)",
            )
        else:
            gap_lines = (
                "=== Missing and partial in-scope coverage",
                _typst_text("No in-scope coverage gaps remain."),
            )
        coverage_block = (
            "== Data coverage gaps",
            _typst_text(
                f"Coverage uses the {coverage.reference_models} exact model identifiers "
                f"in the final supplied cohort, {coverage.reference_cohort}, as the "
                f"reference roster and targets {coverage.target_sessions} sessions per "
                "in-scope cell. Identifiers are not aliased across model names. Tutorials "
                "absent from a cohort's manifest are not applicable (N/A), not missing."
            ),
            "=== Cohort coverage",
            "#table(",
            "  columns: (0.7fr, 1.4fr, 1fr, 0.8fr, 0.8fr, 0.8fr, 0.6fr),",
            "  " + ",\n  ".join(summary_cells),
            ")",
            *gap_lines,
            "#pagebreak()",
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
    kimi_block = (
        (
            "== Kimi family comparison",
            _typst_text(
                "This chart compares aggregate capability, decision latency, and "
                "logical-token efficiency. Kimi K2.7 Code is a code-specialized branch. "
                "K3 used OpenRouter while the K2 models used Ollama Cloud, so latency "
                "includes provider infrastructure differences."
            ),
            f'#image({json.dumps(kimi_chart_path)}, width: 100%, height: 150mm, fit: "contain")',
            "#pagebreak()",
        )
        if kimi_chart_path is not None
        else ()
    )
    return "\n".join(
        (
            '#set page(paper: "a4", flipped: true, margin: 12mm)',
            "#set text(size: 9pt)",
            "#set heading(numbering: none)",
            '#set table(inset: 4pt, stroke: 0.5pt + rgb("ccd3dc"))',
            f"= {_typst_text(title)}",
            "",
            "Generated from authoritative benchmark artifacts.",
            "",
            *coverage_block,
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
                "  columns: (1.2fr, 2fr, 1fr, 0.8fr, 1fr, 0.8fr, 1fr),"
                if cohort_mode
                else "  columns: (2fr, 1fr, 0.8fr, 1fr, 0.8fr, 1fr),"
            ),
            "  " + ",\n  ".join(token_cells),
            ")",
            "#set text(size: 9pt)",
            "",
            *_typst_performance_leaderboards(rows, latency),
            "",
            "== Latency distribution",
            "",
            "Decision latency comes from scored turn traces. Provider and hardware panels "
            "are separate because local and cloud timing are not directly interchangeable.",
            "",
            *_typst_latency_block(latency),
            "#pagebreak()",
            "",
            "== Model comparison",
            "",
            "#table(",
            (
                "  columns: (1.2fr, 2.2fr, 1fr, 1fr, 1fr, 1fr),"
                if cohort_mode
                else "  columns: (2.2fr, 1fr, 1fr, 1fr, 1fr),"
            ),
            "  " + ",\n  ".join(cells),
            ")",
            "",
            *_typst_frontier_cost_block(rows, frontier_chart_path),
            "",
            "== Tutorial acceptance policy",
            "",
            "These calibration goals do not change per-session milestone scoring. "
            "Strong models are selected before results are read, using a reproducible "
            "public popularity or usage metric.",
            "",
            "#set text(size: 7pt)",
            "#table(",
            "  columns: (0.7fr, 1.6fr, 1.8fr, 1.1fr),",
            "  " + ",\n  ".join(acceptance_policy_cells),
            ")",
            "#set text(size: 9pt)",
            "",
            "== Difficulty distribution",
            "",
            "Possible pass means at least 1/5, likely pass at least 3/5, and consistent "
            "pass at least 4/5. Incomplete cells are excluded.",
            "",
            *difficulty_block,
            "",
            *kimi_block,
            "== Cohort deltas",
            "",
            "Deltas compare consecutive cohorts in the supplied order. Missing model/cohort "
            "cells are not treated as failures. Tutorial totals reflect each cohort's "
            "tested model mix; matching model/tutorial rows are like-for-like.",
            "",
            *delta_block,
            "#pagebreak()",
            *_typst_analysis_block(
                change_breadth_rows,
                bottlenecks,
                behavior_rows,
                quantization_rows,
            ),
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
    difficulty_rows = _difficulty_rows(results)
    scatter_metadata = _parameter_scatter_metadata(labeled_sources)
    rows = _model_rows(results, _model_usage(labeled_sources))
    latency = _latency_analysis(labeled_sources)
    output.mkdir(parents=True, exist_ok=True)
    diagrams = output / "diagrams"
    diagrams.mkdir(exist_ok=True)
    success_chart_path = diagrams / "tutorial-success-trend-chart.svg"
    threshold_chart_path = diagrams / "threshold-attainment-chart.svg"
    success_chart_path.write_text(render_success_trend_svg(results), encoding="utf-8")
    threshold_chart_path.write_text(
        render_threshold_chart_svg(difficulty_rows),
        encoding="utf-8",
    )
    chart_paths = (
        str(success_chart_path.relative_to(output)),
        str(threshold_chart_path.relative_to(output)),
    )
    scatter_chart_paths: list[str] = []
    for tutorial in TUTORIAL_MAPS:
        scatter_path = diagrams / f"{tutorial}-parameter-milestone-scatter-chart.svg"
        scatter_path.write_text(
            render_parameter_scatter_svg(
                results,
                tutorial,
                scatter_metadata,
            ),
            encoding="utf-8",
        )
        scatter_chart_paths.append(str(scatter_path.relative_to(output)))
    kimi_rows = _kimi_family_rows(rows, latency)
    kimi_chart_path: str | None = None
    if len(kimi_rows) >= 2:
        kimi_chart = diagrams / "kimi-family-comparison-chart.svg"
        kimi_chart.write_text(render_kimi_family_svg(kimi_rows), encoding="utf-8")
        kimi_chart_path = str(kimi_chart.relative_to(output))
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
    frontier_cost_rows = _frontier_cost_rows(rows)
    frontier_chart_path: str | None = None
    if frontier_cost_rows:
        frontier_chart = diagrams / "frontier-api-cost-performance-chart.svg"
        frontier_chart.write_text(
            render_frontier_cost_svg(frontier_cost_rows),
            encoding="utf-8",
        )
        frontier_chart_path = str(frontier_chart.relative_to(output))
    cohort_order = tuple(
        dict.fromkeys(
            cohort for cohort, _source in labeled_sources if cohort is not None
        )
    )
    aggregate_deltas, model_deltas = _cohort_delta_rows(results, cohort_order)
    change_breadth_rows = _change_breadth_rows(model_deltas)
    coverage = _coverage_analysis(results, labeled_sources)
    bottlenecks = _milestone_bottleneck_rows(results)
    behavior_rows = _behavior_rows(results)
    quantization_rows = _quantization_rows(results, labeled_sources)
    template = (Path(__file__).parent / "templates" / "tutorial_report.md").read_text(
        encoding="utf-8"
    )
    markdown = (
        template.replace("{{TITLE}}", title)
        .replace("{{COMPLETED}}", str(len(results)))
        .replace("{{PASSES}}", str(sum(item.result.passed for item in results)))
        .replace("{{COVERAGE_GAPS}}", _coverage_gap_section(coverage))
        .replace("{{RUNTIME_SUMMARY}}", _runtime_summary(rows))
        .replace("{{TOKEN_TABLE}}", _token_table(rows))
        .replace(
            "{{PERFORMANCE_LEADERBOARDS}}",
            _performance_leaderboards(rows, latency),
        )
        .replace("{{LATENCY_SECTION}}", _latency_section(latency))
        .replace("{{COMPARISON_TABLE}}", _comparison_table(rows))
        .replace(
            "{{FRONTIER_COST_SECTION}}",
            _frontier_cost_section(rows, frontier_chart_path),
        )
        .replace("{{ACCEPTANCE_POLICY}}", _acceptance_policy_table())
        .replace("{{DIFFICULTY_TABLE}}", _difficulty_table(difficulty_rows))
        .replace(
            "{{SUMMARY_CHARTS}}",
            "\n\n".join(f"![{Path(path).stem}]({path})" for path in chart_paths),
        )
        .replace(
            "{{PARAMETER_SCATTER_PLOTS}}",
            "\n\n".join(
                f"![{Path(path).stem}]({path})" for path in scatter_chart_paths
            ),
        )
        .replace(
            "{{KIMI_FAMILY_CHART}}",
            (
                f"![Kimi family comparison]({kimi_chart_path})"
                if kimi_chart_path is not None
                else "At least two Kimi family models are required for this comparison."
            ),
        )
        .replace(
            "{{COHORT_DELTAS}}",
            _cohort_delta_table(aggregate_deltas, model_deltas),
        )
        .replace(
            "{{CHANGE_BREADTH_TABLE}}",
            _change_breadth_table(change_breadth_rows),
        )
        .replace(
            "{{MILESTONE_BOTTLENECKS}}",
            _milestone_bottleneck_table(bottlenecks),
        )
        .replace("{{BEHAVIOR_TABLE}}", _behavior_table(behavior_rows))
        .replace(
            "{{QUANTIZATION_TABLE}}",
            _quantization_table(quantization_rows),
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
            change_breadth_rows,
            coverage,
            latency,
            bottlenecks,
            behavior_rows,
            quantization_rows,
            frontier_chart_path,
            kimi_chart_path,
            (*chart_paths, *scatter_chart_paths, *diagram_paths),
        ),
        encoding="utf-8",
    )
    evidence_sources = "\n".join(
        (
            "# Evidence sources",
            "",
            "Authoritative benchmark artifact cohorts used to generate the report:",
            "",
            *(
                "- "
                + (f"`{cohort}` / " if cohort is not None else "")
                + f"`{source.path.name}` — "
                f"{len(source.results)} completed sessions"
                for cohort, source in labeled_sources
            ),
            "",
        )
    )
    (output / "evidence-sources.md").write_text(evidence_sources, encoding="utf-8")
    (output / "comparison-table.md").write_text(_comparison_table(rows) + "\n", encoding="utf-8")
    (output / "token-stats.md").write_text(_token_table(rows) + "\n", encoding="utf-8")


def package_report(report: Path, archive: Path) -> None:
    files = (
        "report.md",
        "report.pdf",
        "comparison-table.md",
        "token-stats.md",
        "findings.md",
        "evidence-sources.md",
    )
    diagrams = tuple(
        sorted(
            (
                *(report / "diagrams").glob("*-tabletop.png"),
                *(report / "diagrams").glob("*-map.svg"),
                *(report / "diagrams").glob("*-milestones.svg"),
                *(report / "diagrams").glob("*-chart.svg"),
            )
        )
    )
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
