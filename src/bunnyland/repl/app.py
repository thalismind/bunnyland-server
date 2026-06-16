"""Textual front-end for the Bunnyland REPL.

A scrolling :class:`~textual.widgets.RichLog` shows command output with characters, items,
rooms, containers, and exits rendered as clickable links; a single command
:class:`~textual.widgets.Input` adds Tab completion and Up/Down command history. Like the
TUI it can host a world in-process (no network port) or drive a running server over HTTP
through the web controller.
"""

from __future__ import annotations

import argparse
import os

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input, RichLog

from ..core.claim_timeout import normalize_claim_timeout
from ..tui.backend import Backend, LocalBackend, RemoteBackend
from ..tui.splash import IntroSplash
from .client import BunnylandRepl, available_generators, format_generator_lines, history_path

REFRESH_SECONDS = 1.0
HISTORY_LIMIT = 1000


class ReplInput(Input):
    """The command line: Tab completes, Up/Down walk submitted-command history."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.history: list[str] = []
        self._index = 0  # points one past the last entry (i.e. the live draft)
        self._draft = ""

    def remember(self, line: str) -> None:
        if line and (not self.history or self.history[-1] != line):
            self.history.append(line)
        self._index = len(self.history)

    async def on_key(self, event: events.Key) -> None:
        if event.key == "tab":
            event.prevent_default()
            event.stop()
            self._complete()
        elif event.key == "up":
            event.prevent_default()
            event.stop()
            self._recall(-1)
        elif event.key == "down":
            event.prevent_default()
            event.stop()
            self._recall(1)

    def _recall(self, delta: int) -> None:
        if not self.history:
            return
        if self._index == len(self.history):
            self._draft = self.value
        self._index = max(0, min(len(self.history), self._index + delta))
        self.value = self._draft if self._index == len(self.history) else self.history[self._index]
        self.cursor_position = len(self.value)

    def _complete(self) -> None:
        matches = self.app.repl.complete(self.value[: self.cursor_position])
        if not matches:
            self.app.bell()
            return
        if len(matches) == 1:
            self.value = matches[0]
        else:
            common = os.path.commonprefix(matches)
            if common and common != self.value:
                self.value = common
            self.app.write_log(Text("  ".join(matches), style="dim"))
        self.cursor_position = len(self.value)


class BunnylandReplApp(App[None]):
    TITLE = "Bunnyland REPL"

    # The log fills the space; the input and Footer flow beneath it. (Docking the input to
    # the bottom collides with the docked Footer and clips the input's last row.)
    CSS = """
    #log { height: 1fr; }
    """

    BINDINGS = [Binding("ctrl+c", "quit", "Quit")]

    def __init__(self, backend: Backend, *, show_intro: bool = False) -> None:
        super().__init__()
        self.repl = BunnylandRepl(backend)
        self.show_intro = show_intro
        self.log_view = RichLog(id="log", wrap=True)
        self.command = ReplInput(
            id="cmd", placeholder="type a command — 'help' for a list, 'quit' to exit"
        )
        self._refresh_error: str | None = None  # last reported refresh failure, for throttling

    def compose(self) -> ComposeResult:
        yield Header()
        yield self.log_view
        yield self.command
        yield Footer()

    async def on_mount(self) -> None:
        if self.show_intro:
            await self.push_screen(IntroSplash())
        await self.repl.backend.start()
        self._load_history()
        await self._safe_refresh(prime=True)  # seed event history without dumping the backlog
        self.write_log(
            Text(f"Bunnyland REPL · {self.repl.backend.label}. Type 'help', 'quit' to exit.",
                 style="bold")
        )
        self.set_interval(REFRESH_SECONDS, self._safe_refresh)
        self.command.focus()

    async def on_unmount(self) -> None:
        self._save_history()
        await self.repl.backend.close()

    # ── helpers ─────────────────────────────────────────────────────────────────
    def write_log(self, renderable) -> None:
        self.log_view.write(renderable)

    async def _safe_refresh(self, prime: bool = False) -> None:
        try:
            await self.repl.refresh()
            events = await self.repl.backend.recent_events()
        except Exception as exc:  # network hiccup, server restart, …
            message = f"⚠ {self.repl.backend.label} — {exc}"
            if message != self._refresh_error:  # report a failure once, not every tick
                self.write_log(Text(message, style="red"))
                self._refresh_error = message
        else:
            if self._refresh_error is not None:
                self.write_log(Text(f"✓ {self.repl.backend.label} — reconnected", style="green"))
                self._refresh_error = None
            narration = self.repl.drain_events(events)
            if not prime:  # on the first pass we only seed the seen-set
                for line in narration:
                    self.write_log(line)
        self.sub_title = self.repl.status_text()

    # ── events ──────────────────────────────────────────────────────────────────
    @on(Input.Submitted, "#cmd")
    async def _submitted(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        self.command.value = ""
        if not line:
            return
        self.command.remember(line)
        self.write_log(Text(f"> {line}", style="bold"))
        if line in {"quit", "exit"}:
            self.exit()
            return
        try:
            output = await self.repl.dispatch(line)
        except Exception as exc:  # keep the REPL alive through a bad command
            output = Text(f"⚠ {exc}", style="red")
        self.write_log(output)
        self.sub_title = self.repl.status_text()

    def action_insert(self, ref: str) -> None:
        """Clicking a target link inserts its name into the input at the cursor."""
        self.command.insert_text_at_cursor(self.repl.name_for(ref) or ref)
        self.command.focus()

    # ── history file ──────────────────────────────────────────────────────────
    def _load_history(self) -> None:
        try:
            text = history_path().read_text(encoding="utf-8")
        except OSError:
            return
        self.command.history = text.splitlines()[-HISTORY_LIMIT:]

    def _save_history(self) -> None:
        path = history_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "\n".join(self.command.history[-HISTORY_LIMIT:]) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bunnyland-repl", description=__doc__)
    parser.add_argument("--server", help="connect to a running server (e.g. http://localhost:8765)")
    parser.add_argument("--seed", default="a quiet marsh", help="seed for a locally hosted world")
    parser.add_argument(
        "--generator", default="apartment-demo", help="generator for a locally hosted world"
    )
    parser.add_argument("--claim-fallback", choices=("suspend", "llm"), default=None)
    parser.add_argument("--claim-timeout-minutes", type=int, default=None)
    parser.add_argument(
        "--list-generators",
        action="store_true",
        help="list the available world generators (demo worlds) for local play and exit",
    )
    args = parser.parse_args(argv)

    if args.list_generators:
        for line in format_generator_lines(available_generators()):
            print(line)
        return 0

    timeout_seconds = (
        normalize_claim_timeout(args.claim_timeout_minutes * 60)
        if args.claim_timeout_minutes is not None
        else None
    )

    backend: Backend = (
        RemoteBackend(
            args.server,
            fallback_controller=args.claim_fallback,
            timeout_seconds=timeout_seconds,
        ) if args.server
        else LocalBackend(
            seed=args.seed,
            generator=args.generator,
            fallback_controller=args.claim_fallback,
            timeout_seconds=timeout_seconds,
        )
    )
    BunnylandReplApp(backend, show_intro=True).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
