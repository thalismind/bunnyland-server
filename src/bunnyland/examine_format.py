"""Shared, presentation-only formatting for an examine view.

The server's ``serialize_examine`` — exposed by the ``/world/character/{id}/examine/{id}``
endpoint and the MCP ``examine`` tool — returns a curated, perception-gated detail view of
one entity (its public component values, plus private needs/affect when you examine
yourself). Every player client (terminal TUI, REPL, Discord bot) renders that same view
through these helpers so an entity is described identically everywhere.

These functions are deliberately dependency-free (plain dict in, plain ``str``/``list`` out)
so any client can reuse them without pulling in textual or the Discord stack.
"""

from __future__ import annotations

from typing import Any


def _fmt(value: Any) -> str:
    """Render a point value as a whole number when it is one, else one decimal place."""
    number = float(value or 0)
    return str(int(number)) if number == int(number) else f"{number:.1f}"


def examine_header(view: dict[str, Any], *, icon: str = "") -> str:
    """The one-line title for an examine view: ``<icon> <name> (<kind>)`` plus ``(you)``
    when inspecting yourself."""
    name = view.get("name") or view.get("id") or "?"
    kind = view.get("kind") or "other"
    suffix = " (you)" if view.get("is_self") else ""
    prefix = f"{icon} " if icon else ""
    return f"{prefix}{name} ({kind}){suffix}"


def examine_detail_lines(view: dict[str, Any]) -> list[str]:
    """The body lines describing an entity (no header), in a stable, human-readable order.

    Renders the curated public facets (appearance, condition, food/drink/door/container/
    light, portability) for any entity, plus mood, status prose, and action/focus points
    when the view is of yourself."""
    details = view.get("details") or {}
    lines: list[str] = []

    description = details.get("description") or {}
    for key in ("short", "appearance", "long"):
        text = str(description.get(key) or "").strip()
        if text:
            lines.append(text)

    condition = details.get("condition")
    if condition:
        lines.append("Condition: " + ", ".join(condition))

    food = details.get("food")
    if food:
        note = (
            f"Food — nutrition {_fmt(food.get('nutrition'))}, "
            f"satiety {_fmt(food.get('satiety'))}"
        )
        flags = [flag for flag in ("raw", "spoiled") if food.get(flag)]
        if flags:
            note += f" ({', '.join(flags)})"
        lines.append(note)

    drink = details.get("drinkable")
    if drink:
        note = f"Drink — hydration {_fmt(drink.get('hydration'))}"
        if float(drink.get("purity", 1.0)) < 1.0:
            note += " (impure)"
        lines.append(note)

    door = details.get("door")
    if door:
        lines.append("Door — " + ("open" if door.get("open") else "closed"))

    container = details.get("container")
    if container:
        state = "open" if container.get("open") else "closed"
        if container.get("locked"):
            state += ", locked"
        lines.append(f"Container — {state}")

    light = details.get("light")
    if light:
        state = "on" if light.get("enabled") else "off"
        lines.append(f"Light — {state} (level {_fmt(light.get('level'))})")

    if details.get("portable"):
        lines.append("Can be carried.")

    affect = details.get("affect") or {}
    labels = affect.get("labels") or ()
    if labels:
        lines.append("Mood: " + ", ".join(labels))

    for status in view.get("status") or ():
        text = str(status).strip()
        if text:
            lines.append(text)

    points = view.get("points")
    if view.get("is_self") and points:
        lines.append(
            f"AP {_fmt(points.get('action'))}/{_fmt(points.get('action_max'))} · "
            f"FP {_fmt(points.get('focus'))}/{_fmt(points.get('focus_max'))}"
        )

    return lines
