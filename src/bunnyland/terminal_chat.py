"""Shared bounded conversation history for terminal character-chat clients."""

from __future__ import annotations

import json
import os
from pathlib import Path

HISTORY_LIMIT = 24


def terminal_data_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "bunnyland"


def history_path(client_id: str, character_id: str) -> Path:
    safe_client = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in client_id)
    safe_character = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in character_id)
    return terminal_data_dir() / "chat" / f"{safe_client}-{safe_character}.json"


def load_history(client_id: str, character_id: str) -> dict:
    try:
        data = json.loads(history_path(client_id, character_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"summary": "", "messages": []}
    if not isinstance(data, dict):
        return {"summary": "", "messages": []}
    messages = [item for item in data.get("messages") or [] if isinstance(item, dict)]
    return {
        "summary": str(data.get("summary") or ""),
        "messages": messages[-HISTORY_LIMIT:],
    }


def save_history(client_id: str, character_id: str, state: dict) -> None:
    path = history_path(client_id, character_id)
    data = {
        "summary": str(state.get("summary") or ""),
        "messages": list(state.get("messages") or [])[-HISTORY_LIMIT:],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return


def append_exchange(state: dict, message: str, reply: str) -> None:
    messages = list(state.get("messages") or [])
    messages.extend(
        [
            {"role": "user", "text": message},
            {"role": "character", "text": reply},
        ]
    )
    state["messages"] = messages[-HISTORY_LIMIT:]


__all__ = ["HISTORY_LIMIT", "append_exchange", "history_path", "load_history", "save_history"]
