"""Plugin-owned callback contracts for persistent entity action overrides."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from relics import EntityId

from .commands import SubmittedCommand
from .handlers.base import HandlerContext, HandlerResult


@runtime_checkable
class EntityActionCallback(Protocol):
    """Synchronous plugin callback selected by an entity's persisted routing data."""

    def __call__(
        self,
        ctx: HandlerContext,
        command: SubmittedCommand,
        owning_entity_id: EntityId,
    ) -> HandlerResult: ...


@dataclass(frozen=True)
class EntityActionCallbackDefinition:
    """Action-adjacent plugin definition with a stable id and executable handler.

    Lane, cost, arguments, and player-facing metadata intentionally come from the
    resolved ``ActionDefinition``. Keeping the familiar ``id``/``handler`` definition
    shape avoids duplicating action metadata that could drift from the overridden verb.
    """

    id: str
    handler: EntityActionCallback


__all__ = ["EntityActionCallback", "EntityActionCallbackDefinition"]
