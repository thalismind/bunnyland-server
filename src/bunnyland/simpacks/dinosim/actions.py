"""Action metadata owned by bunnyland.dinosim."""

from ...core.actions import (
    EXTENDED_ACTION_COST,
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "extract-ancient-sample",
        ("fossil_id",),
        tool_name="extract_ancient_sample",
        description=(
            "Extract a viable ancient DNA sample from a fossil and add it to "
            "your inventory. The fossil must be identified first, so survey or identify it before "
            "extracting."
        ),
    ),
    define_action(
        "prepare-clone",
        ("sample_id",),
        tool_name="prepare_clone",
        cost=EXTENDED_ACTION_COST,
        description=(
            "Turn an ancient sample into a fertilized clone egg ready for "
            "incubation, consuming the sample. Extract an ancient sample from an identified fossil "
            "first."
        ),
    ),
    define_action(
        "lay-egg",
        ("parent_id",),
        tool_name="lay_egg",
        description=(
            "Have a fertile parent creature lay an egg into the current room. "
            "The parent must be a fertile reptile, dinosaur, or egg-laying species."
        ),
    ),
    define_action(
        "fertilize-egg",
        ("egg_id", "parent_id"),
        tool_name="fertilize_egg",
        description=(
            "Fertilize an unhatched egg using a fertile parent so it can be "
            "incubated. Only works on an egg that is not already fertilized or hatched."
        ),
    ),
    define_action(
        "incubate-egg",
        ("egg_id", "duration_seconds"),
        tool_name="incubate_egg",
        description=(
            "Begin incubating a fertilized egg for a set duration, after which "
            "it becomes ready to hatch. The egg must be fertilized and not yet hatched."
        ),
    ),
    define_action(
        "hatch-egg",
        ("egg_id",),
        tool_name="hatch_egg",
        description=(
            "Hatch a fully incubated egg into a live hatchling in the room. "
            "The egg must already be incubating and ready; incubate it first if it is not."
        ),
    ),
    define_action(
        "survey-fossil",
        ("fossil_id",),
        tool_name="survey_fossil",
        description=(
            "Survey a fossil in place to begin recording its condition and "
            "excavation state. Do this before excavating or stabilizing a fossil."
        ),
    ),
    define_action(
        "excavate-fossil",
        ("fossil_id", "progress"),
        tool_name="excavate_fossil",
        description=(
            "Dig out a fossil, adding to its excavation progress until it is "
            "fully unearthed. Repeat until the fossil is completely excavated."
        ),
    ),
    define_action(
        "clean-fossil",
        ("fossil_id",),
        tool_name="clean_fossil",
        description=(
            "Clean a fossil fragment to remove surrounding rock and prepare it "
            "for study or sampling."
        ),
    ),
    define_action(
        "stabilize-fossil",
        ("fossil_id",),
        tool_name="stabilize_fossil",
        description=(
            "Stabilize an excavated fossil so it holds together and can be "
            "safely handled or sampled."
        ),
    ),
    define_action(
        "lab-incubate-egg",
        ("egg_id", "lab_id"),
        tool_name="lab_incubate_egg",
        description=(
            "Incubate a fertilized egg inside a lab incubator for controlled, "
            "monitored hatching. Use this instead of natural incubation when a lab is available."
        ),
    ),
    define_action(
        "imprint-creature",
        ("creature_id", "bond"),
        tool_name="imprint_creature",
        description=(
            "Imprint on a young creature to form a lasting bond with it. Works "
            "best on a hatchling or juvenile you have raised."
        ),
    ),
    define_action(
        "care-for-juvenile",
        ("creature_id", "care"),
        tool_name="care_for_juvenile",
        description=(
            "Tend to a juvenile creature to raise its care level and help it "
            "grow up healthy. Repeat care over time as the creature matures."
        ),
    ),
    define_action(
        "study-water-creature",
        ("creature_id",),
        tool_name="study_water_creature",
        description=(
            "Study an aquatic creature to record research notes about its "
            "species. The target must be a water creature you can reach."
        ),
    ),
    define_action(
        "brood-egg",
        ("egg_id", "warmth"),
        tool_name="brood_egg",
        description=(
            "Brood an egg with body warmth to keep it viable while it develops. "
            "Use it on an unhatched egg to nurture it before hatching."
        ),
    ),
    define_action(
        "set-incubation-temperature",
        ("egg_id", "temperature"),
        tool_name="set_incubation_temperature",
        description=(
            "Set the temperature of an egg that is already incubating to tune "
            "its development. The egg must be under active incubation."
        ),
    ),
    define_action(
        "trigger-containment-panic",
        ("enclosure_id", "severity"),
        tool_name="trigger_containment_panic",
        description=(
            "Set off a panic among the creatures in an enclosure at the chosen "
            "severity, spooking them into a frenzy."
        ),
    ),
    define_action(
        "track-creature",
        ("creature_id",),
        tool_name="track_creature",
        patterns=("track {creature_id}",),
        description=(
            "Track a creature to record its fresh location so you can find and "
            "follow it. The trail fades over time, so track again to refresh it."
        ),
    ),
    define_action(
        "mark-territory",
        ("territory_id",),
        tool_name="mark_territory",
        description=(
            "Mark a territory as your own by scent so creatures recognize your "
            "claim. You cannot mark the same territory twice."
        ),
    ),
    define_action(
        "track-herd",
        ("herd_id",),
        tool_name="track_herd",
        description=(
            "Track a herd to note its current size and whereabouts. The target "
            "must be a herd you can reach."
        ),
    ),
    define_action(
        "prepare-nest",
        ("nest_id",),
        tool_name="prepare_nest",
        description=(
            "Prepare a nest so it is ready to hold and shelter eggs. An "
            "already-prepared nest cannot be prepared again."
        ),
    ),
    define_action(
        "set-bait",
        ("bait_id", "target_species", "potency"),
        tool_name="set_bait",
        patterns=("set bait {bait_id}",),
        description=(
            "Set out bait tuned to a target species to lure it in and ease "
            "taming. Matching bait boosts your taming progress on that species."
        ),
    ),
    define_action(
        "tranquilize-creature",
        ("creature_id", "tranquilizer_id", "duration_seconds"),
        tool_name="tranquilize_creature",
        patterns=("tranquilize {creature_id}",),
        description=(
            "Sedate a creature with a tranquilizer, leaving it drowsy for a "
            "time and easier to tame or recapture. You need a tranquilizer with uses remaining in "
            "hand."
        ),
    ),
    define_action(
        "approach-creature",
        ("creature_id",),
        tool_name="approach_creature",
        patterns=("approach {creature_id}",),
        description=(
            "Slowly approach a wild creature to build taming progress, raising "
            "its trust and lowering its fear. Repeat, and bait or sedation helps it along."
        ),
    ),
    define_action(
        "tame-creature",
        ("creature_id", "role"),
        tool_name="tame_creature",
        patterns=("tame {creature_id}",),
        description=(
            "Push taming forward on a creature and, once its progress is full, "
            "claim it as your companion. Approach or bait it first if it is still too wild."
        ),
    ),
    define_action(
        "train-command",
        ("creature_id", "command_name", "progress"),
        tool_name="train_command",
        description=(
            "Train a companion creature to learn a named command through "
            "repeated practice. Only a creature you have already tamed can be trained."
        ),
    ),
    define_action(
        "mount-creature",
        ("creature_id",),
        tool_name="mount_creature",
        patterns=("mount {creature_id}",),
        description=(
            "Climb onto your tamed companion to ride it. The creature must "
            "already be your companion."
        ),
    ),
    define_action(
        "recall-creature",
        ("creature_id",),
        tool_name="recall_creature",
        patterns=("recall {creature_id}",),
        description=(
            "Recall your companion creature to your current room from wherever "
            "it wandered. Only works on a creature that is already your companion."
        ),
    ),
    define_action(
        "repair-fence",
        ("enclosure_id", "amount"),
        tool_name="repair_fence",
        description=(
            "Repair an enclosure's fence, restoring its integrity to keep "
            "creatures contained. Reach or stand in the enclosure to work on it."
        ),
    ),
    define_action(
        "reinforce-gate",
        ("enclosure_id", "amount"),
        tool_name="reinforce_gate",
        description=(
            "Reinforce an enclosure's gate to make it harder for creatures to "
            "break out. The enclosure must have a gate to reinforce."
        ),
    ),
    define_action(
        "lock-pen",
        ("enclosure_id",),
        tool_name="lock_pen",
        description=(
            "Close and lock an enclosure's gate so nothing can pass through "
            "it."
        ),
    ),
    define_action(
        "open-pen",
        ("enclosure_id",),
        tool_name="open_pen",
        description=(
            "Open and unlock an enclosure's gate so creatures and people can "
            "pass through."
        ),
    ),
    define_action(
        "trigger-containment",
        ("enclosure_id",),
        tool_name="trigger_containment",
        description=(
            "Trigger an enclosure's containment protocol, slamming the gate "
            "locked and resetting its escape risk. Reach for this when a breach is imminent."
        ),
    ),
    define_action(
        "recapture-creature",
        ("creature_id", "enclosure_id"),
        tool_name="recapture_creature",
        description=(
            "Return an escaped creature to an enclosure and secure it behind a "
            "locked gate. Track or corner the loose creature first."
        ),
    ),
    define_action(
        "hide-from-creature",
        ("creature_id",),
        tool_name="hide_from_creature",
        description=(
            "Hide from a dangerous creature to slip out of its attention and "
            "calm it down. Use it to break contact before a creature turns on you."
        ),
    ),
    define_action(
        "evacuate-room",
        ("room_id", "destination_id"),
        tool_name="evacuate_room",
        description=(
            "Move everyone out of a room to a safer destination when danger threatens, "
            "such as a rampaging creature or an unstable enclosure."
        ),
    ),
    define_action(
        "dodge-creature",
        ("creature_id",),
        tool_name="dodge_creature",
        description=(
            "Dodge a creature's charge or attack, evading the blow and "
            "spoiling any charge it was winding up."
        ),
    ),
    define_action(
        "fight-creature",
        ("creature_id", "damage"),
        tool_name="fight_creature",
        description=(
            "Strike a creature with a direct attack, dealing damage and "
            "breaking its grip on you. Expect a counterattack, so consider dodging or hiding if it "
            "is too strong."
        ),
    ),
    define_action(
        "target-weak-point",
        ("creature_id", "damage"),
        tool_name="target_weak_point",
        description=(
            "Strike a creature's exposed weak point for multiplied damage "
            "against tough foes. The weak point must currently be exposed to hit it."
        ),
    ),
    define_action(
        "drive-off-predator",
        ("creature_id",),
        tool_name="drive_off_predator",
        description=(
            "Drive a predator out of the room through a nearby exit, scaring it "
            "away from you and your creatures."
        ),
    ),
    define_action(
        "call-for-help",
        ("room_id", "strength"),
        tool_name="call_for_help",
        description=(
            "Call for help, summoning an armed response to a room. Reach for it "
            "when a room is under threat and you need backup."
        ),
    ),
    define_action(
        "signal-army",
        ("room_id", "creature_id", "strength"),
        tool_name="signal_army",
        description=(
            "Signal an army to respond in force to a room and, if you name a "
            "rampaging creature, beat down its threat. Use this against apex predators and kaiju."
        ),
    ),
    define_action(
        "repair-damage",
        ("damage_id", "amount"),
        tool_name="repair_damage",
        description=(
            "Repair damage a settlement or structure has taken, reducing its "
            "severity until it is fully mended. Defaults to the damage where you are standing."
        ),
    ),
    define_action(
        "stock-feed",
        ("feed_store_id", "amount"),
        tool_name="stock_feed",
        description=(
            "Add feed to a feed store so it can be used to feed creatures "
            "later. Naming a resource type spends that resource from your inventory."
        ),
    ),
    define_action(
        "collect-egg",
        ("egg_id",),
        tool_name="collect_egg",
        description=(
            "Collect an unhatched egg into your inventory as a harvested "
            "product. The egg must not have hatched yet."
        ),
    ),
    define_action(
        "assign-ranch-work",
        ("creature_id", "work_type", "target_id"),
        tool_name="assign_ranch_work",
        description=(
            "Put a tamed creature to work on a ranch task, optionally aimed at "
            "a target. Tame the creature before assigning it work."
        ),
    ),
    define_action(
        "assign-guard",
        ("creature_id", "location_id"),
        tool_name="assign_guard",
        description=(
            "Station a creature to guard a room, keeping watch over that "
            "location. Defaults to your current room if you name no location."
        ),
    ),
    define_action(
        "feed-creature",
        ("creature_id", "feed_store_id"),
        tool_name="feed_creature",
        description=(
            "Feed a creature from a feed store to ease its hunger. The store "
            "must hold enough feed to draw from."
        ),
    ),
    define_action(
        "calm-creature",
        ("creature_id",),
        tool_name="calm_creature",
        description=(
            "Calm an agitated creature to reduce its stress. Observe a creature "
            "first to see how stressed it is."
        ),
    ),
    define_action(
        "observe-creature",
        ("creature_id",),
        tool_name="observe_creature",
        description=(
            "Observe a creature up close to read its current hunger and stress "
            "levels. Use it before deciding whether to feed or calm the creature."
        ),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
