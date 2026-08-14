"""Concurrent LLM players exercising a live Bunnyland server through player claims."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ..llm_agents import (
    CharacterAgent,
    InvalidAgentResponse,
    OllamaAgent,
    OpenRouterAgent,
    ToolCall,
)
from ..prompts.builder import PromptContext
from ..secure_files import secure_write_text
from ..server.models import (
    CharacterProjectionResponse,
    CharacterSummaryView,
    ClientActionView,
)
from ..tui.backend import ControlClaim, RemoteBackend, SubmitResult
from ..tui.model import World

PlayerProvider = Literal["ollama-local", "ollama-cloud", "openrouter"]
PlayerStatus = Literal["completed", "turn_limit", "timeout", "failed"]
_JSON_ARGUMENTS = TypeAdapter(dict[str, JsonValue])

DEFAULT_PLAYER_SYSTEM_PROMPT = (
    "You are a player in Bunnyland, a persistent multiplayer social sandbox. Choose exactly "
    "one available structured tool call that advances your objective using only what your "
    "character can currently perceive. Other players and characters are independent people; "
    "coordinate through normal in-world actions. Call the wait tool when waiting is useful. "
    "Never describe a tool call only in prose or invent facts, actions, or results."
)


class MultiplayerHarnessError(RuntimeError):
    """The harness configuration or a live player session cannot be completed."""


class PlayerSpec(BaseModel):
    """One independent simulated player."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    character: str = Field(min_length=1)
    provider: PlayerProvider | None = None
    model: str | None = None
    system_prompt: str = Field(min_length=1)
    objective: str = Field(default="Explore the world and interact meaningfully.", min_length=1)
    access_token_env: str = ""
    username: str = ""
    password_env: str = ""

    @model_validator(mode="after")
    def validate_auth(self) -> PlayerSpec:
        if bool(self.username) != bool(self.password_env):
            raise ValueError("player username and password_env must be set together")
        return self


class MultiplayerHarnessConfig(BaseModel):
    """Shared settings and an arbitrary non-empty roster of simulated players."""

    model_config = ConfigDict(extra="forbid")

    server_url: str = Field(min_length=1)
    shared_provider: PlayerProvider = "ollama-cloud"
    shared_model: str = Field(min_length=1)
    players: tuple[PlayerSpec, ...] = Field(min_length=1)
    turns: int = Field(default=60, ge=1)
    timeout_seconds: float = Field(default=600.0, gt=0)
    turn_interval_seconds: float = Field(default=1.0, ge=0)
    history_turns: int = Field(default=12, ge=1)
    log_thinking: bool = True
    max_concurrency: int | None = Field(default=None, ge=1)
    release_claims: bool = True
    ollama_host: str = ""
    openrouter_server_url: str = ""

    @model_validator(mode="after")
    def validate_players(self) -> MultiplayerHarnessConfig:
        names = [player.name for player in self.players]
        if len(names) != len(set(names)):
            raise ValueError("player names must be unique")
        return self


@dataclass(frozen=True)
class PlayerTurn:
    turn: int
    world_epoch: int
    tool: str | None
    arguments: dict[str, JsonValue]
    accepted: bool
    reason: str
    latency_seconds: float
    system_prompt: str
    prompt: str
    provider_requests: tuple[dict[str, JsonValue], ...]
    provider_responses: tuple[dict[str, JsonValue], ...]


@dataclass(frozen=True)
class AdminTraceRecord:
    """Sensitive, operator-only evidence for one simulated player turn."""

    schema_version: int
    sensitive: bool
    run_id: str
    recorded_at: str
    player_name: str
    character_id: str
    character_name: str
    provider: PlayerProvider
    model: str
    turn: PlayerTurn


@dataclass(frozen=True)
class PlayerResult:
    name: str
    character_id: str
    character_name: str
    provider: PlayerProvider
    model: str
    status: PlayerStatus
    elapsed_seconds: float
    turns: tuple[PlayerTurn, ...]
    error: str = ""


@dataclass(frozen=True)
class MultiplayerRunResult:
    run_id: str
    started_at: str
    server_url: str
    players: tuple[PlayerResult, ...]
    elapsed_seconds: float

    @property
    def completed_players(self) -> int:
        return sum(player.status == "completed" for player in self.players)

    def write_json(self, path: str | Path) -> Path:
        output = Path(path)
        secure_write_text(output, json.dumps(asdict(self), indent=2))
        return output


class PlayerAgentFactory(Protocol):
    def __call__(
        self,
        player: PlayerSpec,
        provider: PlayerProvider,
        model: str,
        config: MultiplayerHarnessConfig,
        request_observer: Callable[[dict[str, JsonValue]], None],
        response_observer: Callable[[dict[str, JsonValue]], None],
    ) -> CharacterAgent: ...


class PlayerBackendFactory(Protocol):
    def __call__(self, player: PlayerSpec, client_id: str) -> PlayerBackend: ...


class PlayerBackend(Protocol):
    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def fetch_character_list(self) -> list[CharacterSummaryView]: ...

    async def fetch_character_projection(
        self, character_id: str
    ) -> dict[str, JsonValue] | None: ...

    async def claim(self, player_id: str, world: World) -> ControlClaim | None: ...

    async def release_claim(self, player_id: str, control: ControlClaim) -> bool: ...

    async def submit(self, command: dict[str, JsonValue]) -> SubmitResult: ...


CompletionProbe = Callable[[CharacterProjectionResponse], bool]
AdminTraceSink = Callable[[AdminTraceRecord], None]


class NdjsonAdminTraceWriter:
    """Write each sensitive admin trace immediately for live ``tail -f`` monitoring."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        secure_write_text(self.path, "")

    def __call__(self, record: AdminTraceRecord) -> None:
        with self.path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(asdict(record), separators=(",", ":")))
            output.write("\n")


@dataclass
class _PlayerRuntime:
    spec: PlayerSpec
    provider: PlayerProvider
    model: str
    backend: PlayerBackend
    agent: CharacterAgent
    character_id: str = ""
    character_name: str = ""
    claim: ControlClaim | None = None
    memory: dict[str, JsonValue] = field(default_factory=dict)
    provider_requests: list[dict[str, JsonValue]] = field(default_factory=list)
    provider_responses: list[dict[str, JsonValue]] = field(default_factory=list)


def load_multiplayer_config(path: str | Path) -> MultiplayerHarnessConfig:
    """Load a strict YAML or JSON harness configuration."""

    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MultiplayerHarnessError(f"could not load multiplayer config: {exc}") from exc
    try:
        return MultiplayerHarnessConfig.model_validate(raw)
    except ValidationError as exc:
        raise MultiplayerHarnessError(f"invalid multiplayer config: {exc}") from exc


class MultiplayerHarness:
    """Run isolated LLM player loops concurrently against one shared live server."""

    def __init__(
        self,
        config: MultiplayerHarnessConfig,
        *,
        agent_factory: PlayerAgentFactory | None = None,
        backend_factory: PlayerBackendFactory | None = None,
        completion_probe: CompletionProbe | None = None,
        admin_trace_sink: AdminTraceSink | None = None,
    ) -> None:
        self.config = config
        self._agent_factory = agent_factory or self._build_agent
        self._backend_factory = backend_factory or self._build_backend
        self._completion_probe = completion_probe
        self._admin_trace_sink = admin_trace_sink
        self._run_id = uuid4().hex

    async def run(self) -> MultiplayerRunResult:
        started_at = datetime.now(UTC).isoformat()
        started = time.perf_counter()
        runtimes = [self._runtime(player) for player in self.config.players]
        limit = self.config.max_concurrency or len(runtimes)
        semaphore = asyncio.Semaphore(limit)

        async def run_limited(runtime: _PlayerRuntime) -> PlayerResult:
            async with semaphore:
                return await self._run_player(runtime)

        players = await asyncio.gather(*(run_limited(runtime) for runtime in runtimes))
        return MultiplayerRunResult(
            run_id=self._run_id,
            started_at=started_at,
            server_url=self.config.server_url,
            players=tuple(players),
            elapsed_seconds=time.perf_counter() - started,
        )

    def _runtime(self, player: PlayerSpec) -> _PlayerRuntime:
        provider = player.provider or self.config.shared_provider
        model = player.model or self.config.shared_model
        client_id = f"llm-playtest-{uuid4()}"
        requests: list[dict[str, JsonValue]] = []
        responses: list[dict[str, JsonValue]] = []
        return _PlayerRuntime(
            spec=player,
            provider=provider,
            model=model,
            backend=self._backend_factory(player, client_id),
            agent=self._agent_factory(
                player,
                provider,
                model,
                self.config,
                requests.append,
                responses.append,
            ),
            provider_requests=requests,
            provider_responses=responses,
        )

    def _build_backend(self, player: PlayerSpec, client_id: str) -> RemoteBackend:
        access_token = (
            os.environ.get(player.access_token_env, "") if player.access_token_env else ""
        )
        password = os.environ.get(player.password_env, "") if player.password_env else ""
        return RemoteBackend(
            self.config.server_url,
            client_id=client_id,
            fallback_controller="suspend",
            username=player.username,
            password=password,
            access_token=access_token,
        )

    @staticmethod
    def _build_agent(
        player: PlayerSpec,
        provider: PlayerProvider,
        model: str,
        config: MultiplayerHarnessConfig,
        request_observer: Callable[[dict[str, JsonValue]], None] | None = None,
        response_observer: Callable[[dict[str, JsonValue]], None] | None = None,
    ) -> CharacterAgent:
        if provider in {"ollama-local", "ollama-cloud"}:
            api_key = (
                os.environ.get("OLLAMA_CLOUD_API_KEY")
                if provider == "ollama-cloud"
                else None
            )
            if provider == "ollama-cloud" and not api_key:
                raise MultiplayerHarnessError(
                    "ollama-cloud players need OLLAMA_CLOUD_API_KEY in the environment"
                )
            return OllamaAgent(
                model=model,
                host=(
                    config.ollama_host
                    or "https://ollama.com"
                    if provider == "ollama-cloud"
                    else config.ollama_host or "http://127.0.0.1:11434"
                ),
                api_key=api_key,
                history_turns=config.history_turns,
                system_prompt=player.system_prompt,
                request_observer=request_observer,
                response_observer=response_observer,
                log_thinking=config.log_thinking,
            )
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise MultiplayerHarnessError(
                "openrouter players need OPENROUTER_API_KEY in the environment"
            )
        return OpenRouterAgent(
            model=model,
            api_key=api_key,
            server_url=config.openrouter_server_url or None,
            history_turns=config.history_turns,
            system_prompt=player.system_prompt,
            request_observer=request_observer,
            response_observer=response_observer,
            log_thinking=config.log_thinking,
        )

    async def _run_player(self, runtime: _PlayerRuntime) -> PlayerResult:
        started = time.perf_counter()
        turns: list[PlayerTurn] = []
        status: PlayerStatus = "turn_limit"
        error = ""
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                await runtime.backend.start()
                runtime.character_id, runtime.character_name = await self._resolve_character(
                    runtime
                )
                runtime.claim = await runtime.backend.claim(runtime.character_id, World())
                if runtime.claim is None:
                    raise MultiplayerHarnessError(
                        f"{runtime.spec.name} could not claim {runtime.spec.character!r}"
                    )
                for turn in range(1, self.config.turns + 1):
                    projection = await self._projection(runtime)
                    if self._completion_probe is not None and self._completion_probe(projection):
                        status = "completed"
                        break
                    player_turn = await self._take_turn(runtime, projection, turn)
                    turns.append(player_turn)
                    self._emit_admin_trace(runtime, player_turn)
                    if turn < self.config.turns and self.config.turn_interval_seconds:
                        await asyncio.sleep(self.config.turn_interval_seconds)
                else:
                    if self._completion_probe is not None:
                        projection = await self._projection(runtime)
                        if self._completion_probe(projection):
                            status = "completed"
        except TimeoutError:
            status = "timeout"
            error = f"player exceeded {self.config.timeout_seconds:g}s timeout"
        except Exception as exc:
            status = "failed"
            error = str(exc)
        finally:
            if self.config.release_claims and runtime.claim is not None:
                try:
                    await runtime.backend.release_claim(runtime.character_id, runtime.claim)
                except Exception:
                    pass
            try:
                await runtime.backend.close()
            except Exception:
                pass
            close = getattr(runtime.agent, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass
        return PlayerResult(
            name=runtime.spec.name,
            character_id=runtime.character_id,
            character_name=runtime.character_name,
            provider=runtime.provider,
            model=runtime.model,
            status=status,
            elapsed_seconds=time.perf_counter() - started,
            turns=tuple(turns),
            error=error,
        )

    def _emit_admin_trace(
        self, runtime: _PlayerRuntime, player_turn: PlayerTurn
    ) -> None:
        if self._admin_trace_sink is None:
            return
        self._admin_trace_sink(
            AdminTraceRecord(
                schema_version=1,
                sensitive=True,
                run_id=self._run_id,
                recorded_at=datetime.now(UTC).isoformat(),
                player_name=runtime.spec.name,
                character_id=runtime.character_id,
                character_name=runtime.character_name,
                provider=runtime.provider,
                model=runtime.model,
                turn=player_turn,
            )
        )

    async def _resolve_character(self, runtime: _PlayerRuntime) -> tuple[str, str]:
        characters = await runtime.backend.fetch_character_list()
        exact_id = next(
            (
                character
                for character in characters
                if character.character_id == runtime.spec.character
            ),
            None,
        )
        matches = [
            character
            for character in characters
            if character.name.casefold() == runtime.spec.character.casefold()
        ]
        selected = exact_id or (matches[0] if len(matches) == 1 else None)
        if selected is None:
            raise MultiplayerHarnessError(
                f"{runtime.spec.name} character {runtime.spec.character!r} "
                "is not uniquely available"
            )
        return selected.character_id, selected.name

    async def _projection(self, runtime: _PlayerRuntime) -> CharacterProjectionResponse:
        data = await runtime.backend.fetch_character_projection(runtime.character_id)
        if data is None:
            raise MultiplayerHarnessError(f"claim for {runtime.character_name} no longer exists")
        return CharacterProjectionResponse.model_validate(data)

    async def _take_turn(
        self,
        runtime: _PlayerRuntime,
        projection: CharacterProjectionResponse,
        turn: int,
    ) -> PlayerTurn:
        prompt, context = _player_prompt(runtime, projection)
        actions = tuple(action for action in projection.actions if action.available)
        schemas = [_tool_schema(action, projection.target_groups) for action in actions]
        runtime.provider_requests.clear()
        runtime.provider_responses.clear()
        started = time.perf_counter()
        decision = await runtime.agent.decide(
            prompt,
            context,
            character_id=runtime.character_id,
            model=runtime.model,
            provider=runtime.provider,
            tools=schemas,
        )
        latency = time.perf_counter() - started
        trace_fields = {
            "system_prompt": runtime.spec.system_prompt,
            "prompt": prompt,
            "provider_requests": tuple(runtime.provider_requests),
            "provider_responses": tuple(runtime.provider_responses),
        }
        if isinstance(decision, InvalidAgentResponse):
            return PlayerTurn(
                turn,
                projection.world_epoch,
                None,
                {},
                False,
                decision.reason,
                latency,
                **trace_fields,
            )
        if decision is None:
            return PlayerTurn(
                turn,
                projection.world_epoch,
                None,
                {},
                False,
                "agent held",
                latency,
                **trace_fields,
            )
        action = next((item for item in actions if item.tool_name == decision.name), None)
        if action is None:
            return PlayerTurn(
                turn,
                projection.world_epoch,
                decision.name,
                _json_arguments(decision.arguments),
                False,
                "tool is not currently available",
                latency,
                **trace_fields,
            )
        payload = _command_payload(decision, action, projection.target_groups)
        result = await runtime.backend.submit(
            {
                "character_id": runtime.character_id,
                "command_type": action.command_type,
                "payload": payload,
                "cost": action.cost.model_dump(mode="json"),
                "lane": action.lane.value,
                "on_insufficient_points": "queue",
            }
        )
        remembered = list(runtime.memory.get("recent_results", []))
        remembered.append(
            f"Turn {turn}: {decision.name} was "
            f"{'accepted' if result.accepted else 'refused'}"
            f"{f': {result.reason}' if result.reason else ''}."
        )
        runtime.memory["recent_results"] = remembered[-self.config.history_turns :]
        return PlayerTurn(
            turn,
            projection.world_epoch,
            decision.name,
            payload,
            result.accepted,
            result.reason,
            latency,
            **trace_fields,
        )


def _player_prompt(
    runtime: _PlayerRuntime, projection: CharacterProjectionResponse
) -> tuple[str, PromptContext]:
    room = projection.room
    visible_characters = tuple(
        entity.name for entity in room.entities if entity.is_character
    )
    visible_objects = tuple(
        entity.name for entity in room.entities if not entity.is_character
    )
    exits = tuple(exit.label for exit in room.exits)
    inventory = tuple(item.label for item in projection.inventory)
    recent_results = tuple(
        str(item)
        for item in runtime.memory.get("recent_results", [])
        if isinstance(item, str)
    )
    context = PromptContext(
        name=runtime.spec.name,
        kind="player",
        status="active",
        action=(projection.points.action, projection.points.action_max),
        focus=(projection.points.focus, projection.points.focus_max),
        location_title=room.title,
        room_summary=(
            f"{room.title}: {room.description}" if room.description else room.title
        ),
        visible_characters=visible_characters,
        visible_objects=visible_objects,
        exits=exits,
        inventory=inventory,
        conditions=tuple(
            item for item in (projection.current_goal, *projection.suggested_actions) if item
        ),
        recent=recent_results,
        commands=tuple(action.title for action in projection.actions if action.available),
    )
    prompt = (
        f"You are player {runtime.spec.name}, controlling {runtime.character_name}.\n"
        f"Objective: {runtime.spec.objective}\n"
        f"World epoch: {projection.world_epoch}.\n"
        f"Location: {context.room_summary}.\n"
        f"Visible characters: {', '.join(visible_characters) or 'none'}.\n"
        f"Visible objects: {', '.join(visible_objects) or 'none'}.\n"
        f"Exits: {', '.join(exits) or 'none'}.\n"
        f"Inventory: {', '.join(inventory) or 'empty'}.\n"
        f"Current goal: {projection.current_goal or 'none'}.\n"
        f"Suggested actions: {'; '.join(projection.suggested_actions) or 'none'}.\n"
        "Choose exactly one available tool call."
    )
    return prompt, context


def _tool_schema(
    action: ClientActionView,
    target_groups: Mapping[str, Sequence[object]],
) -> dict[str, JsonValue]:
    properties: dict[str, JsonValue] = {}
    required: list[str] = []
    for argument in action.arguments:
        schema_type = "number" if argument.kind == "number" else (
            "boolean" if argument.kind == "boolean" else "string"
        )
        schema: dict[str, JsonValue] = {"type": schema_type}
        if argument.title:
            schema["title"] = argument.title
        candidates = target_groups.get(argument.target_group or "", ())
        ids = [
            getattr(candidate, "id", None)
            for candidate in candidates
            if isinstance(getattr(candidate, "id", None), str)
        ]
        if ids:
            schema["enum"] = ids
        elif argument.key == "direction":
            directions = [
                str(getattr(candidate, "label", "")).split(":", 1)[0].strip()
                for candidate in target_groups.get("exits", ())
            ]
            if directions:
                schema["enum"] = directions
        properties[argument.key] = schema
        if argument.required:
            required.append(argument.key)
    parameters: dict[str, JsonValue] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": action.tool_name,
            "description": action.description or action.title,
            "parameters": parameters,
        },
    }


def _json_arguments(arguments: Mapping[str, object]) -> dict[str, JsonValue]:
    try:
        return _JSON_ARGUMENTS.validate_python(dict(arguments))
    except ValidationError as exc:
        raise MultiplayerHarnessError(f"provider returned invalid tool arguments: {exc}") from exc


def _command_payload(
    decision: ToolCall,
    action: ClientActionView,
    target_groups: Mapping[str, Sequence[object]],
) -> dict[str, JsonValue]:
    payload = _json_arguments(decision.arguments)
    if action.command_type == "move" and not payload.get("direction") and payload.get("exit_id"):
        exit_id = str(payload["exit_id"])
        for candidate in target_groups.get("exits", ()):
            if getattr(candidate, "id", None) != exit_id:
                continue
            label = str(getattr(candidate, "label", ""))
            payload["direction"] = label.split(":", 1)[0].strip()
            break
    return payload


__all__ = [
    "DEFAULT_PLAYER_SYSTEM_PROMPT",
    "MultiplayerHarness",
    "MultiplayerHarnessConfig",
    "MultiplayerHarnessError",
    "MultiplayerRunResult",
    "PlayerResult",
    "PlayerSpec",
    "load_multiplayer_config",
]
