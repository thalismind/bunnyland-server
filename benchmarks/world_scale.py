"""Deterministic world-size benchmarks for the Relics-backed Bunnyland runtime."""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import csv
import gc
import importlib.metadata
import json
import math
import os
import platform
import resource
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import NotRequired, TypedDict

from pydantic import TypeAdapter
from pydantic.dataclasses import dataclass as pydantic_dataclass
from relics import Component, Edge, EntityId

from bunnyland.core.components import (
    CharacterComponent,
    IdentityComponent,
    RoomComponent,
)
from bunnyland.core.ecs import spawn_entity
from bunnyland.core.edges import ContainmentMode, Contains, KnowsRoom
from bunnyland.core.graph_query import EdgeTerm, GraphQueryExecutor, GraphQuerySpec
from bunnyland.core.mutations import (
    AddEdge,
    MutationPlan,
    RemoveEdge,
    SetComponent,
    execute_mutation_plan,
    validate_core_invariants,
)
from bunnyland.core.world_actor import WorldActor
from bunnyland.persistence import WorldMeta, load_world, save_world
from bunnyland.plugins.model import EcsContribution, Plugin, PluginPlacement
from bunnyland.plugins.registry import PluginRegistry
from bunnyland.server.serialization import (
    serialize_character_projection,
    serialize_room_projection,
    serialize_world,
)

POWERS_OF_TEN = (1, 10, 100, 1_000, 10_000, 100_000, 1_000_000)
TOPOLOGIES = ("balanced", "concentrated")
SCHEMA_VERSION = 1


@pydantic_dataclass(frozen=True)
class BenchmarkDenseComponent(Component):
    value: int = 0


@pydantic_dataclass(frozen=True)
class BenchmarkSingletonComponent(Component):
    value: int = 0


@pydantic_dataclass(frozen=True)
class BenchmarkEdge(Edge):
    weight: int = 1


BENCHMARK_PLUGIN = Plugin(
    id="benchmark.world_scale",
    name="World scale benchmark types",
    placement=PluginPlacement.ADDON,
    ecs=EcsContribution(
        components=(BenchmarkDenseComponent, BenchmarkSingletonComponent),
        edges=(BenchmarkEdge,),
    ),
)


@dataclass(frozen=True)
class MatrixPoint:
    entities: int
    edges: int
    topology: str


@dataclass(frozen=True)
class Measurement:
    schema_version: int
    entities: int
    edges: int
    topology: str
    operation: str
    status: str
    median_ns: int | None
    p95_ns: int | None
    iterations: int
    operations_per_second: float | None
    rss_bytes: int
    peak_rss_bytes: int
    detail: str = ""


class MeasurementRow(TypedDict):
    schema_version: int
    entities: int
    edges: int
    topology: str
    operation: str
    status: str
    median_ns: int | None
    p95_ns: int | None
    iterations: int
    operations_per_second: float | None
    rss_bytes: int
    peak_rss_bytes: int
    detail: str


class SlopeRecord(TypedDict):
    topology: str
    operation: str
    axis: str
    slope: float


class ProblemRecord(TypedDict):
    severity: str
    operation: str
    topology: str
    reason: str
    axis: NotRequired[str]
    slope: NotRequired[float]
    entities: NotRequired[int]
    edges: NotRequired[int]


class WorkerFailure(TypedDict):
    entities: int
    topology: str
    returncode: int


class Analysis(TypedDict):
    slopes: list[SlopeRecord]
    problems: list[ProblemRecord]
    regressions: list[ProblemRecord]
    failures: list[MeasurementRow]
    worker_failures: NotRequired[list[WorkerFailure]]
    impossible_points: NotRequired[tuple[tuple[int, int], ...]]


class EnvironmentMetadata(TypedDict):
    schema_version: int
    commit: str
    python: str
    platform: str
    machine: str
    processor: str
    cpu_count: int | None
    page_size: int
    relics_version: str


PointRow = dict[str, int | float | str]
_MEASUREMENT_ADAPTER = TypeAdapter(Measurement)


@dataclass(frozen=True)
class BuiltWorld:
    actor: WorldActor
    ids: list[EntityId]
    room_id: EntityId | None
    character_id: EntityId | None


def feasible_points(
    *, max_entities: int, max_edges: int, topologies: Iterable[str] = TOPOLOGIES
) -> tuple[MatrixPoint, ...]:
    """Return all requested power-of-ten points representable by one edge type."""
    return tuple(
        MatrixPoint(entities, edges, topology)
        for entities in POWERS_OF_TEN
        if entities <= max_entities
        for edges in POWERS_OF_TEN
        if edges <= max_edges and edges <= entities * (entities - 1)
        for topology in topologies
    )


def impossible_points(*, max_entities: int, max_edges: int) -> tuple[tuple[int, int], ...]:
    return tuple(
        (entities, edges)
        for entities in POWERS_OF_TEN
        if entities <= max_entities
        for edges in POWERS_OF_TEN
        if edges <= max_edges and edges > entities * (entities - 1)
    )


def edge_pair(index: int, entity_count: int, topology: str) -> tuple[int, int]:
    """Map an edge ordinal to a deterministic unique source/target pair."""
    if topology not in TOPOLOGIES:
        raise ValueError(f"unknown topology: {topology}")
    capacity = entity_count * (entity_count - 1)
    if index < 0 or index >= capacity:
        raise ValueError("edge index exceeds the unique directed-pair capacity")
    if topology == "concentrated":
        source = index // (entity_count - 1)
        target = index % (entity_count - 1)
        return source, target if target < source else target + 1
    if topology == "balanced":
        source = index % entity_count
        layer = index // entity_count
        return source, (source + layer + 1) % entity_count
    raise AssertionError("validated topology was not handled")


def count_edges(actor: WorldActor) -> int:
    return sum(
        len(targets)
        for edge_types in actor.world._relationships.values()
        for targets in edge_types.values()
    )


def current_rss_bytes() -> int:
    try:
        pages = int(Path("/proc/self/statm").read_text().split()[1])
    except (FileNotFoundError, IndexError, ValueError):
        return 0
    return pages * os.sysconf("SC_PAGE_SIZE")


def peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        raise ValueError("cannot compute a percentile of no values")
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def measure(
    point: MatrixPoint,
    operation: str,
    function: Callable[[], object],
    *,
    samples: int = 7,
    target_batch_seconds: float = 0.025,
    max_iterations: int = 10_000,
    warmup: bool = True,
) -> Measurement:
    """Measure batched calls while discarding return values between batches."""
    gc.collect()
    if warmup:
        function()
    iterations = 1
    while iterations < max_iterations:
        started = time.perf_counter_ns()
        for _ in range(iterations):
            function()
        elapsed = time.perf_counter_ns() - started
        if elapsed >= target_batch_seconds * 1_000_000_000:
            break
        iterations = min(max_iterations, iterations * 2)
    timings: list[int] = []
    for _ in range(samples):
        started = time.perf_counter_ns()
        for _ in range(iterations):
            function()
        timings.append((time.perf_counter_ns() - started) // iterations)
    median = int(statistics.median(timings))
    return Measurement(
        schema_version=SCHEMA_VERSION,
        entities=point.entities,
        edges=point.edges,
        topology=point.topology,
        operation=operation,
        status="ok",
        median_ns=median,
        p95_ns=percentile(timings, 0.95),
        iterations=iterations * samples,
        operations_per_second=(1_000_000_000 / median if median else None),
        rss_bytes=current_rss_bytes(),
        peak_rss_bytes=peak_rss_bytes(),
    )


def skipped(point: MatrixPoint, operation: str, detail: str) -> Measurement:
    return Measurement(
        SCHEMA_VERSION,
        point.entities,
        point.edges,
        point.topology,
        operation,
        "skipped",
        None,
        None,
        0,
        None,
        current_rss_bytes(),
        peak_rss_bytes(),
        detail,
    )


def failed(point: MatrixPoint, operation: str, exc: BaseException) -> Measurement:
    return Measurement(
        SCHEMA_VERSION,
        point.entities,
        point.edges,
        point.topology,
        operation,
        "failed",
        None,
        None,
        0,
        None,
        current_rss_bytes(),
        peak_rss_bytes(),
        f"{type(exc).__name__}: {exc}",
    )


def build_world(entity_count: int) -> BuiltWorld:
    if entity_count < 1:
        raise ValueError("entity_count must include at least the world clock")
    actor = WorldActor()
    clock = actor._clock_entity
    clock.add_component(BenchmarkDenseComponent())
    clock.add_component(BenchmarkSingletonComponent())
    ids = [clock.id]
    for index in range(1, entity_count):
        entity = spawn_entity(actor.world, [BenchmarkDenseComponent(index)])
        ids.append(entity.id)

    room_id = None
    character_id = None
    if entity_count >= 3:
        room = actor.world.get_entity(ids[1])
        character = actor.world.get_entity(ids[2])
        room.add_component(RoomComponent(title="Benchmark Room"))
        room.add_component(IdentityComponent(name="Benchmark Room", kind="room"))
        character.add_component(CharacterComponent())
        character.add_component(IdentityComponent(name="Benchmark Character", kind="character"))
        room_id = room.id
        character_id = character.id
    return BuiltWorld(actor, ids, room_id, character_id)


def add_edges(built: BuiltWorld, start: int, stop: int, topology: str) -> None:
    """Add deterministic unique synthetic edges."""
    if stop <= start:
        return
    for ordinal in range(start, stop):
        source_index, target_index = edge_pair(ordinal, len(built.ids), topology)
        built.actor.world.get_entity(built.ids[source_index]).add_relationship(
            BenchmarkEdge(), built.ids[target_index]
        )


def _unused_edge_pair(built: BuiltWorld) -> tuple[EntityId, EntityId] | None:
    world = built.actor.world
    for source_id in (built.ids[-1], built.ids[0]):
        source = world.get_entity(source_id)
        existing = {target for _edge, target in source.get_relationships(BenchmarkEdge)}
        for target_id in reversed(built.ids):
            if target_id != source_id and target_id not in existing:
                return source_id, target_id
    return None


def _degree_extremes(built: BuiltWorld) -> tuple[EntityId, EntityId]:
    relationships = built.actor.world._relationships
    ranked = sorted(
        built.ids,
        key=lambda entity_id: len(relationships.get(entity_id, {}).get(BenchmarkEdge, {})),
    )
    return ranked[0], ranked[-1]


def _remove_tick_knowledge(built: BuiltWorld) -> None:
    if built.character_id is None or built.room_id is None:
        return
    character = built.actor.world.get_entity(built.character_id)
    if character.has_relationship(KnowsRoom, built.room_id):
        character.remove_relationship(KnowsRoom, built.room_id)


def _timed_once(
    point: MatrixPoint, operation: str, function: Callable[[], object]
) -> Measurement:
    gc.collect()
    try:
        started = time.perf_counter_ns()
        function()
        elapsed = time.perf_counter_ns() - started
    except BaseException as exc:
        return failed(point, operation, exc)
    return Measurement(
        SCHEMA_VERSION,
        point.entities,
        point.edges,
        point.topology,
        operation,
        "ok",
        elapsed,
        elapsed,
        1,
        1_000_000_000 / elapsed if elapsed else None,
        current_rss_bytes(),
        peak_rss_bytes(),
    )


def _isolated_timed_once(
    point: MatrixPoint,
    operation: str,
    function: Callable[[], object],
    *,
    output_dir: Path,
) -> Measurement:
    """Measure allocation-heavy work in a fork so its arenas die with the child."""
    if not hasattr(os, "fork"):
        return _timed_once(point, operation, function)
    result_path = output_dir / (
        f".isolated-{os.getpid()}-{point.entities}-{point.edges}-{point.topology}-{operation}.json"
    )
    result_path.unlink(missing_ok=True)
    pid = os.fork()
    if pid == 0:
        try:
            result = _timed_once(point, operation, function)
            result_path.write_text(json.dumps(asdict(result), sort_keys=True) + "\n")
        finally:
            os._exit(0)
    _waited, status = os.waitpid(pid, 0)
    if result_path.exists():
        result = Measurement(**json.loads(result_path.read_text()))
        result_path.unlink(missing_ok=True)
        return result
    if os.WIFSIGNALED(status):
        detail = RuntimeError(f"isolated worker killed by signal {os.WTERMSIG(status)}")
    else:
        detail = RuntimeError(f"isolated worker exited with status {os.WEXITSTATUS(status)}")
    return failed(point, operation, detail)


def benchmark_point(
    built: BuiltWorld,
    point: MatrixPoint,
    *,
    include_persistence: bool,
    output_dir: Path,
) -> list[Measurement]:
    actor = built.actor
    world = actor.world
    low_degree, high_degree = _degree_extremes(built)
    singleton = BenchmarkSingletonComponent
    measurements = [
        measure(point, "point_lookup", lambda: world.get_entity(built.ids[-1])),
        measure(
            point,
            "indexed_singleton_query",
            lambda: sum(1 for _ in world.query().with_all([singleton]).execute_ids()),
        ),
        measure(
            point,
            "indexed_dense_query",
            lambda: sum(
                1
                for _ in world.query().with_all([BenchmarkDenseComponent]).execute_ids()
            ),
            max_iterations=64,
        ),
        measure(
            point,
            "full_world_iteration",
            lambda: sum(1 for _ in world.query().execute_ids()),
            max_iterations=64,
        ),
        measure(
            point,
            "exact_edge_lookup",
            lambda: world.get_entity(high_degree).has_relationship(BenchmarkEdge),
        ),
        measure(
            point,
            "enumerate_low_degree_edges",
            lambda: len(world.get_entity(low_degree).get_relationships(BenchmarkEdge)),
        ),
        measure(
            point,
            "enumerate_high_degree_edges",
            lambda: len(world.get_entity(high_degree).get_relationships(BenchmarkEdge)),
            max_iterations=1_000,
        ),
    ]
    graph_source_index, graph_target_index = edge_pair(0, point.entities, point.topology)
    graph_spec = GraphQuerySpec(
        terms=(EdgeTerm(source="source", edge="BenchmarkEdge", target="target"),),
        bindings={
            "source": str(built.ids[graph_source_index]),
            "target": str(built.ids[graph_target_index]),
        },
        select=("source", "target"),
    )
    graph_executor = GraphQueryExecutor(PluginRegistry((BENCHMARK_PLUGIN,)))
    measurements.append(
        measure(
            point,
            "bounded_graph_query",
            lambda: graph_executor.execute(world, graph_spec),
            max_iterations=1_000,
        )
    )

    counter = 0

    def mutate_component(entity_id: EntityId) -> None:
        nonlocal counter
        counter += 1
        execute_mutation_plan(
            world,
            MutationPlan(
                (SetComponent(entity_id, BenchmarkDenseComponent(counter)),)
            ),
        )

    measurements.extend(
        (
            measure(
                point,
                "mutation_component_low_degree",
                lambda: mutate_component(low_degree),
                max_iterations=1_000,
            ),
            measure(
                point,
                "mutation_component_high_degree",
                lambda: mutate_component(high_degree),
                max_iterations=1_000,
            ),
            measure(
                point,
                "full_invariant_validation",
                lambda: validate_core_invariants(world),
                max_iterations=32,
            ),
        )
    )

    unused = _unused_edge_pair(built)
    if unused is None:
        measurements.append(skipped(point, "mutation_edge_add_remove", "edge set is full"))
    else:
        source_id, target_id = unused

        def add_remove_edge() -> None:
            execute_mutation_plan(
                world, MutationPlan((AddEdge(source_id, target_id, BenchmarkEdge()),))
            )
            execute_mutation_plan(
                world, MutationPlan((RemoveEdge(source_id, target_id, BenchmarkEdge),))
            )

        measurements.append(
            measure(
                point,
                "mutation_edge_add_remove",
                add_remove_edge,
                max_iterations=512,
            )
        )

    if built.room_id is None or built.character_id is None or point.edges < 1:
        measurements.extend(
            (
                skipped(point, "room_projection", "requires at least 3 entities and 1 edge"),
                skipped(
                    point, "character_projection", "requires at least 3 entities and 1 edge"
                ),
            )
        )
    else:
        fixture_source_index, fixture_target_index = edge_pair(
            0, point.entities, point.topology
        )
        fixture_source = world.get_entity(built.ids[fixture_source_index])
        fixture_target = built.ids[fixture_target_index]
        fixture_source.remove_relationship(BenchmarkEdge, fixture_target)
        world.get_entity(built.room_id).add_relationship(
            Contains(mode=ContainmentMode.ROOM_CONTENT), built.character_id
        )
        try:
            measurements.extend(
                (
                    measure(
                        point,
                        "room_projection",
                        lambda: serialize_room_projection(actor, str(built.room_id)),
                        max_iterations=1_000,
                    ),
                    measure(
                        point,
                        "character_projection",
                        lambda: serialize_character_projection(actor, str(built.character_id)),
                        max_iterations=256,
                    ),
                )
            )
        finally:
            world.get_entity(built.room_id).remove_relationship(
                Contains, built.character_id
            )
            fixture_source.add_relationship(BenchmarkEdge(), fixture_target)

    loop = asyncio.new_event_loop()

    def idle_tick() -> None:
        loop.run_until_complete(actor.tick(0))
        _remove_tick_knowledge(built)

    try:
        measurements.append(measure(point, "idle_tick", idle_tick, max_iterations=64))
    finally:
        loop.close()

    measurements.append(
        _isolated_timed_once(
            point,
            "serialize_world",
            lambda: len(serialize_world(actor)["entities"]),
            output_dir=output_dir,
        )
    )

    if include_persistence:
        snapshot = output_dir / f"world-{point.entities}-{point.edges}-{point.topology}.json"
        meta = WorldMeta(seed="benchmark", plugins=(BENCHMARK_PLUGIN.id,))
        measurements.append(
            _isolated_timed_once(
                point,
                "save_world",
                lambda: save_world(actor, snapshot, meta=meta, backup_count=0),
                output_dir=output_dir,
            )
        )
        registry = PluginRegistry((BENCHMARK_PLUGIN,))
        if snapshot.exists():
            measurements.append(
                _isolated_timed_once(
                    point,
                    "load_world",
                    lambda: load_world(snapshot, registry=registry),
                    output_dir=output_dir,
                )
            )
        else:
            measurements.append(skipped(point, "load_world", "save failed"))
        for path in output_dir.glob(f"world-{point.entities}-{point.edges}-{point.topology}.json*"):
            path.unlink(missing_ok=True)
    return measurements


def append_measurements(path: Path, measurements: Iterable[Measurement]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for measurement in measurements:
            handle.write(json.dumps(asdict(measurement), sort_keys=True) + "\n")
        handle.flush()


def run_worker(args: argparse.Namespace) -> int:
    output = Path(args.output)
    point_file = output / f"worker-{args.entities}-{args.topology}.jsonl"
    point_file.unlink(missing_ok=True)
    started = time.perf_counter_ns()
    built = build_world(args.entities)
    entity_elapsed = time.perf_counter_ns() - started
    entity_rss = current_rss_bytes()
    entity_peak_rss = peak_rss_bytes()
    previous_edges = 0
    for edges in POWERS_OF_TEN:
        if edges > args.max_edges or edges > args.entities * (args.entities - 1):
            continue
        point = MatrixPoint(args.entities, edges, args.topology)
        edge_started = time.perf_counter_ns()
        add_edges(built, previous_edges, edges, args.topology)
        edge_elapsed = time.perf_counter_ns() - edge_started
        if count_edges(built.actor) != edges:
            raise RuntimeError(f"expected {edges} edges, found {count_edges(built.actor)}")
        build_rows = [
            Measurement(
                SCHEMA_VERSION,
                point.entities,
                point.edges,
                point.topology,
                "build_entities",
                "ok",
                entity_elapsed,
                entity_elapsed,
                point.entities,
                point.entities * 1_000_000_000 / entity_elapsed,
                entity_rss,
                entity_peak_rss,
                "cumulative time for this entity tier",
            ),
            Measurement(
                SCHEMA_VERSION,
                point.entities,
                point.edges,
                point.topology,
                "build_edge_increment",
                "ok",
                edge_elapsed,
                edge_elapsed,
                point.edges - previous_edges,
                (
                    (point.edges - previous_edges) * 1_000_000_000 / edge_elapsed
                    if edge_elapsed
                    else None
                ),
                current_rss_bytes(),
                peak_rss_bytes(),
                f"edges {previous_edges}..{point.edges}",
            ),
        ]
        append_measurements(point_file, build_rows)
        rows = benchmark_point(
            built,
            point,
            include_persistence=args.include_persistence,
            output_dir=output,
        )
        append_measurements(point_file, rows)
        previous_edges = edges
    return 0


def _measurement_row(measurement: Measurement) -> MeasurementRow:
    return {
        "schema_version": measurement.schema_version,
        "entities": measurement.entities,
        "edges": measurement.edges,
        "topology": measurement.topology,
        "operation": measurement.operation,
        "status": measurement.status,
        "median_ns": measurement.median_ns,
        "p95_ns": measurement.p95_ns,
        "iterations": measurement.iterations,
        "operations_per_second": measurement.operations_per_second,
        "rss_bytes": measurement.rss_bytes,
        "peak_rss_bytes": measurement.peak_rss_bytes,
        "detail": measurement.detail,
    }


def load_measurements(paths: Iterable[Path]) -> list[MeasurementRow]:
    rows: list[MeasurementRow] = []
    for path in paths:
        if not path.exists():
            continue
        rows.extend(
            _measurement_row(_MEASUREMENT_ADAPTER.validate_json(line))
            for line in path.read_text().splitlines()
            if line
        )
    return rows


def log_slope(points: list[tuple[int, int]]) -> float | None:
    usable = [(x, y) for x, y in points if x > 0 and y > 0]
    if len(usable) < 3 or len({x for x, _ in usable}) < 3:
        return None
    xs = [math.log10(x) for x, _ in usable]
    ys = [math.log10(y) for _, y in usable]
    x_mean = statistics.mean(xs)
    y_mean = statistics.mean(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return None
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True)) / denominator


CONSTANT_WORLD_OPERATIONS = {
    "point_lookup",
    "indexed_singleton_query",
    "exact_edge_lookup",
    "bounded_graph_query",
    "enumerate_high_degree_edges",
    "enumerate_low_degree_edges",
    "idle_tick",
    "mutation_component_high_degree",
    "mutation_component_low_degree",
    "mutation_edge_add_remove",
    "room_projection",
    "character_projection",
}

CONSTANT_EDGE_OPERATIONS = (
    CONSTANT_WORLD_OPERATIONS
    - {"enumerate_high_degree_edges", "mutation_component_high_degree"}
) | {
    "indexed_dense_query",
    "full_world_iteration",
    "idle_tick",
    "mutation_component_low_degree",
    "mutation_edge_add_remove",
}

KNOWN_SCALING_LIMITS = {
    ("bounded_graph_query", "edges_at_largest_world"): 1.2,
}


def analyze(rows: list[MeasurementRow]) -> Analysis:
    ok = [row for row in rows if row["status"] == "ok" and row["median_ns"]]
    operations = sorted({row["operation"] for row in ok})
    topologies = sorted({row["topology"] for row in ok})
    slopes: list[SlopeRecord] = []
    problems: list[ProblemRecord] = []
    for topology in topologies:
        for operation in operations:
            entity_points = [
                (row["entities"], row["median_ns"])
                for row in ok
                if row["topology"] == topology
                and row["operation"] == operation
                and row["edges"] == 1
            ]
            slope = log_slope(entity_points)
            if slope is None:
                continue
            record: SlopeRecord = {
                "topology": topology,
                "operation": operation,
                "axis": "entities_at_one_edge",
                "slope": round(slope, 3),
            }
            slopes.append(record)
            if operation in CONSTANT_WORLD_OPERATIONS and slope > 0.35:
                problems.append(
                    ProblemRecord(
                        **record,
                        severity="high" if slope > 0.75 else "medium",
                        reason="local/lookup work scales with unrelated world entities",
                    )
                )
            largest_entities = max(row["entities"] for row in ok)
            edge_points = [
                (row["edges"], row["median_ns"])
                for row in ok
                if row["topology"] == topology
                and row["operation"] == operation
                and row["entities"] == largest_entities
            ]
            edge_slope = log_slope(edge_points)
            if edge_slope is None:
                continue
            edge_record: SlopeRecord = {
                "topology": topology,
                "operation": operation,
                "axis": "edges_at_largest_world",
                "slope": round(edge_slope, 3),
            }
            slopes.append(edge_record)
            if operation in CONSTANT_EDGE_OPERATIONS and edge_slope > 0.35:
                problems.append(
                    ProblemRecord(
                        **edge_record,
                        severity="high" if edge_slope > 0.75 else "medium",
                        reason="bounded work scales with unrelated world edges",
                    )
                )
    failures = [row for row in rows if row["status"] == "failed"]
    for row in failures:
        problems.append(
            ProblemRecord(
                severity="high",
                operation=row["operation"],
                topology=row["topology"],
                entities=row["entities"],
                edges=row["edges"],
                reason=row["detail"],
            )
        )
    regressions = [
        problem
        for problem in problems
        if "slope" not in problem
        or problem["slope"]
        > KNOWN_SCALING_LIMITS.get(
            (problem["operation"], problem.get("axis", "")), 0.75
        )
    ]
    return {
        "slopes": slopes,
        "problems": problems,
        "regressions": regressions,
        "failures": failures,
    }


def write_outputs(output: Path, rows: list[MeasurementRow], analysis: Analysis) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )
    if rows:
        with (output / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        operations = sorted({row["operation"] for row in rows})
        point_rows: list[PointRow] = []
        point_keys = sorted(
            {(row["entities"], row["edges"], row["topology"]) for row in rows}
        )
        for entities, edges, topology in point_keys:
            point: PointRow = {
                "entities": entities,
                "edges": edges,
                "topology": topology,
            }
            selected = {
                row["operation"]: row
                for row in rows
                if row["entities"] == entities
                and row["edges"] == edges
                and row["topology"] == topology
            }
            build = selected.get("build_edge_increment")
            point["live_rss_bytes"] = build["rss_bytes"] if build is not None else ""
            for operation in operations:
                row = selected.get(operation)
                point[f"{operation}_median_ms"] = (
                    round(row["median_ns"] / 1_000_000, 6)
                    if row is not None and row["median_ns"] is not None
                    else ""
                )
            point_rows.append(point)
        point_fields = [
            "entities",
            "edges",
            "topology",
            "live_rss_bytes",
            *(f"{operation}_median_ms" for operation in operations),
        ]
        with (output / "points.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=point_fields)
            writer.writeheader()
            writer.writerows(point_rows)
    (output / "analysis.json").write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n")
    lines = [
        "# World-scale benchmark summary",
        "",
        f"Measurements: {len(rows)}",
        f"Failures: {len(analysis['failures'])}",
        f"Flagged scaling problems: {len(analysis['problems'])}",
        f"CI regressions: {len(analysis['regressions'])}",
        "",
        "## Scaling slopes",
        "",
        "| Topology | Operation | Axis | Slope |",
        "| --- | --- | --- | ---: |",
    ]
    lines.extend(
        f"| {row['topology']} | {row['operation']} | {row['axis']} | {row['slope']:.3f} |"
        for row in analysis["slopes"]
    )
    lines.extend(("", "## Problems", ""))
    if analysis["problems"]:
        lines.extend(
            f"- **{row['severity']}** `{row['operation']}`: {row['reason']}"
            for row in analysis["problems"]
        )
    else:
        lines.append("No automatic complexity violations were detected.")
    (output / "report.md").write_text("\n".join(lines) + "\n")


def environment_metadata() -> EnvironmentMetadata:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    return {
        "schema_version": SCHEMA_VERSION,
        "commit": commit,
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "page_size": os.sysconf("SC_PAGE_SIZE"),
        "relics_version": importlib.metadata.version("relics-ecs"),
    }


def run_parent(args: argparse.Namespace) -> int:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    for old in output.glob("worker-*.jsonl"):
        old.unlink()
    (output / "environment.json").write_text(
        json.dumps(environment_metadata(), indent=2, sort_keys=True) + "\n"
    )
    worker_failures: list[WorkerFailure] = []
    for entities in POWERS_OF_TEN:
        if entities > args.max_entities:
            continue
        if not any(
            edges <= args.max_edges and edges <= entities * (entities - 1)
            for edges in POWERS_OF_TEN
        ):
            continue
        for topology in TOPOLOGIES:
            command = [
                sys.executable,
                "-m",
                "benchmarks.world_scale",
                "--worker",
                "--entities",
                str(entities),
                "--max-edges",
                str(args.max_edges),
                "--topology",
                topology,
                "--output",
                str(output),
            ]
            if args.include_persistence:
                command.append("--include-persistence")
            completed = subprocess.run(command, check=False)
            if completed.returncode:
                worker_failures.append(
                    {
                        "entities": entities,
                        "topology": topology,
                        "returncode": completed.returncode,
                    }
                )
    rows = load_measurements(sorted(output.glob("worker-*.jsonl")))
    analysis = analyze(rows)
    analysis["worker_failures"] = worker_failures
    analysis["impossible_points"] = impossible_points(
        max_entities=args.max_entities, max_edges=args.max_edges
    )
    write_outputs(output, rows, analysis)
    if args.fail_on_regression and (analysis["regressions"] or worker_failures):
        return 1
    return 0


def run_profile(args: argparse.Namespace) -> int:
    if args.edges > args.entities * (args.entities - 1):
        raise SystemExit("requested edge count is not feasible")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    built = build_world(args.entities)
    add_edges(built, 0, args.edges, args.topology)
    point = MatrixPoint(args.entities, args.edges, args.topology)
    graph_source_index, graph_target_index = edge_pair(0, args.entities, args.topology)
    graph_spec = GraphQuerySpec(
        terms=(EdgeTerm(source="source", edge="BenchmarkEdge", target="target"),),
        bindings={
            "source": str(built.ids[graph_source_index]),
            "target": str(built.ids[graph_target_index]),
        },
        select=("source", "target"),
    )
    graph_executor = GraphQueryExecutor(PluginRegistry((BENCHMARK_PLUGIN,)))
    snapshot = output / "profile-world.json"
    operations: dict[str, Callable[[], object]] = {
        "bounded_graph_query": lambda: graph_executor.execute(
            built.actor.world, graph_spec
        ),
        "full_invariant_validation": lambda: validate_core_invariants(built.actor.world),
        "idle_tick": lambda: asyncio.run(built.actor.tick(0)),
        "serialize_world": lambda: len(serialize_world(built.actor)["entities"]),
        "save_world": lambda: save_world(
            built.actor,
            snapshot,
            meta=WorldMeta(seed="benchmark", plugins=(BENCHMARK_PLUGIN.id,)),
            backup_count=0,
        ),
        "mutation_component_high_degree": lambda: execute_mutation_plan(
            built.actor.world,
            MutationPlan(
                (
                    SetComponent(
                        _degree_extremes(built)[1], BenchmarkDenseComponent(42)
                    ),
                )
            ),
        ),
    }
    if args.operation not in operations:
        raise SystemExit(f"unknown profile operation: {args.operation}")
    profile_path = output / (
        f"{args.operation}-{point.entities}-{point.edges}-{point.topology}.prof"
    )
    profiler = cProfile.Profile()
    profiler.enable()
    operations[args.operation]()
    profiler.disable()
    profiler.dump_stats(profile_path)
    for path in output.glob("profile-world.json*"):
        path.unlink(missing_ok=True)
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("mode", nargs="?", choices=("smoke", "full", "profile"), default="smoke")
    result.add_argument("--output", default="artifacts/performance")
    result.add_argument("--max-entities", type=int)
    result.add_argument("--max-edges", type=int)
    result.add_argument("--include-persistence", action="store_true")
    result.add_argument("--fail-on-regression", action="store_true")
    result.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    result.add_argument("--entities", type=int, default=10)
    result.add_argument("--edges", type=int, default=1)
    result.add_argument("--topology", choices=TOPOLOGIES, default="balanced")
    result.add_argument("--operation", default="full_invariant_validation")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.worker:
        return run_worker(args)
    if args.mode == "profile":
        return run_profile(args)
    if args.max_entities is None:
        args.max_entities = 10_000 if args.mode == "smoke" else 1_000_000
    if args.max_edges is None:
        args.max_edges = 10_000 if args.mode == "smoke" else 1_000_000
    if args.mode == "full":
        args.include_persistence = True
    return run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
