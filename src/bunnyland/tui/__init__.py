"""Bunnyland terminal client (Textual): host a world in-process or connect to a server.

The Textual app is imported lazily so lightweight clients (such as the REPL) can reuse
this package's textual-free ``backend`` and ``model`` modules without requiring Textual to
be installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["BunnylandTUI", "main"]

if TYPE_CHECKING:  # pragma: no cover
    from .app import BunnylandTUI, main


def __getattr__(name: str):
    if name in __all__:
        from . import app

        return getattr(app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
