"""Client-neutral action metadata for verbs.

Action definitions describe how a command is presented and parsed. Command handlers still
own execution; definitions are shared by Discord help, LLM tool schemas, natural-language
patterns, and future clients.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .commands import CommandCost, Lane

ArgumentKind = Literal["string", "number", "boolean", "entity"]


@dataclass(frozen=True)
class ActionArgument:
    """One named action argument."""

    title: str = ""
    description: str = ""
    kind: ArgumentKind = "string"
    required: bool = False

    def json_schema(self) -> dict[str, Any]:
        schema_type = {
            "string": "string",
            "entity": "string",
            "number": "number",
            "boolean": "boolean",
        }[self.kind]
        schema: dict[str, Any] = {"type": schema_type}
        if self.title:
            schema["title"] = self.title
        if self.description:
            schema["description"] = self.description
        return schema


@dataclass(frozen=True)
class ActionExample:
    """A command example, rendered by clients from shared action metadata."""

    text: str
    natural: bool = False


@dataclass(frozen=True)
class ActionPattern:
    """Natural-language pattern with named slots, e.g. ``give {item_id} to {target_id}``."""

    text: str
    fixed_arguments: dict[str, Any] | None = None
    argument_aliases: dict[str, str] | None = None


@dataclass(frozen=True)
class ActionRequirement:
    """Coarse, declarative capability gate for an action.

    Each tuple is an *any-of* set of names resolved at runtime against the world's
    component/edge registries. A character meets the requirement when any one of the
    sub-checks passes (component present, edge present, or a reachable entity carries a
    component). This is intentionally a cheap, argument-agnostic hint -- the handler stays
    the source of truth for fine-grained, argument-specific gates (e.g. skill thresholds).
    """

    character_components: tuple[str, ...] = ()
    character_edges: tuple[str, ...] = ()
    reachable_components: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.character_components or self.character_edges or self.reachable_components)


@dataclass(frozen=True)
class ActionDefinition:
    """Shared metadata for one character action."""

    command_type: str
    tool_name: str | None = None
    title: str = ""
    description: str = ""
    icon: str = ""
    lane: Lane = Lane.WORLD
    cost: CommandCost = field(default_factory=lambda: CommandCost(action=1))
    arguments: dict[str, ActionArgument] | None = None
    examples: tuple[ActionExample, ...] = ()
    natural_patterns: tuple[ActionPattern, ...] = ()
    requirement: ActionRequirement = field(default_factory=ActionRequirement)

    @property
    def name(self) -> str:
        return self.tool_name or self.command_type.replace("-", "_")

    @property
    def arg_keys(self) -> tuple[str, ...]:
        return tuple(self.arguments or ())

    @property
    def reference_arg_keys(self) -> frozenset[str]:
        return frozenset(key for key, arg in (self.arguments or {}).items() if arg.kind == "entity")

    def tool_schema(self) -> dict[str, Any]:
        arguments = self.arguments or {}
        properties = {key: argument.json_schema() for key, argument in arguments.items()}
        required = [key for key, argument in arguments.items() if argument.required]
        parameters: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            parameters["required"] = required
        description = self.description or self.title or f"Character action: {self.name}"
        examples = tuple(example.text.strip() for example in self.examples if example.text.strip())
        if examples:
            label = "Example" if len(examples) == 1 else "Examples"
            description = f"{description} {label}: {', '.join(examples)}."
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": description,
                "parameters": parameters,
            },
        }


_ACTION = CommandCost(action=1)
_SPEECH = CommandCost(action=1, focus=1)
_FOCUS = CommandCost(focus=1)
_FREE = CommandCost()
_NO_REQUIREMENT = ActionRequirement()

ACTION_ICON_BY_COMMAND_TYPE: dict[str, str] = {
    "look": "👁️",
    "inspect": "🔎",
    "move": "➡️",
    "take": "🤲",
    "put": "📥",
    "drop": "📤",
    "open": "🚪",
    "close": "🚪",
    "lock": "🔒",
    "unlock": "🔓",
    "hold": "✊",
    "unhold": "🫳",
    "wear": "🧥",
    "remove": "🧥",
    "use": "🛠️",
    "write": "✍️",
    "sleep": "💤",
    "wake": "☀️",
    "wait": "⏳",
    "move-sprite": "🎯",
    "say": "💬",
    "tell": "🗣️",
    "start-conversation": "💬",
    "conversation-line": "💬",
    "end-conversation": "🔚",
    "take-note": "📝",
    "remember": "🧠",
    "forget": "🧹",
    "reflect": "💭",
    "ignite": "🔥",
    "extinguish": "🧯",
    "water-crop": "💧",
    "fish": "🎣",
    "mine": "⛏️",
    "eat": "🍽️",
    "drink": "💧",
    "bathe": "🛁",
    "clean-self": "🧼",
    "play": "🎲",
    "relax": "🛋️",
    "go-to-work": "💼",
    "pay-bill": "🧾",
    "buy-item": "🛒",
    "sell-item": "🏷️",
    "craft": "🛠️",
    "bake": "🍞",
    "sneak": "🥷",
    "steal": "🫴",
    "pick-lock": "🗝️",
    "attack": "⚔️",
    "defend": "🛡️",
    "cast-spell": "✨",
    "rest": "💤",
    "scan": "📡",
    "jump": "🚀",
    "dock": "⚓",
    "undock": "⚓",
    "land": "🛬",
    "launch": "🚀",
    "decontaminate": "☢️",
}

_ACTION_ICON_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("move", "➡️"),
    ("travel", "🧭"),
    ("enter", "🚪"),
    ("leave", "🚪"),
    ("open", "🚪"),
    ("close", "🚪"),
    ("lock", "🔒"),
    ("unlock", "🔓"),
    ("search", "🔎"),
    ("inspect", "🔎"),
    ("scan", "📡"),
    ("survey", "🗺️"),
    ("study", "📚"),
    ("learn", "📚"),
    ("read", "📖"),
    ("write", "✍️"),
    ("say", "💬"),
    ("tell", "🗣️"),
    ("ask", "❓"),
    ("talk", "💬"),
    ("persuade", "🗣️"),
    ("remember", "🧠"),
    ("reflect", "💭"),
    ("note", "📝"),
    ("forget", "🧹"),
    ("take", "🤲"),
    ("collect", "🤲"),
    ("claim", "🏳️"),
    ("drop", "📤"),
    ("put", "📥"),
    ("store", "📥"),
    ("retrieve", "📤"),
    ("haul", "📦"),
    ("cargo", "📦"),
    ("deliver", "📦"),
    ("buy", "🛒"),
    ("sell", "🏷️"),
    ("trade", "🤝"),
    ("pay", "💰"),
    ("deposit", "💰"),
    ("withdraw", "💰"),
    ("loan", "💰"),
    ("rent", "🏠"),
    ("work", "💼"),
    ("job", "💼"),
    ("craft", "🛠️"),
    ("repair", "🛠️"),
    ("build", "🏗️"),
    ("upgrade", "⬆️"),
    ("install", "🔧"),
    ("fabricate", "🏭"),
    ("machine", "⚙️"),
    ("power", "⚡"),
    ("water", "💧"),
    ("drink", "💧"),
    ("purify", "💧"),
    ("plant", "🌱"),
    ("harvest", "🌾"),
    ("forage", "🌿"),
    ("fertilize", "🌱"),
    ("till", "🌱"),
    ("weed", "🌿"),
    ("egg", "🥚"),
    ("feed", "🍽️"),
    ("eat", "🍽️"),
    ("cook", "🍳"),
    ("potion", "⚗️"),
    ("chem", "⚗️"),
    ("heal", "🩹"),
    ("treat", "🩹"),
    ("rescue", "🚑"),
    ("poison", "☠️"),
    ("radiation", "☢️"),
    ("mutation", "🧬"),
    ("sample", "🧪"),
    ("fossil", "🦴"),
    ("clone", "🧬"),
    ("mine", "⛏️"),
    ("scavenge", "🔧"),
    ("salvage", "🔧"),
    ("scrap", "🔧"),
    ("quest", "📜"),
    ("objective", "📜"),
    ("faction", "🏳️"),
    ("rank", "🏅"),
    ("crime", "⚖️"),
    ("jail", "⚖️"),
    ("bounty", "⚖️"),
    ("attack", "⚔️"),
    ("fight", "⚔️"),
    ("raid", "⚔️"),
    ("defeat", "⚔️"),
    ("defend", "🛡️"),
    ("fortify", "🛡️"),
    ("trap", "🪤"),
    ("sneak", "🥷"),
    ("hide", "🥷"),
    ("steal", "🫴"),
    ("pickpocket", "🫴"),
    ("spell", "✨"),
    ("magic", "✨"),
    ("ritual", "✨"),
    ("enchant", "✨"),
    ("dungeon", "🗝️"),
    ("map", "🗺️"),
    ("recall", "🌀"),
    ("rest", "💤"),
    ("sleep", "💤"),
    ("airlock", "🚪"),
    ("bulkhead", "🚪"),
    ("ship", "🚀"),
    ("orbit", "🪐"),
    ("drone", "🛰️"),
    ("ai", "🤖"),
    ("network", "📡"),
    ("hack", "💻"),
    ("exploit", "💻"),
    ("terminal", "💻"),
    ("credential", "🪪"),
    ("data", "💾"),
    ("evidence", "🧾"),
    ("camera", "📷"),
    ("sensor", "📡"),
    ("implant", "🦾"),
    ("boost", "⬆️"),
    ("call", "📣"),
    ("signal", "📣"),
    ("command", "📣"),
    ("assign", "📌"),
    ("set", "📌"),
    ("configure", "⚙️"),
    ("resolve", "✅"),
    ("complete", "✅"),
    ("accept", "✅"),
    ("decline", "✋"),
    ("refuse", "✋"),
    ("abandon", "🚫"),
    ("cancel", "🚫"),
    ("release", "🫳"),
    ("clean", "🧼"),
    ("wipe", "🧹"),
    ("clear", "🧹"),
)


def action_icon_for(command_type: str) -> str:
    """Return the default icon for a command type."""
    key = command_type.strip().lower()
    if key in ACTION_ICON_BY_COMMAND_TYPE:
        return ACTION_ICON_BY_COMMAND_TYPE[key]
    tokens = key.replace("_", "-").split("-")
    for token, icon in _ACTION_ICON_KEYWORDS:
        if token in tokens:
            return icon
    return "•"


REFERENCE_ARG_KEYS: frozenset[str] = frozenset(
    {
        "airlock_id",
        "animal_id",
        "artifact_id",
        "ai_id",
        "bank_id",
        "bait_id",
        "base_id",
        "bill_id",
        "bin_id",
        "body_id",
        "boss_id",
        "bulkhead_id",
        "business_id",
        "bundle_id",
        "building_id",
        "beacon_id",
        "child_id",
        "co_parent_id",
        "compartment_id",
        "contact_id",
        "conversation_id",
        "crate_id",
        "crime_id",
        "creature_id",
        "customer_id",
        "damage_id",
        "data_id",
        "debt_id",
        "destination_id",
        "door_id",
        "drone_id",
        "dungeon_id",
        "egg_id",
        "enclosure_id",
        "encounter_id",
        "emergency_id",
        "exit_id",
        "faction_id",
        "fertilizer_id",
        "festival_id",
        "feed_store_id",
        "fossil_id",
        "forage_id",
        "geode_id",
        "gap_id",
        "gravity_id",
        "guard_id",
        "guest_id",
        "grid_id",
        "hold_id",
        "incident_id",
        "institution_id",
        "ingredient_id",
        "item_id",
        "job_id",
        "key_id",
        "kit_id",
        "ladder_id",
        "lab_id",
        "loan_id",
        "lock_id",
        "location_id",
        "machine_id",
        "mail_id",
        "mate_id",
        "matrix_id",
        "module_id",
        "museum_id",
        "mission_id",
        "mortgage_id",
        "node_id",
        "obligation_id",
        "objective_id",
        "object_id",
        "offer_id",
        "partner_id",
        "parent_id",
        "passenger_id",
        "policy_id",
        "prisoner_id",
        "project_id",
        "property_id",
        "protocol_id",
        "quest_id",
        "reactor_id",
        "rival_id",
        "room_id",
        "rumor_id",
        "reward_id",
        "route_id",
        "seed_id",
        "seller_id",
        "service_id",
        "shrine_id",
        "sample_id",
        "schematic_id",
        "ship_id",
        "signal_id",
        "site_id",
        "soil_id",
        "spot_id",
        "station_id",
        "stockpile_id",
        "storage_id",
        "student_id",
        "system_id",
        "spell_id",
        "target_container_id",
        "target_id",
        "target_ids",
        "template_id",
        "tenant_id",
        "terminal_id",
        "threat_id",
        "tool_id",
        "tranquilizer_id",
        "treasure_id",
        "tree_id",
        "weapon_id",
        "worker_id",
        "word_id",
        "zone_id",
        "bed_id",
        "medicine_id",
        "patient_id",
        "injury_id",
        "source_id",
        "surgery_id",
        "whim_id",
    }
)


def _argument_for_key(key: str, *, required: bool = False) -> ActionArgument:
    title = key.removesuffix("_ids").removesuffix("_id").replace("_", " ").title()
    kind: ArgumentKind = "entity" if key in REFERENCE_ARG_KEYS else "string"
    if key in {
        "amount",
        "access_level",
        "capacity",
        "bounty",
        "bond",
        "care",
        "damage",
        "damage_per_hour",
        "default_price",
        "due_epoch",
        "due_in_seconds",
        "durability_cost",
        "duration_seconds",
        "gestation_seconds",
        "hourly_pay",
        "intensity",
        "interval_seconds",
        "limit",
        "adult_age_seconds",
        "elder_age_seconds",
        "natural_death_age_seconds",
        "natural_death_checks",
        "next_due_epoch",
        "next_shift_epoch",
        "performance_gain",
        "potency",
        "price",
        "progress",
        "priority",
        "quantity",
        "reduction",
        "reputation_delta",
        "reward_quantity",
        "reward_xp",
        "score",
        "seconds",
        "severity",
        "shift_duration_seconds",
        "shift_interval_seconds",
        "timeout_seconds",
        "standing_delta",
        "stamina_cost",
        "strength",
        "temperature",
        "unit_price",
        "warmth",
        "work",
        "xp",
    }:
        kind = "number"
    if key in {
        "audible",
        "contraband_found",
        "enabled",
        "feeding_pen",
        "lethal",
        "natural_aging",
        "quarantine",
    }:
        kind = "boolean"
    return ActionArgument(
        title=title,
        description=f"{title.lower()} for the action.",
        kind=kind,
        required=required,
    )


def _definition(
    command_type: str,
    args: tuple[str, ...] = (),
    *,
    tool_name: str | None = None,
    description: str | None = None,
    lane: Lane = Lane.WORLD,
    cost: CommandCost = _ACTION,
    required: tuple[str, ...] = (),
    patterns: tuple[str | ActionPattern, ...] = (),
    examples: tuple[str, ...] = (),
    requirement: ActionRequirement = _NO_REQUIREMENT,
    icon: str | None = None,
) -> ActionDefinition:
    title = command_type.replace("-", " ").title()
    return ActionDefinition(
        command_type=command_type,
        tool_name=tool_name,
        title=title,
        description=description or f"Character action: {command_type.replace('-', ' ')}",
        icon=icon or action_icon_for(command_type),
        lane=lane,
        cost=cost,
        arguments={key: _argument_for_key(key, required=key in required) for key in args},
        natural_patterns=tuple(
            pattern if isinstance(pattern, ActionPattern) else ActionPattern(pattern)
            for pattern in patterns
        ),
        examples=tuple(ActionExample(example, natural=True) for example in examples),
        requirement=requirement,
    )


# Public construction primitives for plugin-owned action catalogues.
ACTION_COST = _ACTION
SPEECH_COST = _SPEECH
FOCUS_COST = _FOCUS
FREE_COST = _FREE
define_action = _definition


def action_definitions(
    extra: tuple[ActionDefinition, ...] | list[ActionDefinition] = (),
) -> tuple[ActionDefinition, ...]:
    """Return the action definitions explicitly supplied by enabled plugins."""

    return tuple(extra)


def definition_by_command_type(
    definitions: tuple[ActionDefinition, ...] | list[ActionDefinition] | None = None,
) -> dict[str, ActionDefinition]:
    """Index definitions by engine command type, preferring the first alias."""

    by_command: dict[str, ActionDefinition] = {}
    for definition in action_definitions(definitions or ()):
        by_command.setdefault(definition.command_type, definition)
    return by_command


def definitions_by_tool_name(
    definitions: tuple[ActionDefinition, ...] | list[ActionDefinition] | None = None,
) -> dict[str, ActionDefinition]:
    """Index definitions by client/tool name."""

    return {definition.name: definition for definition in action_definitions(definitions or ())}


def reference_arg_keys(
    definitions: tuple[ActionDefinition, ...] | list[ActionDefinition] | None = None,
) -> frozenset[str]:
    return frozenset(
        key
        for definition in action_definitions(definitions or ())
        for key in definition.reference_arg_keys
    )


__all__ = [
    "ACTION_COST",
    "ActionArgument",
    "ActionDefinition",
    "ActionExample",
    "ActionPattern",
    "ActionRequirement",
    "ArgumentKind",
    "FOCUS_COST",
    "FREE_COST",
    "REFERENCE_ARG_KEYS",
    "action_definitions",
    "define_action",
    "definition_by_command_type",
    "definitions_by_tool_name",
    "reference_arg_keys",
    "SPEECH_COST",
]
