"""Bounded, collection-time checks for live world structure."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Literal

from relics import Component, Edge, EntityId, World

from ..core import (
    CharacterComponent,
    ClaimedComponent,
    ControlledBy,
    SubmittedCommand,
    TransientControllerComponent,
    WorldActor,
    parse_entity_id,
)

type Severity = Literal["error", "warning"]
type IssueKey = tuple[str, Severity]
type ComponentMap = Mapping[type[Component], Component]
type RelationshipKey = tuple[EntityId, type[Edge], EntityId]

HEALTH_CHECKS: tuple[IssueKey, ...] = (
    ("dangling_relationship", "error"),
    ("relationship_index_mismatch", "error"),
    ("controller_source_not_character", "error"),
    ("character_without_controller", "warning"),
    ("character_has_multiple_controllers", "error"),
    ("invalid_controller_target", "error"),
    ("multiple_controller_components", "error"),
    ("transient_marker_without_controller", "error"),
    ("detached_transient_controller", "error"),
    ("detached_controller", "warning"),
    ("invalid_claim_controller_cardinality", "error"),
    ("claim_character_mismatch", "error"),
    ("duplicate_command_id", "error"),
    ("queued_command_missing_character", "error"),
    ("queued_command_target_not_character", "error"),
    ("queued_command_from_future", "error"),
    ("expired_queued_command", "warning"),
)

_SEVERITY_BY_CHECK: dict[str, Severity] = dict(HEALTH_CHECKS)


def _increment(counts: Counter[IssueKey], check: str) -> None:
    counts[(check, _SEVERITY_BY_CHECK[check])] += 1


def _controller_components(components: ComponentMap) -> tuple[type[Component], ...]:
    return tuple(
        component_type
        for component_type in components
        if component_type.__name__.endswith("ControllerComponent")
        and component_type is not TransientControllerComponent
    )


def _relationship_maps(
    world: World,
) -> tuple[dict[RelationshipKey, Edge], dict[RelationshipKey, Edge]]:
    outgoing = {
        (source_id, edge_type, target_id): edge
        for source_id, edge_types in world._relationships.items()
        for edge_type, targets in edge_types.items()
        for target_id, edge in targets.items()
    }
    incoming = {
        (source_id, edge_type, target_id): edge
        for target_id, edge_types in world._incoming_relationships.items()
        for edge_type, sources in edge_types.items()
        for source_id, edge in sources.items()
    }
    return outgoing, incoming


def _check_relationships(world: World, counts: Counter[IssueKey]) -> None:
    live_ids = set(world._entities)
    outgoing, incoming = _relationship_maps(world)
    for source_id, _edge_type, target_id in outgoing.keys() | incoming.keys():
        key = (source_id, _edge_type, target_id)
        if source_id not in live_ids or target_id not in live_ids:
            _increment(counts, "dangling_relationship")
        if outgoing.get(key) != incoming.get(key):
            _increment(counts, "relationship_index_mismatch")


def _check_controllers(world: World, counts: Counter[IssueKey]) -> None:
    controller_sources: dict[EntityId, list[EntityId]] = {}
    for source_id, components in world._entities.items():
        targets = tuple(
            world._relationships.get(source_id, {}).get(ControlledBy, {})
        )
        is_character = CharacterComponent in components
        if targets and not is_character:
            _increment(counts, "controller_source_not_character")
        if is_character and not targets:
            _increment(counts, "character_without_controller")
        if is_character and len(targets) > 1:
            _increment(counts, "character_has_multiple_controllers")
        for target_id in targets:
            controller_sources.setdefault(target_id, []).append(source_id)
            target_components = world._entities.get(target_id)
            if target_components is not None and not _controller_components(target_components):
                _increment(counts, "invalid_controller_target")

    for entity_id, components in world._entities.items():
        controller_components = _controller_components(components)
        if len(controller_components) > 1:
            _increment(counts, "multiple_controller_components")
        transient = TransientControllerComponent in components
        if transient and not controller_components:
            _increment(counts, "transient_marker_without_controller")
        if not controller_components:
            continue
        sources = controller_sources.get(entity_id, [])
        if not sources:
            _increment(
                counts,
                "detached_transient_controller" if transient else "detached_controller",
            )
        claim = components.get(ClaimedComponent)
        if claim is None:
            continue
        if len(sources) != 1:
            _increment(counts, "invalid_claim_controller_cardinality")
        elif claim.character_id != str(sources[0]):
            _increment(counts, "claim_character_mismatch")


def _queued_commands(actor: WorldActor) -> list[SubmittedCommand]:
    commands = actor.pending_submissions()
    for character_id in actor.queues.characters_with_pending():
        commands.extend(actor.queues.pending(character_id))
    return commands


def _check_queues(actor: WorldActor, counts: Counter[IssueKey]) -> None:
    seen_commands: set[tuple[str, str]] = set()
    for command in _queued_commands(actor):
        command_key = (command.character_id, command.command_id)
        if command_key in seen_commands:
            _increment(counts, "duplicate_command_id")
        seen_commands.add(command_key)
        character_id = parse_entity_id(command.character_id)
        if character_id is None or not actor.world.has_entity(character_id):
            _increment(counts, "queued_command_missing_character")
        elif not actor.world.get_entity(character_id).has_component(CharacterComponent):
            _increment(counts, "queued_command_target_not_character")
        if command.submitted_at_epoch > actor.epoch:
            _increment(counts, "queued_command_from_future")
        if command.expires_at_epoch is not None and command.expires_at_epoch < actor.epoch:
            _increment(counts, "expired_queued_command")


def collect_world_health_issues(actor: WorldActor) -> Mapping[tuple[str, str], int]:
    """Return every bounded health series, including explicit zero values.

    This is an O(entities + relationships + queued commands) audit. It intentionally uses
    Relics' private relationship indexes because the public API does not enumerate edge
    types; keeping that access here makes the optional cost and compatibility boundary
    explicit.
    """

    counts: Counter[IssueKey] = Counter({check: 0 for check in HEALTH_CHECKS})
    _check_relationships(actor.world, counts)
    _check_controllers(actor.world, counts)
    _check_queues(actor, counts)
    return dict(counts)


__all__ = ["HEALTH_CHECKS", "collect_world_health_issues"]
