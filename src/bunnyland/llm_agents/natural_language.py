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
    ``tell Hazel hello``, ``note ...``, ``remember basin``, ``forget <note id>``,
    ``reflect ...``, and
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

    if verb == "till":
        soil = _rest(words, 1)
        return ToolCall("till", {"soil_id": soil}) if soil else None

    if verb == "plant":
        lowered = [word.lower() for word in words]
        for marker in ("in", "into"):
            if marker in lowered[1:]:
                index = lowered.index(marker)
                seed = _rest(words[:index], 1)
                soil = _rest(words, index + 1)
                if seed and soil:
                    return ToolCall("plant", {"seed_id": seed, "soil_id": soil})
        return None

    if verb == "water":
        soil = _rest(words, 1)
        return ToolCall("water_crop", {"soil_id": soil}) if soil else None

    if verb == "fertilize":
        lowered = [word.lower() for word in words]
        if "with" in lowered[1:]:
            index = lowered.index("with")
            soil = _rest(words[:index], 1)
            fertilizer = _rest(words, index + 1)
            if soil and fertilizer:
                return ToolCall(
                    "fertilize", {"soil_id": soil, "fertilizer_id": fertilizer}
                )
        return None

    if verb == "harvest":
        soil = _rest(words, 1)
        return ToolCall("harvest_crop", {"soil_id": soil}) if soil else None

    if verb == "discover":
        location = _rest(words, 1)
        return ToolCall("discover_location", {"location_id": location}) if location else None

    if verb == "accept" and len(words) > 1 and words[1].lower() == "quest":
        quest = _rest(words, 2)
        return ToolCall("accept_quest", {"quest_id": quest}) if quest else None

    if verb == "complete" and len(words) > 1 and words[1].lower() == "objective":
        objective = _rest(words, 2)
        return ToolCall("complete_objective", {"objective_id": objective}) if objective else None

    if verb == "join" and len(words) > 1 and words[1].lower() == "faction":
        faction = _rest(words, 2)
        return ToolCall("join_faction", {"faction_id": faction}) if faction else None

    if verb == "join" and len(words) > 1 and words[1].lower() == "household":
        household = _rest(words, 2)
        return (
            ToolCall("join_household", {"household_id": household, "name": household})
            if household
            else None
        )

    if verb == "leave" and len(words) > 1 and words[1].lower() == "faction":
        faction = _rest(words, 2)
        return ToolCall("leave_faction", {"faction_id": faction}) if faction else None

    if verb == "claim" and len(words) > 1 and words[1].lower() == "home":
        room = _rest(words, 2)
        return ToolCall("claim_home", {"room_id": room} if room else {})

    if verb == "claim" and len(words) > 1 and words[1].lower() == "room":
        room = _rest(words, 2)
        return ToolCall("claim_room", {"room_id": room} if room else {})

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

    if verb == "buy" and len(words) >= 4:
        lowered = [word.lower() for word in words]
        if "from" in lowered[2:]:
            index = lowered.index("from")
            item = _rest(words[:index], 1)
            seller = _rest(words, index + 1)
            if item and seller:
                return ToolCall("buy_item", {"item_id": item, "seller_id": seller})

    if verb == "sell" and len(words) >= 4:
        lowered = [word.lower() for word in words]
        if "to" in lowered[2:]:
            index = lowered.index("to")
            item = _rest(words[:index], 1)
            customer = _rest(words, index + 1)
            if item and customer:
                return ToolCall("sell_item", {"item_id": item, "customer_id": customer})

    if verb == "charge" and len(words) >= 4 and words[1].lower() == "rent":
        amount = words[-1]
        tenant = _rest(words[2:-1], 0)
        if tenant and amount.isdigit():
            return ToolCall("charge_rent", {"tenant_id": tenant, "amount": amount})

    if verb == "pay" and len(words) > 1 and words[1].lower() == "bill":
        bill = _rest(words, 2)
        return ToolCall("pay_bill", {"bill_id": bill} if bill else {})

    if verb == "open" and len(words) > 1 and words[1].lower() == "business":
        name = _rest(words, 2)
        return ToolCall("open_business", {"name": name}) if name else None

    if verb == "adopt":
        child = _rest(words, 1)
        return ToolCall("adopt_child", {"child_id": child}) if child else None

    if verb in {"note", "remember", "forget", "reflect"}:
        body = _rest(words, 1)
        name = "take_note" if verb == "note" else verb
        if verb in {"note", "reflect"}:
            key = "text"
        elif verb == "forget":
            key = "note_id"
        else:
            key = "query"
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
