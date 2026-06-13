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
class ActionDefinition:
    """Shared metadata for one character action."""

    command_type: str
    tool_name: str | None = None
    title: str = ""
    description: str = ""
    lane: Lane = Lane.WORLD
    cost: CommandCost = field(default_factory=lambda: CommandCost(action=1))
    arguments: dict[str, ActionArgument] | None = None
    examples: tuple[ActionExample, ...] = ()
    natural_patterns: tuple[ActionPattern, ...] = ()

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
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description or self.title or f"Character action: {self.name}",
                "parameters": parameters,
            },
        }


def inferred_action_definition(command_type: str) -> ActionDefinition:
    title = command_type.replace("-", " ").title()
    return ActionDefinition(
        command_type=command_type,
        title=title,
        description=f"Character action: {command_type.replace('-', ' ')}",
        arguments={},
    )


_ACTION = CommandCost(action=1)
_SPEECH = CommandCost(action=1, focus=1)
_FOCUS = CommandCost(focus=1)
_FREE = CommandCost()

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
    patterns: tuple[str | ActionPattern, ...] = (),
    examples: tuple[str, ...] = (),
) -> ActionDefinition:
    title = command_type.replace("-", " ").title()
    return ActionDefinition(
        command_type=command_type,
        tool_name=tool_name,
        title=title,
        description=description or f"Character action: {command_type.replace('-', ' ')}",
        lane=lane,
        cost=cost,
        arguments={key: _argument_for_key(key) for key in args},
        natural_patterns=tuple(
            pattern if isinstance(pattern, ActionPattern) else ActionPattern(pattern)
            for pattern in patterns
        ),
        examples=tuple(ActionExample(example, natural=True) for example in examples),
    )


DEFAULT_ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    # Core verbs.
    _definition(
        "look",
        tool_name="look",
        cost=_FREE,
        patterns=(ActionPattern("look", {}), ActionPattern("look around", {})),
        examples=("look",),
    ),
    _definition(
        "inspect",
        ("target_id",),
        tool_name="inspect",
        patterns=("inspect {target_id}", "look at {target_id}", "examine {target_id}"),
        examples=("inspect woven basket",),
    ),
    _definition(
        "move",
        ("direction", "exit_id"),
        tool_name="move",
        patterns=(
            "go {direction}",
            "move {direction}",
            "walk {direction}",
            "run {direction}",
            "go {exit_id}",
            "move {exit_id}",
            "walk {exit_id}",
            "run {exit_id}",
            ActionPattern("north", {"direction": "north"}),
            ActionPattern("south", {"direction": "south"}),
            ActionPattern("east", {"direction": "east"}),
            ActionPattern("west", {"direction": "west"}),
            ActionPattern("up", {"direction": "up"}),
            ActionPattern("down", {"direction": "down"}),
            ActionPattern("inside", {"direction": "inside"}),
            ActionPattern("outside", {"direction": "outside"}),
            ActionPattern("in", {"direction": "in"}),
            ActionPattern("out", {"direction": "out"}),
        ),
        examples=("go north",),
    ),
    _definition(
        "take",
        ("item_id",),
        tool_name="take",
        patterns=(
            "take {item_id}",
            "get {item_id}",
            "grab {item_id}",
            "pick up {item_id}",
            "pick {item_id}",
        ),
        examples=("take brass key",),
    ),
    _definition(
        "put",
        ("item_id", "target_container_id"),
        tool_name="put",
        patterns=(
            "put {item_id} in {target_container_id}",
            "put {item_id} into {target_container_id}",
            "put {item_id} on {target_container_id}",
            "put {item_id} onto {target_container_id}",
        ),
    ),
    _definition(
        "drop",
        ("item_id",),
        tool_name="drop",
        patterns=("drop {item_id}", "put {item_id}"),
        examples=("drop brass key",),
    ),
    _definition(
        "open",
        ("target_id",),
        tool_name="open",
        patterns=("open {target_id}",),
        examples=("open woven basket",),
    ),
    _definition(
        "close",
        ("target_id",),
        tool_name="close",
        patterns=("close {target_id}",),
    ),
    _definition(
        "lock",
        ("target_id", "tool_id"),
        tool_name="lock",
        patterns=("lock {target_id} with {tool_id}", "lock {target_id}"),
    ),
    _definition(
        "unlock",
        ("target_id", "tool_id"),
        tool_name="unlock",
        patterns=("unlock {target_id} with {tool_id}", "unlock {target_id}"),
        examples=("unlock burrow door with brass key",),
    ),
    _definition(
        "hold",
        ("item_id",),
        tool_name="hold",
        patterns=("hold {item_id}", "equip {item_id}"),
    ),
    _definition(
        "unhold",
        ("item_id",),
        tool_name="unhold",
        patterns=("unhold {item_id}", "unequip {item_id}"),
    ),
    _definition("wear", ("item_id",), tool_name="wear", patterns=("wear {item_id}",)),
    _definition("remove", ("item_id",), tool_name="remove", patterns=("remove {item_id}",)),
    _definition(
        "use",
        ("target_id", "tool_id"),
        tool_name="use",
        patterns=("use {target_id} with {tool_id}", "use {target_id}"),
    ),
    _definition(
        "write",
        ("target_id", "text"),
        tool_name="write",
        cost=_SPEECH,
        patterns=("write {text} on {target_id}",),
    ),
    _definition("sleep", tool_name="sleep", cost=_FREE, patterns=(ActionPattern("sleep", {}),)),
    _definition("wake", tool_name="wake", cost=_FREE, patterns=(ActionPattern("wake", {}),)),
    _definition(
        "wait",
        tool_name="wait",
        cost=_FREE,
        patterns=(ActionPattern("wait", {}), ActionPattern("yield", {})),
        examples=("wait",),
    ),
    _definition("move-sprite", ("x", "y"), tool_name="move_sprite", cost=_FREE),
    _definition(
        "say",
        ("text", "intent", "approach"),
        tool_name="say",
        cost=_SPEECH,
        patterns=("say {text}",),
    ),
    _definition(
        "tell",
        ("target_id", "text", "intent", "approach", "audible"),
        tool_name="tell",
        cost=_SPEECH,
        patterns=("tell {target_id:word} {text}",),
    ),
    # Memory.
    _definition(
        "take-note",
        ("text", "tags", "scope", "collection"),
        tool_name="take_note",
        lane=Lane.FOCUS,
        cost=_FOCUS,
        patterns=("take note {text}", "note {text}"),
    ),
    _definition(
        "remember",
        ("query", "mode", "limit", "scope", "collection"),
        tool_name="remember",
        lane=Lane.FOCUS,
        cost=_FOCUS,
        patterns=("remember {query}",),
    ),
    _definition(
        "forget",
        ("note_id", "scope", "collection"),
        tool_name="forget",
        lane=Lane.FOCUS,
        cost=_FOCUS,
        patterns=("forget {note_id}",),
    ),
    _definition(
        "reflect",
        ("text", "query", "mode", "limit"),
        tool_name="reflect",
        lane=Lane.FOCUS,
        cost=_FOCUS,
        patterns=("reflect {text}",),
    ),
    # Environment and garden.
    _definition("ignite", ("target_id", "intensity"), tool_name="ignite"),
    _definition("extinguish", ("target_id",), tool_name="extinguish"),
    _definition("till", ("soil_id",), tool_name="till", patterns=("till {soil_id}",)),
    _definition(
        "plant",
        ("soil_id", "seed_id"),
        tool_name="plant",
        patterns=("plant {seed_id} in {soil_id}", "plant {seed_id} into {soil_id}"),
    ),
    _definition(
        "water-crop",
        ("soil_id",),
        tool_name="water_crop",
        patterns=("water {soil_id}",),
    ),
    _definition(
        "fertilize",
        ("soil_id", "fertilizer_id"),
        tool_name="fertilize",
        patterns=("fertilize {soil_id} with {fertilizer_id}",),
    ),
    _definition("inspect-crop", ("soil_id",), tool_name="inspect_crop"),
    _definition("weed-crop", ("soil_id",), tool_name="weed_crop"),
    _definition("treat-pests", ("soil_id",), tool_name="treat_pests"),
    _definition(
        "harvest-crop",
        ("soil_id",),
        tool_name="harvest_crop",
        patterns=("harvest {soil_id}",),
    ),
    _definition(
        "clear-dead-crop",
        ("soil_id",),
        tool_name="clear_dead_crop",
        patterns=("clear dead crop from {soil_id}",),
    ),
    _definition(
        "tap-tree",
        ("tree_id",),
        tool_name="tap_tree",
        patterns=("tap {tree_id}", "tap tree {tree_id}"),
    ),
    _definition(
        "harvest-sap",
        ("tree_id",),
        tool_name="harvest_sap",
        patterns=("harvest sap from {tree_id}", "collect sap from {tree_id}"),
    ),
    _definition("start-machine", ("machine_id", "recipe_id"), tool_name="start_machine"),
    _definition(
        "collect-machine-output",
        ("machine_id",),
        tool_name="collect_machine_output",
    ),
    _definition("cancel-machine", ("machine_id",), tool_name="cancel_machine"),
    _definition("repair-machine", ("machine_id",), tool_name="repair_machine"),
    _definition("feed-animal", ("animal_id", "feed_type"), tool_name="feed_animal"),
    _definition("pet-animal", ("animal_id",), tool_name="pet_animal"),
    _definition(
        "breed-animal",
        ("animal_id", "mate_id", "gestation_seconds"),
        tool_name="breed_animal",
    ),
    _definition(
        "collect-animal-product",
        ("animal_id",),
        tool_name="collect_animal_product",
    ),
    _definition("fish", ("spot_id",), tool_name="fish", patterns=("fish {spot_id}",)),
    _definition("mine", ("node_id",), tool_name="mine", patterns=("mine {node_id}",)),
    _definition("discover-ladder", ("ladder_id",), tool_name="discover_ladder"),
    _definition("open-geode", ("geode_id",), tool_name="open_geode"),
    _definition("forage", ("forage_id",), tool_name="forage", patterns=("forage {forage_id}",)),
    _definition("give-gift", ("target_id", "item_id"), tool_name="give_gift"),
    _definition("join-festival", ("festival_id",), tool_name="join_festival"),
    _definition(
        "contribute-bundle",
        ("bundle_id", "resource_type", "quantity"),
        tool_name="contribute_bundle",
    ),
    _definition("claim-mail", ("mail_id",), tool_name="claim_mail"),
    _definition("complete-farm-quest", ("quest_id",), tool_name="complete_farm_quest"),
    _definition(
        "ship-items",
        ("bin_id", "resource_type", "quantity", "unit_price"),
        tool_name="ship_items",
    ),
    _definition("donate-museum", ("museum_id", "resource_type"), tool_name="donate_museum"),
    _definition("claim-reward", ("reward_id",), tool_name="claim_reward"),
    # Dino sim.
    _definition(
        "identify-fossil",
        ("fossil_id", "species_name"),
        tool_name="identify_fossil",
    ),
    _definition(
        "extract-ancient-sample",
        ("fossil_id",),
        tool_name="extract_ancient_sample",
    ),
    _definition("prepare-clone", ("sample_id",), tool_name="prepare_clone"),
    _definition("lay-egg", ("parent_id",), tool_name="lay_egg"),
    _definition("fertilize-egg", ("egg_id", "parent_id"), tool_name="fertilize_egg"),
    _definition(
        "incubate-egg",
        ("egg_id", "duration_seconds"),
        tool_name="incubate_egg",
    ),
    _definition("hatch-egg", ("egg_id",), tool_name="hatch_egg"),
    _definition("survey-fossil", ("fossil_id",), tool_name="survey_fossil"),
    _definition(
        "excavate-fossil",
        ("fossil_id", "progress"),
        tool_name="excavate_fossil",
    ),
    _definition("clean-fossil", ("fossil_id",), tool_name="clean_fossil"),
    _definition("stabilize-fossil", ("fossil_id",), tool_name="stabilize_fossil"),
    _definition(
        "lab-incubate-egg",
        ("egg_id", "lab_id"),
        tool_name="lab_incubate_egg",
    ),
    _definition(
        "inspect-egg",
        ("egg_id", "viability"),
        tool_name="inspect_egg",
    ),
    _definition(
        "imprint-creature",
        ("creature_id", "bond"),
        tool_name="imprint_creature",
    ),
    _definition(
        "care-for-juvenile",
        ("creature_id", "care"),
        tool_name="care_for_juvenile",
    ),
    _definition(
        "study-water-creature",
        ("creature_id",),
        tool_name="study_water_creature",
    ),
    _definition(
        "brood-egg",
        ("egg_id", "warmth"),
        tool_name="brood_egg",
    ),
    _definition(
        "set-incubation-temperature",
        ("egg_id", "temperature"),
        tool_name="set_incubation_temperature",
    ),
    _definition(
        "trigger-containment-panic",
        ("enclosure_id", "severity"),
        tool_name="trigger_containment_panic",
    ),
    _definition(
        "track-creature",
        ("creature_id",),
        tool_name="track_creature",
        patterns=("track {creature_id}",),
    ),
    _definition("mark-territory", ("territory_id",), tool_name="mark_territory"),
    _definition("track-herd", ("herd_id",), tool_name="track_herd"),
    _definition("prepare-nest", ("nest_id",), tool_name="prepare_nest"),
    _definition(
        "set-bait",
        ("bait_id", "target_species", "potency"),
        tool_name="set_bait",
        patterns=("set bait {bait_id}",),
    ),
    _definition(
        "tranquilize-creature",
        ("creature_id", "tranquilizer_id", "duration_seconds"),
        tool_name="tranquilize_creature",
        patterns=("tranquilize {creature_id}",),
    ),
    _definition(
        "approach-creature",
        ("creature_id",),
        tool_name="approach_creature",
        patterns=("approach {creature_id}",),
    ),
    _definition(
        "tame-creature",
        ("creature_id", "role"),
        tool_name="tame_creature",
        patterns=("tame {creature_id}",),
    ),
    _definition(
        "train-command",
        ("creature_id", "command_name", "progress"),
        tool_name="train_command",
    ),
    _definition(
        "mount-creature",
        ("creature_id",),
        tool_name="mount_creature",
        patterns=("mount {creature_id}",),
    ),
    _definition(
        "command-companion",
        ("creature_id", "command_name", "target_id"),
        tool_name="command_companion",
    ),
    _definition(
        "recall-creature",
        ("creature_id",),
        tool_name="recall_creature",
        patterns=("recall {creature_id}",),
    ),
    _definition(
        "build-enclosure",
        ("room_id", "name", "capacity", "feeding_pen", "quarantine"),
        tool_name="build_enclosure",
    ),
    _definition(
        "repair-fence",
        ("enclosure_id", "amount"),
        tool_name="repair_fence",
    ),
    _definition(
        "reinforce-gate",
        ("enclosure_id", "amount"),
        tool_name="reinforce_gate",
    ),
    _definition("lock-pen", ("enclosure_id",), tool_name="lock_pen"),
    _definition("open-pen", ("enclosure_id",), tool_name="open_pen"),
    _definition(
        "trigger-containment",
        ("enclosure_id",),
        tool_name="trigger_containment",
    ),
    _definition(
        "recapture-creature",
        ("creature_id", "enclosure_id"),
        tool_name="recapture_creature",
    ),
    _definition(
        "hide-from-creature",
        ("creature_id",),
        tool_name="hide_from_creature",
    ),
    _definition(
        "evacuate-room",
        ("room_id", "destination_id"),
        tool_name="evacuate_room",
    ),
    _definition("dodge-creature", ("creature_id",), tool_name="dodge_creature"),
    _definition(
        "fight-creature",
        ("creature_id", "damage"),
        tool_name="fight_creature",
    ),
    _definition(
        "target-weak-point",
        ("creature_id", "damage"),
        tool_name="target_weak_point",
    ),
    _definition(
        "drive-off-predator",
        ("creature_id",),
        tool_name="drive_off_predator",
    ),
    _definition(
        "call-for-help",
        ("room_id", "strength"),
        tool_name="call_for_help",
    ),
    _definition(
        "signal-army",
        ("room_id", "creature_id", "strength"),
        tool_name="signal_army",
    ),
    _definition(
        "repair-damage",
        ("damage_id", "amount"),
        tool_name="repair_damage",
    ),
    _definition(
        "stock-feed",
        ("feed_store_id", "amount"),
        tool_name="stock_feed",
    ),
    _definition("collect-egg", ("egg_id",), tool_name="collect_egg"),
    _definition(
        "harvest-product",
        ("creature_id", "product_type", "quantity"),
        tool_name="harvest_product",
    ),
    _definition(
        "assign-ranch-work",
        ("creature_id", "work_type", "target_id"),
        tool_name="assign_ranch_work",
    ),
    _definition(
        "assign-guard",
        ("creature_id", "location_id"),
        tool_name="assign_guard",
    ),
    _definition(
        "feed-creature",
        ("creature_id", "feed_store_id"),
        tool_name="feed_creature",
    ),
    _definition("calm-creature", ("creature_id",), tool_name="calm_creature"),
    _definition("observe-creature", ("creature_id",), tool_name="observe_creature"),
    # Life sim.
    _definition("eat", ("item_id",), tool_name="eat", patterns=("eat {item_id}",)),
    _definition("drink", ("source_id",), tool_name="drink", patterns=("drink {source_id}",)),
    _definition(
        "bathe",
        ("target_id",),
        tool_name="bathe",
        patterns=("bathe", "bathe at {target_id}"),
    ),
    _definition("clean-self", ("target_id",), tool_name="clean_self", patterns=("clean self",)),
    _definition(
        "play",
        ("target_id",),
        tool_name="play",
        patterns=("play", "play with {target_id}"),
    ),
    _definition(
        "relax",
        ("target_id",),
        tool_name="relax",
        patterns=("relax", "relax on {target_id}"),
    ),
    _definition(
        "seek-privacy",
        ("target_id",),
        tool_name="seek_privacy",
        patterns=("seek privacy",),
    ),
    _definition("seek-safety", ("target_id",), tool_name="seek_safety", patterns=("seek safety",)),
    _definition("choose-aspiration", ("name", "milestones"), tool_name="choose_aspiration"),
    _definition("complete-milestone", ("milestone", "reward_name"), tool_name="complete_milestone"),
    _definition("practice-skill", ("skill", "xp"), tool_name="practice_skill"),
    _definition("study-skill", ("skill", "xp"), tool_name="study_skill"),
    _definition("mentor-skill", ("student_id", "skill", "xp"), tool_name="mentor_skill"),
    _definition(
        "update-profile",
        ("traits", "interests", "preferred_routine"),
        tool_name="update_profile",
    ),
    _definition("add-whim", ("want", "reward_xp"), tool_name="add_whim"),
    _definition("complete-whim", ("whim_id",), tool_name="complete_whim"),
    _definition("use-home-object", ("object_id",), tool_name="use_home_object"),
    _definition(
        "maintain-home-object",
        ("object_id", "action"),
        tool_name="maintain_home_object",
    ),
    _definition("invite-over", ("guest_id", "room_id"), tool_name="invite_over"),
    _definition(
        "configure-aging",
        (
            "natural_aging",
            "adult_age_seconds",
            "elder_age_seconds",
            "natural_death_age_seconds",
            "natural_death_checks",
        ),
        tool_name="configure_aging",
    ),
    _definition(
        "find-job",
        (
            "title",
            "hourly_pay",
            "next_shift_epoch",
            "shift_duration_seconds",
            "shift_interval_seconds",
        ),
        tool_name="find_job",
    ),
    _definition("go-to-work", ("performance_gain",), tool_name="go_to_work"),
    _definition("quit-job", tool_name="quit_job"),
    _definition("pay-wage", ("worker_id", "amount"), tool_name="pay_wage"),
    _definition("assess-tax", ("amount", "reason", "due_epoch"), tool_name="assess_tax"),
    _definition(
        "charge-rent",
        ("tenant_id", "amount", "reason", "due_epoch"),
        tool_name="charge_rent",
        patterns=("charge rent {tenant_id} {amount}",),
    ),
    _definition(
        "pay-bill",
        ("bill_id",),
        tool_name="pay_bill",
        patterns=("pay bill {bill_id}", ActionPattern("pay bill", {})),
    ),
    _definition(
        "open-business",
        ("name", "default_price"),
        tool_name="open_business",
        patterns=("open business {name}",),
    ),
    _definition(
        "buy-item",
        ("seller_id", "item_id", "business_id", "price"),
        tool_name="buy_item",
        patterns=("buy {item_id} from {seller_id}",),
    ),
    _definition(
        "sell-item",
        ("item_id", "customer_id", "business_id", "price"),
        tool_name="sell_item",
        patterns=("sell {item_id} to {customer_id}",),
    ),
    _definition("promote-business", ("business_id",), tool_name="promote_business"),
    _definition(
        "join-household",
        ("household_id", "name"),
        tool_name="join_household",
        patterns=(
            ActionPattern(
                "join household {household_id}",
                argument_aliases={"name": "household_id"},
            ),
        ),
    ),
    _definition(
        "claim-home",
        ("room_id",),
        tool_name="claim_home",
        patterns=("claim home {room_id}", ActionPattern("claim home", {})),
    ),
    _definition(
        "claim-room",
        ("room_id",),
        tool_name="claim_room",
        patterns=("claim room {room_id}", ActionPattern("claim room", {})),
    ),
    _definition(
        "set-routine", ("activity", "interval_seconds", "next_due_epoch"), tool_name="set_routine"
    ),
    _definition(
        "set-relationship-status", ("target_id", "status"), tool_name="set_relationship_status"
    ),
    _definition(
        "spread-gossip", ("target_id", "text", "reputation_delta"), tool_name="spread_gossip"
    ),
    _definition(
        "witness-romance", ("partner_id", "rival_id", "intensity"), tool_name="witness_romance"
    ),
    _definition("start-partnership", ("target_id",), tool_name="start_partnership"),
    _definition("end-partnership", ("target_id",), tool_name="end_partnership"),
    _definition("start-pregnancy", ("co_parent_id", "due_in_seconds"), tool_name="start_pregnancy"),
    _definition("resolve-birth", ("child_name",), tool_name="resolve_birth"),
    _definition(
        "adopt-child",
        ("child_id",),
        tool_name="adopt_child",
        patterns=("adopt {child_id}",),
    ),
    # Colony, dragon, and barbarian sims.
    _definition("reserve", ("target_id",), tool_name="reserve"),
    _definition("release-reservation", ("target_id",), tool_name="release_reservation"),
    _definition("gather-resource", ("node_id", "quantity"), tool_name="gather_resource"),
    _definition(
        "create-stockpile",
        ("name", "capacity", "allowed_types"),
        tool_name="create_stockpile",
    ),
    _definition(
        "set-storage-filter",
        ("stockpile_id", "allowed_types"),
        tool_name="set_storage_filter",
    ),
    _definition("forbid-item", ("item_id",), tool_name="forbid_item"),
    _definition("allow-item", ("item_id",), tool_name="allow_item"),
    _definition(
        "haul-item",
        ("item_id", "target_container_id"),
        tool_name="haul_item",
    ),
    _definition("split-stack", ("item_id", "quantity"), tool_name="split_stack"),
    _definition("merge-stack", ("source_id", "target_id"), tool_name="merge_stack"),
    _definition("craft", ("recipe_id",), tool_name="craft"),
    _definition("bake", ("recipe_id",), tool_name="bake", patterns=("bake {recipe_id}",)),
    _definition("set-work-priority", ("work_type", "priority"), tool_name="set_work_priority"),
    _definition("set-allowed-area", ("room_ids",), tool_name="set_allowed_area"),
    _definition(
        "update-pawn-profile",
        ("backstory", "passions", "expectations"),
        tool_name="update_pawn_profile",
    ),
    _definition("progress-job-bill", ("bill_id", "work"), tool_name="progress_job_bill"),
    _definition(
        "set-prisoner-policy",
        ("prisoner_id", "policy"),
        tool_name="set_prisoner_policy",
    ),
    _definition(
        "recruit-prisoner",
        ("prisoner_id", "progress"),
        tool_name="recruit_prisoner",
    ),
    _definition("research-project", ("project_id", "work"), tool_name="research_project"),
    _definition("complete-trade", ("offer_id",), tool_name="complete_trade"),
    _definition(
        "form-caravan",
        ("destination", "cargo", "member_ids"),
        tool_name="form_caravan",
    ),
    _definition(
        "perform-surgery",
        ("patient_id", "surgery_id"),
        tool_name="perform_surgery",
    ),
    _definition("tend-wound", ("patient_id", "injury_id", "medicine_id"), tool_name="tend_wound"),
    _definition("rescue-to-bed", ("patient_id", "bed_id"), tool_name="rescue_to_bed"),
    _definition("assign-job", ("job_id",), tool_name="assign_job"),
    _definition("complete-job", ("job_id",), tool_name="complete_job"),
    _definition(
        "claim-ownership",
        ("target_id",),
        tool_name="claim_ownership",
        patterns=("claim {target_id}",),
    ),
    _definition(
        "release-ownership",
        ("target_id",),
        tool_name="release_ownership",
        patterns=("release ownership {target_id}",),
    ),
    _definition(
        "discover-location",
        ("location_id",),
        tool_name="discover_location",
        patterns=("discover {location_id}",),
    ),
    _definition(
        "mark-map",
        ("location_id", "label"),
        tool_name="mark_map",
        patterns=("mark {location_id} on map",),
    ),
    _definition(
        "trigger-encounter",
        ("zone_id",),
        tool_name="trigger_encounter",
        patterns=("enter encounter {zone_id}",),
    ),
    _definition(
        "accept-quest",
        ("quest_id",),
        tool_name="accept_quest",
        patterns=("accept quest {quest_id}",),
    ),
    _definition(
        "complete-objective",
        ("objective_id",),
        tool_name="complete_objective",
        patterns=("complete objective {objective_id}",),
    ),
    _definition(
        "join-faction",
        ("faction_id", "rank"),
        tool_name="join_faction",
        patterns=("join faction {faction_id}",),
    ),
    _definition(
        "leave-faction",
        ("faction_id",),
        tool_name="leave_faction",
        patterns=("leave faction {faction_id}",),
    ),
    _definition(
        "unlock-perk",
        ("perk_id",),
        tool_name="unlock_perk",
        patterns=("unlock perk {perk_id}",),
    ),
    _definition(
        "absorb-great-soul",
        ("beast_id",),
        tool_name="absorb_great_soul",
        patterns=("absorb great soul {beast_id}",),
    ),
    _definition(
        "learn-word-of-power",
        ("word_id",),
        tool_name="learn_word_of_power",
        patterns=("learn word {word_id}",),
    ),
    _definition(
        "speak-word-of-power",
        ("word_id",),
        tool_name="speak_word_of_power",
        patterns=("speak word {word_id}",),
    ),
    _definition(
        "inscribe-voice-phrase",
        ("target_id", "word_id", "phrase"),
        tool_name="inscribe_voice_phrase",
        patterns=("inscribe {phrase} on {target_id}",),
    ),
    _definition(
        "study-voice-inscription",
        ("target_id",),
        tool_name="study_voice_inscription",
        patterns=("study inscription on {target_id}",),
    ),
    _definition("sneak", tool_name="sneak", patterns=(ActionPattern("sneak", {}),)),
    _definition(
        "steal",
        ("target_id", "item_id"),
        tool_name="steal",
        patterns=("steal {item_id} from {target_id:word}",),
    ),
    _definition(
        "pay-bounty",
        ("faction_id",),
        tool_name="pay_bounty",
        patterns=("pay bounty {faction_id}",),
    ),
    _definition(
        "change-faction-rank",
        ("faction_id", "rank"),
        tool_name="change_faction_rank",
    ),
    _definition("bribe-guard", ("guard_id",), tool_name="bribe_guard"),
    _definition("serve-jail-time", tool_name="serve_jail_time"),
    _definition("pick-lock", ("lock_id",), tool_name="pick_lock"),
    _definition(
        "read-lore-book",
        ("book_id",),
        tool_name="read_lore_book",
        patterns=("read {book_id}",),
    ),
    _definition("learn-spell", ("spell_id",), tool_name="learn_spell"),
    _definition("cast-dragon-spell", ("spell_id",), tool_name="cast_dragon_spell"),
    _definition("brew-potion", ("recipe_id",), tool_name="brew_potion"),
    _definition("use-artifact", ("artifact_id",), tool_name="use_artifact"),
    _definition("track-quest", ("quest_id",), tool_name="track_quest"),
    _definition("decline-quest", ("quest_id",), tool_name="decline_quest"),
    _definition(
        "choose-quest-branch",
        ("quest_id", "branch"),
        tool_name="choose_quest_branch",
    ),
    _definition("persuade", ("target_id", "amount"), tool_name="persuade"),
    _definition("surrender", ("target_id", "reason"), tool_name="surrender"),
    _definition(
        "report-crime",
        ("criminal_id", "faction_id", "bounty"),
        tool_name="report_crime",
    ),
    _definition("recover-magicka", ("amount",), tool_name="recover_magicka"),
    _definition("identify-artifact", ("artifact_id",), tool_name="identify_artifact"),
    _definition(
        "appease-ancient-beast",
        ("beast_id", "method"),
        tool_name="appease_ancient_beast",
    ),
    _definition(
        "attack",
        ("target_id", "weapon_id", "lethal", "body_part", "stamina_cost", "durability_cost"),
        tool_name="attack",
    ),
    _definition(
        "spar",
        ("target_id", "weapon_id", "body_part", "stamina_cost", "durability_cost"),
        tool_name="spar",
    ),
    _definition("defend", ("stamina_cost", "reduction"), tool_name="defend"),
    _definition("challenge", ("target_id", "terms"), tool_name="challenge"),
    _definition("fortify", ("target_id", "strength"), tool_name="fortify"),
    _definition("claim-base", ("base_id", "clan"), tool_name="claim_base"),
    _definition("place-trap", ("damage",), tool_name="place_trap"),
    _definition("disarm-trap", ("trap_id",), tool_name="disarm_trap"),
    _definition("raid", ("target_id", "intensity"), tool_name="raid"),
    _definition("bridge-survival-gap", ("gap_id",), tool_name="bridge_survival_gap"),
    _definition("decay-building", ("building_id", "amount"), tool_name="decay_building"),
    _definition(
        "upgrade-building",
        ("building_id", "integrity"),
        tool_name="upgrade_building",
    ),
    _definition("demolish-building", ("building_id",), tool_name="demolish_building"),
    _definition("prepare-siege", ("base_id", "score"), tool_name="prepare_siege"),
    _definition("start-purge-wave", ("base_id", "intensity"), tool_name="start_purge_wave"),
    _definition(
        "perform-ritual",
        ("shrine_id", "ritual_id"),
        tool_name="perform_ritual",
    ),
    _definition("explore-danger-zone", ("zone_id",), tool_name="explore_danger_zone"),
    _definition("defeat-boss", ("boss_id",), tool_name="defeat_boss"),
    _definition(
        "unlock-treasure",
        ("treasure_id", "key_id"),
        tool_name="unlock_treasure",
    ),
    _definition("claim-treasure", ("treasure_id",), tool_name="claim_treasure"),
    _definition("climb", ("gate_id",), tool_name="climb"),
    _definition("repair-item", ("item_id", "amount"), tool_name="repair_item"),
    _definition(
        "poison-character",
        ("target_id", "severity", "damage_per_hour"),
        tool_name="poison_character",
    ),
    _definition("treat-poison", ("target_id",), tool_name="treat_poison"),
    _definition("gain-corruption", ("amount",), tool_name="gain_corruption"),
    _definition("cleanse-corruption", tool_name="cleanse_corruption"),
    _definition(
        "pickpocket",
        ("target_id", "item_id"),
        tool_name="pickpocket",
        patterns=("pickpocket {target_id:word} {item_id}",),
    ),
    _definition("subdue", ("target_id", "task"), tool_name="subdue"),
    _definition("recruit-follower", ("target_id",), tool_name="recruit_follower"),
    _definition("command-follower", ("target_id", "orders"), tool_name="command_follower"),
    _definition("release-thrall", ("target_id",), tool_name="release_thrall"),
    # Dagger sim.
    _definition("expand-site", ("site_id", "generator_id", "trigger"), tool_name="expand_site"),
    _definition("ask-rumor", ("rumor_id",), tool_name="ask_rumor"),
    _definition("investigate-rumor", ("rumor_id",), tool_name="investigate_rumor"),
    _definition("plan-travel", ("destination_id",), tool_name="plan_travel"),
    _definition("join-institution", ("institution_id", "rank"), tool_name="join_institution"),
    _definition("use-institution-service", ("service_id",), tool_name="use_institution_service"),
    _definition(
        "promote-institution",
        ("institution_id", "rank"),
        tool_name="promote_institution",
    ),
    _definition(
        "pay-institution-dues",
        ("institution_id", "amount"),
        tool_name="pay_institution_dues",
    ),
    _definition("ask-for-work", ("template_id",), tool_name="ask_for_work"),
    _definition("accept-generated-quest", ("quest_id",), tool_name="accept_generated_quest"),
    _definition("complete-generated-quest", ("quest_id",), tool_name="complete_generated_quest"),
    _definition(
        "refuse-generated-quest",
        ("quest_id",),
        tool_name="refuse_generated_quest",
    ),
    _definition(
        "abandon-generated-quest",
        ("quest_id",),
        tool_name="abandon_generated_quest",
    ),
    _definition(
        "extend-generated-quest",
        ("quest_id", "seconds"),
        tool_name="extend_generated_quest",
    ),
    _definition(
        "lie-about-quest",
        ("quest_id", "lie"),
        tool_name="lie_about_quest",
    ),
    _definition("open-bank-account", ("bank_id",), tool_name="open_bank_account"),
    _definition("deposit", ("bank_id", "amount"), tool_name="deposit"),
    _definition("withdraw", ("bank_id", "amount"), tool_name="withdraw"),
    _definition("take-loan", ("bank_id", "amount", "duration_seconds"), tool_name="take_loan"),
    _definition("repay-loan", ("loan_id", "amount"), tool_name="repay_loan"),
    _definition(
        "issue-letter-of-credit",
        ("bank_id", "amount"),
        tool_name="issue_letter_of_credit",
    ),
    _definition(
        "store-safe-item",
        ("storage_id", "item_id"),
        tool_name="store_safe_item",
    ),
    _definition(
        "retrieve-safe-item",
        ("storage_id", "item_id"),
        tool_name="retrieve_safe_item",
    ),
    _definition("send-debt-collector", ("debt_id",), tool_name="send_debt_collector"),
    _definition("commit-crime", ("crime_type",), tool_name="commit_crime"),
    _definition("pay-fine", ("crime_id",), tool_name="pay_fine"),
    _definition("sentence-crime", ("crime_id", "sentence"), tool_name="sentence_crime"),
    _definition(
        "rent-lodging",
        ("lodging_id", "duration_seconds"),
        tool_name="rent_lodging",
    ),
    _definition("camp", ("risk",), tool_name="camp"),
    _definition("buy-travel-supplies", ("quantity",), tool_name="buy_travel_supplies"),
    _definition(
        "resolve-travel-interruption",
        ("interruption_id",),
        tool_name="resolve_travel_interruption",
    ),
    _definition("buy-property", ("property_id",), tool_name="buy_property"),
    _definition(
        "create-custom-class",
        (
            "template_id",
            "class_name",
            "primary_skills",
            "major_skills",
            "minor_skills",
            "advantages",
            "disadvantages",
        ),
        tool_name="create_custom_class",
    ),
    _definition("create-spell", ("template_id", "spell_name"), tool_name="create_spell"),
    _definition(
        "cast-spell",
        ("spell_id", "target_id"),
        tool_name="cast_spell",
        patterns=(
            "cast {spell_id} on {target_id}",
            "cast {spell_id} at {target_id}",
            "cast {spell_id}",
        ),
        examples=("cast moss charm on Juniper",),
    ),
    _definition(
        "enchant-item",
        ("item_id", "spell_id"),
        tool_name="enchant_item",
        patterns=("enchant {item_id} with {spell_id}",),
        examples=("enchant moss charm with Mend Moss",),
    ),
    _definition("make-potion", ("maker_id",), tool_name="make_potion"),
    _definition(
        "recharge-enchanted-item",
        ("item_id", "service_id"),
        tool_name="recharge_enchanted_item",
    ),
    _definition(
        "identify-ingredient",
        ("ingredient_id",),
        tool_name="identify_ingredient",
    ),
    _definition("attempt-pacify", ("target_id", "language"), tool_name="attempt_pacify"),
    _definition("contract-affliction", ("affliction_type",), tool_name="contract_affliction"),
    _definition(
        "progress-affliction-incubation",
        ("target_id",),
        tool_name="progress_affliction_incubation",
    ),
    _definition(
        "mark-affliction-stigma",
        ("target_id", "region_id", "severity"),
        tool_name="mark_affliction_stigma",
    ),
    _definition("request-cure-quest", ("quest_id",), tool_name="request_cure_quest"),
    _definition("transform", ("form_name",), tool_name="transform"),
    _definition("feed-on", ("target_id",), tool_name="feed_on"),
    _definition("end-transformation", tool_name="end_transformation"),
    _definition("cure-affliction", tool_name="cure_affliction"),
    _definition("request-dungeon", ("dungeon_id",), tool_name="request_dungeon"),
    _definition("enter-dungeon", ("dungeon_id",), tool_name="enter_dungeon"),
    _definition("search-room", tool_name="search_room"),
    _definition("open-secret-door", ("door_id",), tool_name="open_secret_door"),
    _definition("mark-path", tool_name="mark_path"),
    _definition("view-map", tool_name="view_map"),
    _definition("set-recall", tool_name="set_recall"),
    _definition("use-recall", tool_name="use_recall"),
    _definition("rest", tool_name="rest"),
    _definition("leave-dungeon", ("dungeon_id",), tool_name="leave_dungeon"),
    # Void sim and storyteller.
    _definition("open-airlock", ("airlock_id",), tool_name="open_airlock"),
    _definition("cycle-airlock", ("airlock_id",), tool_name="cycle_airlock"),
    _definition("seal-bulkhead", ("bulkhead_id",), tool_name="seal_bulkhead"),
    _definition("repair-system", ("system_id",), tool_name="repair_system"),
    _definition("reroute-power", ("grid_id", "system_id", "amount"), tool_name="reroute_power"),
    _definition("inspect-ship-system", ("system_id",), tool_name="inspect_ship_system"),
    _definition("fabricate", ("fabricator_id", "blueprint_id"), tool_name="fabricate"),
    _definition("install-upgrade", ("upgrade_id", "system_id"), tool_name="install_upgrade"),
    _definition("accept-contract", ("contract_id",), tool_name="accept_contract"),
    _definition("load-cargo", ("contract_id", "cargo_id", "ship_id"), tool_name="load_cargo"),
    _definition(
        "deliver-cargo",
        ("contract_id", "cargo_id", "ship_id"),
        tool_name="deliver_cargo",
    ),
    _definition("claim-salvage", ("claim_id", "contract_id"), tool_name="claim_salvage"),
    _definition("initiate-contact", ("contact_id",), tool_name="initiate_contact"),
    _definition(
        "attempt-translation",
        ("matrix_id", "progress"),
        tool_name="attempt_translation",
    ),
    _definition("quarantine-sample", ("target_id", "reason"), tool_name="quarantine_sample"),
    _definition(
        "negotiate-alien",
        ("mission_id", "standing_delta"),
        tool_name="negotiate_alien",
    ),
    _definition(
        "study-alien-artifact",
        ("artifact_id",),
        tool_name="study_alien_artifact",
    ),
    _definition("dock", ("ship_id", "station_id", "port"), tool_name="dock"),
    _definition("undock", ("ship_id", "station_id"), tool_name="undock"),
    _definition("evacuate-module", ("module_id", "destination_id"), tool_name="evacuate_module"),
    _definition("plot-course", ("ship_id", "destination_id"), tool_name="plot_course"),
    _definition("jump", ("ship_id",), tool_name="jump"),
    _definition("scan", ("ship_id",), tool_name="scan"),
    _definition("answer-distress-signal", ("signal_id",), tool_name="answer_distress_signal"),
    _definition("refuel", ("ship_id", "amount"), tool_name="refuel"),
    _definition(
        "assign-crew-shift",
        ("shift_id", "station"),
        tool_name="assign_crew_shift",
        patterns=("take watch {shift_id}",),
    ),
    _definition(
        "relieve-crew-shift",
        ("shift_id",),
        tool_name="relieve_crew_shift",
        patterns=("stand down from watch {shift_id}",),
    ),
    _definition("deploy-away-team", ("team_id",), tool_name="deploy_away_team"),
    _definition("boost-morale", ("amount",), tool_name="boost_morale"),
    _definition("start-mutiny", tool_name="start_mutiny"),
    _definition("command-drone", ("drone_id", "task"), tool_name="command_drone"),
    _definition("hack-ship-ai", ("ai_id",), tool_name="hack_ship_ai"),
    _definition("salvage-data", ("data_id",), tool_name="salvage_data"),
    _definition(
        "study-xenobiology",
        ("sample_id",),
        tool_name="study_xenobiology",
    ),
    _definition(
        "accept-trade-protocol",
        ("protocol_id",),
        tool_name="accept_trade_protocol",
    ),
    _definition("resolve-emergency", ("emergency_id",), tool_name="resolve_emergency"),
    _definition(
        "stabilize-reactor",
        ("reactor_id", "amount"),
        tool_name="stabilize_reactor",
    ),
    _definition(
        "adjust-gravity",
        ("gravity_id", "enabled", "strength"),
        tool_name="adjust_gravity",
    ),
    _definition("repel-boarders", ("threat_id",), tool_name="repel_boarders"),
    _definition("deliver-passenger", ("passenger_id",), tool_name="deliver_passenger"),
    _definition("survey-site", ("site_id",), tool_name="survey_site"),
    _definition(
        "mine-asteroid",
        ("site_id", "quantity"),
        tool_name="mine_asteroid",
    ),
    _definition(
        "inspect-customs",
        ("hold_id", "contraband_found"),
        tool_name="inspect_customs",
    ),
    _definition(
        "search-smuggling-compartment",
        ("compartment_id",),
        tool_name="search_smuggling_compartment",
    ),
    _definition("claim-insurance", ("policy_id",), tool_name="claim_insurance"),
    _definition("pay-mortgage", ("mortgage_id", "amount"), tool_name="pay_mortgage"),
    _definition("enter-orbit", ("ship_id", "body_id"), tool_name="enter_orbit"),
    _definition("leave-orbit", ("ship_id",), tool_name="leave_orbit"),
    _definition("land", ("ship_id",), tool_name="land"),
    _definition("launch", ("ship_id",), tool_name="launch"),
    # Nuke sim.
    _definition("scan-radiation", ("target_id",), tool_name="scan_radiation"),
    _definition(
        "seal-radiation-source", ("target_id",), tool_name="seal_radiation_source"
    ),
    _definition(
        "decontaminate",
        ("target_id", "station_id"),
        tool_name="decontaminate",
    ),
    _definition(
        "use-rad-medicine",
        ("item_id", "target_id"),
        tool_name="use_rad_medicine",
    ),
    _definition("scavenge", ("site_id",), tool_name="scavenge"),
    _definition("scrap-item", ("item_id",), tool_name="scrap_item"),
    _definition("stabilize-mutation", ("mutation_id",), tool_name="stabilize_mutation"),
    _definition(
        "mark-hotspot",
        ("source_id", "label"),
        tool_name="mark_hotspot",
    ),
    _definition("use-suppressant", ("item_id",), tool_name="use_suppressant"),
    _definition("harvest-sample", ("sample_type",), tool_name="harvest_sample"),
    _definition("study-sample", ("sample_id",), tool_name="study_sample"),
    _definition("unlock-crate", ("crate_id",), tool_name="unlock_crate"),
    _definition(
        "study-wasteland-artifact",
        ("artifact_id",),
        tool_name="study_wasteland_artifact",
    ),
    _definition(
        "claim-faction-salvage",
        ("salvage_id",),
        tool_name="claim_faction_salvage",
    ),
    _definition(
        "install-mod",
        ("item_id", "schematic_id"),
        tool_name="install_mod",
    ),
    _definition("field-repair", ("item_id", "kit_id"), tool_name="field_repair"),
    _definition("brew-chem", ("recipe_id",), tool_name="brew_chem"),
    _definition("activate-beacon", ("beacon_id",), tool_name="activate_beacon"),
    _definition("open-trader-route", ("route_id",), tool_name="open_trader_route"),
    _definition(
        "increase-raider-pressure",
        ("target_id", "amount"),
        tool_name="increase_raider_pressure",
    ),
    _definition(
        "boot-terminal",
        ("terminal_id", "access_level"),
        tool_name="boot_terminal",
    ),
    _definition("take-chem", ("chem_id",), tool_name="take_chem"),
    _definition("purify-water", ("water_id",), tool_name="purify_water"),
    _definition("drink-water", ("water_id",), tool_name="drink_water"),
    _definition(
        "identify-tech",
        ("tech_id",),
        tool_name="identify_tech",
        patterns=("identify {tech_id}",),
    ),
    _definition(
        "restore-tech",
        ("tech_id",),
        tool_name="restore_tech",
        patterns=("restore {tech_id}",),
    ),
    _definition("claim-settlement", ("settlement_id",), tool_name="claim_settlement"),
    _definition("salvage-settlement", ("settlement_id",), tool_name="salvage_settlement"),
    _definition("build-purifier", ("settlement_id",), tool_name="build_purifier"),
    _definition("power-generator", ("generator_id",), tool_name="power_generator"),
    _definition("resolve-colony-incident", ("incident_id",), tool_name="resolve_colony_incident"),
    _definition("resolve-incident", ("incident_id",), tool_name="resolve_incident"),
    # Neon sim.
    _definition(
        "enter-district",
        ("target_id",),
        tool_name="enter_district",
        patterns=("enter {target_id}", "sneak into {target_id}"),
    ),
    _definition(
        "show-credentials",
        ("target_id",),
        tool_name="show_credentials",
        patterns=("show credentials at {target_id}",),
    ),
    _definition(
        "bribe-checkpoint",
        ("target_id",),
        tool_name="bribe_checkpoint",
        patterns=("bribe the guard at {target_id}",),
    ),
    _definition(
        "sneak-through-checkpoint",
        ("target_id",),
        tool_name="sneak_through_checkpoint",
        patterns=("sneak through {target_id}",),
    ),
    _definition("claim-safehouse", ("target_id",), tool_name="claim_safehouse"),
    _definition(
        "case-location",
        ("target_id",),
        tool_name="case_location",
        patterns=("case {target_id}", "scope out {target_id}"),
    ),
    _definition("inspect-device", ("target_id",), tool_name="inspect_device"),
    _definition(
        "disable-camera",
        ("target_id",),
        tool_name="disable_camera",
        patterns=("disable camera {target_id}",),
    ),
    _definition(
        "loop-camera",
        ("target_id",),
        tool_name="loop_camera",
        patterns=("loop camera {target_id}", "loop the feed on {target_id}"),
    ),
    _definition(
        "jam-sensor",
        ("target_id",),
        tool_name="jam_sensor",
        patterns=("jam sensor {target_id}",),
    ),
    _definition(
        "deploy-drone",
        ("target_id",),
        tool_name="deploy_drone",
        patterns=("deploy drone {target_id}",),
    ),
    _definition(
        "wipe-evidence",
        ("target_id",),
        tool_name="wipe_evidence",
        patterns=("wipe evidence {target_id}", "erase the footage {target_id}"),
    ),
    _definition("scan-network", ("target_id",), tool_name="scan_network"),
    _definition("trace-network", ("target_id",), tool_name="trace_network"),
    _definition(
        "run-exploit",
        ("target_id",),
        tool_name="run_exploit",
        patterns=("run exploit on {target_id}", "hack {target_id}"),
    ),
    _definition("use-credential", ("target_id",), tool_name="use_credential"),
    _definition("access-terminal", ("target_id",), tool_name="access_terminal"),
    _definition(
        "escalate-privileges",
        ("target_id",),
        tool_name="escalate_privileges",
        patterns=("escalate privileges on {target_id}",),
    ),
    _definition("install-backdoor", ("target_id",), tool_name="install_backdoor"),
    _definition(
        "exfiltrate-data",
        ("target_id",),
        tool_name="exfiltrate_data",
        patterns=("exfiltrate data from {target_id}", "steal data from {target_id}"),
    ),
    _definition(
        "sabotage-system",
        ("target_id",),
        tool_name="sabotage_system",
        patterns=("sabotage {target_id}",),
    ),
    _definition(
        "unlock-door",
        ("target_id",),
        tool_name="unlock_door",
        patterns=("unlock door {target_id}",),
    ),
    _definition("evade-trace", (), tool_name="evade_trace", patterns=("evade the trace",)),
    _definition("spoof-identity", (), tool_name="spoof_identity", patterns=("spoof your id",)),
    _definition(
        "buy-contraband",
        ("target_id",),
        tool_name="buy_contraband",
        patterns=("buy contraband from {target_id}",),
    ),
    _definition(
        "sell-data",
        ("broker_id", "data_id"),
        tool_name="sell_data",
        patterns=("sell {data_id} to {broker_id}",),
    ),
    _definition(
        "call-favor",
        ("target_id",),
        tool_name="call_favor",
        patterns=("call in a favor from {target_id}",),
    ),
    _definition("pay-debt", (), tool_name="pay_debt", patterns=("pay off your debt",)),
    _definition("hide-from-law", (), tool_name="hide_from_law", patterns=("lay low",)),
    _definition("clear-warrant", (), tool_name="clear_warrant", patterns=("clear your warrant",)),
    _definition(
        "post-bounty",
        ("target_id", "amount"),
        tool_name="post_bounty",
        patterns=("post a bounty on {target_id}",),
    ),
    _definition(
        "turn-informant",
        ("target_id",),
        tool_name="turn_informant",
        patterns=("turn {target_id} into an informant",),
    ),
    _definition(
        "install-implant",
        ("implant_id", "clinic_id"),
        tool_name="install_implant",
        patterns=("install {implant_id} at {clinic_id}",),
    ),
    _definition(
        "remove-implant",
        ("implant_id",),
        tool_name="remove_implant",
        patterns=("remove implant {implant_id}",),
    ),
    _definition(
        "service-implant",
        ("implant_id", "clinic_id"),
        tool_name="service_implant",
        patterns=("service {implant_id} at {clinic_id}",),
    ),
    _definition(
        "overclock-implant",
        ("implant_id",),
        tool_name="overclock_implant",
        patterns=("overclock {implant_id}",),
    ),
    _definition(
        "disable-implant",
        ("implant_id",),
        tool_name="disable_implant",
        patterns=("disable implant {implant_id}",),
    ),
    _definition(
        "license-implant",
        ("implant_id",),
        tool_name="license_implant",
        patterns=("license {implant_id}",),
    ),
    _definition(
        "scan-implant",
        ("target_id",),
        tool_name="scan_implant",
        patterns=("scan {target_id} for implants",),
    ),
    _definition(
        "exploit-implant",
        ("target_id",),
        tool_name="exploit_implant",
        patterns=("exploit the implants of {target_id}",),
    ),
)


def action_definitions(
    extra: tuple[ActionDefinition, ...] | list[ActionDefinition] = (),
) -> tuple[ActionDefinition, ...]:
    """Return core action definitions plus caller/plugin overrides."""

    overridden = {definition.command_type for definition in extra}
    definitions = [
        definition
        for definition in DEFAULT_ACTION_DEFINITIONS
        if definition.command_type not in overridden
    ]
    definitions.extend(extra)
    return tuple(definitions)


def action_definition_for_command_type(command_type: str) -> ActionDefinition | None:
    for definition in DEFAULT_ACTION_DEFINITIONS:
        if definition.command_type == command_type:
            return definition
    return None


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
    "ActionArgument",
    "ActionDefinition",
    "ActionExample",
    "ActionPattern",
    "ArgumentKind",
    "DEFAULT_ACTION_DEFINITIONS",
    "REFERENCE_ARG_KEYS",
    "action_definition_for_command_type",
    "action_definitions",
    "definition_by_command_type",
    "definitions_by_tool_name",
    "inferred_action_definition",
    "reference_arg_keys",
]
