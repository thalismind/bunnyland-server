"""A Textual terminal client for Bunnyland: the room on the left, the action menu on the
right, click to select, pick a target after the action — the toon client in a terminal.
"""

from __future__ import annotations

import argparse

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from .backend import Backend, LocalBackend, RemoteBackend
from .model import World, entity_icon, entity_name, fmt_points, has
from .verbs import ACTION_VERBS, Verb

REFRESH_SECONDS = 1.0


class TargetPicker(ModalScreen[str]):
    """Modal list of candidate targets for a verb; dismisses with the chosen id or None."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, verb: Verb, candidates) -> None:
        super().__init__()
        self.verb = verb
        self.candidates = candidates

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Label(f"{self.verb.label} — choose a target", id="picker-title")
            if self.candidates:
                yield OptionList(
                    *[Option(f"{c.icon} {c.label}", id=c.value) for c in self.candidates],
                    id="picker-list",
                )
            else:
                yield Label("No valid targets nearby.", id="picker-empty")

    def on_mount(self) -> None:
        if self.candidates:
            self.query_one("#picker-list", OptionList).focus()

    @on(OptionList.OptionSelected, "#picker-list")
    def _chosen(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TextPrompt(ModalScreen[str]):
    """Modal single-line input; dismisses with the text or None."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title_text = title

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt"):
            yield Label(self.title_text, id="prompt-title")
            yield Input(id="prompt-input")

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()

    @on(Input.Submitted, "#prompt-input")
    def _submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BunnylandTUI(App[None]):
    TITLE = "Bunnyland TUI"

    CSS = """
    #body { height: 1fr; }
    #world { width: 3fr; border-right: solid $panel; }
    #actions { width: 2fr; padding: 0 1; }
    #status { padding: 0 1; color: $text-muted; height: 1; }
    .col-title { padding: 0 1; color: $accent; text-style: bold; }
    #members, #doors, #verbs { height: auto; max-height: 1fr; }
    #doors { border-top: solid $panel; }
    #points { padding: 0 1; height: 1; }
    #picker, #prompt {
        width: 60; height: auto; max-height: 80%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    TargetPicker, TextPrompt { align: center middle; }
    #picker-title, #prompt-title { text-style: bold; padding-bottom: 1; }
    #picker-empty { color: $text-muted; }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("f", "follow", "Follow player"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, backend: Backend) -> None:
        super().__init__()
        self.backend = backend
        self.world = World()
        self.player_id = ""
        self.control: tuple[str, int] | None = None
        self.view_room_id: str | None = None
        self.follow = True
        self.selected_id: str | None = None
        self._player_choice_ids: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Starting…", id="status")
        with Horizontal(id="body"):
            with Vertical(id="world"):
                yield Static("Room", id="room-title", classes="col-title")
                yield OptionList(id="members")
                yield Static("Doors", classes="col-title")
                yield OptionList(id="doors")
            with Vertical(id="actions"):
                yield Select([], prompt="— pick a player —", allow_blank=True, id="player")
                yield Static("", id="points")
                yield OptionList(id="verbs")
        yield Footer()

    async def on_mount(self) -> None:
        await self.backend.start()
        await self.refresh_world()
        self.set_interval(REFRESH_SECONDS, self.refresh_world)

    async def on_unmount(self) -> None:
        await self.backend.close()

    # ── data ────────────────────────────────────────────────────────────────
    async def refresh_world(self) -> None:
        try:
            self.world = World.parse(await self.backend.fetch_snapshot())
            status = self.backend.label
        except Exception as exc:  # network hiccup, server restart, …
            self.query_one("#status", Static).update(f"⚠ {self.backend.label} — {exc}")
            return

        self._sync_players()
        if self.player_id and self.player_id not in self.world.entities:
            self.player_id = ""
            self.control = None
        if self.follow or not self.world.get(self.view_room_id):
            self.view_room_id = self.world.room_of(self.player_id) or self.world.first_room_id()

        epoch = self.world.epoch
        who = entity_name(self.world.get(self.player_id)) if self.player_id else "no player"
        self.query_one("#status", Static).update(f"{status} · epoch {epoch}s · {who}")
        self._render_room()
        self._render_actions()

    def _sync_players(self) -> None:
        ids = [c["id"] for c in self.world.characters()]
        if ids == self._player_choice_ids:
            return
        self._player_choice_ids = ids
        select = self.query_one("#player", Select)
        select.set_options(
            [(entity_name(self.world.get(i)), i) for i in ids]
        )
        if self.player_id in ids:
            select.value = self.player_id

    # ── rendering ─────────────────────────────────────────────────────────────
    def _render_room(self) -> None:
        room = self.world.get(self.view_room_id)
        player_room = self.world.room_of(self.player_id)
        spectating = bool(self.player_id) and self.view_room_id != player_room
        title = entity_name(room) if room else "No room"
        if spectating:
            title += "  · spectating (f to follow)"
        self.query_one("#room-title", Static).update(title)

        members = self.query_one("#members", OptionList)
        members.clear_options()
        if room:
            shown = [
                m for m in self.world.room_members(self.view_room_id)
                if not has(m, "DoorComponent") and not has(m, "RoomComponent")
            ]
            shown.sort(key=lambda m: (m["components"].get("SpriteLayer", {}).get("layer", 20),
                                      entity_name(m).lower()))
            for m in shown:
                me = "  ← you" if m["id"] == self.player_id else ""
                members.add_option(Option(f"{entity_icon(m)} {entity_name(m)}{me}", id=m["id"]))
            self._restore_highlight(members)

        doors = self.query_one("#doors", OptionList)
        doors.clear_options()
        for target_id, direction, dest in self.world.doors(self.view_room_id):
            tag = f"[{direction}] " if direction else ""
            doors.add_option(Option(f"🚪 {tag}{entity_name(dest)}", id=f"door:{target_id}"))

    def _restore_highlight(self, members: OptionList) -> None:
        if not self.selected_id:
            return
        try:
            members.highlighted = members.get_option_index(self.selected_id)
        except Exception:
            pass

    def _render_actions(self) -> None:
        pts = self.world.points(self.player_id) if self.player_id else {"has": False}
        if pts.get("has"):
            line = (f"⚡ {fmt_points(pts['ap'])}/{fmt_points(pts['ap_max'])} AP   "
                    f"🔹 {fmt_points(pts['fp'])}/{fmt_points(pts['fp_max'])} FP")
        else:
            line = "Pick a player to see their actions."
        self.query_one("#points", Static).update(line)

        verbs = self.query_one("#verbs", OptionList)
        verbs.clear_options()
        for verb in ACTION_VERBS:
            affordable = pts.get("has") and pts["ap"] >= verb.ap and pts["fp"] >= verb.fp
            cost = (" · ".join(
                [f"{verb.ap} AP"] * bool(verb.ap) + [f"{verb.fp} FP"] * bool(verb.fp)
            ) or "free")
            tgt = " ⌖" if verb.target_kind else ""
            verbs.add_option(
                Option(f"{verb.label}{tgt}  ({cost})", id=verb.tool, disabled=not affordable)
            )

    # ── events ──────────────────────────────────────────────────────────────────
    @on(Select.Changed, "#player")
    async def _player_changed(self, event: Select.Changed) -> None:
        new_id = "" if event.value is Select.BLANK else str(event.value)
        if new_id == self.player_id:
            return
        self.player_id = new_id
        self.selected_id = None
        self.follow = True
        self.control = await self.backend.claim(new_id, self.world) if new_id else None
        await self.refresh_world()

    @on(OptionList.OptionSelected, "#members")
    def _member_selected(self, event: OptionList.OptionSelected) -> None:
        self.selected_id = event.option.id

    @on(OptionList.OptionSelected, "#doors")
    def _door_selected(self, event: OptionList.OptionSelected) -> None:
        self.view_room_id = event.option.id.removeprefix("door:")
        self.follow = False
        self._render_room()

    @on(OptionList.OptionSelected, "#verbs")
    async def _verb_selected(self, event: OptionList.OptionSelected) -> None:
        verb = next((v for v in ACTION_VERBS if v.tool == event.option.id), None)
        if verb:
            await self._do_verb(verb)

    # ── actions ─────────────────────────────────────────────────────────────────
    async def _do_verb(self, verb: Verb) -> None:
        if not self.player_id or not self.control:
            return
        payload: dict = {}
        if verb.target_kind:
            candidates = self.world.target_candidates(self.player_id, verb.target_kind)
            choice = await self.push_screen_wait(TargetPicker(verb, candidates))
            if not choice:
                return
            payload[verb.target_key] = choice
        if verb.prompt:
            value = await self.push_screen_wait(TextPrompt(f"{verb.label} — {verb.prompt}"))
            if not value:
                return
            payload[verb.prompt] = value

        await self.backend.submit({
            "character_id": self.player_id,
            "controller_id": self.control[0],
            "controller_generation": self.control[1],
            "command_type": verb.cmd,
            "payload": payload,
            "cost": {"action": verb.ap, "focus": verb.fp},
            "lane": verb.lane,
            "on_insufficient_points": "queue",
        })
        await self.refresh_world()

    async def action_refresh(self) -> None:
        await self.refresh_world()

    def action_follow(self) -> None:
        self.follow = True
        self.view_room_id = self.world.room_of(self.player_id)
        self._render_room()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bunnyland-tui", description=__doc__)
    parser.add_argument(
        "--server", help="connect to a running server (e.g. http://localhost:8765)"
    )
    parser.add_argument("--seed", default="a quiet marsh", help="seed for a locally hosted world")
    parser.add_argument(
        "--generator", default="apartment-demo", help="generator for a locally hosted world"
    )
    args = parser.parse_args(argv)

    backend: Backend = (
        RemoteBackend(args.server) if args.server
        else LocalBackend(seed=args.seed, generator=args.generator)
    )
    BunnylandTUI(backend).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
