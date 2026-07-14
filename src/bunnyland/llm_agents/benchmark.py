"""Fixed-snapshot controller comparison harness."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from relics import Component

from ..core.commands import CommitStatus
from ..core.components import CharacterComponent
from ..core.ecs import parse_entity_id, spawn_entity
from ..persistence import load_world
from ..plugins import PluginRegistry, collect_persona_fragments
from ..prompts.builder import PromptBuilder
from .agent import CharacterAgent
from .dispatch import ControllerDispatch, Decision


@dataclass(frozen=True)
class ControllerBenchmarkCase:
    """One controller implementation to run from the shared canonical snapshot."""

    name: str
    family: str
    controller_factory: Callable[[], Component]
    agent_factory: Callable[[], CharacterAgent]


@dataclass(frozen=True)
class ControllerBenchmarkResult:
    case: str
    family: str
    snapshot_sha256: str
    world_seed: str
    turns: int
    decisions: tuple[Decision, ...]
    attempted_actions: int
    structurally_valid_actions: int
    committed_commands: int
    rejected_commands: int
    recovered_rejections: int
    trace_complete: bool
    elapsed_seconds: float

    @property
    def structural_validity_rate(self) -> float:
        if not self.attempted_actions:
            return 1.0
        return self.structurally_valid_actions / self.attempted_actions

    @property
    def rejection_recovery_rate(self) -> float:
        if not self.rejected_commands:
            return 1.0
        return self.recovered_rejections / self.rejected_commands


async def run_fixed_snapshot_controller_benchmark(
    snapshot_path: str | Path,
    *,
    registry: PluginRegistry,
    character_id: str,
    cases: tuple[ControllerBenchmarkCase, ...],
    turns: int = 1,
) -> tuple[ControllerBenchmarkResult, ...]:
    """Run every controller from an independent load of one checksummed snapshot."""

    if turns < 1:
        raise ValueError("benchmark turns must be positive")
    path = Path(snapshot_path)
    snapshot_hash = sha256(path.read_bytes()).hexdigest()
    results = []
    for case in cases:
        actor, meta = load_world(path, registry=registry)
        parsed_character = parse_entity_id(character_id)
        if parsed_character is None or not actor.world.has_entity(parsed_character):
            raise ValueError("benchmark character does not exist in snapshot")
        character = actor.world.get_entity(parsed_character)
        if not character.has_component(CharacterComponent):
            raise ValueError("benchmark entity is not a character")
        controller = spawn_entity(actor.world, [case.controller_factory()])
        actor.assign_controller(parsed_character, controller.id)
        plugins = tuple(actor.plugins.plugins.values())
        dispatch = ControllerDispatch(
            actor,
            PromptBuilder(
                actor.world,
                fragment_providers=actor.prompt_fragment_providers,
                persona_providers=collect_persona_fragments(plugins),
            ),
            case.agent_factory(),
        )
        decisions: list[Decision] = []
        started = time.perf_counter()
        for _turn in range(turns):
            immediate = await dispatch.run_once()
            pending = await dispatch.await_pending()
            turn_decisions = [*immediate, *pending]
            if any(decision.command_id for decision in turn_decisions):
                await actor.tick(0)
            decisions.extend(
                decision.with_receipt(
                    actor.receipt_for(decision.command_id) if decision.command_id else None
                )
                for decision in turn_decisions
            )
        elapsed = time.perf_counter() - started
        attempted = [decision for decision in decisions if decision.selected_action is not None]
        structurally_valid = [
            decision
            for decision in attempted
            if decision.command_id is not None and decision.submission_accepted is True
        ]
        committed = [
            decision
            for decision in decisions
            if decision.receipt_status == CommitStatus.COMMITTED.value
        ]
        rejected = [
            index
            for index, decision in enumerate(decisions)
            if decision.receipt_status
            in {CommitStatus.REJECTED.value, "policy_rejected"}
        ]
        recovered = sum(
            any(
                candidate.receipt_status == CommitStatus.COMMITTED.value
                for candidate in decisions[index + 1 : index + 3]
            )
            for index in rejected
        )
        results.append(
            ControllerBenchmarkResult(
                case=case.name,
                family=case.family,
                snapshot_sha256=snapshot_hash,
                world_seed=meta.seed,
                turns=turns,
                decisions=tuple(decisions),
                attempted_actions=len(attempted),
                structurally_valid_actions=len(structurally_valid),
                committed_commands=len(committed),
                rejected_commands=len(rejected),
                recovered_rejections=recovered,
                trace_complete=all(_trace_complete(decision) for decision in decisions),
                elapsed_seconds=elapsed,
            )
        )
    return tuple(results)


def _trace_complete(decision: Decision) -> bool:
    if not decision.governing_pressure or decision.input_epoch < 0:
        return False
    if decision.selected_action is None:
        return decision.receipt_status == "wait"
    if not decision.candidate_actions:
        return False
    if decision.command_id is None:
        return decision.receipt_status == "policy_rejected"
    return bool(decision.receipt_status)


__all__ = [
    "ControllerBenchmarkCase",
    "ControllerBenchmarkResult",
    "run_fixed_snapshot_controller_benchmark",
]
