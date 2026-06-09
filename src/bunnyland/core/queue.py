"""Volatile two-lane command queues (spec sections 5.3, 5.4).

Each active character has a Focus lane and a World lane, each FIFO. Queues are engine
memory, not ECS state and not durable persistence: they are cleared on restart.

A queued command is an intent, revalidated at execution time. When a character changes
controller or is suspended, the previous controller's queued commands are flushed.
"""

from __future__ import annotations

from collections import deque

from .commands import Lane, SubmittedCommand


class CommandQueues:
    """All per-character, per-lane command queues for the world."""

    def __init__(self) -> None:
        # character_id -> lane -> FIFO of SubmittedCommand
        self._lanes: dict[str, dict[Lane, deque[SubmittedCommand]]] = {}

    def _character_lanes(self, character_id: str) -> dict[Lane, deque[SubmittedCommand]]:
        lanes = self._lanes.get(character_id)
        if lanes is None:
            lanes = {Lane.FOCUS: deque(), Lane.WORLD: deque()}
            self._lanes[character_id] = lanes
        return lanes

    def enqueue(self, command: SubmittedCommand) -> None:
        self._character_lanes(command.character_id)[command.lane].append(command)

    def peek(self, character_id: str, lane: Lane) -> SubmittedCommand | None:
        lanes = self._lanes.get(character_id)
        if not lanes or not lanes[lane]:
            return None
        return lanes[lane][0]

    def pop(self, character_id: str, lane: Lane) -> SubmittedCommand | None:
        lanes = self._lanes.get(character_id)
        if not lanes or not lanes[lane]:
            return None
        return lanes[lane].popleft()

    def has_pending(self, character_id: str, lane: Lane | None = None) -> bool:
        lanes = self._lanes.get(character_id)
        if not lanes:
            return False
        if lane is not None:
            return bool(lanes[lane])
        return any(lanes[la] for la in Lane)

    def pending(self, character_id: str, lane: Lane | None = None) -> list[SubmittedCommand]:
        lanes = self._lanes.get(character_id)
        if not lanes:
            return []
        if lane is not None:
            return list(lanes[lane])
        commands: list[SubmittedCommand] = []
        for command_lane in Lane:
            commands.extend(lanes[command_lane])
        return commands

    def characters_with_pending(self) -> list[str]:
        return [cid for cid, lanes in self._lanes.items() if any(lanes[la] for la in Lane)]

    def flush_character(self, character_id: str) -> list[SubmittedCommand]:
        """Drop all queued commands for a character (e.g. controller change). Returns them."""
        lanes = self._lanes.pop(character_id, None)
        if not lanes:
            return []
        dropped: list[SubmittedCommand] = []
        for lane in Lane:
            dropped.extend(lanes[lane])
        return dropped


__all__ = ["CommandQueues"]
