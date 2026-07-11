"""Small natural-language command parser for the existing tool surface (spec 28.3).

This is intentionally narrow: it compiles ``ActionDefinition.natural_patterns`` into an
in-memory matcher and returns a ``ToolCall``. Dispatch still resolves references and the
world actor still validates costs, reachability, policy, and command state.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Any

from ..core.actions import ActionDefinition, ActionPattern
from .tools import ToolCall, action_definitions

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

_SLOT = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z_][a-zA-Z0-9_]*))?\}")


@dataclass(frozen=True)
class _CompiledPattern:
    tool_name: str
    matcher: re.Pattern[str]
    fixed_arguments: dict[str, Any]
    argument_aliases: dict[str, str]
    slot_kinds: dict[str, str]


def _slot_kind(definition: ActionDefinition, name: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    if name == "direction":
        return "direction"
    argument = (definition.arguments or {}).get(name)
    return argument.kind if argument is not None else "text"


def _slot_regex(kind: str) -> str:
    if kind == "direction":
        directions = "|".join(
            re.escape(direction) for direction in sorted(_DIRECTIONS, key=len, reverse=True)
        )
        return rf"(?:{directions})"
    if kind == "number":
        return r"-?\d+(?:\.\d+)?"
    if kind == "word":
        return r"\S+"
    return r".+"


def _split_pattern(pattern: str) -> list[str]:
    parts: list[str] = []
    position = 0
    for match in _SLOT.finditer(pattern):
        if match.start() > position:
            parts.append(pattern[position : match.start()])
        parts.append(match.group(0))
        position = match.end()
    if position < len(pattern):
        parts.append(pattern[position:])
    return parts


def _slot_name_kind(part: str) -> tuple[str, str | None] | None:
    match = _SLOT.fullmatch(part)
    if match is None:
        return None
    return match.group(1), match.group(2)


def _pattern_regex(
    definition: ActionDefinition, pattern: ActionPattern
) -> tuple[re.Pattern[str], dict[str, str]] | None:
    parts = _split_pattern(pattern.text)
    slots = [part for part in parts if _slot_name_kind(part) is not None]
    if not slots:
        if pattern.fixed_arguments is None:
            return None
        literal = re.escape(pattern.text).replace(r"\ ", r"\s+")
        return re.compile("^" + literal + "$", re.IGNORECASE), {}

    slot_kinds: dict[str, str] = {}
    for part in slots:
        # ``slots`` is already filtered to parts where ``_slot_name_kind`` is not None.
        name, explicit = _slot_name_kind(part)  # type: ignore[misc]
        slot_kinds[name] = _slot_kind(definition, name, explicit)
    regex = "^"
    for index, part in enumerate(parts):
        slot = _slot_name_kind(part)
        if slot is None:
            regex += re.escape(part).replace(r"\ ", r"\s+")
            continue

        name, explicit = slot
        kind = _slot_kind(definition, name, explicit)
        base = _slot_regex(kind)
        quantifier = ""
        if kind in {"text", "string", "entity"}:
            next_literal = parts[index + 1] if index + 1 < len(parts) else ""
            next_slot = parts[index + 2] if index + 2 < len(parts) else ""
            next_slot_info = _slot_name_kind(next_slot)
            if next_literal.strip():
                quantifier = "?"
            elif next_slot_info is not None:
                next_name, next_explicit = next_slot_info
                next_kind = _slot_kind(definition, next_name, next_explicit)
                if next_kind in {"text", "string", "entity"}:
                    return None
                quantifier = "?"
            elif next_literal:
                return None
        regex += rf"(?P<{name}>{base}{quantifier})"
    regex += "$"
    return re.compile(regex, re.IGNORECASE), slot_kinds


def _pattern_priority(pattern: str) -> int:
    return len(_SLOT.sub("", pattern).strip())


def _unquote(value: str) -> str:
    try:
        words = shlex.split(value)
    except ValueError:
        return value
    if len(words) == 1 and words[0] != value:
        return words[0]
    return value


def _normalized_arguments(compiled: _CompiledPattern, match: re.Match[str]) -> dict[str, Any]:
    args = dict(compiled.fixed_arguments)
    for key, value in match.groupdict().items():
        stripped = value.strip()
        if not stripped:
            continue
        stripped = _unquote(stripped)
        if compiled.slot_kinds.get(key) == "direction":
            stripped = stripped.lower()
        args[key] = stripped
    for target, source in compiled.argument_aliases.items():
        if target not in args and source in args:
            args[target] = args[source]
    return args


class NaturalCommandParser:
    """Runtime parser compiled from action metadata."""

    def __init__(
        self,
        definitions: tuple[ActionDefinition, ...] | list[ActionDefinition] | None = None,
    ) -> None:
        self._patterns = self._compile(tuple(action_definitions(tuple(definitions or ()))))

    @staticmethod
    def _compile(definitions: tuple[ActionDefinition, ...]) -> tuple[_CompiledPattern, ...]:
        compiled: list[tuple[int, int, _CompiledPattern]] = []
        index = 0
        for definition in definitions:
            for pattern in definition.natural_patterns:
                result = _pattern_regex(definition, pattern)
                if result is None:
                    continue
                matcher, slot_kinds = result
                priority = _pattern_priority(pattern.text)
                compiled.append(
                    (
                        -priority,
                        index,
                        _CompiledPattern(
                            definition.name,
                            matcher,
                            dict(pattern.fixed_arguments or {}),
                            dict(pattern.argument_aliases or {}),
                            slot_kinds,
                        ),
                    )
                )
                index += 1
        return tuple(item for _, _, item in sorted(compiled, key=lambda item: (item[0], item[1])))

    def parse(self, text: str) -> ToolCall | None:
        stripped = text.strip()
        if not stripped:
            return None
        for pattern in self._patterns:
            match = pattern.matcher.match(stripped)
            if match:
                return ToolCall(pattern.tool_name, _normalized_arguments(pattern, match))
        return None


def parse_natural_command(
    text: str,
    definitions: tuple[ActionDefinition, ...] | list[ActionDefinition] | None = None,
) -> ToolCall | None:
    """Parse a concise player command into a ``ToolCall``.

    Supported forms include ``go north``, ``take basket``, ``say hello``,
    ``tell Hazel hello``, ``note ...``, ``remember basin``, ``forget <note id>``,
    ``reflect ...``, and
    ``wait``. Unknown or ambiguous text returns ``None`` so a caller can clarify.
    """
    return NaturalCommandParser(definitions).parse(text)


__all__ = ["NaturalCommandParser", "parse_natural_command"]
