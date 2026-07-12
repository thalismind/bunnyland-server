"""Action metadata owned by bunnyland.dinosim."""

from ...core.actions import (
    EXTENDED_ACTION_COST,
    MAJOR_ACTION_COST,
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "extract-ancient-sample",
        ("fossil_id",),
        tool_name="extract_ancient_sample",
    ),
    define_action(
        "prepare-clone", ("sample_id",), tool_name="prepare_clone", cost=EXTENDED_ACTION_COST
    ),
    define_action("lay-egg", ("parent_id",), tool_name="lay_egg"),
    define_action("fertilize-egg", ("egg_id", "parent_id"), tool_name="fertilize_egg"),
    define_action(
        "incubate-egg",
        ("egg_id", "duration_seconds"),
        tool_name="incubate_egg",
    ),
    define_action("hatch-egg", ("egg_id",), tool_name="hatch_egg"),
    define_action("survey-fossil", ("fossil_id",), tool_name="survey_fossil"),
    define_action(
        "excavate-fossil",
        ("fossil_id", "progress"),
        tool_name="excavate_fossil",
    ),
    define_action("clean-fossil", ("fossil_id",), tool_name="clean_fossil"),
    define_action("stabilize-fossil", ("fossil_id",), tool_name="stabilize_fossil"),
    define_action(
        "lab-incubate-egg",
        ("egg_id", "lab_id"),
        tool_name="lab_incubate_egg",
    ),
    define_action(
        "imprint-creature",
        ("creature_id", "bond"),
        tool_name="imprint_creature",
    ),
    define_action(
        "care-for-juvenile",
        ("creature_id", "care"),
        tool_name="care_for_juvenile",
    ),
    define_action(
        "study-water-creature",
        ("creature_id",),
        tool_name="study_water_creature",
    ),
    define_action(
        "brood-egg",
        ("egg_id", "warmth"),
        tool_name="brood_egg",
    ),
    define_action(
        "set-incubation-temperature",
        ("egg_id", "temperature"),
        tool_name="set_incubation_temperature",
    ),
    define_action(
        "trigger-containment-panic",
        ("enclosure_id", "severity"),
        tool_name="trigger_containment_panic",
    ),
    define_action(
        "track-creature",
        ("creature_id",),
        tool_name="track_creature",
        patterns=("track {creature_id}",),
    ),
    define_action("mark-territory", ("territory_id",), tool_name="mark_territory"),
    define_action("track-herd", ("herd_id",), tool_name="track_herd"),
    define_action("prepare-nest", ("nest_id",), tool_name="prepare_nest"),
    define_action(
        "set-bait",
        ("bait_id", "target_species", "potency"),
        tool_name="set_bait",
        patterns=("set bait {bait_id}",),
    ),
    define_action(
        "tranquilize-creature",
        ("creature_id", "tranquilizer_id", "duration_seconds"),
        tool_name="tranquilize_creature",
        patterns=("tranquilize {creature_id}",),
    ),
    define_action(
        "approach-creature",
        ("creature_id",),
        tool_name="approach_creature",
        patterns=("approach {creature_id}",),
    ),
    define_action(
        "tame-creature",
        ("creature_id", "role"),
        tool_name="tame_creature",
        patterns=("tame {creature_id}",),
    ),
    define_action(
        "train-command",
        ("creature_id", "command_name", "progress"),
        tool_name="train_command",
    ),
    define_action(
        "mount-creature",
        ("creature_id",),
        tool_name="mount_creature",
        patterns=("mount {creature_id}",),
    ),
    define_action(
        "command-companion",
        ("creature_id", "command_name", "target_id"),
        tool_name="command_companion",
    ),
    define_action(
        "recall-creature",
        ("creature_id",),
        tool_name="recall_creature",
        patterns=("recall {creature_id}",),
    ),
    define_action(
        "build-enclosure",
        ("room_id", "name", "capacity", "feeding_pen", "quarantine"),
        tool_name="build_enclosure",
        cost=MAJOR_ACTION_COST,
    ),
    define_action(
        "repair-fence",
        ("enclosure_id", "amount"),
        tool_name="repair_fence",
    ),
    define_action(
        "reinforce-gate",
        ("enclosure_id", "amount"),
        tool_name="reinforce_gate",
    ),
    define_action("lock-pen", ("enclosure_id",), tool_name="lock_pen"),
    define_action("open-pen", ("enclosure_id",), tool_name="open_pen"),
    define_action(
        "trigger-containment",
        ("enclosure_id",),
        tool_name="trigger_containment",
    ),
    define_action(
        "recapture-creature",
        ("creature_id", "enclosure_id"),
        tool_name="recapture_creature",
    ),
    define_action(
        "hide-from-creature",
        ("creature_id",),
        tool_name="hide_from_creature",
    ),
    define_action(
        "evacuate-room",
        ("room_id", "destination_id"),
        tool_name="evacuate_room",
    ),
    define_action("dodge-creature", ("creature_id",), tool_name="dodge_creature"),
    define_action(
        "fight-creature",
        ("creature_id", "damage"),
        tool_name="fight_creature",
    ),
    define_action(
        "target-weak-point",
        ("creature_id", "damage"),
        tool_name="target_weak_point",
    ),
    define_action(
        "drive-off-predator",
        ("creature_id",),
        tool_name="drive_off_predator",
    ),
    define_action(
        "call-for-help",
        ("room_id", "strength"),
        tool_name="call_for_help",
    ),
    define_action(
        "signal-army",
        ("room_id", "creature_id", "strength"),
        tool_name="signal_army",
    ),
    define_action(
        "repair-damage",
        ("damage_id", "amount"),
        tool_name="repair_damage",
    ),
    define_action(
        "stock-feed",
        ("feed_store_id", "amount"),
        tool_name="stock_feed",
    ),
    define_action("collect-egg", ("egg_id",), tool_name="collect_egg"),
    define_action(
        "assign-ranch-work",
        ("creature_id", "work_type", "target_id"),
        tool_name="assign_ranch_work",
    ),
    define_action(
        "assign-guard",
        ("creature_id", "location_id"),
        tool_name="assign_guard",
    ),
    define_action(
        "feed-creature",
        ("creature_id", "feed_store_id"),
        tool_name="feed_creature",
    ),
    define_action("calm-creature", ("creature_id",), tool_name="calm_creature"),
    define_action("observe-creature", ("creature_id",), tool_name="observe_creature"),
)

__all__ = ["ACTION_DEFINITIONS"]
