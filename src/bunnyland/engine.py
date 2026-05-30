"""The game loop that ties the actor, simulation clock, and agents together (spec 5, 24).

One iteration is: advance the world by one tick (clock, regen, queued commands,
consequences), then let the dispatch propose the next action for each LLM-controlled
character (those commands run on the *following* tick). ``time_scale`` maps one real loop
iteration to a span of game seconds so a slow real cadence can drive a faster world.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from .llm_agents.dispatch import ControllerDispatch


class GameLoop:
    """Runs ``tick`` then ``dispatch.run_once`` on a cadence until stopped.

    If ``autosave`` and ``autosave_every`` are set, ``autosave(ticks)`` is called every that
    many ticks so a long-running server checkpoints itself.
    """

    def __init__(
        self,
        actor,
        dispatch: ControllerDispatch,
        *,
        tick_seconds: float = 1.0,
        time_scale: float = 3600.0,
        autosave: Callable[[int], None] | None = None,
        autosave_every: int = 0,
    ) -> None:
        self.actor = actor
        self.dispatch = dispatch
        self.tick_seconds = tick_seconds
        self.time_scale = time_scale
        self.autosave = autosave
        self.autosave_every = autosave_every
        self._running = False

    async def run(self, max_ticks: int | None = None) -> int:
        """Run the loop. Stops after ``max_ticks`` iterations, or until ``stop()``.

        Returns the number of ticks executed. With ``max_ticks=None`` it sleeps
        ``tick_seconds`` between iterations; tests pass a finite ``max_ticks`` and skip the
        sleep so the loop is deterministic and fast.
        """
        self._running = True
        ticks = 0
        while self._running and (max_ticks is None or ticks < max_ticks):
            await self.actor.tick(self.tick_seconds * self.time_scale)
            await self.dispatch.run_once()
            ticks += 1
            if self.autosave and self.autosave_every > 0 and ticks % self.autosave_every == 0:
                self.autosave(ticks)
            if max_ticks is None and self._running:
                await asyncio.sleep(self.tick_seconds)
        self._running = False
        return ticks

    def stop(self) -> None:
        self._running = False


__all__ = ["GameLoop"]
