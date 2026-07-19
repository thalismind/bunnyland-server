"""Terminal client for opt-in character chat."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import uuid4

HISTORY_LIMIT = 24


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "bunnyland"


def persistent_client_id() -> str:
    path = config_dir() / "chat-client-id"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    if value:
        return value
    value = str(uuid4())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{value}\n", encoding="utf-8")
    except OSError:
        pass
    return value


def history_path(client_id: str, character_id: str) -> Path:
    safe_client = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in client_id)
    safe_character = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in character_id)
    return config_dir() / "chat" / f"{safe_client}-{safe_character}.json"


def load_history(client_id: str, character_id: str) -> dict:
    try:
        data = json.loads(history_path(client_id, character_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"summary": "", "messages": []}
    return {
        "summary": str(data.get("summary") or ""),
        "messages": list(data.get("messages") or [])[-HISTORY_LIMIT:],
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
        pass


def api_url(base: str, path: str) -> str:
    return f"{base.strip().rstrip('/')}{path}"


def get_json(base: str, path: str, client_id: str = "") -> dict:
    request = urllib.request.Request(
        api_url(base, path),
        headers={"X-Bunnyland-Client-Id": client_id} if client_id else {},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(
    base: str,
    path: str,
    payload: dict,
    *,
    client_id: str = "",
) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        api_url(base, path),
        data=body,
        headers={
            "Content-Type": "application/json",
            **({"X-Bunnyland-Client-Id": client_id} if client_id else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = json.loads(exc.read().decode("utf-8") or "{}").get("detail")
        raise RuntimeError(detail or f"HTTP {exc.code}") from exc


def choose_character(base: str, wanted: str, client_id: str = "") -> tuple[str, str]:
    data = get_json(base, "/profile/characters", client_id)
    characters = data.get("characters") or []
    if not characters:
        raise RuntimeError("no characters are available")
    if wanted:
        query = wanted.strip().lower()
        for character in characters:
            if (
                character.get("id") == wanted
                or character.get("name", "").lower() == query
            ):
                return character["id"], character.get("name") or character["id"]
        raise RuntimeError(f"no such character: {wanted!r}")
    first = characters[0]
    return first["id"], first.get("name") or first["id"]


def request_payload(client_id: str, state: dict, message: str) -> dict:
    return {
        "kind": "chat",
        "message": message,
        "history_summary": str(state.get("summary") or ""),
        "history": list(state.get("messages") or [])[-HISTORY_LIMIT:],
    }


def append_exchange(state: dict, message: str, reply: str) -> None:
    messages = list(state.get("messages") or [])
    messages.extend(
        [
            {"role": "user", "text": message},
            {"role": "character", "text": reply},
        ]
    )
    state["messages"] = messages[-HISTORY_LIMIT:]


def wait_for_job(base: str, character_id: str, client_id: str, job: dict) -> dict:
    while job.get("status") in {"queued", "running"}:
        time.sleep(0.5)
        job = get_json(
            base,
            "/chat/characters/"
            f"{urllib.parse.quote(character_id, safe='')}/jobs/"
            f"{urllib.parse.quote(str(job.get('id') or ''), safe='')}",
            client_id,
        )
    return job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bunnyland chat", description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8765/v1")
    parser.add_argument("--character", default="", help="character id or exact name")
    args = parser.parse_args(argv)

    client_id = persistent_client_id()
    features = get_json(args.server, "/public/features")
    if not features.get("character_chat"):
        raise SystemExit("Character chat is not enabled on this server.")
    character_id, name = choose_character(args.server, args.character, client_id)
    state = load_history(client_id, character_id)
    print(f"Chatting with {name}. Ctrl-D or /quit exits.")
    while True:
        try:
            message = input("> ").strip()
        except EOFError:
            print()
            break
        if not message:
            continue
        if message in {"/quit", "/exit"}:
            break
        response = post_json(
            args.server,
            f"/chat/characters/{urllib.parse.quote(character_id, safe='')}/jobs",
            request_payload(client_id, state, message),
            client_id=client_id,
        )
        response = wait_for_job(args.server, character_id, client_id, response)
        if response.get("status") == "failed":
            failure = response.get("failure") or {}
            print(f"{name}: {failure.get('detail') or 'Chat failed.'}")
            continue
        result = response.get("result") or {}
        reply = result.get("reply") or ""
        action = result.get("action") or {}
        suffix = f" [{action.get('tool')} {action.get('status')}]" if action.get("tool") else ""
        print(f"{name}: {reply}{suffix}")
        append_exchange(state, message, reply)
        save_history(client_id, character_id, state)
    save_history(client_id, character_id, state)
    return 0


__all__ = [
    "HISTORY_LIMIT",
    "append_exchange",
    "choose_character",
    "history_path",
    "load_history",
    "persistent_client_id",
    "request_payload",
    "save_history",
    "wait_for_job",
]
