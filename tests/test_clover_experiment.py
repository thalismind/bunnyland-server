"""Public Clover City experiment artifact regressions."""

import hashlib
import json

import pytest

from benchmarks.clover_city import PROBE_NAMES, export_experiment


async def test_clover_experiment_exports_and_reproduces_from_immutable_snapshot(tmp_path):
    exported = tmp_path / "exported"
    results = await export_experiment(
        exported,
        implementation_commit="test-implementation-commit",
    )

    assert {result.family for result in results} == {
        "scripted",
        "behavior_tree",
        "goal_directed",
        "llm",
    }
    assert all(result.rejected_commands == 1 for result in results)
    assert all(result.recovered_rejections == 1 for result in results)
    assert all(dict(result.outcomes) == {name: True for name in PROBE_NAMES} for result in results)

    manifest = json.loads((exported / "manifest.json").read_text())
    assert manifest["implementation_commit"] == "test-implementation-commit"
    assert manifest["expected_probes"] == list(PROBE_NAMES)
    assert manifest["final_state_reload_verified"] == [
        "behavior_tree",
        "goal_directed",
        "llm",
        "scripted",
    ]
    for name, expected_hash in manifest["artifacts_sha256"].items():
        assert hashlib.sha256((exported / name).read_bytes()).hexdigest() == expected_hash

    reproduced = tmp_path / "reproduced"
    reproduced_results = await export_experiment(
        reproduced,
        snapshot=exported / "initial-world.json",
        implementation_commit="test-implementation-commit",
    )
    assert [result.snapshot_sha256 for result in reproduced_results] == [
        result.snapshot_sha256 for result in results
    ]
    assert [result.outcomes for result in reproduced_results] == [
        result.outcomes for result in results
    ]

    with pytest.raises(ValueError, match="output directory is not empty"):
        await export_experiment(
            exported,
            implementation_commit="test-implementation-commit",
        )
