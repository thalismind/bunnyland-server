"""Shared visual language for requesting images across clients (spec 27).

Every client uses the same iconography so the gesture reads the same everywhere: react with
the camera in Discord, press the camera button in the toon/TUI clients, or run the matching
command in the REPL. Keeping these here means one source of truth for the emoji and labels.
"""

from __future__ import annotations

#: The emoji a player uses to request an image (Discord reaction, TUI/web button icon).
REQUEST_EMOJI = "📷"
#: The emoji a client/bot shows to acknowledge that a request was queued.
ACK_EMOJI = "👀"
#: The emoji a client/bot shows when the finished image is delivered.
DELIVER_EMOJI = "📸"
#: The emoji a client/bot shows when a requested image could not be generated.
FAIL_EMOJI = "⚠️"

#: Human-readable label for the request affordance (button tooltip / menu entry).
REQUEST_LABEL = "Request image"
#: The command name used by text clients (REPL/TUI command palette).
REQUEST_COMMAND = "image"

#: Coming-soon affordance for event/interaction videos (not yet generated).
VIDEO_COMING_SOON = "Event & interaction videos: coming soon!"


__all__ = [
    "ACK_EMOJI",
    "DELIVER_EMOJI",
    "FAIL_EMOJI",
    "REQUEST_COMMAND",
    "REQUEST_EMOJI",
    "REQUEST_LABEL",
    "VIDEO_COMING_SOON",
]
