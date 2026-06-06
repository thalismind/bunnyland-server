"""Read-only view over a world snapshot, shared by every TUI backend.

The shape is exactly what ``server.serialization.serialize_world`` returns (and what the
HTTP ``/world/snapshot`` endpoint serves): ``entities`` is a list of dicts carrying a
``components`` map and a ``relationships`` map whose edges use ``target_id``. The helpers
here mirror the web toon client so both clients reason about a room the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KIND_ICON = {
    "room": "🏠", "character": "🐰", "container": "📦", "item": "✦",
    "door": "🚪", "food": "🍎", "water": "💧", "chair": "🪑", "table": "🪵",
    "bed": "🛏", "art": "🖼", "window": "🪟", "other": "⬡",
}

# Compass direction → unit edge offset, used only to order/label doors in the list.
DIR_LABEL = {
    "north": "N", "south": "S", "east": "E", "west": "W",
    "northeast": "NE", "northwest": "NW", "southeast": "SE", "southwest": "SW",
    "up": "↑", "down": "↓", "fore": "fore", "aft": "aft", "port": "port",
    "starboard": "starboard",
}


def has(entity: dict, component: str) -> bool:
    """Whether an entity carries a component. Membership, not truthiness — a fieldless
    component serializes to an empty dict, which is falsy in Python (but not in JS)."""
    return component in entity["components"]


@dataclass(frozen=True)
class Target:
    """A candidate an action verb can be aimed at."""

    value: str
    label: str
    icon: str


@dataclass
class World:
    """A parsed snapshot keyed by entity id."""

    entities: dict[str, dict] = field(default_factory=dict)
    epoch: int = 0

    @classmethod
    def parse(cls, data: dict | None) -> World:
        entities: dict[str, dict] = {}
        for entity in (data or {}).get("entities", []):
            rels: dict[str, list[dict]] = {}
            for rtype, edges in (entity.get("relationships") or {}).items():
                rels[rtype] = [
                    {"target": edge["target_id"], "edge": edge.get("edge") or {}}
                    for edge in edges
                ]
            entities[entity["id"]] = {
                "id": entity["id"],
                "components": entity.get("components") or {},
                "relationships": rels,
            }
        return cls(entities=entities, epoch=(data or {}).get("world_epoch", 0))

    # ── lookups ──────────────────────────────────────────────────────────────
    def get(self, entity_id: str | None) -> dict | None:
        return self.entities.get(entity_id) if entity_id else None

    def rooms(self) -> list[dict]:
        return [e for e in self.entities.values() if has(e, "RoomComponent")]

    def first_room_id(self) -> str | None:
        rooms = self.rooms()
        return rooms[0]["id"] if rooms else None

    def characters(self) -> list[dict]:
        chars = [e for e in self.entities.values() if has(e, "CharacterComponent")]
        return sorted(chars, key=lambda e: entity_name(e).lower())

    def room_of(self, entity_id: str | None) -> str | None:
        if not entity_id:
            return None
        for room in self.rooms():
            for link in room["relationships"].get("Contains", []):
                if link["target"] == entity_id:
                    return room["id"]
        return None

    def room_members(self, room_id: str | None) -> list[dict]:
        room = self.get(room_id)
        if not room:
            return []
        members = [self.get(link["target"]) for link in room["relationships"].get("Contains", [])]
        return [m for m in members if m]

    def doors(self, room_id: str | None) -> list[tuple[str, str, dict | None]]:
        """Return ``(target_room_id, direction, dest_entity)`` for each exit."""
        room = self.get(room_id)
        if not room:
            return []
        out = []
        for link in room["relationships"].get("ExitTo", []):
            direction = (link["edge"].get("direction") or "").lower()
            out.append((link["target"], direction, self.get(link["target"])))
        return out

    def carried(self, player_id: str) -> list[dict]:
        player = self.get(player_id)
        if not player:
            return []
        out = []
        for rtype in ("Contains", "Holding", "Wearing"):
            for link in player["relationships"].get(rtype, []):
                entity = self.get(link["target"])
                if entity:
                    out.append(entity)
        return out

    def control(self, player_id: str) -> tuple[str, int] | None:
        """The controller (id, generation) currently driving the player, from the snapshot."""
        player = self.get(player_id)
        edges = player["relationships"].get("ControlledBy", []) if player else []
        if not edges:
            return None
        edge = edges[0]
        return edge["target"], int(edge["edge"].get("generation", 0))

    def points(self, player_id: str) -> dict[str, Any]:
        player = self.get(player_id)
        ap = (player or {}).get("components", {}).get("ActionPointsComponent") or {}
        fp = (player or {}).get("components", {}).get("FocusPointsComponent") or {}
        return {
            "has": player is not None,
            "ap": ap.get("current", 0), "ap_max": ap.get("maximum", 0),
            "fp": fp.get("current", 0), "fp_max": fp.get("maximum", 0),
        }

    def target_candidates(self, player_id: str, kind: str) -> list[Target]:
        """Reachable targets for a verb. Permissive — the server still validates."""
        room_id = self.room_of(player_id)
        members = [
            m for m in self.room_members(room_id)
            if m["id"] != player_id and not has(m, "RoomComponent")
        ]
        room_items = [m for m in members if not has(m, "CharacterComponent")]
        carried = self.carried(player_id)
        as_target = lambda e: Target(e["id"], entity_name(e), entity_icon(e))  # noqa: E731

        if kind == "exits":
            out = []
            for target_id, direction, dest in self.doors(room_id):
                name = entity_name(dest) if dest else target_id
                tag = f"{direction} → " if direction else ""
                out.append(Target(target_id, f"{tag}{name}", "🚪"))
            return out
        if kind == "roomItems":
            return [as_target(e) for e in room_items if has(e, "PortableComponent")]
        if kind == "inventory":
            return [as_target(e) for e in carried]
        if kind == "characters":
            return [as_target(e) for e in members if has(e, "CharacterComponent")]
        if kind == "reachableItems":
            return [as_target(e) for e in (*room_items, *carried)]
        return []


# ── entity presentation (mirrors the toon client) ─────────────────────────────
def entity_type(entity: dict) -> str:
    if has(entity, "RoomComponent"):
        return "room"
    if has(entity, "CharacterComponent"):
        return "character"
    if has(entity, "DoorComponent"):
        return "door"
    if has(entity, "ContainerComponent"):
        return "container"
    if has(entity, "PortableComponent"):
        return "item"
    return "other"


def entity_icon(entity: dict) -> str:
    emoji = entity["components"].get("EditorDisplayComponent", {}).get("emoji")
    if emoji:
        return emoji
    kind = entity["components"].get("IdentityComponent", {}).get("kind")
    return KIND_ICON.get(kind) or KIND_ICON.get(entity_type(entity)) or KIND_ICON["other"]


def entity_name(entity: dict | None) -> str:
    if not entity:
        return "?"
    c = entity["components"]
    if has(entity, "RoomComponent"):
        return c["RoomComponent"].get("title") or entity["id"]
    return c.get("IdentityComponent", {}).get("name") or entity["id"][:16]


def fmt_points(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"
