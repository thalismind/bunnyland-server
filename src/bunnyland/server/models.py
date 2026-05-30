"""Pydantic models for the optional HTTP API."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from ..core.commands import CommandCost, Lane, OnInsufficientPoints, SubmittedCommand


class CommandCostRequest(BaseModel):
    action: int = 0
    focus: int = 0


class CommandRequest(BaseModel):
    character_id: str
    controller_id: str
    controller_generation: int
    command_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    cost: CommandCostRequest = Field(default_factory=CommandCostRequest)
    lane: Lane = Lane.WORLD
    on_insufficient_points: OnInsufficientPoints = OnInsufficientPoints.QUEUE
    expires_at_epoch: int | None = None
    command_id: str | None = None

    def to_submitted(self, *, submitted_at_epoch: int) -> SubmittedCommand:
        return SubmittedCommand(
            command_id=self.command_id or uuid4().hex,
            character_id=self.character_id,
            controller_id=self.controller_id,
            controller_generation=self.controller_generation,
            command_type=self.command_type,
            payload=dict(self.payload),
            cost=CommandCost(action=self.cost.action, focus=self.cost.focus),
            lane=self.lane,
            on_insufficient_points=self.on_insufficient_points,
            submitted_at_epoch=submitted_at_epoch,
            expires_at_epoch=self.expires_at_epoch,
        )


class CommandResponse(BaseModel):
    queued: bool
    command_id: str


__all__ = ["CommandCostRequest", "CommandRequest", "CommandResponse"]
