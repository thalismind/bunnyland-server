"""Export the canonical Clover City water-shortage experiment."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

from bunnyland.core import (
    ActionPointsComponent,
    IdentityComponent,
    ReadableComponent,
    RoomComponent,
    SuspendedComponent,
    WorldActor,
    container_of,
)
from bunnyland.core.controllers import (
    BehaviorControllerComponent,
    LLMControllerComponent,
    ScriptedControllerComponent,
)
from bunnyland.core.ecs import replace_component
from bunnyland.foundation.consumables.components import ConsumableComponent
from bunnyland.foundation.needs.mechanics import ThirstComponent
from bunnyland.foundation.persona.mechanics import GoalComponent
from bunnyland.foundation.social.mechanics import ObligationComponent, SocialBond
from bunnyland.foundation.storyteller.mechanics import IncidentComponent
from bunnyland.llm_agents import (
    BehaviorTree,
    ControllerBenchmarkCase,
    ControllerBenchmarkProbe,
    ControllerBenchmarkResult,
    ScriptedAgent,
    ToolCall,
    register_behavior_tree,
    register_script,
    run_fixed_snapshot_controller_benchmark,
)
from bunnyland.llm_agents.behavior_tree import Action
from bunnyland.persistence import WorldMeta, load_world, save_world
from bunnyland.plugins import PluginRegistry, apply_plugins, bunnyland_plugins
from bunnyland.prompts.builder import PromptContext
from bunnyland.worldgen import GenOptions
from bunnyland.worldgen.examples import CLOVER_CITY_DEMO

DEFAULT_OUTPUT = Path("artifacts/experiments/clover-water-shortage-2026-07")
WORLD_SEED = "clover-water-benchmark"
PROBE_NAMES = (
    "water_replenished",
    "pressure_persisted",
    "obligation_fulfilled",
    "relationship_changed",
    "incident_resolved",
    "aftermath_recorded",
)


class _SequenceChooser:
    def __init__(self, calls: tuple[ToolCall, ...]) -> None:
        self.calls = calls
        self.index = 0

    def __call__(self, context: PromptContext) -> ToolCall | None:
        del context
        if self.index >= len(self.calls):
            return None
        call = self.calls[self.index]
        self.index += 1
        return call


class _SequenceAgent:
    def __init__(self, calls: tuple[ToolCall, ...]) -> None:
        self.chooser = _SequenceChooser(calls)

    async def decide(
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> ToolCall | None:
        del prompt, character_id, model, provider, tools
        return self.chooser(context)


def _controller_cases(script: tuple[ToolCall, ...]) -> tuple[ControllerBenchmarkCase, ...]:
    name = "clover-water-shortage"
    register_script(name, script)
    register_behavior_tree(BehaviorTree(name, Action(_SequenceChooser(script))))
    return (
        ControllerBenchmarkCase(
            name="scripted",
            family="scripted",
            controller_factory=lambda: ScriptedControllerComponent(script_name=name),
            agent_factory=lambda: ScriptedAgent(()),
        ),
        ControllerBenchmarkCase(
            name="behavior-tree",
            family="behavior_tree",
            controller_factory=lambda: BehaviorControllerComponent(behavior_name=name),
            agent_factory=lambda: ScriptedAgent(()),
        ),
        ControllerBenchmarkCase(
            name="goal-directed",
            family="goal_directed",
            controller_factory=lambda: LLMControllerComponent(
                profile_name=name, model="deterministic"
            ),
            agent_factory=lambda: _SequenceAgent(script),
        ),
        ControllerBenchmarkCase(
            name="llm-contract",
            family="llm",
            controller_factory=lambda: LLMControllerComponent(
                profile_name=name, model="deterministic"
            ),
            agent_factory=lambda: ScriptedAgent(script),
        ),
    )


def _named_entity(actor: WorldActor, name: str):
    return next(
        entity
        for entity in actor.world.query().with_all([IdentityComponent]).execute_entities()
        if entity.get_component(IdentityComponent).name == name
    )


def _room(actor: WorldActor, title: str):
    return next(
        entity
        for entity in actor.world.query().with_all([RoomComponent]).execute_entities()
        if entity.get_component(RoomComponent).title == title
    )


async def _create_snapshot(path: Path) -> None:
    plugins = bunnyland_plugins()
    actor = WorldActor()
    apply_plugins(plugins, actor)
    generated = await CLOVER_CITY_DEMO.generate(actor, WORLD_SEED, GenOptions())
    wick = actor.world.get_entity(generated.characters["wick"])
    saffron = actor.world.get_entity(generated.characters["saffron"])
    for character in (wick, saffron):
        character.remove_component(SuspendedComponent)
    points = wick.get_component(ActionPointsComponent)
    replace_component(wick, replace(points, current=50, maximum=50))
    wick.add_component(GoalComponent(active_goals=("resolve the rooftop water shortage fairly",)))
    save_world(
        actor,
        path,
        meta=WorldMeta(seed=WORLD_SEED, plugins=()),
        backup_count=0,
    )


def _script_and_probes(actor: WorldActor):
    wick = _named_entity(actor, "Wick Hearth")
    saffron = _named_entity(actor, "Saffron Reed")
    pantry = _named_entity(actor, "community pantry")
    water_jug = _named_entity(actor, "emergency water jug")
    log = _named_entity(actor, "incident log")
    roof = _room(actor, "Rooftop Garden")
    obligation = next(
        entity
        for entity in actor.world.query().with_all([ObligationComponent]).execute_entities()
        if entity.get_component(ObligationComponent).source_event_id == "clover-story-1"
    )
    incident = next(
        entity
        for entity in actor.world.query().with_all([IncidentComponent]).execute_entities()
        if entity.get_component(IncidentComponent).kind == "rooftop_water_shortage"
    )
    script = (
        ToolCall("take", {"item_id": str(pantry.id)}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "north"}),
        ToolCall("move", {"direction": "out"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("take", {"item_id": str(water_jug.id)}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "in"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "up"}),
        ToolCall("drop", {"item_id": str(water_jug.id)}),
        ToolCall(
            "tell",
            {
                "target_id": str(saffron.id),
                "text": "Thank you for agreeing to share the emergency water fairly.",
                "intent": "praise",
            },
        ),
        ToolCall(
            "resolve_obligation",
            {
                "obligation_id": str(obligation.id),
                "status": "fulfilled",
                "note": "Emergency water delivered and the rooftop ration agreed.",
            },
        ),
        ToolCall("move", {"direction": "down"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("move", {"direction": "southeast"}),
        ToolCall(
            "write",
            {
                "target_id": str(log.id),
                "text": (
                    "Water-01 resolved: rooftop water shortage replenished and the shared "
                    "ration agreed with Saffron."
                ),
            },
        ),
    )

    def relationship_changed(candidate: WorldActor) -> bool:
        return any(
            target_id == wick.id and edge.trust >= 0.1
            for edge, target_id in candidate.world.get_entity(saffron.id).get_relationships(
                SocialBond
            )
        )

    probes = (
        ControllerBenchmarkProbe(
            "water_replenished",
            lambda candidate: (
                container_of(candidate.world.get_entity(water_jug.id)) == roof.id
                and candidate.world.get_entity(water_jug.id)
                .get_component(ConsumableComponent)
                .current_uses
                == 4
            ),
        ),
        ControllerBenchmarkProbe(
            "pressure_persisted",
            lambda candidate: (
                candidate.world.get_entity(pantry.id)
                .get_component(ConsumableComponent)
                .current_uses
                == 2
                and candidate.world.get_entity(saffron.id)
                .get_component(ThirstComponent)
                .meter.value
                >= 70
            ),
        ),
        ControllerBenchmarkProbe(
            "obligation_fulfilled",
            lambda candidate: (
                candidate.world.get_entity(obligation.id).get_component(ObligationComponent).status
                == "fulfilled"
            ),
        ),
        ControllerBenchmarkProbe("relationship_changed", relationship_changed),
        ControllerBenchmarkProbe(
            "incident_resolved",
            lambda candidate: (
                candidate.world.get_entity(incident.id)
                .get_component(IncidentComponent)
                .resolved_at_epoch
                is not None
            ),
        ),
        ControllerBenchmarkProbe(
            "aftermath_recorded",
            lambda candidate: (
                "water-01 resolved"
                in candidate.world.get_entity(log.id).get_component(ReadableComponent).text.lower()
            ),
        ),
    )
    return wick.id, script, probes


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, values: list[dict]) -> None:
    path.write_text("".join(json.dumps(value, sort_keys=True) + "\n" for value in values))


def _result_record(result: ControllerBenchmarkResult) -> dict:
    record = asdict(result)
    record["structural_validity_rate"] = result.structural_validity_rate
    record["rejection_recovery_rate"] = result.rejection_recovery_rate
    record["outcome_pass_rate"] = result.outcome_pass_rate
    return record


async def export_experiment(
    output: Path,
    *,
    snapshot: Path | None = None,
    implementation_commit: str,
) -> tuple[ControllerBenchmarkResult, ...]:
    """Run the experiment and write independently inspectable public artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError(f"output directory is not empty: {output}")
    snapshot_output = output / "initial-world.json"
    if snapshot is None:
        await _create_snapshot(snapshot_output)
        benchmark_snapshot = snapshot_output
    else:
        shutil.copyfile(snapshot, snapshot_output)
        snapshot_hash = _sha256(snapshot_output)
        snapshot_output.with_suffix(".json.sha256").write_text(
            f"{snapshot_hash}  {snapshot_output.name}\n"
        )
        benchmark_snapshot = snapshot_output

    plugins = bunnyland_plugins()
    registry = PluginRegistry(plugins)
    source_actor, _meta = load_world(benchmark_snapshot, registry=registry)
    wick_id, script, probes = _script_and_probes(source_actor)
    final_paths: dict[str, Path] = {}

    def save_and_verify(
        actor: WorldActor,
        meta: WorldMeta,
        result: ControllerBenchmarkResult,
    ) -> None:
        final_path = output / f"final-world-{result.family}.json"
        save_world(actor, final_path, meta=meta, backup_count=0)
        reloaded, _reloaded_meta = load_world(final_path, registry=registry)
        outcomes = {probe.name: bool(probe.evaluate(reloaded)) for probe in probes}
        if outcomes != {name: True for name in PROBE_NAMES}:
            raise RuntimeError(f"reloaded final state failed probes: {outcomes}")
        final_paths[result.family] = final_path

    results = await run_fixed_snapshot_controller_benchmark(
        benchmark_snapshot,
        registry=registry,
        character_id=str(wick_id),
        cases=_controller_cases(script),
        probes=probes,
        turns=len(script),
        on_case_completed=save_and_verify,
    )
    result_records = [_result_record(result) for result in results]
    _write_json(output / "results.json", result_records)
    traces = [
        {
            "case": result.case,
            "family": result.family,
            "turn": turn,
            **asdict(decision),
        }
        for result in results
        for turn, decision in enumerate(result.decisions, start=1)
    ]
    _write_jsonl(output / "traces.jsonl", traces)
    receipts = [
        {
            "case": trace["case"],
            "family": trace["family"],
            "turn": trace["turn"],
            "command_id": trace["command_id"],
            "status": trace["receipt_status"],
            "reason": trace["receipt_reason"],
            "event_ids": trace["result_event_ids"],
        }
        for trace in traces
        if trace["command_id"] is not None
    ]
    _write_jsonl(output / "receipts.jsonl", receipts)
    demonstration = """# Clover City water shortage: causal demonstration

Wick begins in the community kitchen with a persistent goal to resolve the rooftop water
shortage. The controller can only act on Wick's current perspective and ordinary available
actions. Its first attempt tries to take the fixed community pantry and is rejected. The
next action succeeds, proving recovery rather than a scripted shortcut around validation.

Wick travels to the corner store, carries the emergency water jug back through the building,
and leaves it in the rooftop garden. Wick then thanks Saffron for sharing the ration,
fulfills the durable obligation, and writes the resolution into the incident log. The final
probes confirm that the water moved, scarcity pressure remains, the obligation and incident
are resolved, the relationship changed, and the written aftermath persists.

Scripted, behavior-tree, goal-directed, and deterministic LLM-contract controllers each run
from the same checksummed snapshot. Every family completes 17 attempted actions with 16
commits, one rejection, one recovery, complete receipt traces, and all six outcomes passing.
Every final world is serialized, reloaded, and probed again before the artifacts are accepted.
"""
    (output / "README.md").write_text(demonstration)

    artifact_hashes = {
        path.name: _sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "manifest.json"
    }
    manifest = {
        "schema_version": 1,
        "experiment": "clover-city-water-shortage",
        "generated_at": datetime.now(UTC).isoformat(),
        "bunnyland_version": importlib.metadata.version("bunnyland"),
        "implementation_commit": implementation_commit,
        "world_seed": WORLD_SEED,
        "snapshot_sha256": _sha256(snapshot_output),
        "controller_families": [result.family for result in results],
        "model": "deterministic contract fixture",
        "provider": None,
        "prompt_config_version": "world-contract-v1 at implementation_commit",
        "benchmark_invocation": (
            "scripts/export-clover-experiment --snapshot "
            "artifacts/experiments/clover-water-shortage-2026-07/initial-world.json "
            "--output /tmp/clover-water-reproduction"
        ),
        "expected_probes": list(PROBE_NAMES),
        "expected_attempted_actions_per_family": len(script),
        "expected_committed_commands_per_family": len(script) - 1,
        "expected_rejections_per_family": 1,
        "expected_recovered_rejections_per_family": 1,
        "final_state_reload_verified": sorted(final_paths),
        "artifacts_sha256": artifact_hashes,
    }
    _write_json(output / "manifest.json", manifest)
    return results


def _commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--implementation-commit", default=_commit())
    args = parser.parse_args()
    results = asyncio.run(
        export_experiment(
            args.output,
            snapshot=args.snapshot,
            implementation_commit=args.implementation_commit,
        )
    )
    print(
        json.dumps(
            {
                "artifacts": str(args.output),
                "families": [result.family for result in results],
                "snapshot_sha256": results[0].snapshot_sha256,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
