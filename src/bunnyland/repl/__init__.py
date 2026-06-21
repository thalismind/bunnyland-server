"""Bunnyland REPL client: a Textual prompt with a RichLog scrollback of clickable targets,
Tab completion, and command history. Hosts a world in-process or drives a server over HTTP.

The Textual app is imported lazily so the command core (``BunnylandRepl``) and its tests
can be used without Textual installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .client import BunnylandRepl

__all__ = ["BunnylandRepl", "BunnylandReplApp", "main"]

if TYPE_CHECKING:
    from .app import BunnylandReplApp, main


def __getattr__(name: str):
    if name in {"BunnylandReplApp", "main"}:
        from . import app

        return getattr(app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
