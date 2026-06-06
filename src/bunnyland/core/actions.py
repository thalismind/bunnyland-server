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
        "bank_id",
        "bill_id",
        "body_id",
        "bulkhead_id",
        "business_id",
        "child_id",
        "co_parent_id",
        "crime_id",
        "customer_id",
        "destination_id",
        "door_id",
        "dungeon_id",
        "egg_id",
        "exit_id",
        "faction_id",
        "fertilizer_id",
        "fossil_id",
        "grid_id",
        "incident_id",
        "institution_id",
        "item_id",
        "job_id",
        "loan_id",
        "location_id",
        "module_id",
        "node_id",
        "objective_id",
        "partner_id",
        "parent_id",
        "quest_id",
        "rival_id",
        "room_id",
        "rumor_id",
        "seed_id",
        "seller_id",
        "service_id",
        "sample_id",
        "ship_id",
        "signal_id",
        "site_id",
        "soil_id",
        "station_id",
        "student_id",
        "system_id",
        "spell_id",
        "target_container_id",
        "target_id",
        "template_id",
        "tenant_id",
        "tool_id",
        "weapon_id",
        "worker_id",
        "source_id",
    }
)


def _argument_for_key(key: str, *, required: bool = False) -> ActionArgument:
    title = key.removesuffix("_ids").removesuffix("_id").replace("_", " ").title()
    kind: ArgumentKind = "entity" if key in REFERENCE_ARG_KEYS else "string"
    if key in {
        "amount",
        "damage_per_hour",
        "default_price",
        "due_epoch",
        "due_in_seconds",
        "durability_cost",
        "duration_seconds",
        "hourly_pay",
        "intensity",
        "interval_seconds",
        "limit",
        "next_due_epoch",
        "next_shift_epoch",
        "performance_gain",
        "price",
        "quantity",
        "reduction",
        "reputation_delta",
        "severity",
        "shift_duration_seconds",
        "shift_interval_seconds",
        "stamina_cost",
        "strength",
        "xp",
    }:
        kind = "number"
    if key in {"audible", "lethal"}:
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
    patterns: tuple[str, ...] = (),
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
        natural_patterns=tuple(ActionPattern(pattern) for pattern in patterns),
        examples=tuple(ActionExample(example, natural=True) for example in examples),
    )


DEFAULT_ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    # Core verbs.
    _definition("move", ("direction", "exit_id"), tool_name="move", examples=("go north",)),
    _definition("take", ("item_id",), tool_name="take", examples=("take brass key",)),
    _definition("put", ("item_id", "target_container_id"), tool_name="put"),
    _definition("put", ("item_id",), tool_name="drop", examples=("drop brass key",)),
    _definition("use", ("target_id", "tool_id"), tool_name="use"),
    _definition("write", ("target_id", "text"), tool_name="write", cost=_SPEECH),
    _definition("sleep", tool_name="sleep", cost=_FREE),
    _definition("wake", tool_name="wake", cost=_FREE),
    _definition("wait", tool_name="wait", cost=_FREE, examples=("wait",)),
    _definition("move-sprite", ("x", "y"), tool_name="move_sprite", cost=_FREE),
    _definition("say", ("text", "intent", "approach"), tool_name="say", cost=_SPEECH),
    _definition(
        "tell",
        ("target_id", "text", "intent", "approach", "audible"),
        tool_name="tell",
        cost=_SPEECH,
    ),
    # Memory.
    _definition(
        "take-note",
        ("text", "tags", "scope", "collection"),
        tool_name="take_note",
        lane=Lane.FOCUS,
        cost=_FOCUS,
    ),
    _definition(
        "remember",
        ("query", "mode", "limit", "scope", "collection"),
        tool_name="remember",
        lane=Lane.FOCUS,
        cost=_FOCUS,
    ),
    _definition(
        "forget",
        ("note_id", "scope", "collection"),
        tool_name="forget",
        lane=Lane.FOCUS,
        cost=_FOCUS,
    ),
    _definition(
        "reflect",
        ("text", "query", "mode", "limit"),
        tool_name="reflect",
        lane=Lane.FOCUS,
        cost=_FOCUS,
    ),
    # Environment and garden.
    _definition("ignite", ("target_id", "intensity"), tool_name="ignite"),
    _definition("extinguish", ("target_id",), tool_name="extinguish"),
    _definition("till", ("soil_id",), tool_name="till"),
    _definition("plant", ("soil_id", "seed_id"), tool_name="plant"),
    _definition("water-crop", ("soil_id",), tool_name="water_crop"),
    _definition("fertilize", ("soil_id", "fertilizer_id"), tool_name="fertilize"),
    _definition("harvest-crop", ("soil_id",), tool_name="harvest_crop"),
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
    # Life sim.
    _definition("eat", ("item_id",), tool_name="eat"),
    _definition("drink", ("source_id",), tool_name="drink"),
    _definition("choose-aspiration", ("name", "milestones"), tool_name="choose_aspiration"),
    _definition("complete-milestone", ("milestone", "reward_name"), tool_name="complete_milestone"),
    _definition("practice-skill", ("skill", "xp"), tool_name="practice_skill"),
    _definition("study-skill", ("skill", "xp"), tool_name="study_skill"),
    _definition("mentor-skill", ("student_id", "skill", "xp"), tool_name="mentor_skill"),
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
        "charge-rent", ("tenant_id", "amount", "reason", "due_epoch"), tool_name="charge_rent"
    ),
    _definition("pay-bill", ("bill_id",), tool_name="pay_bill"),
    _definition("open-business", ("name", "default_price"), tool_name="open_business"),
    _definition("buy-item", ("seller_id", "item_id", "business_id", "price"), tool_name="buy_item"),
    _definition(
        "sell-item", ("item_id", "customer_id", "business_id", "price"), tool_name="sell_item"
    ),
    _definition("promote-business", ("business_id",), tool_name="promote_business"),
    _definition("join-household", ("household_id", "name"), tool_name="join_household"),
    _definition("claim-home", ("room_id",), tool_name="claim_home"),
    _definition("claim-room", ("room_id",), tool_name="claim_room"),
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
    _definition("adopt-child", ("child_id",), tool_name="adopt_child"),
    # Colony, dragon, and barbarian sims.
    _definition("reserve", ("target_id",), tool_name="reserve"),
    _definition("release-reservation", ("target_id",), tool_name="release_reservation"),
    _definition("gather-resource", ("node_id", "quantity"), tool_name="gather_resource"),
    _definition("craft", ("recipe_id",), tool_name="craft"),
    _definition("assign-job", ("job_id",), tool_name="assign_job"),
    _definition("complete-job", ("job_id",), tool_name="complete_job"),
    _definition("claim-ownership", ("target_id",), tool_name="claim_ownership"),
    _definition("release-ownership", ("target_id",), tool_name="release_ownership"),
    _definition("discover-location", ("location_id",), tool_name="discover_location"),
    _definition("accept-quest", ("quest_id",), tool_name="accept_quest"),
    _definition("complete-objective", ("objective_id",), tool_name="complete_objective"),
    _definition("join-faction", ("faction_id", "rank"), tool_name="join_faction"),
    _definition("leave-faction", ("faction_id",), tool_name="leave_faction"),
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
    _definition("raid", ("target_id", "intensity"), tool_name="raid"),
    _definition("repair-item", ("item_id", "amount"), tool_name="repair_item"),
    _definition(
        "poison-character",
        ("target_id", "severity", "damage_per_hour"),
        tool_name="poison_character",
    ),
    _definition("treat-poison", ("target_id",), tool_name="treat_poison"),
    _definition("gain-corruption", ("amount",), tool_name="gain_corruption"),
    _definition("cleanse-corruption", tool_name="cleanse_corruption"),
    _definition("pickpocket", ("target_id", "item_id"), tool_name="pickpocket"),
    # Dagger sim.
    _definition("expand-site", ("site_id", "generator_id", "trigger"), tool_name="expand_site"),
    _definition("ask-rumor", ("rumor_id",), tool_name="ask_rumor"),
    _definition("investigate-rumor", ("rumor_id",), tool_name="investigate_rumor"),
    _definition("plan-travel", ("destination_id",), tool_name="plan_travel"),
    _definition("join-institution", ("institution_id", "rank"), tool_name="join_institution"),
    _definition("use-institution-service", ("service_id",), tool_name="use_institution_service"),
    _definition("ask-for-work", ("template_id",), tool_name="ask_for_work"),
    _definition("accept-generated-quest", ("quest_id",), tool_name="accept_generated_quest"),
    _definition("complete-generated-quest", ("quest_id",), tool_name="complete_generated_quest"),
    _definition("open-bank-account", ("bank_id",), tool_name="open_bank_account"),
    _definition("deposit", ("bank_id", "amount"), tool_name="deposit"),
    _definition("withdraw", ("bank_id", "amount"), tool_name="withdraw"),
    _definition("take-loan", ("bank_id", "amount", "duration_seconds"), tool_name="take_loan"),
    _definition("repay-loan", ("loan_id", "amount"), tool_name="repay_loan"),
    _definition("commit-crime", ("crime_type",), tool_name="commit_crime"),
    _definition("pay-fine", ("crime_id",), tool_name="pay_fine"),
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
        patterns=("cast {spell_id} on {target_id}", "cast {spell_id} at {target_id}"),
        examples=("cast moss charm on Juniper",),
    ),
    _definition(
        "enchant-item",
        ("item_id", "spell_id"),
        tool_name="enchant_item",
        patterns=("enchant {item_id} with {spell_id}",),
        examples=("enchant moss charm with Mend Moss",),
    ),
    _definition("attempt-pacify", ("target_id", "language"), tool_name="attempt_pacify"),
    _definition("contract-affliction", ("affliction_type",), tool_name="contract_affliction"),
    _definition("transform", ("form_name",), tool_name="transform"),
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
    _definition("dock", ("ship_id", "station_id", "port"), tool_name="dock"),
    _definition("undock", ("ship_id", "station_id"), tool_name="undock"),
    _definition("evacuate-module", ("module_id", "destination_id"), tool_name="evacuate_module"),
    _definition("plot-course", ("ship_id", "destination_id"), tool_name="plot_course"),
    _definition("jump", ("ship_id",), tool_name="jump"),
    _definition("scan", ("ship_id",), tool_name="scan"),
    _definition("answer-distress-signal", ("signal_id",), tool_name="answer_distress_signal"),
    _definition("refuel", ("ship_id", "amount"), tool_name="refuel"),
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
    _definition("resolve-incident", ("incident_id",), tool_name="resolve_incident"),
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
