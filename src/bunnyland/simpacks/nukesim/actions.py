"""Action metadata owned by bunnyland.nukesim."""

from ...core.actions import (
    EXTENDED_ACTION_COST,
    MAJOR_ACTION_COST,
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "scan-radiation",
        ("target_id",),
        tool_name="scan_radiation",
        description=(
            "Read a radiation source to reveal its type, output in rads per hour, and "
            "whether it is sealed. Scan before deciding to seal, mark, or avoid a hotspot."
        ),
    ),
    define_action(
        "seal-radiation-source",
        ("target_id",),
        tool_name="seal_radiation_source",
        description=(
            "Seal a radiation source so it stops irradiating everyone nearby. Only works on "
            "an unsealed source; scan first if you are unsure what you are facing."
        ),
    ),
    define_action(
        "decontaminate",
        ("target_id", "station_id"),
        tool_name="decontaminate",
        description=(
            "Run yourself or a reachable ally through a decontamination station to cut "
            "radiation dose, sickness, and mutation pressure. Requires a nearby station with "
            "uses remaining."
        ),
    ),
    define_action(
        "scavenge",
        ("site_id",),
        tool_name="scavenge",
        description=(
            "Search a scavenge site to pull resource loot into your inventory, spending one "
            "of its charges. Hazardous sites may dose you with radiation, so scan the area first."
        ),
    ),
    define_action(
        "scrap-item",
        ("item_id",),
        tool_name="scrap_item",
        description=(
            "Break down a piece of junk into its component resource stacks. Contaminated junk "
            "irradiates you as you work it, so handle it with radiation protection."
        ),
    ),
    define_action(
        "stabilize-mutation",
        ("mutation_id",),
        tool_name="stabilize_mutation",
        description=(
            "Lock in the mutation you have already manifested so it becomes stable rather "
            "than unstable. You must currently carry an unstable mutation to stabilize it."
        ),
    ),
    define_action(
        "mark-hotspot",
        ("source_id", "label"),
        tool_name="mark_hotspot",
        description=(
            "Drop a labelled marker into your inventory that flags a radiation source for "
            "later reference. Useful for tagging hotspots you want to seal or steer around."
        ),
    ),
    define_action(
        "use-suppressant",
        ("item_id",),
        tool_name="use_suppressant",
        description=(
            "Consume a radiation suppressant to lower your accumulated mutation pressure and "
            "hold off a mutation. Each suppressant has limited uses before it is spent."
        ),
    ),
    define_action(
        "study-sample",
        ("sample_id",),
        tool_name="study_sample",
        description=(
            "Study a harvested sample to record that you have analyzed it. Harvest a sample "
            "first, then study it to log your findings."
        ),
    ),
    define_action(
        "study-wasteland-artifact",
        ("artifact_id",),
        tool_name="study_wasteland_artifact",
        description=(
            "Examine a wasteland artifact closely to mark it studied and learn what it is. "
            "Reach for this when you find an unstudied relic in the ruins."
        ),
    ),
    define_action(
        "claim-faction-salvage",
        ("salvage_id",),
        tool_name="claim_faction_salvage",
        description=(
            "Stake your claim on a piece of faction salvage so it is registered to you. "
            "Only unclaimed salvage can be claimed, so move quickly when you spot it."
        ),
    ),
    define_action(
        "install-mod",
        ("item_id", "schematic_id"),
        tool_name="install_mod",
        description=(
            "Fit a schematic's modification onto a reachable item, upgrading it in place. "
            "You need both the target item and a matching schematic within reach."
        ),
    ),
    define_action(
        "field-repair",
        ("item_id", "kit_id"),
        tool_name="field_repair",
        description=(
            "Patch up a damaged item with a repair kit, restoring durability and clearing "
            "the broken state. The item must have durability and the kit must be within reach."
        ),
    ),
    define_action(
        "brew-chem",
        ("recipe_id",),
        tool_name="brew_chem",
        description=(
            "Cook up a chem from a recipe, spending the required resources from your "
            "inventory and adding the finished chem to it. Gather the ingredients first."
        ),
    ),
    define_action(
        "activate-beacon",
        ("beacon_id",),
        tool_name="activate_beacon",
        description=(
            "Switch on a beacon so it broadcasts its message to the surrounding area. "
            "Find an inactive beacon nearby to bring it online."
        ),
    ),
    define_action(
        "open-trader-route",
        ("route_id",),
        tool_name="open_trader_route",
        description=(
            "Open a trader route so caravans can run to its destination. The route must be "
            "reachable and currently closed."
        ),
    ),
    define_action(
        "increase-raider-pressure",
        ("target_id", "amount"),
        tool_name="increase_raider_pressure",
        description=(
            "Ratchet up raider pressure on a target location by a chosen amount, drawing "
            "more raiders toward it. Use it to escalate threat where you want a confrontation."
        ),
    ),
    define_action(
        "boot-terminal",
        ("terminal_id", "access_level"),
        tool_name="boot_terminal",
        description=(
            "Power up a terminal and bring it online at a chosen access level. Boot a terminal "
            "before you can work with the systems it controls."
        ),
    ),
    define_action(
        "take-chem",
        ("chem_id",),
        tool_name="take_chem",
        description=(
            "Dose yourself with a chem to relieve radiation dose and sickness at the cost of "
            "building addiction to it. Withdrawal fades the addiction over time if you abstain."
        ),
    ),
    define_action(
        "purify-water",
        ("water_id",),
        tool_name="purify_water",
        description=(
            "Purify a contaminated water source so drinking from it no longer doses you with "
            "radiation. Only unpurified sources can be cleaned."
        ),
    ),
    define_action(
        "restore-tech",
        ("tech_id",),
        tool_name="restore_tech",
        cost=EXTENDED_ACTION_COST,
        patterns=("restore {tech_id}",),
        description=(
            "Rebuild an identified piece of old-world tech into working order by spending "
            "scrap from your inventory. Identify the device first and carry enough scrap."
        ),
    ),
    define_action(
        "salvage-settlement",
        ("settlement_id",),
        tool_name="salvage_settlement",
        cost=MAJOR_ACTION_COST,
        description=(
            "Strip a settlement you have claimed for its resource outputs, wearing down its "
            "durability in the process. Claim the settlement before you can salvage it."
        ),
    ),
    define_action(
        "power-generator",
        ("generator_id",),
        tool_name="power_generator",
        description=(
            "Bring a generator online by feeding it fuel from your inventory. The generator "
            "must be reachable, unpowered, and you must carry enough fuel."
        ),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
