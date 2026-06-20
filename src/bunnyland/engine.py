"""The game loop that ties the actor, simulation clock, and agents together (spec 5, 24).

One iteration is: advance the world by one tick (clock, regen, queued commands,
consequences), then let the dispatch propose the next action for each LLM-controlled
character (those commands run on the *following* tick). ``time_scale`` maps one real loop
iteration to a span of game seconds so a slow real cadence can drive a faster world.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from . import telemetry
from .core.events import WorldPauseStatusChangedEvent
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
        paused: bool = False,
    ) -> None:
        self.actor = actor
        self.dispatch = dispatch
        self.tick_seconds = tick_seconds
        self.time_scale = time_scale
        self.autosave = autosave
        self.autosave_every = autosave_every
        self._running = False
        self._paused = paused
        self._next_tick_at_unix: float | None = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def next_tick_at_unix(self) -> float | None:
        return self._next_tick_at_unix

    def pause(self) -> asyncio.Task[None] | None:
        if self._paused:
            return None
        self._paused = True
        return self._publish_pause_status(paused=True)

    def resume(self) -> asyncio.Task[None] | None:
        if not self._paused:
            return None
        self._paused = False
        return self._publish_pause_status(paused=False)

    def _publish_pause_status(self, *, paused: bool) -> asyncio.Task[None] | None:
        state = "paused" if paused else "resumed"
        event = WorldPauseStatusChangedEvent(
            event_id=uuid4().hex,
            world_epoch=self.actor.epoch,
            created_at=datetime.now(UTC),
            paused=paused,
            state=state,
            message=f"World {state}.",
        )
        publish = self.actor.bus.publish(event)
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(publish)
            return None
        return running_loop.create_task(publish)

    async def run(self, max_ticks: int | None = None) -> int:
        """Run the loop. Stops after ``max_ticks`` iterations, or until ``stop()``.

        Returns the number of ticks executed. With ``max_ticks=None`` it sleeps
        ``tick_seconds`` between iterations; tests pass a finite ``max_ticks`` and skip the
        sleep so the loop is deterministic and fast.
        """
        self._running = True
        ticks = 0
        try:
            while self._running and (max_ticks is None or ticks < max_ticks):
                if self._paused:
                    self._next_tick_at_unix = None
                    await asyncio.sleep(self.tick_seconds)
                    continue
                game_delta_seconds = self.tick_seconds * self.time_scale
                # One iteration root span ties the world tick and the dispatch turn together
                # so a trace shows the full chain above controller.run_once (loop -> tick +
                # dispatch). ``run_once`` hands slow LLM prompts to background tasks and
                # returns promptly, so the world keeps ticking on cadence while agents think.
                with telemetry.span(
                    "game.loop.iteration",
                    {
                        "loop.tick_index": ticks,
                        "loop.game_delta_seconds": game_delta_seconds,
                    },
                ):
                    await self.actor.tick(game_delta_seconds)
                    await self.dispatch.run_once()
                ticks += 1
                if self.autosave and self.autosave_every > 0 and ticks % self.autosave_every == 0:
                    self.autosave(ticks)
                if max_ticks is None and self._running:
                    self._next_tick_at_unix = time.time() + self.tick_seconds
                    await asyncio.sleep(self.tick_seconds)
        finally:
            self._running = False
            self._next_tick_at_unix = None
            # Drop any in-flight agent decisions rather than leaking their tasks past the loop.
            self.dispatch.cancel_pending()
        return ticks

    def stop(self) -> None:
        self._running = False


__all__ = ["GameLoop"]
