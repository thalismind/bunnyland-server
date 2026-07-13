"""Action metadata owned by bunnyland.barbariansim."""

from ...core.actions import (
    EPIC_ACTION_COST,
    EXTENDED_ACTION_COST,
    MAJOR_ACTION_COST,
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "attack",
        ("target_id", "weapon_id", "lethal", "body_part", "stamina_cost", "durability_cost"),
        tool_name="attack",
    ),
    define_action(
        "spar",
        ("target_id", "weapon_id", "body_part", "stamina_cost", "durability_cost"),
        tool_name="spar",
    ),
    define_action("defend", ("stamina_cost", "reduction"), tool_name="defend"),
    define_action("challenge", ("target_id", "terms"), tool_name="challenge"),
    define_action(
        "fortify", ("target_id", "strength"), tool_name="fortify", cost=EXTENDED_ACTION_COST
    ),
    define_action(
        "claim-base", ("base_id", "clan"), tool_name="claim_base", cost=MAJOR_ACTION_COST
    ),
    define_action("place-trap", ("damage",), tool_name="place_trap"),
    define_action("disarm-trap", ("trap_id",), tool_name="disarm_trap"),
    define_action("raid", ("target_id", "intensity"), tool_name="raid", cost=MAJOR_ACTION_COST),
    define_action("bridge-survival-gap", ("gap_id",), tool_name="bridge_survival_gap"),
    define_action("decay-building", ("building_id", "amount"), tool_name="decay_building"),
    define_action(
        "upgrade-building",
        ("building_id", "integrity"),
        tool_name="upgrade_building",
        cost=EXTENDED_ACTION_COST,
    ),
    define_action(
        "demolish-building",
        ("building_id",),
        tool_name="demolish_building",
        cost=EXTENDED_ACTION_COST,
    ),
    define_action(
        "prepare-siege", ("base_id", "score"), tool_name="prepare_siege", cost=MAJOR_ACTION_COST
    ),
    define_action(
        "start-purge-wave",
        ("base_id", "intensity"),
        tool_name="start_purge_wave",
        cost=EPIC_ACTION_COST,
    ),
    define_action(
        "perform-ritual",
        ("shrine_id", "ritual_id"),
        tool_name="perform_ritual",
        cost=EXTENDED_ACTION_COST,
    ),
    define_action("explore-danger-zone", ("zone_id",), tool_name="explore_danger_zone"),
    define_action("defeat-boss", ("boss_id",), tool_name="defeat_boss", cost=EPIC_ACTION_COST),
    define_action(
        "unlock-treasure",
        ("treasure_id", "key_id"),
        tool_name="unlock_treasure",
    ),
    define_action("claim-treasure", ("treasure_id",), tool_name="claim_treasure"),
    define_action("climb", ("gate_id",), tool_name="climb"),
    define_action("repair-item", ("item_id", "amount"), tool_name="repair_item"),
    define_action(
        "poison-character",
        ("target_id", "severity", "damage_per_hour"),
        tool_name="poison_character",
    ),
    define_action("treat-poison", ("target_id",), tool_name="treat_poison"),
    define_action("gain-corruption", ("amount",), tool_name="gain_corruption"),
    define_action("cleanse-corruption", tool_name="cleanse_corruption"),
    define_action(
        "pickpocket",
        ("target_id", "item_id"),
        tool_name="pickpocket",
        patterns=("pickpocket {target_id:word} {item_id}",),
    ),
    define_action("subdue", ("target_id", "task"), tool_name="subdue"),
    define_action("recruit-follower", ("target_id",), tool_name="recruit_follower"),
    define_action("release-thrall", ("target_id",), tool_name="release_thrall"),
)

__all__ = ["ACTION_DEFINITIONS"]
