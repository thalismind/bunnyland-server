"""Deterministic Discord-adapter playtests.

The harness feeds fake Discord messages through ``DiscordBot.handle_text_command`` and
then lets the normal game loop phases process submitted commands. It mocks only the
Discord context objects: command parsing, controller lookup, world queues, handlers,
consequences, and rendered replies all use the production code paths.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from ..core.events import CommandExecutedEvent, CommandRejectedEvent
from ..engine import GameLoop
from ..llm_agents import DEFAULT_MODEL
from .bot import DiscordBot


@dataclass(frozen=True)
class PlaytestInput:
    content: str
    tick: int | None = None
    epoch: int | None = None
    user_id: int = 1
    channel_id: int = 1
    expect: tuple[str, ...] = ()

    def due(self, *, tick: int, epoch: int) -> bool:
        if self.tick is not None:
            return self.tick == tick
        return self.epoch == epoch


@dataclass(frozen=True)
class PlaytestMessage:
    input_index: int
    tick: int
    epoch: int
    user_id: int
    channel_id: int
    content: str


@dataclass(frozen=True)
class PlaytestInputResult:
    input_index: int
    tick: int
    epoch: int
    content: str
    messages: tuple[str, ...]
    reactions: tuple[str, ...]


@dataclass(frozen=True)
class DiscordPlaytest:
    inputs: tuple[PlaytestInput, ...]
    ticks: int | None = None
    allow_child_claims: bool = False
    llm_provider: str = "ollama"
    character_model: str = DEFAULT_MODEL

    def resolved_ticks(self, fallback: int | None) -> int:
        if self.ticks is not None:
            return self.ticks
        if fallback is not None:
            return fallback
        tick_inputs = [item.tick for item in self.inputs if item.tick is not None]
        if tick_inputs:
            return max(tick_inputs) + 1
        raise ValueError("epoch-keyed playtests need either a spec `ticks` value or CLI --ticks")


@dataclass(frozen=True)
class PlaytestResult:
    ticks: int
    messages: tuple[PlaytestMessage, ...]
    inputs: tuple[PlaytestInputResult, ...]


class _FakeAuthor:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.mention = f"<@{user_id}>"
        self.bot = False


class _FakeChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id


class _FakeMessage:
    def __init__(self, content: str, author: _FakeAuthor, channel: _FakeChannel) -> None:
        self.content = content
        self.author = author
        self.channel = channel
        self.reactions: list[str] = []

    async def add_reaction(self, reaction: str) -> None:
        self.reactions.append(reaction)


class _FakeContext:
    def __init__(
        self,
        harness: DiscordPlaytestHarness,
        *,
        input_index: int,
        tick: int,
        epoch: int,
        content: str,
        user_id: int,
        channel_id: int,
    ) -> None:
        self.author = _FakeAuthor(user_id)
        self.channel = _FakeChannel(channel_id)
        self.message = _FakeMessage(content, self.author, self.channel)
        self.valid = True
        self._harness = harness
        self._input_index = input_index
        self._tick = tick
        self._epoch = epoch

    async def send(self, body: str) -> None:
        self._harness.messages.append(
            PlaytestMessage(
                input_index=self._input_index,
                tick=self._tick,
                epoch=self._epoch,
                user_id=self.author.id,
                channel_id=self.channel.id,
                content=body,
            )
        )


class DiscordPlaytestHarness:
    """Schedules fake Discord messages against a live ``GameLoop``."""

    def __init__(self, loop: GameLoop, spec: DiscordPlaytest) -> None:
        self.loop = loop
        self.spec = spec
        self.messages: list[PlaytestMessage] = []
        self.results: list[PlaytestInputResult] = []
        self._scheduled: set[int] = set()
        self._tasks: dict[int, asyncio.Task[PlaytestInputResult]] = {}
        self._bot = object.__new__(DiscordBot)
        self._bot.actor = loop.actor
        self._bot.allow_child_claims = spec.allow_child_claims
        self._bot.llm_provider = spec.llm_provider
        self._bot.character_model = spec.character_model
        self._bot._pause_status = lambda: loop.paused
        self._bot._world_paused = loop.paused
        self._bot._pending = {}
        self._bot._paused_reactions = {}
        loop.actor.bus.subscribe(CommandExecutedEvent, self._bot._complete_pending)
        loop.actor.bus.subscribe(CommandRejectedEvent, self._bot._complete_pending)

    async def close(self) -> None:
        self.loop.actor.bus.unsubscribe(CommandExecutedEvent, self._bot._complete_pending)
        self.loop.actor.bus.unsubscribe(CommandRejectedEvent, self._bot._complete_pending)
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def before_tick(self, tick: int) -> None:
        epoch = self.loop.actor.epoch
        due = [
            (index, item)
            for index, item in enumerate(self.spec.inputs)
            if index not in self._scheduled and item.due(tick=tick, epoch=epoch)
        ]
        for index, item in due:
            self._scheduled.add(index)
            self._tasks[index] = asyncio.create_task(self._run_input(index, item, tick, epoch))
            await asyncio.sleep(0)
            self._drain_finished()

    def _drain_finished(self) -> None:
        for index, task in tuple(self._tasks.items()):
            if not task.done():
                continue
            self.results.append(task.result())
            del self._tasks[index]

    def assert_no_unfinished_inputs(self) -> None:
        self._drain_finished()
        unscheduled = [
            (index, item)
            for index, item in enumerate(self.spec.inputs)
            if index not in self._scheduled
        ]
        if unscheduled:
            details = ", ".join(
                f"#{index} {item.content!r} at {self._schedule_label(item)}"
                for index, item in unscheduled
            )
            raise AssertionError(f"playtest input(s) were never scheduled: {details}")
        if self._tasks:
            details = ", ".join(
                f"#{index} {self.spec.inputs[index].content!r}" for index in self._tasks
            )
            raise AssertionError(
                f"playtest input(s) did not finish before the run ended: {details}"
            )

    @staticmethod
    def _schedule_label(item: PlaytestInput) -> str:
        if item.tick is not None:
            return f"tick {item.tick}"
        return f"epoch {item.epoch}"

    async def _run_input(
        self, index: int, item: PlaytestInput, tick: int, epoch: int
    ) -> PlaytestInputResult:
        start = len(self.messages)
        content = item.content if item.content.startswith("!") else f"!{item.content}"
        ctx = _FakeContext(
            self,
            input_index=index,
            tick=tick,
            epoch=epoch,
            content=content,
            user_id=item.user_id,
            channel_id=item.channel_id,
        )
        await self._bot.handle_text_command(ctx, content[1:])
        sent = tuple(message.content for message in self.messages[start:])
        rendered = "\n".join(sent)
        missing = tuple(expected for expected in item.expect if expected not in rendered)
        if missing:
            raise AssertionError(
                f"playtest input #{index} expected output containing {missing!r}, "
                f"got {rendered!r}"
            )
        return PlaytestInputResult(
            input_index=index,
            tick=tick,
            epoch=epoch,
            content=content,
            messages=sent,
            reactions=tuple(ctx.message.reactions),
        )


def _expect_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def load_discord_playtest(path: str | Path) -> DiscordPlaytest:
    data = json.loads(Path(path).read_text())
    default_user_id = int(data.get("default_user_id", data.get("user_id", 1)))
    default_channel_id = int(data.get("default_channel_id", data.get("channel_id", 1)))
    inputs = []
    for index, raw in enumerate(data.get("inputs", ())):
        has_tick = "tick" in raw
        has_epoch = "epoch" in raw
        if has_tick == has_epoch:
            raise ValueError(f"playtest input #{index} must set exactly one of `tick` or `epoch`")
        content = raw.get("content", raw.get("command"))
        if not content:
            raise ValueError(f"playtest input #{index} needs `content` or `command`")
        expected = raw.get("expect", raw.get("expected", raw.get("expected_outputs")))
        inputs.append(
            PlaytestInput(
                content=str(content),
                tick=int(raw["tick"]) if has_tick else None,
                epoch=int(raw["epoch"]) if has_epoch else None,
                user_id=int(raw.get("user_id", default_user_id)),
                channel_id=int(raw.get("channel_id", default_channel_id)),
                expect=_expect_tuple(expected),
            )
        )
    return DiscordPlaytest(
        inputs=tuple(inputs),
        ticks=int(data["ticks"]) if "ticks" in data else None,
        allow_child_claims=bool(data.get("allow_child_claims", False)),
        llm_provider=str(data.get("llm_provider", "ollama")),
        character_model=str(data.get("character_model", DEFAULT_MODEL)),
    )


async def run_discord_playtest(
    loop: GameLoop,
    spec: DiscordPlaytest,
    *,
    max_ticks: int | None = None,
) -> PlaytestResult:
    ticks = spec.resolved_ticks(max_ticks)
    harness = DiscordPlaytestHarness(loop, spec)
    try:
        loop._running = True
        for tick in range(ticks):
            if loop.paused:
                await asyncio.sleep(loop.tick_seconds)
                continue
            await harness.before_tick(tick)
            await loop.actor.tick(loop.tick_seconds * loop.time_scale)
            await loop.dispatch.run_once()
            if loop.autosave and loop.autosave_every > 0 and (tick + 1) % loop.autosave_every == 0:
                loop.autosave(tick + 1)
            harness._drain_finished()
        loop._running = False
        await asyncio.sleep(0)
        harness.assert_no_unfinished_inputs()
        return PlaytestResult(
            ticks=ticks,
            messages=tuple(harness.messages),
            inputs=tuple(sorted(harness.results, key=lambda result: result.input_index)),
        )
    finally:
        loop._running = False
        await harness.close()


__all__ = [
    "DiscordPlaytest",
    "DiscordPlaytestHarness",
    "PlaytestInput",
    "PlaytestInputResult",
    "PlaytestMessage",
    "PlaytestResult",
    "load_discord_playtest",
    "run_discord_playtest",
]
