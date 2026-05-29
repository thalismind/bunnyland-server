"""Core relationships / edges (spec sections 10, 12).

``Contains`` is the single canonical physical containment/possession edge. ``Holding``
and ``Wearing`` are active equipment overlays that must coexist with a ``Contains`` edge
from the same holder/wearer. ``ControlledBy`` carries the controller generation used to
reject stale commands.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic.dataclasses import dataclass
from relics import Edge


class ContainmentMode(StrEnum):
    ROOM_CONTENT = "room_content"
    INVENTORY = "inventory"
    CONTAINER = "container"
    SURFACE = "surface"
    ATTACHED = "attached"


@dataclass(frozen=True)
class Contains(Edge):
    """container -> physical entity. Answers where something physically is."""

    mode: ContainmentMode = ContainmentMode.CONTAINER
    visible: bool = True
    discovered: bool = True
    order: int = 0


@dataclass(frozen=True)
class ExitTo(Edge):
    """room -> room directed connection."""

    direction: str = ""
    label: str = ""
    locked: bool = False
    hidden: bool = False
    action_cost: int = 1


@dataclass(frozen=True)
class Holding(Edge):
    slot: str = "hand"


@dataclass(frozen=True)
class Wearing(Edge):
    slot: str = ""


@dataclass(frozen=True)
class ControlledBy(Edge):
    """character -> controller. ``generation`` increments on every control change."""

    generation: int = 0
    since_epoch: int = 0


__all__ = [
    "ContainmentMode",
    "Contains",
    "ControlledBy",
    "ExitTo",
    "Holding",
    "Wearing",
]
