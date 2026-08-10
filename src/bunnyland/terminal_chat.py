"""Shared bounded conversation history for terminal character-chat clients."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

HISTORY_LIMIT = 24
PARAGRAPH_REVEAL_DELAY_SECONDS = 0.2


@dataclass(frozen=True)
class ChatPreferences:
    markdown: bool = True
    remember_history: bool = True
    separate_reply_paragraphs: bool = False


def split_reply_paragraphs(reply: str) -> tuple[str, ...]:
    """Split a reply on blank lines without changing its logical history entry."""

    normalized = reply.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = tuple(
        paragraph.strip()
        for paragraph in re.split(r"\n[ \t]*\n+", normalized)
        if paragraph.strip()
    )
    return paragraphs or (normalized.strip(),)


def terminal_data_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "bunnyland"


def history_path(client_id: str, character_id: str) -> Path:
    safe_client = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in client_id)
    safe_character = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in character_id)
    return terminal_data_dir() / "chat" / f"{safe_client}-{safe_character}.json"


def chat_preferences_path() -> Path:
    return terminal_data_dir() / "chat-preferences.json"


def load_chat_preferences() -> ChatPreferences:
    try:
        data = json.loads(chat_preferences_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ChatPreferences()
    if not isinstance(data, dict):
        return ChatPreferences()
    defaults = ChatPreferences()
    return ChatPreferences(
        markdown=(
            data["markdown"] if isinstance(data.get("markdown"), bool) else defaults.markdown
        ),
        remember_history=(
            data["remember_history"]
            if isinstance(data.get("remember_history"), bool)
            else defaults.remember_history
        ),
        separate_reply_paragraphs=(
            data["separate_reply_paragraphs"]
            if isinstance(data.get("separate_reply_paragraphs"), bool)
            else defaults.separate_reply_paragraphs
        ),
    )


def save_chat_preferences(preferences: ChatPreferences) -> None:
    path = chat_preferences_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(preferences), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


def clear_history(client_id: str, character_id: str) -> None:
    try:
        history_path(client_id, character_id).unlink(missing_ok=True)
    except OSError:
        return


def clear_all_history() -> None:
    try:
        for path in (terminal_data_dir() / "chat").glob("*.json"):
            path.unlink()
    except OSError:
        return


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


__all__ = [
    "ChatPreferences",
    "HISTORY_LIMIT",
    "PARAGRAPH_REVEAL_DELAY_SECONDS",
    "append_exchange",
    "chat_preferences_path",
    "clear_all_history",
    "clear_history",
    "history_path",
    "load_chat_preferences",
    "load_history",
    "save_chat_preferences",
    "save_history",
    "split_reply_paragraphs",
]
