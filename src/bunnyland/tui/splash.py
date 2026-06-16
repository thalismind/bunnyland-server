"""Shared intro splash screen for terminal clients."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Static

BUNNY_ASCII = r"""
   /)\_/\\
  ( =.= )
   )   (
  (__ __)
"""

TITLE = "Bunnyland"


class IntroSplash(ModalScreen[None]):
    """Brief title/intro overlay that fades away automatically."""

    DEFAULT_CSS = """
    IntroSplash {
        background: $surface;
        align: center middle;
        opacity: 1;
    }
    IntroSplash > #splash {
        width: 28;
        height: auto;
        min-width: 28;
        border: thick $accent;
        padding: 1 2;
        background: $panel;
        content-align: center middle;
    }
    #splash-title {
        text-style: bold;
        width: 100%;
        color: $text;
        margin-bottom: 1;
        text-align: center;
    }
    #splash-bunny {
        width: 100%;
        color: $text;
        text-align: center;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="splash"):
            yield Static(TITLE, id="splash-title")
            yield Static(BUNNY_ASCII, id="splash-bunny")

    def on_mount(self) -> None:
        self.set_timer(1.0, self._start_fade)

    def _start_fade(self) -> None:
        try:
            splash = self.query_one("#splash")
        except NoMatches:
            self.dismiss()
            return
        splash.styles.opacity = 1
        steps = 8
        duration = 0.8
        interval = duration / steps
        for index in range(1, steps + 1):
            opacity = 1 - index / steps
            self.set_timer(
                index * interval,
                lambda level=opacity: self._set_opacity(splash, level),
            )
        self.set_timer(duration, self._finish)

    def _set_opacity(self, widget: Widget, value: float) -> None:
        widget.styles.opacity = value

    def _finish(self) -> None:
        self.dismiss()
