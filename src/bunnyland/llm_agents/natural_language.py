"""Small natural-language command parser for the existing tool surface (spec 28.3).

This is intentionally narrow: it recognizes common command phrases and returns a
``ToolCall``. Dispatch still resolves references and the world actor still validates costs,
reachability, policy, and command state.
"""

from __future__ import annotations

import shlex

from .tools import ToolCall

_DIRECTIONS = {
    "north",
    "south",
    "east",
    "west",
    "up",
    "down",
    "inside",
    "outside",
    "in",
    "out",
}


def _split(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _rest(words: list[str], start: int) -> str:
    return " ".join(words[start:]).strip()


def parse_natural_command(text: str) -> ToolCall | None:
    """Parse a concise player command into a ``ToolCall``.

    Supported forms include ``go north``, ``take basket``, ``say hello``,
    ``tell Hazel hello``, ``note ...``, ``remember basin``, ``reflect ...``, and
    ``wait``. Unknown or ambiguous text returns ``None`` so a caller can clarify.
    """
    stripped = text.strip()
    if not stripped:
        return None
    words = _split(stripped)
    if not words:
        return None

    verb = words[0].lower()
    if verb in {"wait", "yield"} and len(words) == 1:
        return ToolCall("wait", {})

    if verb in {"go", "move", "walk", "run"}:
        direction = words[1].lower() if len(words) > 1 else ""
        if direction in _DIRECTIONS:
            return ToolCall("move", {"direction": direction})
        target = _rest(words, 1)
        return ToolCall("move", {"exit_id": target}) if target else None
    if verb in _DIRECTIONS and len(words) == 1:
        return ToolCall("move", {"direction": verb})

    if verb == "take" and len(words) > 1 and words[1].lower() == "note":
        body = _rest(words, 2)
        return ToolCall("take_note", {"text": body}) if body else None

    if verb in {"take", "get", "grab", "pick"}:
        start = 2 if len(words) > 1 and words[1].lower() == "up" else 1
        item = _rest(words, start)
        return ToolCall("take", {"item_id": item}) if item else None

    if verb in {"drop"}:
        item = _rest(words, 1)
        return ToolCall("drop", {"item_id": item}) if item else None

    if verb == "put":
        lowered = [word.lower() for word in words]
        for marker in ("in", "into", "on", "onto"):
            if marker in lowered[1:]:
                index = lowered.index(marker)
                item = _rest(words, 1) if index <= 1 else _rest(words[:index], 1)
                target = _rest(words, index + 1)
                if item and target:
                    return ToolCall(
                        "put", {"item_id": item, "target_container_id": target}
                    )
        item = _rest(words, 1)
        return ToolCall("drop", {"item_id": item}) if item else None

    if verb == "use":
        lowered = [word.lower() for word in words]
        if "with" in lowered[1:]:
            index = lowered.index("with")
            target = _rest(words[:index], 1)
            tool = _rest(words, index + 1)
            if target and tool:
                return ToolCall("use", {"target_id": target, "tool_id": tool})
        target = _rest(words, 1)
        return ToolCall("use", {"target_id": target}) if target else None

    if verb == "claim":
        target = _rest(words, 1)
        return ToolCall("claim_ownership", {"target_id": target}) if target else None

    if verb == "release" and len(words) > 1 and words[1].lower() == "ownership":
        target = _rest(words, 2)
        return ToolCall("release_ownership", {"target_id": target}) if target else None

    if verb in {"eat", "drink"}:
        target = _rest(words, 1)
        key = "item_id" if verb == "eat" else "source_id"
        return ToolCall(verb, {key: target}) if target else None

    if verb == "say":
        spoken = _rest(words, 1)
        return ToolCall("say", {"text": spoken}) if spoken else None

    if verb == "tell" and len(words) >= 3:
        return ToolCall("tell", {"target_id": words[1], "text": _rest(words, 2)})

    if verb == "pickpocket" and len(words) >= 3:
        return ToolCall("pickpocket", {"target_id": words[1], "item_id": _rest(words, 2)})

    if verb == "adopt":
        child = _rest(words, 1)
        return ToolCall("adopt_child", {"child_id": child}) if child else None

    if verb in {"note", "remember", "reflect"}:
        body = _rest(words, 1)
        name = "take_note" if verb == "note" else verb
        key = "text" if verb in {"note", "reflect"} else "query"
        return ToolCall(name, {key: body}) if body else None

    if verb == "write":
        lowered = [word.lower() for word in words]
        if "on" in lowered[1:]:
            index = lowered.index("on")
            body = _rest(words[:index], 1)
            target = _rest(words, index + 1)
            if body and target:
                return ToolCall("write", {"target_id": target, "text": body})
        return None

    return None


__all__ = ["parse_natural_command"]
