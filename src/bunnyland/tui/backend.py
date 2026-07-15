"""Two ways to drive the TUI: host a world in this process, or talk to a running server.

Both expose the same tiny surface — fetch a snapshot, submit a command, claim a player —
so the app never needs to know which one it is using.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import stat
import time
import urllib.parse
import webbrowser
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from ..claims import (
    CLIENT_KIND_WEB,
    ClaimSecretRegistry,
    add_claim,
    remove_claim,
    transfer_claim,
)
from ..core import (
    CommandCost,
    Lane,
    LLMControllerComponent,
    OnInsufficientPoints,
    SuspendedComponent,
    SuspendedControllerComponent,
    WebControllerComponent,
    build_submitted_command,
    container_of,
    spawn_entity,
)
from ..core.claim_timeout import apply_claim_timeout_settings
from ..core.ecs import parse_entity_id
from ..server.models import CharacterListResponse, CharacterSummaryView
from ..server.serialization import (
    serialize_character_list,
    serialize_character_projection,
    serialize_character_queued_commands,
    serialize_room_projection,
    serialize_world,
)
from .model import World

logger = logging.getLogger("bunnyland.tui")

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "bunnyland"
CLIENT_ID_PATH = CONFIG_DIR / "client-id"


def _validate_remote_server_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("remote server must be an absolute HTTP(S) URL")
    if parsed.scheme == "http":
        try:
            import ipaddress

            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname == "localhost"
        if not loopback:
            raise ValueError("remote non-loopback servers require HTTPS")
    return value.rstrip("/")


def _validate_token_file_mode(path: Path) -> None:
    if os.name != "posix" or not path.exists():
        return
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PermissionError(f"token file must not be group/world accessible: {path}")


async def _call_update_callback(callback: Callable, value) -> None:
    result = callback(value)
    if hasattr(result, "__await__"):
        await result


@dataclass(frozen=True)
class ControlClaim:
    controller_id: str
    generation: int
    claim_id: str = ""
    claim_secret: str = ""
    active: bool = True

    def __iter__(self):
        yield self.controller_id
        yield self.generation

    def __getitem__(self, index: int):
        return (self.controller_id, self.generation)[index]

    def __eq__(self, other) -> bool:
        if isinstance(other, ControlClaim):
            return (
                self.controller_id == other.controller_id
                and self.generation == other.generation
                and self.claim_id == other.claim_id
                and self.claim_secret == other.claim_secret
                and self.active == other.active
            )
        if isinstance(other, (tuple, list)) and len(other) == 2:
            return (self.controller_id, self.generation) == tuple(other)
        return False


def _client_id_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "bunnyland" / "client-id"


def persistent_client_id(path: Path | None = None) -> str:
    path = path or _client_id_path()
    if path.exists():
        try:
            value = path.read_text(encoding="utf-8").strip()
            return str(UUID(value))
        except ValueError:
            logger.warning("Ignoring invalid TUI client id in %s", path, exc_info=True)
        except OSError:
            logger.warning("Could not read TUI client id from %s", path, exc_info=True)

    client_id = str(uuid4())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{client_id}\n", encoding="utf-8")
    except OSError:
        logger.warning("Could not persist TUI client id to %s", path, exc_info=True)
    return client_id


def _claim_path(client_id: str, character_id: str) -> Path:
    safe_client = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in client_id)
    safe_character = "".join(ch if ch.isalnum() or ch in "-_:" else "_" for ch in character_id)
    return CONFIG_DIR / "claims" / safe_client / f"{safe_character}.json"


def load_claim_control(client_id: str, character_id: str) -> ControlClaim | None:
    try:
        data = json.loads(_claim_path(client_id, character_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not data.get("claim_id") or not data.get("claim_secret"):
        return None
    return ControlClaim(
        controller_id=str(data.get("controller_id") or ""),
        generation=int(data.get("generation") or 0),
        claim_id=str(data["claim_id"]),
        claim_secret=str(data["claim_secret"]),
        active=bool(data.get("active", True)),
    )


def save_claim_control(client_id: str, character_id: str, control: ControlClaim) -> None:
    if not control.claim_id or not control.claim_secret:
        return
    path = _claim_path(client_id, character_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "controller_id": control.controller_id,
                    "generation": control.generation,
                    "claim_id": control.claim_id,
                    "claim_secret": control.claim_secret,
                    "active": control.active,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Could not persist TUI claim data to %s", path, exc_info=True)


def clear_claim_control(client_id: str, character_id: str) -> None:
    try:
        _claim_path(client_id, character_id).unlink()
    except FileNotFoundError:
        return
    except OSError:
        logger.warning("Could not remove TUI claim data for %s", character_id, exc_info=True)


@dataclass(frozen=True)
class ImageRequestResult:
    """Outcome of a camera (image) request: whether it was accepted, and a status/url."""

    ok: bool
    status: str = ""
    url: str = ""
    reason: str = ""


@dataclass(frozen=True)
class SheetOpenResult:
    """Outcome of opening a browser character sheet from a terminal client."""

    ok: bool
    url: str = ""
    reason: str = ""


@dataclass(frozen=True)
class SubmitResult:
    """Outcome of submitting a command: accepted for queuing, or rejected at submit.

    Mirrors the server's ``SubmissionOutcome`` / ``CommandResponse`` so both the local and
    remote backends report the synchronous rejection ``reason`` to the client UI.
    """

    accepted: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.accepted


class Backend(ABC):
    """A source of world snapshots that also accepts player commands."""

    label: str = ""
    supports_character_sheets: bool = False
    supports_image_requests: bool = False

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def fetch_snapshot(self) -> dict: ...

    async def fetch_character_list(self) -> list[CharacterSummaryView]:
        """The claim lobby — one typed :class:`CharacterSummaryView` per character — used to
        populate the player picker without the admin-gated full snapshot. Remote backends
        re-validate the server JSON back into the shared model, so the client owns
        validation of its server interaction layer."""
        return []

    async def fetch_character_projection(self, character_id: str) -> dict | None:
        return None

    async def fetch_room_projection(self, room_id: str, character_id: str) -> dict | None:
        return None

    async def fetch_queued_commands(self, character_id: str) -> dict:
        return {
            "ok": True,
            "schema_version": 1,
            "world_epoch": 0,
            "character_id": character_id,
            "generated_at_unix": time.time(),
            "next_tick_at_unix": None,
            "tick_seconds": None,
            "time_scale": None,
            "game_seconds_per_tick": None,
            "commands": [],
        }

    async def cancel_command(
        self,
        character_id: str,
        command_id: str,
        controller_id: str,
        controller_generation: int,
    ) -> bool:
        return False

    @abstractmethod
    async def submit(self, command: dict) -> SubmitResult: ...

    @abstractmethod
    async def claim(self, player_id: str, world: World) -> ControlClaim | None:
        """Return the controller (id, generation) the player should submit commands as."""

    async def release_controller(
        self,
        player_id: str,
        control: ControlClaim,
    ) -> ControlClaim | None:
        return control

    async def release_claim(self, player_id: str, control: ControlClaim) -> bool:
        return False

    async def recent_events(self, character_id: str = "") -> list[dict]:
        """Recent domain-event messages (``{"type": "event", "data": {...}}``) for clients
        that narrate perceived activity. Backends without an event feed return nothing."""
        return []

    def supports_live_updates(self) -> bool:
        return False

    async def watch_updates(
        self,
        character_id: str,
        control: ControlClaim | None,
        on_message: Callable[[dict], object],
        on_state: Callable[[str], object],
    ) -> None:
        """Watch player updates until cancelled. Local backends remain polling-only."""
        return None

    async def request_image(self, character_id: str) -> ImageRequestResult:
        """Request an image of the character's current scene (the 📷 camera affordance)."""
        return ImageRequestResult(ok=False, status="unavailable", reason="not available")

    async def open_character_sheet(self, character_id: str) -> SheetOpenResult:
        """Open the web character-sheet deep link for a character."""
        return SheetOpenResult(ok=False, reason="Character sheets require a remote server URL")


def frontend_base_for_api(api_base: str) -> str:
    """Best-effort frontend origin for an API base URL.

    Deployed Bunnyland serves the web bundle at the same origin as ``/api``. Raw server
    URLs without an ``/api`` path still produce a stable same-origin deep link.
    """
    parsed = urllib.parse.urlparse(api_base.rstrip("/"))
    path = parsed.path.rstrip("/")
    if path == "/api":
        path = ""
    elif path.endswith("/api"):
        path = path[: -len("/api")]
    stripped = parsed._replace(path=path or "", params="", query="", fragment="")
    return urllib.parse.urlunparse(stripped).rstrip("/")


def character_sheet_url(api_base: str, character_id: str) -> str:
    frontend = frontend_base_for_api(api_base)
    query = urllib.parse.urlencode({"server": api_base.rstrip("/")})
    fragment = urllib.parse.quote(character_id, safe=":")
    return f"{frontend}/character-sheet.html?{query}#{fragment}"


class LocalBackend(Backend):
    """Generate an offline world and tick it in-process, the TUI as a real player."""

    def __init__(
        self,
        *,
        seed: str = "a quiet marsh",
        generator: str = "apartment-demo",
        tick_seconds: float = 1.0,
        time_scale: float = 3600.0,
        autorun: bool = True,
        client_id: str | None = None,
        fallback_controller: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.seed = seed
        self.generator_name = generator
        self.tick_seconds = tick_seconds
        self.time_scale = time_scale
        self.autorun = autorun
        self.label = f"local · {generator}"
        self.actor = None
        self.meta = None
        self._loop = None
        self._task: asyncio.Task | None = None
        self._controller = None
        self._claim_secrets = ClaimSecretRegistry()
        self._events = None
        self.client_id = client_id or persistent_client_id()
        self.fallback_controller = fallback_controller
        self.timeout_seconds = timeout_seconds
        self.imagegen = None

    @property
    def supports_image_requests(self) -> bool:
        return self.imagegen is not None

    def configure_world(self, *, seed: str, generator: str) -> None:
        """Update local generation inputs before ``start`` creates the world."""
        self.seed = seed
        self.generator_name = generator
        self.label = f"local · {generator}"

    async def start(self) -> None:
        # Imported here so the optional server/llm wiring is only pulled when hosting.
        from ..core.world_actor import WorldActor
        from ..engine import GameLoop
        from ..llm_agents import ControllerDispatch, ScriptedAgent
        from ..persistence import WorldMeta
        from ..plugins import (
            apply_plugins,
            bunnyland_plugins,
            collect_persona_fragments,
            collect_prompt_fragments,
            select,
        )
        from ..prompts.builder import PromptBuilder
        from ..server.subscriptions import EventStream
        from ..worldgen import GenOptions, collect_generators

        plugins = select(list(bunnyland_plugins()), None)
        self.actor = WorldActor()
        apply_plugins(plugins, self.actor)
        self._events = EventStream(self.actor)  # record events for clients that narrate them

        registry = collect_generators(plugins)
        generator = registry.get(self.generator_name)
        if generator is None:
            names = ", ".join(sorted(registry)) or "(none)"
            raise SystemExit(f"unknown generator {self.generator_name!r}; available: {names}")
        await generator.generate(self.actor, self.seed, GenOptions())
        self.meta = WorldMeta(seed=self.seed, generator=generator.name)

        builder = PromptBuilder(
            self.actor.world,
            fragment_providers=collect_prompt_fragments(plugins),
            persona_providers=collect_persona_fragments(plugins),
        )
        dispatch = ControllerDispatch(self.actor, builder, ScriptedAgent([]))
        self._loop = GameLoop(
            self.actor, dispatch, tick_seconds=self.tick_seconds, time_scale=self.time_scale
        )
        if self.autorun:
            self._task = asyncio.create_task(self._loop.run())

    async def close(self) -> None:
        if self._loop is not None:
            self._loop.stop()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    async def fetch_snapshot(self) -> dict:
        return serialize_world(self.actor, self.meta)

    async def fetch_character_list(self) -> list[CharacterSummaryView]:
        return list(serialize_character_list(self.actor).characters)

    async def fetch_character_projection(self, character_id: str) -> dict | None:
        return serialize_character_projection(self.actor, character_id).model_dump(mode="json")

    async def fetch_room_projection(self, room_id: str, character_id: str) -> dict | None:
        character = self.actor.world.get_entity(parse_entity_id(character_id))
        if container_of(character) != parse_entity_id(room_id):
            raise PermissionError("room is not currently visible to character")
        return serialize_room_projection(self.actor, room_id).model_dump(mode="json")

    async def fetch_queued_commands(self, character_id: str) -> dict:
        now = time.time()
        tick_seconds = getattr(self._loop, "tick_seconds", None) if self._loop is not None else None
        time_scale = getattr(self._loop, "time_scale", None) if self._loop is not None else None
        next_tick_at_unix = (
            getattr(self._loop, "next_tick_at_unix", None) if self._loop is not None else None
        )
        if (
            next_tick_at_unix is None
            and tick_seconds is not None
            and self._loop is not None
            and self._loop.running
            and not self._loop.paused
        ):
            next_tick_at_unix = now + float(tick_seconds)
        return serialize_character_queued_commands(
            self.actor,
            character_id,
            generated_at_unix=now,
            next_tick_at_unix=next_tick_at_unix,
            tick_seconds=float(tick_seconds) if tick_seconds is not None else None,
            time_scale=float(time_scale) if time_scale is not None else None,
            game_seconds_per_tick=(
                float(tick_seconds) * float(time_scale)
                if tick_seconds is not None and time_scale is not None
                else None
            ),
        ).model_dump(mode="json")

    async def cancel_command(
        self,
        character_id: str,
        command_id: str,
        controller_id: str,
        controller_generation: int,
    ) -> bool:
        controller = parse_entity_id(controller_id)
        character = parse_entity_id(character_id)
        if (
            character is None
            or controller is None
            or self.actor.current_generation(character, controller) != controller_generation
        ):
            return False
        return await self.actor.cancel_command(character_id, command_id) is not None

    async def submit(self, command: dict) -> SubmitResult:
        cost = command.get("cost") or {}
        outcome = await self.actor.submit(
            build_submitted_command(
                character_id=command["character_id"],
                controller_id=command["controller_id"],
                controller_generation=command["controller_generation"],
                command_type=command["command_type"],
                payload=command.get("payload") or {},
                cost=CommandCost(action=cost.get("action", 0), focus=cost.get("focus", 0)),
                lane=Lane(command.get("lane", "world")),
                on_insufficient_points=OnInsufficientPoints(
                    command.get("on_insufficient_points", "queue")
                ),
                submitted_at_epoch=self.actor.epoch,
            )
        )
        return SubmitResult(accepted=outcome.accepted, reason=outcome.reason)

    async def recent_events(self, character_id: str = "") -> list[dict]:
        return self._events.recent_messages() if self._events is not None else []

    async def request_image(self, character_id: str) -> ImageRequestResult:
        if self.imagegen is None:
            return ImageRequestResult(
                ok=False, status="unavailable", reason="image generation is not configured"
            )
        from ..imagegen.scene import request_scene_image

        job = await request_scene_image(self.actor, self.imagegen, character_id=character_id)
        if job is None:
            return ImageRequestResult(
                ok=False, status="no-room", reason="your character has no room to illustrate"
            )
        return ImageRequestResult(ok=True, status=job.status, url=job.url)

    async def claim(self, player_id: str, world: World) -> ControlClaim | None:
        """Hand the character to a single reusable web controller, bumping its generation
        so the offline dispatch stops driving it."""
        async with self.actor._lock:
            stored = load_claim_control(self.client_id, player_id)
            stored_valid = (
                stored
                if stored and self._claim_secrets.validate(stored.claim_id, stored.claim_secret)
                else None
            )
            if self._controller is None:
                self._controller = spawn_entity(
                    self.actor.world,
                    [WebControllerComponent(client_id=self.client_id, label="tui")],
                )
            claim = add_claim(
                self._controller,
                client_kind=CLIENT_KIND_WEB,
                client_id=self.client_id,
                character_id=player_id,
                label="tui",
                claim_id=stored_valid.claim_id if stored_valid else None,
                now_unix=int(time.time()),
            )
            claim_secret = (
                stored_valid.claim_secret
                if stored_valid is not None
                else self._claim_secrets.issue(claim.claim_id)
            )
            apply_claim_timeout_settings(
                self._controller,
                now_unix=int(time.time()),
                fallback_controller=self.fallback_controller,
                timeout_seconds=self.timeout_seconds,
                reset_activity=True,
            )
            generation = self.actor.assign_controller(
                parse_entity_id(player_id), self._controller.id
            )
            character = self.actor.world.get_entity(parse_entity_id(player_id))
            if character.has_component(SuspendedComponent):
                character.remove_component(SuspendedComponent)
        control = ControlClaim(
            controller_id=str(self._controller.id),
            generation=generation,
            claim_id=claim.claim_id,
            claim_secret=claim_secret,
            active=True,
        )
        save_claim_control(self.client_id, player_id, control)
        return control

    async def release_controller(
        self,
        player_id: str,
        control: ControlClaim,
    ) -> ControlClaim | None:
        async with self.actor._lock:
            character_id = parse_entity_id(player_id)
            if character_id is None or not self.actor.world.has_entity(character_id):
                return None
            old_controller_id = parse_entity_id(control.controller_id)
            if old_controller_id is None or not self.actor.world.has_entity(old_controller_id):
                return None
            old_controller = self.actor.world.get_entity(old_controller_id)
            fallback = (self.fallback_controller or "suspend").strip()
            parsed_fallback = parse_entity_id(fallback)
            if parsed_fallback is not None and self.actor.world.has_entity(parsed_fallback):
                new_controller = self.actor.world.get_entity(parsed_fallback)
                kind = self.actor._controller_kind(parsed_fallback)
                if kind == "unknown":
                    return None
            elif fallback == "llm":
                new_controller = spawn_entity(
                    self.actor.world,
                    [
                        LLMControllerComponent(
                            profile_name="default",
                            model=os.environ.get("BUNNYLAND_CHARACTER_MODEL", "deepseek-v4-flash"),
                        )
                    ],
                )
                kind = "llm"
            else:
                new_controller = spawn_entity(
                    self.actor.world,
                    [SuspendedControllerComponent(reason="released by TUI client")],
                )
                kind = "suspended"
            transfer_claim(old_controller, new_controller)
            character = self.actor.world.get_entity(character_id)
            if kind == "suspended":
                generation = self.actor.suspend(
                    character_id,
                    new_controller.id,
                    reason="released by TUI client",
                )
            else:
                generation = self.actor.assign_controller(character_id, new_controller.id)
                if character.has_component(SuspendedComponent):
                    character.remove_component(SuspendedComponent)
        released = ControlClaim(
            controller_id=str(new_controller.id),
            generation=generation,
            claim_id=control.claim_id,
            claim_secret=control.claim_secret,
            active=False,
        )
        save_claim_control(self.client_id, player_id, released)
        return released

    async def release_claim(self, player_id: str, control: ControlClaim) -> bool:
        controller_id = parse_entity_id(control.controller_id)
        if controller_id is None or not self.actor.world.has_entity(controller_id):
            return False
        remove_claim(self.actor.world.get_entity(controller_id), self._claim_secrets)
        clear_claim_control(self.client_id, player_id)
        return True


class RemoteBackend(Backend):
    """Poll a running server over HTTP for snapshots and post commands to it."""

    supports_character_sheets = True
    supports_image_requests = True

    def __init__(
        self,
        base_url: str,
        *,
        client_id: str | None = None,
        fallback_controller: str | None = None,
        timeout_seconds: int | None = None,
        username: str = "",
        password: str = "",
        token_file: str | Path | None = None,
    ) -> None:
        self.base = _validate_remote_server_url(base_url)
        self.label = f"remote · {self.base}"
        self._client = None
        self.client_id = client_id or persistent_client_id()
        self.fallback_controller = fallback_controller
        self.timeout_seconds = timeout_seconds
        self.username = username
        self._password = password
        self.token_file = Path(token_file) if token_file else None
        if self.token_file is not None:
            _validate_token_file_mode(self.token_file)
        self._access_token = ""
        self._rotate_after: int | None = None
        self._rotation_task = None
        self._claims: dict[str, ControlClaim] = {}

    def _claim_for(self, character_id: str) -> ControlClaim | None:
        return self._claims.get(character_id) or load_claim_control(self.client_id, character_id)

    def _claim_headers(self, character_id: str) -> dict[str, str]:
        claim = self._claim_for(character_id)
        return (
            {"X-Bunnyland-Claim-Secret": claim.claim_secret} if claim and claim.claim_secret else {}
        )

    def _claim_params(self, character_id: str) -> dict[str, str]:
        claim = self._claim_for(character_id)
        return {"claim_id": claim.claim_id} if claim and claim.claim_id else {}

    def _claim_request_kwargs(self, character_id: str, *, params: bool = False) -> dict:
        kwargs = {}
        claim_headers = self._claim_headers(character_id)
        if claim_headers:
            kwargs["headers"] = claim_headers
        claim_params = self._claim_params(character_id)
        if params and claim_params:
            kwargs["params"] = claim_params
        return kwargs

    async def start(self) -> None:
        import httpx

        self._client = httpx.AsyncClient(timeout=10.0)
        if self.token_file is not None and self.token_file.exists():
            self._access_token = self.token_file.read_text(encoding="utf-8").strip()
            self._set_access_token(self._access_token)
            await self._refresh_auth_metadata()
        elif self.username and self._password:
            await self._login()
        if self._access_token:
            self._rotation_task = asyncio.create_task(self._rotation_loop())

    async def close(self) -> None:
        if self._rotation_task is not None:
            self._rotation_task.cancel()
            try:
                await self._rotation_task
            except asyncio.CancelledError:
                pass
        if self._client is not None:
            await self._client.aclose()

    def _set_access_token(self, token: str) -> None:
        self._access_token = token
        if self._client is not None:
            self._client.headers["Authorization"] = f"Bearer {token}"

    def _persist_access_token(self) -> None:
        if self.token_file is None:
            return
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.token_file,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(f"{self._access_token}\n")
        self.token_file.chmod(0o600)

    async def _login(self) -> None:
        res = await self._client.post(
            f"{self.base}/auth/login",
            json={"username": self.username, "password": self._password, "delivery": "body"},
        )
        self._password = ""
        res.raise_for_status()
        body = res.json()
        self._set_access_token(str(body["token"]))
        self._rotate_after = body.get("rotate_after")
        self._persist_access_token()

    async def _refresh_auth_metadata(self) -> None:
        res = await self._client.get(f"{self.base}/auth/me")
        res.raise_for_status()
        self._rotate_after = res.json().get("rotate_after")

    async def _rotate_token(self) -> None:
        res = await self._client.post(f"{self.base}/auth/rotate")
        if res.status_code == 409:
            await self._refresh_auth_metadata()
            return
        res.raise_for_status()
        body = res.json()
        self._set_access_token(str(body["token"]))
        self._rotate_after = body.get("rotate_after")
        self._persist_access_token()

    async def _rotation_loop(self) -> None:
        while True:
            delay = 60.0
            if self._rotate_after is not None:
                delay = max(0.0, min(60.0, self._rotate_after - time.time()))
            await asyncio.sleep(delay)
            if self._rotate_after is not None and time.time() >= self._rotate_after:
                try:
                    await self._rotate_token()
                except Exception:
                    logger.warning("Could not rotate Bunnyland access token", exc_info=True)
                    await asyncio.sleep(30.0)

    async def fetch_snapshot(self) -> dict:
        res = await self._client.get(f"{self.base}/admin/world/snapshot")
        res.raise_for_status()
        return res.json()

    async def fetch_character_list(self) -> list[CharacterSummaryView]:
        res = await self._client.get(f"{self.base}/play/world/characters")
        res.raise_for_status()
        return list(CharacterListResponse.model_validate(res.json()).characters)

    async def fetch_character_projection(self, character_id: str) -> dict | None:
        res = await self._client.get(
            f"{self.base}/play/world/character/{character_id}",
            **self._claim_request_kwargs(character_id, params=True),
        )
        res.raise_for_status()
        return res.json()

    async def fetch_room_projection(self, room_id: str, character_id: str) -> dict | None:
        kwargs = self._claim_request_kwargs(character_id, params=True)
        kwargs["params"] = {
            **kwargs.get("params", {}),
            "character_id": character_id,
        }
        res = await self._client.get(f"{self.base}/play/world/room/{room_id}", **kwargs)
        res.raise_for_status()
        return res.json()

    async def fetch_queued_commands(self, character_id: str) -> dict:
        res = await self._client.get(
            f"{self.base}/play/world/character/{character_id}/commands",
            **self._claim_request_kwargs(character_id, params=True),
        )
        res.raise_for_status()
        return res.json()

    async def cancel_command(
        self,
        character_id: str,
        command_id: str,
        controller_id: str,
        controller_generation: int,
    ) -> bool:
        kwargs = self._claim_request_kwargs(character_id)
        kwargs["params"] = {
            "controller_id": controller_id,
            "controller_generation": controller_generation,
            **self._claim_params(character_id),
        }
        res = await self._client.delete(
            f"{self.base}/play/world/character/{character_id}/commands/{command_id}",
            **kwargs,
        )
        if not res.is_success:
            return False
        return bool(res.json().get("cancelled"))

    async def submit(self, command: dict) -> SubmitResult:
        character_id = str(command.get("character_id") or "")
        claim = self._claim_for(character_id)
        if claim is not None and claim.claim_id:
            command = {**command, "claim_id": claim.claim_id}
        kwargs = self._claim_request_kwargs(character_id)
        kwargs["json"] = command
        res = await self._client.post(f"{self.base}/play/world/commands", **kwargs)
        try:
            body = res.json()
        except Exception:
            body = {}
        if not res.is_success:
            reason = str(
                body.get("reason") or f"request failed ({getattr(res, 'status_code', '?')})"
            )
            return SubmitResult(accepted=False, reason=reason)
        return SubmitResult(
            accepted=bool(body.get("queued", True)), reason=str(body.get("reason", ""))
        )

    async def recent_events(self, character_id: str = "") -> list[dict]:
        if not character_id:
            return []
        res = await self._client.get(
            f"{self.base}/play/world/character/{character_id}/events/recent",
            **self._claim_request_kwargs(character_id, params=True),
        )
        res.raise_for_status()
        return res.json().get("events", [])

    def supports_live_updates(self) -> bool:
        try:
            import websockets  # noqa: F401
        except ImportError:
            return False
        return True

    async def watch_updates(
        self,
        character_id: str,
        control: ControlClaim | None,
        on_message: Callable[[dict], object],
        on_state: Callable[[str], object],
    ) -> None:
        try:
            import websockets
        except ImportError:
            await _call_update_callback(on_state, "fallback")
            return
        parsed = urllib.parse.urlparse(self.base)
        encoded_character = urllib.parse.quote(character_id, safe="")
        path = f"{parsed.path.rstrip('/')}/play/world/character/{encoded_character}/updates"
        url = urllib.parse.urlunparse(
            parsed._replace(
                scheme="wss" if parsed.scheme == "https" else "ws",
                path=path,
                params="",
                query="",
                fragment="",
            )
        )
        attempt = 0
        while True:
            await _call_update_callback(on_state, "connecting")
            ready = False
            try:
                async with websockets.connect(url, open_timeout=10) as socket:
                    await socket.send(
                        json.dumps(
                            {
                                "type": "authenticate",
                                "data": {
                                    "token": self._access_token or None,
                                    "claim_id": control.claim_id if control else None,
                                    "claim_secret": control.claim_secret if control else None,
                                },
                            }
                        )
                    )
                    while True:
                        raw = await asyncio.wait_for(socket.recv(), timeout=70.0)
                        try:
                            frame = json.loads(raw)
                        except (TypeError, json.JSONDecodeError):
                            continue
                        if not isinstance(frame, dict) or frame.get("type") not in {
                            "ready",
                            "event",
                            "invalidate",
                            "resync",
                            "heartbeat",
                        }:
                            continue
                        if frame["type"] == "ready":
                            ready = True
                            attempt = 0
                            await _call_update_callback(on_state, "live")
                        await _call_update_callback(on_message, frame)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("Remote player update stream disconnected", exc_info=True)
            await _call_update_callback(on_state, "fallback")
            delay = (1, 2, 4, 8, 16, 30)[min(attempt, 5)]
            attempt = 0 if ready else attempt + 1
            await asyncio.sleep(delay * random.uniform(0.8, 1.2))

    async def request_image(self, character_id: str) -> ImageRequestResult:
        res = await self._client.post(
            f"{self.base}/play/world/character/{character_id}/scene-image",
            **self._claim_request_kwargs(character_id, params=True),
        )
        if res.status_code == 409:
            return ImageRequestResult(
                ok=False, status="unavailable", reason="image generation is not available"
            )
        if not res.is_success:
            return ImageRequestResult(
                ok=False, status="error", reason=f"request failed ({res.status_code})"
            )
        body = res.json()
        return ImageRequestResult(ok=True, status=body.get("status", ""), url=body.get("url", ""))

    async def open_character_sheet(self, character_id: str) -> SheetOpenResult:
        url = character_sheet_url(self.base, character_id)
        opened = webbrowser.open(url, new=2)
        if not opened:
            return SheetOpenResult(ok=False, url=url, reason="could not open browser")
        return SheetOpenResult(ok=True, url=url)

    async def claim(self, player_id: str, world: World) -> ControlClaim | None:
        stored = load_claim_control(self.client_id, player_id)
        headers = (
            {"X-Bunnyland-Claim-Secret": stored.claim_secret}
            if stored and stored.claim_secret
            else {}
        )
        kwargs = {
            "json": {
                "character_id": player_id,
                "client_id": self.client_id,
                "label": "tui",
                "fallback_controller": self.fallback_controller,
                "timeout_seconds": self.timeout_seconds,
            },
        }
        if stored is not None:
            kwargs["json"]["claim_id"] = stored.claim_id
        if headers:
            kwargs["headers"] = headers
        res = await self._client.post(f"{self.base}/play/world/controllers/web/claim", **kwargs)
        if not res.is_success:
            logger.warning(
                "Remote web controller claim failed for %s: HTTP %s %s",
                player_id,
                res.status_code,
                res.text,
            )
            return None
        data = res.json()
        control = ControlClaim(
            controller_id=data["controller_id"],
            generation=int(data["controller_generation"]),
            claim_id=str(data.get("claim_id") or ""),
            claim_secret=str(data.get("claim_secret") or ""),
            active=True,
        )
        self._claims[player_id] = control
        save_claim_control(self.client_id, player_id, control)
        return control

    async def release_controller(
        self,
        player_id: str,
        control: ControlClaim,
    ) -> ControlClaim | None:
        res = await self._client.post(
            f"{self.base}/play/world/controllers/web/release-controller",
            headers={"X-Bunnyland-Claim-Secret": control.claim_secret},
            json={
                "character_id": player_id,
                "client_id": self.client_id,
                "claim_id": control.claim_id,
                "fallback_controller": self.fallback_controller,
                "timeout_seconds": self.timeout_seconds,
            },
        )
        if not res.is_success:
            logger.warning(
                "Remote web controller release failed for %s: HTTP %s %s",
                player_id,
                res.status_code,
                res.text,
            )
            return None
        data = res.json()
        released = ControlClaim(
            controller_id=data["controller_id"],
            generation=int(data["controller_generation"]),
            claim_id=str(data.get("claim_id") or control.claim_id),
            claim_secret=str(data.get("claim_secret") or control.claim_secret),
            active=False,
        )
        self._claims[player_id] = released
        save_claim_control(self.client_id, player_id, released)
        return released

    async def release_claim(self, player_id: str, control: ControlClaim) -> bool:
        res = await self._client.post(
            f"{self.base}/play/world/controllers/web/release-claim",
            headers={"X-Bunnyland-Claim-Secret": control.claim_secret},
            json={
                "character_id": player_id,
                "client_id": self.client_id,
                "claim_id": control.claim_id,
            },
        )
        if not res.is_success:
            logger.warning(
                "Remote web claim release failed for %s: HTTP %s %s",
                player_id,
                res.status_code,
                res.text,
            )
            return False
        self._claims.pop(player_id, None)
        clear_claim_control(self.client_id, player_id)
        return True
