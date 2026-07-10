"""Action metadata owned by bunnyland.nukesim."""

from ...core.actions import (
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action("scan-radiation", ("target_id",), tool_name="scan_radiation"),
    define_action("seal-radiation-source", ("target_id",), tool_name="seal_radiation_source"),
    define_action(
        "decontaminate",
        ("target_id", "station_id"),
        tool_name="decontaminate",
    ),
    define_action("scavenge", ("site_id",), tool_name="scavenge"),
    define_action("scrap-item", ("item_id",), tool_name="scrap_item"),
    define_action("stabilize-mutation", ("mutation_id",), tool_name="stabilize_mutation"),
    define_action(
        "mark-hotspot",
        ("source_id", "label"),
        tool_name="mark_hotspot",
    ),
    define_action("use-suppressant", ("item_id",), tool_name="use_suppressant"),
    define_action("study-sample", ("sample_id",), tool_name="study_sample"),
    define_action(
        "study-wasteland-artifact",
        ("artifact_id",),
        tool_name="study_wasteland_artifact",
    ),
    define_action(
        "claim-faction-salvage",
        ("salvage_id",),
        tool_name="claim_faction_salvage",
    ),
    define_action(
        "install-mod",
        ("item_id", "schematic_id"),
        tool_name="install_mod",
    ),
    define_action("field-repair", ("item_id", "kit_id"), tool_name="field_repair"),
    define_action("brew-chem", ("recipe_id",), tool_name="brew_chem"),
    define_action("activate-beacon", ("beacon_id",), tool_name="activate_beacon"),
    define_action("open-trader-route", ("route_id",), tool_name="open_trader_route"),
    define_action(
        "increase-raider-pressure",
        ("target_id", "amount"),
        tool_name="increase_raider_pressure",
    ),
    define_action(
        "boot-terminal",
        ("terminal_id", "access_level"),
        tool_name="boot_terminal",
    ),
    define_action("take-chem", ("chem_id",), tool_name="take_chem"),
    define_action("purify-water", ("water_id",), tool_name="purify_water"),
    define_action(
        "restore-tech",
        ("tech_id",),
        tool_name="restore_tech",
        patterns=("restore {tech_id}",),
    ),
    define_action("claim-settlement", ("settlement_id",), tool_name="claim_settlement"),
    define_action("salvage-settlement", ("settlement_id",), tool_name="salvage_settlement"),
    define_action("build-purifier", ("settlement_id",), tool_name="build_purifier"),
    define_action("power-generator", ("generator_id",), tool_name="power_generator"),
)

__all__ = ["ACTION_DEFINITIONS"]
