"""Shared intro splash screen for terminal clients."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
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
        width: auto;
        opacity: 1;
        border: thick $accent;
        padding: 1 2;
        background: $panel;
    }
    #splash-title {
        content-align: center middle;
        text-style: bold;
        width: 100%;
        color: $accent;
        margin-bottom: 1;
    }
    #splash-bunny {
        content-align: center middle;
        width: 100%;
        color: $text;
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
        splash.animate("opacity", 0, duration=0.8)
        self.set_timer(0.8, self.dismiss)
