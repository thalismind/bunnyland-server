"""Commands: costs, lanes, the submission envelope, and typed command payloads.

Commands are *attempted* actions (spec section 13). A submitted command is an intent,
not a point reservation: it is revalidated immediately before execution (spec 5.4).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic.dataclasses import dataclass


class Lane(StrEnum):
    """The two volatile command lanes per character (spec 5.3)."""

    FOCUS = "focus"
    WORLD = "world"


class SpeechIntent(StrEnum):
    """Social meaning of an utterance (spec 14.2). Evolves during implementation."""

    NEUTRAL = "neutral"
    INFORM = "inform"
    QUESTION = "question"
    REQUEST = "request"
    OFFER = "offer"
    JOKE = "joke"
    INSULT = "insult"
    THREAT = "threat"
    COMFORT = "comfort"
    APOLOGY = "apology"
    PRAISE = "praise"
    FLIRT = "flirt"
    CONFESSION = "confession"
    PROMISE = "promise"
    GOSSIP = "gossip"


class OnInsufficientPoints(StrEnum):
    """What to do when a character cannot yet afford a command (spec 5.1)."""

    DENY = "deny"
    QUEUE = "queue"


class CommitStatus(StrEnum):
    """Terminal outcome recorded for an idempotent command."""

    COMMITTED = "committed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class CommandCost:
    action: int = 0
    focus: int = 0


@dataclass(frozen=True)
class Command:
    """Base class for typed command payloads."""

    actor_id: str


@dataclass(frozen=True)
class SubmittedCommand:
    """Envelope carrying a command through the queue and into execution (spec 13.2)."""

    command_id: str
    character_id: str
    controller_id: str
    controller_generation: int
    command_type: str
    payload: Mapping[str, Any]
    cost: CommandCost
    lane: Lane
    on_insufficient_points: OnInsufficientPoints
    submitted_at_epoch: int
    expires_at_epoch: int | None = None
    expected_epoch: int | None = None
    submission_sequence: int = 0


@dataclass(frozen=True)
class CommitReceipt:
    """Stable terminal result returned for original and duplicate submissions."""

    command_id: str
    character_id: str
    command_type: str
    status: CommitStatus
    submitted_at_epoch: int
    committed_at_epoch: int
    submission_sequence: int
    reason: str = ""
    event_ids: tuple[str, ...] = ()


# --------------------------------------------------------------------------------------
# Typed command payloads (spec 13.3+). More verbs are added as handlers land.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MoveCommand(Command):
    direction: str | None = None
    exit_id: str | None = None


@dataclass(frozen=True)
class SayCommand(Command):
    """Room-scoped speech (spec 13.8)."""

    text: str = ""
    intent: SpeechIntent | None = None


@dataclass(frozen=True)
class TellCommand(Command):
    """Speech directed to one character (spec 13.8)."""

    target_id: str = ""
    text: str = ""
    intent: SpeechIntent | None = None


@dataclass(frozen=True)
class WaitCommand(Command):
    """No-op; yields the character's turn (spec 13.1)."""


def build_submitted_command(
    *,
    character_id: str,
    controller_id: str,
    controller_generation: int,
    command_type: str,
    cost: CommandCost,
    lane: Lane,
    payload: Mapping[str, Any] | None = None,
    on_insufficient_points: OnInsufficientPoints = OnInsufficientPoints.QUEUE,
    submitted_at_epoch: int = 0,
    expires_at_epoch: int | None = None,
    expected_epoch: int | None = None,
    command_id: str | None = None,
) -> SubmittedCommand:
    """Convenience factory for a command envelope (used by tests and controller layers)."""
    return SubmittedCommand(
        command_id=command_id or uuid4().hex,
        character_id=character_id,
        controller_id=controller_id,
        controller_generation=controller_generation,
        command_type=command_type,
        payload=dict(payload or {}),
        cost=cost,
        lane=lane,
        on_insufficient_points=on_insufficient_points,
        submitted_at_epoch=submitted_at_epoch,
        expires_at_epoch=expires_at_epoch,
        expected_epoch=expected_epoch,
    )


__all__ = [
    "build_submitted_command",
    "Command",
    "CommandCost",
    "CommitReceipt",
    "CommitStatus",
    "Lane",
    "MoveCommand",
    "OnInsufficientPoints",
    "SayCommand",
    "SpeechIntent",
    "SubmittedCommand",
    "TellCommand",
    "WaitCommand",
]
