"""Behavioral tests for the standalone world-scale benchmark harness."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from benchmarks.world_scale import (
    MatrixPoint,
    Measurement,
    _isolated_timed_once,
    _unused_edge_pair,
    add_edges,
    analyze,
    build_world,
    count_edges,
    edge_pair,
    environment_metadata,
    feasible_points,
    impossible_points,
    load_measurements,
    log_slope,
    measure,
    percentile,
    write_outputs,
)


def test_feasible_matrix_contains_only_unique_directed_edge_capacities():
    points = feasible_points(max_entities=100, max_edges=1_000)

    assert points[0] == MatrixPoint(10, 1, "balanced")
    assert all(point.edges <= point.entities * (point.entities - 1) for point in points)
    assert {(point.entities, point.edges) for point in points} == {
        (10, 1),
        (10, 10),
        (100, 1),
        (100, 10),
        (100, 100),
        (100, 1_000),
    }
    assert impossible_points(max_entities=100, max_edges=1_000) == (
        (1, 1),
        (1, 10),
        (1, 100),
        (1, 1_000),
        (10, 100),
        (10, 1_000),
    )


@pytest.mark.parametrize("topology", ["balanced", "concentrated"])
def test_edge_pair_is_unique_and_covers_capacity(topology):
    pairs = {edge_pair(index, 10, topology) for index in range(90)}

    assert len(pairs) == 90
    assert all(0 <= source < 10 and 0 <= target < 10 for source, target in pairs)
    assert all(source != target for source, target in pairs)


def test_edge_pair_rejects_bad_inputs():
    with pytest.raises(ValueError, match="capacity"):
        edge_pair(0, 1, "balanced")
    with pytest.raises(ValueError, match="unknown topology"):
        edge_pair(0, 2, "diagonal")


@pytest.mark.parametrize("topology", ["balanced", "concentrated"])
def test_generated_world_has_exact_counts_and_projection_fixtures(topology):
    built = build_world(10)
    add_edges(built, 0, 90, topology)

    assert len(built.actor.world._entities) == 10
    assert count_edges(built.actor) == 90
    assert built.room_id is not None
    assert built.character_id is not None
    assert all(
        source != target
        for source, edge_types in built.actor.world._relationships.items()
        for targets in edge_types.values()
        for target in targets
    )
    assert _unused_edge_pair(built) is None


def test_unused_edge_pair_uses_distinct_low_degree_endpoints():
    built = build_world(10)
    add_edges(built, 0, 10, "concentrated")

    source, target = _unused_edge_pair(built)

    assert source != target
    assert source != built.ids[0]
    assert target != built.ids[0]


def test_measurement_records_batch_statistics():
    calls = 0

    def operation():
        nonlocal calls
        calls += 1

    result = measure(
        MatrixPoint(2, 1, "balanced"),
        "counter",
        operation,
        samples=3,
        target_batch_seconds=0,
        max_iterations=1,
    )

    assert result.status == "ok"
    assert result.iterations == 3
    assert result.median_ns is not None
    assert result.p95_ns is not None
    assert calls == 4
    assert percentile([10, 20, 30], 0.95) == 30
    with pytest.raises(ValueError, match="no values"):
        percentile([], 0.5)


def test_isolated_measurement_returns_success_and_failure(tmp_path):
    point = MatrixPoint(2, 1, "balanced")
    success = _isolated_timed_once(point, "success", lambda: 1, output_dir=tmp_path)

    def explode():
        raise MemoryError("synthetic exhaustion")

    failure = _isolated_timed_once(point, "failure", explode, output_dir=tmp_path)

    assert success.status == "ok"
    assert failure.status == "failed"
    assert "synthetic exhaustion" in failure.detail
    assert list(tmp_path.iterdir()) == []


def _row(entities, elapsed, *, operation="point_lookup", edges=1):
    return asdict(
        Measurement(
            schema_version=1,
            entities=entities,
            edges=edges,
            topology="balanced",
            operation=operation,
            status="ok",
            median_ns=elapsed,
            p95_ns=elapsed,
            iterations=1,
            operations_per_second=1.0,
            rss_bytes=1,
            peak_rss_bytes=1,
        )
    )


def test_analysis_flags_world_and_edge_scaling_for_bounded_operations():
    rows = [
        _row(size, size * 1_000) for size in (2, 20, 200)
    ] + [
        _row(size, 1_000, operation="exact_edge_lookup")
        for size in (2, 20, 200)
    ] + [
        _row(200, edges * 1_000, operation="exact_edge_lookup", edges=edges)
        for edges in (10, 100)
    ]

    analysis = analyze(rows)

    assert log_slope([(2, 2), (20, 20), (200, 200)]) == pytest.approx(1.0)
    assert {problem["axis"] for problem in analysis["problems"]} == {
        "entities_at_one_edge",
        "edges_at_largest_world",
    }
    assert len(analysis["regressions"]) == 2


def test_analysis_records_failed_measurements():
    row = _row(2, 1)
    row.update(status="failed", median_ns=None, detail="MemoryError: exhausted")

    analysis = analyze([row])

    assert analysis["failures"] == [row]
    assert analysis["problems"][0]["severity"] == "high"
    assert analysis["regressions"] == analysis["problems"]


def test_results_round_trip_and_report(tmp_path):
    rows = [_row(2, 100)]
    source = tmp_path / "worker-2-balanced.jsonl"
    source.write_text(json.dumps(rows[0]) + "\n")
    loaded = load_measurements([source, tmp_path / "missing.jsonl"])

    write_outputs(tmp_path, loaded, analyze(loaded))

    assert loaded == rows
    assert (tmp_path / "results.jsonl").exists()
    assert "point_lookup" in (tmp_path / "summary.csv").read_text()
    assert "point_lookup_median_ms" in (tmp_path / "points.csv").read_text()
    assert "No automatic complexity violations" in (tmp_path / "report.md").read_text()


def test_environment_metadata_uses_published_relics_distribution(monkeypatch):
    requested: list[str] = []
    monkeypatch.setattr(
        "benchmarks.world_scale.importlib.metadata.version",
        lambda name: requested.append(name) or "0.1.1",
    )

    metadata = environment_metadata()

    assert requested == ["relics-ecs"]
    assert metadata["relics_version"] == "0.1.1"
