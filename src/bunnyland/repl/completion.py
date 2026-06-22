"""Tab-completion core for the REPL client — pure functions over a world snapshot.

Completion returns *full-line* replacements so it can be wired into ``readline`` with an
empty delimiter set (``set_completer_delims("")``). That sidesteps readline's word
splitting, which would otherwise break on entity names that contain spaces ("a brass
key"). Each returned string is the whole input line with the current token completed.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..core.actions import ActionDefinition
from ..tui.model import World, entity_name, has


def reference_candidates(world: World, player_id: str | None) -> list[tuple[str, str]]:
    """Reachable ``(name, id)`` pairs an entity-reference argument could name.

    Mirrors the TUI's notion of reachability: other entities in the room, things the
    player carries, and the destinations of the room's exits. Permissive — the server
    still validates the chosen target.
    """
    if not player_id:
        return []
    room_id = world.room_of(player_id)
    members = [
        m
        for m in world.room_members(room_id)
        if m["id"] != player_id and not has(m, "RoomComponent")
    ]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entity in (*members, *world.carried(player_id)):
        if entity["id"] not in seen:
            seen.add(entity["id"])
            out.append((entity_name(entity), entity["id"]))
    for target_id, _direction, dest in world.doors(room_id):
        if target_id not in seen:
            seen.add(target_id)
            out.append((entity_name(dest) if dest else target_id, target_id))
    return out


def value_candidates(
    definition: ActionDefinition, key: str, entity_names: Sequence[str]
) -> list[str]:
    """Completion values for one argument: reachable names for entity references, the
    booleans for boolean args, otherwise any fixed values the natural patterns enumerate
    (which is how ``direction`` exposes north/south/...)."""
    argument = (definition.arguments or {}).get(key)
    if argument is None:
        return []
    if argument.kind == "entity":
        return list(entity_names)
    if argument.kind == "boolean":
        return ["false", "true"]
    fixed: set[str] = set()
    for pattern in definition.natural_patterns:
        value = (pattern.fixed_arguments or {}).get(key)
        if value is not None:
            fixed.add(str(value))
    return sorted(fixed)


def complete_line(
    line: str,
    *,
    definitions: dict[str, ActionDefinition],
    commands: Sequence[str],
    entity_names: Sequence[str] = (),
    players: Sequence[str] = (),
) -> list[str]:
    """Return full-line completions for ``line``.

    The first token completes to a command name; a later bare token completes to a parameter
    name (``key=``); once a token contains ``=`` the text after it completes to a value, and
    because values may contain spaces, value completion is anchored on the last ``=`` rather
    than the last space. ``help`` completes command names and ``play`` completes player names
    (both of which may also contain spaces, so they take everything after the first token).
    """
    if " " not in line:
        return [word for word in sorted(commands) if word.startswith(line)]

    command, _, rest = line.partition(" ")
    if command == "help":
        return [f"{command} {word}" for word in sorted(commands) if word.startswith(rest)]
    if command == "play":
        return [f"{command} {name}" for name in sorted(players) if name.startswith(rest)]
    if command in {"examine", "x"}:
        return [f"{command} {name}" for name in sorted(entity_names) if name.startswith(rest)]

    definition = definitions.get(command)
    if definition is None:
        return []

    current = line.rsplit(" ", 1)[1]
    if "=" in current:  # typing a value for the current ``key=`` token
        key, _, value_prefix = current.partition("=")
        base = line[: len(line) - len(current)] + f"{key}="
        return [
            base + value
            for value in value_candidates(definition, key, entity_names)
            if value.startswith(value_prefix)
        ]

    matches: list[str] = []
    # A bare trailing token completes to a parameter name.
    name_base = line[: len(line) - len(current)]
    matches += [f"{name_base}{key}=" for key in definition.arg_keys if key.startswith(current)]
    # …or extends a multi-word value of the most recent ``key=`` token.
    last_eq = line.rfind("=")
    if last_eq != -1:
        key = line[:last_eq].rsplit(" ", 1)[-1]
        value_prefix = line[last_eq + 1 :]
        base = line[: last_eq + 1]
        matches += [
            base + value
            for value in value_candidates(definition, key, entity_names)
            if value.startswith(value_prefix)
        ]
    return matches


__all__ = ["complete_line", "reference_candidates", "value_candidates"]
