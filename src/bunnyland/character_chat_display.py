"""Shared display formatting for character-chat actions."""

from __future__ import annotations

import json

from pydantic import JsonValue


def format_action_call(tool: str, parameters: dict[str, JsonValue]) -> str:
    if not parameters:
        return tool
    details: list[str] = []
    for key, value in parameters.items():
        label = key.removesuffix("_id").replace("_", " ")
        rendered = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
        details.append(f"{label}: {rendered}")
    return f"{tool} — {', '.join(details)}"


__all__ = ["format_action_call"]
