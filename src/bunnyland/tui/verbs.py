"""The room/focus verbs a player can attempt, mirroring the canonical costs in the
server's ``llm_agents/tools.py`` (there is no server endpoint that lists verbs, so the
catalogue is duplicated here exactly as the web toon client does). Domain/situational
verbs (farming, ships, economy, ...) are intentionally omitted for now.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Verb:
    tool: str
    label: str
    cmd: str
    ap: int
    fp: int
    lane: str
    target_key: str | None = None   # payload key the picked target fills
    target_kind: str | None = None  # which nearby entities are candidates
    prompt: str | None = None       # free-text payload key to collect


ACTION_VERBS: tuple[Verb, ...] = (
    Verb("move", "Move", "move", 1, 0, "world", "exit_id", "exits"),
    Verb("take", "Take", "take", 1, 0, "world", "item_id", "roomItems"),
    Verb("drop", "Drop", "put", 1, 0, "world", "item_id", "inventory"),
    Verb("use", "Use", "use", 1, 0, "world", "target_id", "reachableItems"),
    Verb("eat", "Eat", "eat", 1, 0, "world", "item_id", "reachableItems"),
    Verb("drink", "Drink", "drink", 1, 0, "world", "source_id", "reachableItems"),
    Verb("tell", "Tell", "tell", 1, 1, "world", "target_id", "characters", prompt="text"),
    Verb("say", "Say", "say", 1, 1, "world", prompt="text"),
    Verb("wait", "Wait", "wait", 0, 0, "world"),
    Verb("take_note", "Take note", "take-note", 0, 1, "focus", prompt="text"),
    Verb("remember", "Remember", "remember", 0, 1, "focus", prompt="query"),
    Verb("reflect", "Reflect", "reflect", 0, 1, "focus", prompt="text"),
)
