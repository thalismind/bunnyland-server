"""Shared event narration for Textual clients."""

from __future__ import annotations

from collections.abc import Callable

from rich.text import Text

# Events that would drown out narration rather than describe activity: command lifecycle,
# continuous point/need/affect telemetry, and perception/look bookkeeping.
_UNNARRATED_EVENT_TYPES = frozenset({
    "CommandSubmittedEvent", "CommandAcceptedEvent", "CommandQueuedEvent",
    "CommandExecutedEvent", "CommandExpiredEvent",
    "ActionPointsChangedEvent", "FocusPointsChangedEvent", "EncumbranceChangedEvent",
    "PainChangedEvent", "BleedingChangedEvent", "AttentionShiftedEvent", "AffectChangedEvent",
    "EntitySeenEvent", "RoomLookedEvent", "RoomQualityUpdatedEvent", "HungerChangedEvent",
    "ThirstChangedEvent", "DailyNeedChangedEvent", "SkillXPChangedEvent",
})

# Fields on every ``DomainEvent``; the rest of a serialized event is its specific payload.
_EVENT_BASE_KEYS = frozenset({
    "event_id", "world_epoch", "created_at", "visibility", "actor_id", "room_id",
    "target_ids", "causation_id", "correlation_id",
})


def _humanize_event_type(event_type: str) -> str:
    """``ResourceGatheredEvent`` -> ``Resource gathered`` (splits on CamelCase)."""
    name = event_type.removesuffix("Event")
    words: list[str] = []
    current = ""
    for char in name:
        if char.isupper() and current:
            words.append(current)
            current = char
        else:
            current += char
    if current:
        words.append(current)
    return " ".join(words).capitalize()


class EventNarrator:
    """Render the not-yet-seen events a player can perceive."""

    def __init__(self) -> None:
        self._seen_event_ids: set[str] = set()

    def drain_events(
        self,
        messages: list[dict],
        *,
        player_id: str,
        room_of: Callable[[str | None], str | None],
        name_for: Callable[[str], str | None],
    ) -> list[Text]:
        rendered: list[Text] = []
        current: set[str] = set()
        for message in messages:
            data = message.get("data", message)
            event = data.get("event", {})
            event_id = event.get("event_id")
            if event_id is None:
                continue
            current.add(event_id)
            if event_id in self._seen_event_ids:
                continue
            event_type = data.get("event_type")
            if event_type in _UNNARRATED_EVENT_TYPES:
                continue
            own = bool(player_id) and event.get("actor_id") == player_id
            if own or self._perceives(event, player_id=player_id, room_of=room_of):
                rendered.append(self._render_event(data, name_for=name_for))
        self._seen_event_ids = current
        return rendered

    def _perceives(
        self,
        event: dict,
        *,
        player_id: str,
        room_of: Callable[[str | None], str | None],
    ) -> bool:
        visibility = event.get("visibility")
        if visibility == "public":
            return True
        if visibility == "room":
            return bool(player_id) and event.get("room_id") == room_of(player_id)
        if visibility == "directed":
            return bool(player_id) and (
                player_id == event.get("actor_id")
                or player_id in (event.get("target_ids") or ())
            )
        if visibility == "private":
            return bool(player_id) and player_id == event.get("actor_id")
        return False

    def _render_event(self, data: dict, *, name_for: Callable[[str], str | None]) -> Text:
        event = data.get("event", {})
        event_type = str(data.get("event_type", "Event"))
        label = _humanize_event_type(event_type)
        actor = name_for(event.get("actor_id") or "") if event.get("actor_id") else None
        details: list[str] = []
        for key, value in event.items():
            if key in _EVENT_BASE_KEYS or value in (None, "", (), []):
                continue
            if key.endswith("_ids"):
                names = [name_for(str(item)) for item in value]
                names = [name for name in names if name]
                if names:
                    details.append(", ".join(names))
            elif key.endswith("_id"):
                name = name_for(str(value))
                if name is not None:
                    details.append(name)
            else:
                details.append(f"{key.replace('_', ' ')} {value}")
        line = f"{actor}: {label}" if actor else label
        if details:
            line += f" — {'; '.join(details)}"
        style = "dark_orange" if event_type == "CommandRejectedEvent" else "dim italic"
        return Text(line, style=style)
