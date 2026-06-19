"""Bounded offline-life advancement for reloaded worlds."""

from __future__ import annotations

from math import ceil

from . import telemetry
from .llm_agents import BehaviorProfileAgent, ControllerDispatch
from .plugins import bunnyland_plugins, collect_persona_fragments
from .prompts.builder import PromptBuilder

DEFAULT_OFFLINE_STEP_SECONDS = 3600.0
DEFAULT_OFFLINE_MAX_TICKS = 6


async def advance_offline_life(
    actor,
    elapsed_seconds: float,
    *,
    step_seconds: float = DEFAULT_OFFLINE_STEP_SECONDS,
    max_ticks: int = DEFAULT_OFFLINE_MAX_TICKS,
    dispatch: ControllerDispatch | None = None,
) -> int:
    """Advance a reloaded world by a bounded amount of offline time.

    The helper deliberately runs the normal actor tick and controller-dispatch path, so
    offline changes are real commands/events. It caps work by ``max_ticks`` and
    ``step_seconds``; callers decide how much wall-clock elapsed time to convert into game
    time.
    """

    if elapsed_seconds <= 0 or max_ticks <= 0 or step_seconds <= 0:
        return 0
    ticks = min(max_ticks, ceil(elapsed_seconds / step_seconds))
    remaining = elapsed_seconds
    runner = dispatch or ControllerDispatch(
        actor,
        PromptBuilder(
            actor.world,
            persona_providers=collect_persona_fragments(bunnyland_plugins()),
        ),
        BehaviorProfileAgent("worker"),
    )
    with telemetry.span(
        "offline.advance_life",
        {"offline.elapsed_seconds": elapsed_seconds, "offline.ticks": ticks},
    ):
        for _index in range(ticks):
            delta = min(step_seconds, remaining)
            await actor.tick(delta)
            await runner.run_once()
            remaining -= delta
        await actor.tick(0.0)
    return ticks


__all__ = [
    "DEFAULT_OFFLINE_MAX_TICKS",
    "DEFAULT_OFFLINE_STEP_SECONDS",
    "advance_offline_life",
]
