"""Terminal client for opt-in character chat."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

from .core.claim_timeout import normalize_claim_timeout
from .terminal_chat import (
    HISTORY_LIMIT,
    append_exchange,
    history_path,
    load_history,
    save_history,
)
from .terminal_config import (
    TerminalConfigError,
    load_terminal_config,
    resolve_terminal_chat_config,
    save_terminal_config,
)
from .terminal_generators import available_generators, format_generator_lines
from .tui.backend import Backend, CharacterChatAccess, LocalBackend, RemoteBackend
from .tui.generator_selector import (
    DEFAULT_LOCAL_GENERATOR,
    DEFAULT_LOCAL_SEED,
    WorldGeneratorSelector,
)
from .tui.screens import CharacterPickerScreen, ConversationScreen, TerminalSetupScreen


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "bunnyland"


def persistent_client_id() -> str:
    from .tui.backend import persistent_client_id as shared_client_id

    return shared_client_id()


def api_url(base: str, path: str) -> str:
    return f"{base.strip().rstrip('/')}{path}"


def get_json(base: str, path: str, client_id: str = "") -> dict:
    request = urllib.request.Request(
        api_url(base, path),
        headers={"X-Bunnyland-Client-Id": client_id} if client_id else {},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(
    base: str,
    path: str,
    payload: dict,
    *,
    client_id: str = "",
) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        api_url(base, path),
        data=body,
        headers={
            "Content-Type": "application/json",
            **({"X-Bunnyland-Client-Id": client_id} if client_id else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8") or "{}").get("detail")
        finally:
            exc.close()
        raise RuntimeError(detail or f"HTTP {exc.code}") from exc


def choose_character(base: str, wanted: str, client_id: str = "") -> tuple[str, str]:
    data = get_json(base, "/profile/characters", client_id)
    characters = data.get("characters") or []
    if not characters:
        raise RuntimeError("no characters are available")
    if wanted:
        query = wanted.strip().lower()
        for character in characters:
            if character.get("id") == wanted or character.get("name", "").lower() == query:
                return character["id"], character.get("name") or character["id"]
        raise RuntimeError(f"no such character: {wanted!r}")
    first = characters[0]
    return first["id"], first.get("name") or first["id"]


def request_payload(client_id: str, state: dict, message: str) -> dict:
    return {
        "kind": "chat",
        "message": message,
        "history_summary": str(state.get("summary") or ""),
        "history": list(state.get("messages") or [])[-HISTORY_LIMIT:],
    }


def wait_for_job(base: str, character_id: str, client_id: str, job: dict) -> dict:
    while job.get("status") in {"queued", "running"}:
        time.sleep(0.5)
        job = get_json(
            base,
            "/chat/characters/"
            f"{urllib.parse.quote(character_id, safe='')}/jobs/"
            f"{urllib.parse.quote(str(job.get('id') or ''), safe='')}",
            client_id,
        )
    return job


class CharacterChatApp(App[None]):
    """Focused character picker and conversation client for local or remote play."""

    TITLE = "Bunnyland Character Chat"

    def __init__(
        self,
        backend: Backend,
        *,
        character: str = "",
        show_generator_selector: bool = False,
        needs_chat_setup: bool = False,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.wanted_character = character
        self.show_generator_selector = show_generator_selector
        self.needs_chat_setup = needs_chat_setup
        self.characters = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Starting character chat…", id="chat-app-status")
        yield Footer()

    async def on_mount(self) -> None:
        if self.needs_chat_setup and isinstance(self.backend, LocalBackend):
            self.push_screen(TerminalSetupScreen(), callback=self._chat_setup_selected)
            return
        self._continue_local_flow()

    def _chat_setup_selected(self, config) -> None:
        if config is None:
            self.exit()
            return
        try:
            save_terminal_config(config)
            settings = resolve_terminal_chat_config(config)
            settings.validate_credentials()
        except TerminalConfigError as exc:
            self.notify(str(exc), severity="error", timeout=8)
            self.push_screen(TerminalSetupScreen(), callback=self._chat_setup_selected)
            return
        self.backend.chat_config = settings
        self.needs_chat_setup = False
        self._continue_local_flow()

    def _continue_local_flow(self) -> None:
        if self.show_generator_selector and isinstance(self.backend, LocalBackend):
            self.push_screen(
                WorldGeneratorSelector(
                    available_generators(),
                    initial_generator=self.backend.generator_name,
                    initial_seed=self.backend.seed,
                ),
                callback=self._generator_selected,
            )
        else:
            self.run_worker(self._start_backend(), exclusive=True)

    def _generator_selected(self, selection) -> None:
        if selection is None:
            self.exit()
            return
        self.backend.configure_world(seed=selection.seed, generator=selection.generator)
        self.run_worker(self._start_backend(), exclusive=True)

    async def _start_backend(self) -> None:
        try:
            await self.backend.start()
            self.characters = await self.backend.fetch_character_list()
        except Exception as exc:
            self.query_one("#chat-app-status", Static).update(f"Could not start chat: {exc}")
            return
        if not self.characters:
            self.query_one("#chat-app-status", Static).update("No characters are available.")
            return
        if self.wanted_character:
            chosen = self._resolve_character(self.wanted_character)
            if chosen is None:
                self.query_one("#chat-app-status", Static).update(
                    f"No such character: {self.wanted_character!r}"
                )
                return
            self._open_conversation(chosen.character_id)
            return
        self._show_picker()

    def _resolve_character(self, wanted: str):
        query = wanted.strip().lower()
        return next(
            (
                item
                for item in self.characters
                if item.character_id == wanted or item.name.lower() == query
            ),
            None,
        )

    def _show_picker(self) -> None:
        self.push_screen(
            CharacterPickerScreen(self.characters, title="Choose a character to chat with"),
            callback=lambda chosen: self._open_conversation(chosen) if chosen else self.exit(),
        )

    def _open_conversation(self, character_id: str) -> None:
        character = self._resolve_character(character_id)
        if character is None:
            return
        self.push_screen(
            ConversationScreen(self.backend, character.character_id, character.name),
            callback=lambda _: self.exit() if self.wanted_character else self._show_picker(),
        )

    async def on_unmount(self) -> None:
        await self.backend.close()


def _print_cli_history(state: dict, character_name: str) -> None:
    for item in state.get("messages") or []:
        label = "You" if item.get("role") == "user" else character_name
        print(f"{label}: {item.get('text') or ''}")


def _print_controller_choices(access: CharacterChatAccess) -> None:
    if not access.controllers:
        print("No assignable LLM controllers are available for this session.")
        return
    print("Assignable LLM controllers:")
    for controller in access.controllers:
        print(f"  {controller.controller_id} · {controller.label}")
    print("Use /controller <id> to assign one.")


async def _run_cli(backend: Backend, wanted: str) -> int:
    await backend.start()
    try:
        available, reason = await backend.character_chat_availability()
        if not available:
            raise SystemExit(reason)
        characters = await backend.fetch_character_list()
        if not characters:
            raise SystemExit("no characters are available")
        query = wanted.strip().lower()
        character = next(
            (
                item
                for item in characters
                if item.character_id == wanted or (query and item.name.lower() == query)
            ),
            None,
        )
        if character is None:
            if wanted:
                raise SystemExit(f"no such character: {wanted!r}")
            character = characters[0]
        state = load_history(backend.client_id, character.character_id)
        print(f"Chatting with {character.name}. Ctrl-D or /quit exits.")
        _print_cli_history(state, character.name)
        access = await backend.character_chat_access(character.character_id)
        if not access.writable:
            print(access.reason)
            if access.can_assign:
                _print_controller_choices(access)
        while True:
            try:
                message = input("> ").strip()
            except EOFError:
                print()
                break
            if not message:
                continue
            if message in {"/quit", "/exit"}:
                break
            if message in {"/help", "/meta"}:
                print("Meta: /controller <id>, /controllers, /help, /quit")
                continue
            if message == "/controllers":
                access = await backend.character_chat_access(character.character_id)
                _print_controller_choices(access)
                continue
            if message == "/controller" or message.startswith("/controller "):
                controller_id = message.removeprefix("/controller").strip()
                if not controller_id:
                    print("Usage: /controller <id>")
                    continue
                access = await backend.character_chat_access(character.character_id)
                if controller_id not in {
                    controller.controller_id for controller in access.controllers
                }:
                    print(
                        "That LLM controller is not assignable; use /controllers to list choices."
                    )
                    continue
                try:
                    access = await backend.assign_character_chat_controller(
                        character.character_id,
                        controller_id,
                    )
                except Exception as exc:
                    print(f"Controller assignment failed: {exc}")
                    continue
                if access.writable:
                    print(f"{character.name} is now assigned to an LLM controller.")
                else:
                    print(access.reason)
                continue
            access = await backend.character_chat_access(character.character_id)
            if not access.writable:
                print(access.reason)
                if access.can_assign:
                    print("Use /controllers to list assignable LLM controllers.")
                continue
            try:
                job = await backend.submit_character_chat(
                    character.character_id,
                    message,
                    history_summary=str(state.get("summary") or ""),
                    history=list(state.get("messages") or []),
                )
                while job.pending:
                    if job.reply:
                        print(
                            f"{character.name}: {job.reply} [pending {job.action.tool or 'action'}]"
                        )
                    await asyncio.sleep(0.25)
                    job = await backend.poll_character_chat(job)
            except Exception as exc:
                print(f"{character.name}: Chat failed: {exc}")
                continue
            if job.status == "failed":
                print(f"{character.name}: {job.failure or 'Chat failed.'}")
                continue
            suffix = f" [{job.action.tool} {job.action.status}]" if job.action.tool else ""
            print(f"{character.name}: {job.reply}{suffix}")
            append_exchange(state, message, job.reply)
            save_history(backend.client_id, character.character_id, state)
        save_history(backend.client_id, character.character_id, state)
        return 0
    finally:
        await backend.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bunnyland chat", description=__doc__)
    parser.add_argument("--server", default=None)
    parser.add_argument("--character", default="", help="character id or exact name")
    parser.add_argument("--username", default="", help="login username for a remote server")
    parser.add_argument("--password-stdin", action="store_true")
    parser.add_argument("--token-file", default=None)
    parser.add_argument("--seed", default=None, help="seed for a locally hosted world")
    parser.add_argument("--generator", default=None, help="generator for a locally hosted world")
    parser.add_argument("--list-generators", action="store_true")
    parser.add_argument("--claim-fallback", choices=("suspend", "llm"), default=None)
    parser.add_argument("--claim-timeout-minutes", type=int, default=None)
    parser.add_argument(
        "--chat-provider",
        choices=("ollama-local", "ollama-cloud", "openrouter"),
        default=None,
    )
    parser.add_argument("--chat-model", default=None)
    parser.add_argument("--ollama-host", default=None)
    parser.add_argument("--openrouter-server-url", default=None)
    parser.add_argument("--no-chat", action="store_true")
    parser.add_argument("--cli", action="store_true", help="use line-oriented chat")
    args = parser.parse_args(argv)
    if args.list_generators:
        for line in format_generator_lines(available_generators()):
            print(line)
        return 0

    try:
        saved_chat = None if args.server else load_terminal_config()
    except TerminalConfigError as exc:
        raise SystemExit(str(exc)) from exc
    explicit_chat = any(
        (
            args.chat_provider,
            args.chat_model,
            args.ollama_host,
            args.openrouter_server_url,
            args.no_chat,
        )
    )
    if args.cli and not args.server and saved_chat is None and not explicit_chat:
        raise SystemExit(
            "local --cli chat needs saved terminal configuration, --chat-provider, or --no-chat"
        )
    settings = resolve_terminal_chat_config(
        saved_chat,
        chat_provider=args.chat_provider,
        chat_model=args.chat_model,
        ollama_host=args.ollama_host,
        openrouter_server_url=args.openrouter_server_url,
        no_chat=args.no_chat,
    )
    if not args.server and (saved_chat is not None or explicit_chat):
        try:
            settings.validate_credentials()
        except TerminalConfigError as exc:
            raise SystemExit(str(exc)) from exc
    if args.cli and not args.server and not settings.enabled:
        raise SystemExit("Character chat is disabled by terminal configuration")

    timeout_seconds = (
        normalize_claim_timeout(args.claim_timeout_minutes * 60)
        if args.claim_timeout_minutes is not None
        else None
    )
    password = ""
    if args.server and args.username:
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            from getpass import getpass

            password = getpass("Bunnyland password: ")
    backend: Backend = (
        RemoteBackend(
            args.server,
            fallback_controller=args.claim_fallback,
            timeout_seconds=timeout_seconds,
            username=args.username,
            password=password,
            token_file=args.token_file,
        )
        if args.server
        else LocalBackend(
            seed=args.seed or DEFAULT_LOCAL_SEED,
            generator=args.generator or DEFAULT_LOCAL_GENERATOR,
            fallback_controller=args.claim_fallback,
            timeout_seconds=timeout_seconds,
            chat_config=settings if saved_chat is not None or explicit_chat else None,
        )
    )
    if args.cli:
        return asyncio.run(_run_cli(backend, args.character))
    app = CharacterChatApp(
        backend,
        character=args.character,
        show_generator_selector=not args.server and args.generator is None,
        needs_chat_setup=not args.server and saved_chat is None and not explicit_chat,
    )
    app.run()
    return 0


__all__ = [
    "HISTORY_LIMIT",
    "append_exchange",
    "CharacterChatApp",
    "choose_character",
    "history_path",
    "load_history",
    "persistent_client_id",
    "request_payload",
    "save_history",
    "wait_for_job",
]
