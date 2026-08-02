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
        description=(
            "Strike another character in your room, dealing damage and wounding a body part. "
            "Hold a weapon and pass its id to hit harder; set lethal to allow a killing blow."
        ),
    ),
    define_action(
        "spar",
        ("target_id", "weapon_id", "body_part", "stamina_cost", "durability_cost"),
        tool_name="spar",
        description=(
            "Trade blows with a willing partner for practice, dealing damage but never "
            "dropping them below barely alive. Use this instead of attack to train without risk."
        ),
    ),
    define_action(
        "defend",
        ("stamina_cost", "reduction"),
        tool_name="defend",
        description=(
            "Take a defensive stance that reduces the next incoming hit against you. "
            "The stance is spent as soon as someone strikes you."
        ),
    ),
    define_action(
        "challenge",
        ("target_id", "terms"),
        tool_name="challenge",
        description=(
            "Publicly challenge another character in your room to a fight, announcing your "
            "terms. This calls them out but does no damage on its own."
        ),
    ),
    define_action(
        "fortify",
        ("target_id", "strength"),
        tool_name="fortify",
        cost=EXTENDED_ACTION_COST,
        description=(
            "Reinforce a reachable structure or your current location, raising its "
            "fortification rating and durability against raids. Defaults to the room you are in."
        ),
    ),
    define_action(
        "claim-base",
        ("base_id", "clan"),
        tool_name="claim_base",
        cost=MAJOR_ACTION_COST,
        description=(
            "Claim an unclaimed base for yourself or your clan, marking it as your "
            "stronghold. Defaults to your current location; a base already claimed cannot be taken."
        ),
    ),
    define_action(
        "place-trap",
        ("damage",),
        tool_name="place_trap",
        description=(
            "Set an armed trap in your current room that lies in wait for whoever triggers it. "
            "Choose how much damage it deals when sprung."
        ),
    ),
    define_action(
        "disarm-trap",
        ("trap_id",),
        tool_name="disarm_trap",
        description=(
            "Safely disarm a reachable trap so it can no longer hurt anyone. "
            "Inspect the room to find armed traps by id."
        ),
    ),
    define_action(
        "raid",
        ("target_id", "intensity"),
        tool_name="raid",
        cost=MAJOR_ACTION_COST,
        description=(
            "Assault a reachable target, wearing down its fortification durability by your "
            "intensity minus its defenses. Stronger fortifications blunt the damage you do."
        ),
    ),
    define_action(
        "bridge-survival-gap",
        ("gap_id",),
        tool_name="bridge_survival_gap",
        description=(
            "Bridge a reachable survival gap such as water or a chasm so it can be crossed. "
            "A gap that is already bridged cannot be bridged again."
        ),
    ),
    define_action(
        "decay-building",
        ("building_id", "amount"),
        tool_name="decay_building",
        description=(
            "Wear down a reachable building, lowering its integrity by the amount you choose. "
            "A demolished building cannot be decayed further."
        ),
    ),
    define_action(
        "upgrade-building",
        ("building_id", "integrity"),
        tool_name="upgrade_building",
        cost=EXTENDED_ACTION_COST,
        description=(
            "Improve a reachable building, raising its level and repairing it to a higher "
            "maximum integrity. A demolished building must be rebuilt before it can be upgraded."
        ),
    ),
    define_action(
        "demolish-building",
        ("building_id",),
        tool_name="demolish_building",
        cost=EXTENDED_ACTION_COST,
        description=(
            "Tear down a reachable building, dropping its integrity to zero and marking it "
            "demolished. A building already demolished cannot be torn down again."
        ),
    ),
    define_action(
        "prepare-siege",
        ("base_id", "score"),
        tool_name="prepare_siege",
        cost=MAJOR_ACTION_COST,
        description=(
            "Build up siege readiness against a reachable base, adding to its accumulated "
            "siege score. Defaults to your current location; repeat to raise the score higher."
        ),
    ),
    define_action(
        "start-purge-wave",
        ("base_id", "intensity"),
        tool_name="start_purge_wave",
        cost=EPIC_ACTION_COST,
        description=(
            "Deprecated compatibility alias that asks the Storyteller to spend its raid "
            "budget on a warning-first phased raid at a reachable base."
        ),
    ),
    define_action(
        "perform-ritual",
        ("shrine_id", "ritual_id"),
        tool_name="perform_ritual",
        cost=EXTENDED_ACTION_COST,
        description=(
            "Perform a reachable ritual at a reachable shrine, which may grant a blessing or "
            "lay a curse and can cost corruption. You cannot perform the same ritual twice."
        ),
    ),
    define_action(
        "explore-danger-zone",
        ("zone_id",),
        tool_name="explore_danger_zone",
        description=(
            "Venture into a reachable danger zone such as a ruin, recording that you have "
            "explored it. Inspect nearby to learn a zone's danger rating before entering."
        ),
    ),
    define_action(
        "defeat-boss",
        ("boss_id",),
        tool_name="defeat_boss",
        cost=EPIC_ACTION_COST,
        description=(
            "Defeat a reachable world boss, marking it beaten and crediting you with the kill. "
            "A boss that is already defeated cannot be fought again."
        ),
    ),
    define_action(
        "unlock-treasure",
        ("treasure_id", "key_id"),
        tool_name="unlock_treasure",
        description=(
            "Unlock a reachable treasure so it can be claimed. If the treasure names a key, "
            "you must be carrying the matching one and pass its id."
        ),
    ),
    define_action(
        "claim-treasure",
        ("treasure_id",),
        tool_name="claim_treasure",
        description=(
            "Claim an unlocked, reachable treasure as your own. Unlock it first, and note that "
            "a treasure already claimed cannot be taken again."
        ),
    ),
    define_action(
        "climb",
        ("gate_id",),
        tool_name="climb",
        description=(
            "Climb past a reachable climbing gate to reach what lies beyond. "
            "Your climbing skill must meet the gate's required level."
        ),
    ),
    define_action(
        "repair-item",
        ("item_id", "amount"),
        tool_name="repair_item",
        description=(
            "Restore durability to a reachable item, mending a worn or broken tool or weapon. "
            "Repair up to its maximum durability."
        ),
    ),
    define_action(
        "poison-character",
        ("target_id", "severity", "damage_per_hour"),
        tool_name="poison_character",
        description=(
            "Poison another character in your room so they take damage over time. "
            "Set the severity and how much health it drains each hour."
        ),
    ),
    define_action(
        "treat-poison",
        ("target_id",),
        tool_name="treat_poison",
        description=(
            "Cure poison from a poisoned character in your room, or from yourself if you "
            "name no target. The target must actually be poisoned."
        ),
    ),
    define_action(
        "gain-corruption",
        ("amount",),
        tool_name="gain_corruption",
        description=(
            "Take on corruption, increasing the taint you carry by the amount you choose. "
            "Corruption builds up until it is cleansed."
        ),
    ),
    define_action(
        "cleanse-corruption",
        tool_name="cleanse_corruption",
        description=(
            "Purge all corruption from yourself, clearing the taint you carry. "
            "Only works if you are currently corrupted."
        ),
    ),
    define_action(
        "pickpocket",
        ("target_id", "item_id"),
        tool_name="pickpocket",
        patterns=("pickpocket {target_id:word} {item_id}",),
        description=(
            "Quietly lift a portable item from another character in your room into your own "
            "inventory. The item must be one they are carrying."
        ),
    ),
    define_action(
        "subdue",
        ("target_id", "task"),
        tool_name="subdue",
        description=(
            "Bind a defeated character in your room as a thrall set to a task such as labor. "
            "The target must be downed and not already serving a master."
        ),
    ),
    define_action(
        "recruit-follower",
        ("target_id",),
        tool_name="recruit_follower",
        description=(
            "Recruit an able character in your room as a willing follower who takes your orders. "
            "They must be conscious and not already bound to another master."
        ),
    ),
    define_action(
        "release-thrall",
        ("target_id",),
        tool_name="release_thrall",
        description=(
            "Free a thrall or follower you command, releasing them from your service. "
            "You can only release a subordinate whose master is you."
        ),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
