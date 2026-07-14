"""Claim-scoped, plugin-owned perspective query catalogue."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class PerspectiveQueryInput(BaseModel):
    actor_id: str


class AvailableActionsInput(PerspectiveQueryInput):
    pass


class ValidTargetsInput(PerspectiveQueryInput):
    action: str


class WhyNotInput(ValidTargetsInput):
    target: str | None = None


class WhatChangedSinceInput(PerspectiveQueryInput):
    epoch: int = Field(ge=0)


class AvailableActionsOutput(RootModel[list[dict[str, Any]]]):
    pass


class TargetOption(BaseModel):
    id: str
    label: str
    kind: str


class ValidTargetsOutput(RootModel[dict[str, list[TargetOption]]]):
    pass


class ActionAvailabilityOutput(BaseModel):
    available: bool
    enough_action_points: bool
    enough_focus_points: bool
    has_required_target: bool
    meets_requirements: bool
    reason: str | None = None


class WhyNotOutput(BaseModel):
    available: bool
    reason: str | None = None
    availability: ActionAvailabilityOutput
    target_valid: bool | None = None


class WhatChangedSinceOutput(BaseModel):
    events: list[dict[str, Any]]
    complete: bool
    resync_required: bool
    requested_epoch: int
    available_after_epoch: int


class PerspectiveQueryResult(BaseModel):
    query: str
    owner: str
    actor_id: str
    world_epoch: int
    visibility: str
    output_type: str
    provenance: tuple[str, ...] = ()
    truncated: bool = False
    result: Any


class PerspectiveQueryRequest(BaseModel):
    query: str
    arguments: dict[str, Any] = Field(default_factory=dict)


QueryExecutor = Callable[[Any, PerspectiveQueryInput], tuple[Any, tuple[str, ...]]]


class PerspectiveQueryDefinition(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    name: str
    input_model: type[PerspectiveQueryInput]
    output_model: type[BaseModel]
    owner: str = ""
    visibility: Literal["claim", "public", "admin"] = "claim"
    result_limit: int = Field(default=100, gt=0)
    execution_budget_ms: float = Field(default=50.0, gt=0)
    required_indexes: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    execute: QueryExecutor


class PerspectiveQueryRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, PerspectiveQueryDefinition] = {}

    def register(self, definition: PerspectiveQueryDefinition, *, owner: str | None = None) -> None:
        owned = definition.model_copy(update={"owner": owner}) if owner else definition
        if owned.name in self._definitions:
            raise ValueError(f"duplicate perspective query {owned.name!r}")
        self._definitions[owned.name] = owned

    def definitions(self) -> tuple[PerspectiveQueryDefinition, ...]:
        return tuple(self._definitions[name] for name in sorted(self._definitions))

    def execute(
        self,
        actor: Any,
        name: str,
        arguments: Mapping[str, Any],
        *,
        actor_id: str,
        access: Literal["public", "claim", "admin"] = "claim",
    ) -> PerspectiveQueryResult:
        definition = self._definitions.get(name)
        if definition is None:
            raise ValueError(f"unknown perspective query {name!r}")
        allowed = {
            "public": {"public", "claim", "admin"},
            "claim": {"claim", "admin"},
            "admin": {"admin"},
        }
        if access not in allowed[definition.visibility]:
            raise PermissionError(
                f"perspective query {name!r} requires {definition.visibility} access"
            )
        available_indexes = set(getattr(actor, "perspective_index_names", ()))
        missing_indexes = set(definition.required_indexes) - available_indexes
        if missing_indexes:
            missing = ", ".join(sorted(missing_indexes))
            raise RuntimeError(
                f"perspective query {name!r} requires unavailable indexes: {missing}"
            )
        values = {**dict(arguments), "actor_id": actor_id}
        validated = definition.input_model.model_validate(values)
        started = time.perf_counter()
        result, runtime_provenance = definition.execute(actor, validated)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms > definition.execution_budget_ms:
            raise TimeoutError(
                f"perspective query {name!r} exceeded {definition.execution_budget_ms:g}ms budget"
            )
        validated_output = definition.output_model.model_validate(result)
        result = validated_output.model_dump(mode="json")
        result, truncated = _truncate_result(result, definition.result_limit)
        result = definition.output_model.model_validate(result).model_dump(mode="json")
        return PerspectiveQueryResult(
            query=name,
            owner=definition.owner,
            actor_id=actor_id,
            world_epoch=actor.epoch,
            visibility=definition.visibility,
            output_type=definition.output_model.__name__,
            provenance=(*definition.provenance, *runtime_provenance),
            truncated=truncated,
            result=result,
        )


def _truncate_result(result: Any, limit: int) -> tuple[Any, bool]:
    if isinstance(result, list):
        return result[:limit], len(result) > limit
    if isinstance(result, dict):
        truncated = False
        bounded = {}
        for key, value in result.items():
            if isinstance(value, list) and len(value) > limit:
                bounded[key] = value[:limit]
                truncated = True
            else:
                bounded[key] = value
        return bounded, truncated
    return result, False


def _projection(actor: Any, actor_id: str):
    from ..server.serialization import serialize_character_projection

    return serialize_character_projection(actor, actor_id)


def _available_actions(actor: Any, request: PerspectiveQueryInput):
    projection = _projection(actor, request.actor_id)
    return (
        [action.model_dump(mode="json") for action in projection.actions if action.available],
        ("character_projection.actions",),
    )


def _action_projection(actor: Any, request: ValidTargetsInput):
    projection = _projection(actor, request.actor_id)
    action = next(
        (item for item in projection.actions if item.command_type == request.action),
        None,
    )
    if action is None:
        raise ValueError(f"unknown action {request.action!r}")
    return projection, action


def _valid_targets(actor: Any, request: ValidTargetsInput):
    projection, action = _action_projection(actor, request)
    groups = {
        name: [candidate.model_dump(mode="json") for candidate in candidates]
        for name, candidates in projection.target_groups.items()
    }
    targets: dict[str, Any] = {}
    for argument in action.arguments:
        group = argument.target_group
        if group:
            targets[argument.key] = groups.get(group, [])
    return targets, ("character_projection.target_groups", f"action:{request.action}")


def _why_not(actor: Any, request: WhyNotInput):
    projection, action = _action_projection(actor, request)
    availability = {
        "available": action.available,
        "enough_action_points": action.enough_action_points,
        "enough_focus_points": action.enough_focus_points,
        "has_required_target": action.has_required_target,
        "meets_requirements": action.meets_requirements,
        "reason": action.unavailable_reason,
    }
    valid_targets, provenance = _valid_targets(actor, request)
    target_valid = None
    if request.target is not None:
        candidates = [candidate for values in valid_targets.values() for candidate in values]
        target_valid = any(candidate.get("id") == request.target for candidate in candidates)
    return {
        "available": action.available and target_valid is not False,
        "reason": ("target is not valid" if target_valid is False else action.unavailable_reason),
        "availability": availability,
        "target_valid": target_valid,
    }, provenance


def _what_changed_since(actor: Any, request: WhatChangedSinceInput):
    stream = getattr(actor, "event_stream", None)
    if stream is None:
        return {
            "events": [],
            "complete": False,
            "resync_required": True,
            "requested_epoch": request.epoch,
            "available_after_epoch": actor.epoch,
        }, ("event_stream:unavailable",)
    updates, complete, available_after_epoch = stream.changes_since(request.actor_id, request.epoch)
    return {
        "events": updates,
        "complete": complete,
        "resync_required": not complete,
        "requested_epoch": request.epoch,
        "available_after_epoch": available_after_epoch,
    }, ("event_stream.occurrence_time_visibility",)


V1_PERSPECTIVE_QUERIES = (
    PerspectiveQueryDefinition(
        name="available_actions",
        input_model=AvailableActionsInput,
        output_model=AvailableActionsOutput,
        execute=_available_actions,
        provenance=("authoritative_ecs",),
    ),
    PerspectiveQueryDefinition(
        name="valid_targets",
        input_model=ValidTargetsInput,
        output_model=ValidTargetsOutput,
        execute=_valid_targets,
        provenance=("authoritative_ecs",),
    ),
    PerspectiveQueryDefinition(
        name="why_not",
        input_model=WhyNotInput,
        output_model=WhyNotOutput,
        execute=_why_not,
        provenance=("authoritative_ecs",),
    ),
    PerspectiveQueryDefinition(
        name="what_changed_since",
        input_model=WhatChangedSinceInput,
        output_model=WhatChangedSinceOutput,
        execute=_what_changed_since,
        provenance=("authoritative_events",),
    ),
)


__all__ = [
    "PerspectiveQueryDefinition",
    "PerspectiveQueryRegistry",
    "PerspectiveQueryRequest",
    "PerspectiveQueryResult",
    "V1_PERSPECTIVE_QUERIES",
    "AvailableActionsOutput",
    "ValidTargetsOutput",
    "WhyNotOutput",
    "WhatChangedSinceOutput",
]
