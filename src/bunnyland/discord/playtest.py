"""Deterministic Discord-adapter playtests.

The harness feeds fake Discord messages through ``DiscordBot.handle_text_command`` and
then lets the normal game loop phases process submitted commands. It mocks only the
Discord context objects: command parsing, controller lookup, world queues, handlers,
consequences, and rendered replies all use the production code paths.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.commands import SubmittedCommand
from ..core.events import CommandExecutedEvent, CommandRejectedEvent, DomainEvent
from ..engine import GameLoop
from ..llm_agents import DEFAULT_MODEL
from ..persistence import WorldMeta, save_world
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
    name: str = "discord-playtest"

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


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


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
        self.received_messages: list[dict[str, Any]] = []
        self.commands: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
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
        self._bot._build_command = self._traced_build_command
        loop.actor.bus.subscribe(CommandExecutedEvent, self._bot._complete_pending)
        loop.actor.bus.subscribe(CommandRejectedEvent, self._bot._complete_pending)
        loop.actor.bus.subscribe(DomainEvent, self._trace_event)

    async def close(self) -> None:
        self.loop.actor.bus.unsubscribe(CommandExecutedEvent, self._bot._complete_pending)
        self.loop.actor.bus.unsubscribe(CommandRejectedEvent, self._bot._complete_pending)
        self.loop.actor.bus.unsubscribe(DomainEvent, self._trace_event)
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def _traced_build_command(
        self, discord_user_id: int, action
    ) -> tuple[SubmittedCommand | None, str | None]:
        command, error = await DiscordBot._build_command(self._bot, discord_user_id, action)
        self.commands.append(
            {
                "discord_user_id": discord_user_id,
                "action": _jsonable(action),
                "command": _jsonable(command) if command is not None else None,
                "error": error,
            }
        )
        return command, error

    def _trace_event(self, event: DomainEvent) -> None:
        self.events.append(
            {"event_type": event.__class__.__name__, **event.model_dump(mode="json")}
        )

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
        self.received_messages.append(
            {
                "input_index": index,
                "tick": tick,
                "epoch": epoch,
                "user_id": item.user_id,
                "channel_id": item.channel_id,
                "content": content,
            }
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

    def write_trace(
        self, trace_dir: str | Path, *, ticks: int, status: str, error: str = ""
    ) -> None:
        trace_dir = Path(trace_dir)
        trace_dir.mkdir(parents=True, exist_ok=True)
        stem = _safe_trace_stem(self.spec.name)
        trace_path = trace_dir / f"{stem}.trace.json"
        world_path = trace_dir / f"{stem}.world.json"
        save_world(
            self.loop.actor,
            world_path,
            meta=WorldMeta(seed=self.spec.name, generator="discord-playtest"),
        )
        final_world = json.loads(world_path.read_text())
        trace = {
            "name": self.spec.name,
            "status": status,
            "error": error,
            "ticks": ticks,
            "final_epoch": self.loop.actor.epoch,
            "spec": _jsonable(self.spec),
            "received_messages": _jsonable(self.received_messages),
            "sent_messages": _jsonable(self.messages),
            "inputs": _jsonable(tuple(sorted(self.results, key=lambda result: result.input_index))),
            "commands": _jsonable(self.commands),
            "events": _jsonable(self.events),
            "final_world_path": world_path.name,
            "final_world": final_world,
        }
        trace_path.write_text(json.dumps(trace, indent=2, default=str))


def _safe_trace_stem(name: str) -> str:
    current_test = os.environ.get("PYTEST_CURRENT_TEST", "").split(" ")[0]
    raw = "--".join(part for part in (current_test, name) if part)
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-")
    return cleaned or "discord-playtest"


def _expect_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def load_discord_playtest(path: str | Path) -> DiscordPlaytest:
    path = Path(path)
    data = json.loads(path.read_text())
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
        name=str(data.get("name", path.stem)),
    )


async def run_discord_playtest(
    loop: GameLoop,
    spec: DiscordPlaytest,
    *,
    max_ticks: int | None = None,
) -> PlaytestResult:
    ticks = spec.resolved_ticks(max_ticks)
    harness = DiscordPlaytestHarness(loop, spec)
    trace_dir = os.environ.get("BUNNYLAND_PLAYTEST_TRACE_DIR")
    trace_error = ""
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
    except BaseException as exc:
        trace_error = repr(exc)
        raise
    finally:
        loop._running = False
        if trace_dir:
            harness.write_trace(
                trace_dir,
                ticks=ticks,
                status="failed" if trace_error else "passed",
                error=trace_error,
            )
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
