"""Action metadata owned by bunnyland.dragonsim."""

from ...core.actions import (
    ActionDefinition,
    ActionRequirement,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "discover-location",
        ("location_id",),
        tool_name="discover_location",
        patterns=("discover {location_id}",),
    ),
    define_action(
        "mark-map",
        ("location_id", "label"),
        tool_name="mark_map",
        patterns=("mark {location_id} on map",),
    ),
    define_action(
        "trigger-encounter",
        ("zone_id",),
        tool_name="trigger_encounter",
        patterns=("enter encounter {zone_id}",),
    ),
    define_action(
        "accept-quest",
        ("quest_id",),
        tool_name="accept_quest",
        patterns=("accept quest {quest_id}",),
    ),
    define_action(
        "complete-objective",
        ("objective_id",),
        tool_name="complete_objective",
        patterns=("complete objective {objective_id}",),
    ),
    define_action(
        "join-faction",
        ("faction_id", "rank"),
        tool_name="join_faction",
        patterns=("join faction {faction_id}",),
    ),
    define_action(
        "leave-faction",
        ("faction_id",),
        tool_name="leave_faction",
        patterns=("leave faction {faction_id}",),
    ),
    define_action(
        "unlock-perk",
        ("perk_id",),
        tool_name="unlock_perk",
        patterns=("unlock perk {perk_id}",),
    ),
    define_action(
        "absorb-great-soul",
        ("beast_id",),
        tool_name="absorb_great_soul",
        patterns=("absorb great soul {beast_id}",),
    ),
    define_action(
        "learn-word-of-power",
        ("word_id",),
        tool_name="learn_word_of_power",
        patterns=("learn word {word_id}",),
    ),
    define_action(
        "speak-word-of-power",
        ("word_id",),
        tool_name="speak_word_of_power",
        patterns=("speak word {word_id}",),
    ),
    define_action(
        "inscribe-voice-phrase",
        ("target_id", "word_id", "phrase"),
        tool_name="inscribe_voice_phrase",
        patterns=("inscribe {phrase} on {target_id}",),
    ),
    define_action(
        "study-voice-inscription",
        ("target_id",),
        tool_name="study_voice_inscription",
        patterns=("study inscription on {target_id}",),
    ),
    define_action(
        "steal",
        ("target_id", "item_id"),
        tool_name="steal",
        patterns=("steal {item_id} from {target_id:word}",),
    ),
    define_action(
        "pay-bounty",
        ("faction_id",),
        tool_name="pay_bounty",
        patterns=("pay bounty {faction_id}",),
    ),
    define_action(
        "change-faction-rank",
        ("faction_id", "rank"),
        tool_name="change_faction_rank",
    ),
    define_action("serve-jail-time", tool_name="serve_jail_time"),
    define_action(
        "pick-lock",
        ("lock_id",),
        tool_name="pick_lock",
        requirement=ActionRequirement(character_components=("SkillSetComponent",)),
    ),
    define_action(
        "read-lore-book",
        ("book_id",),
        tool_name="read_lore_book",
        patterns=("read {book_id}",),
    ),
    define_action(
        "learn-spell",
        ("spell_id",),
        tool_name="learn_spell",
        requirement=ActionRequirement(character_components=("SkillSetComponent",)),
    ),
    define_action(
        "cast-dragon-spell",
        ("spell_id",),
        tool_name="cast_dragon_spell",
        requirement=ActionRequirement(character_edges=("KnowsSpell",)),
    ),
    define_action(
        "brew-potion",
        ("recipe_id",),
        tool_name="brew_potion",
        requirement=ActionRequirement(character_components=("SkillSetComponent",)),
    ),
    define_action("track-quest", ("quest_id",), tool_name="track_quest"),
    define_action("decline-quest", ("quest_id",), tool_name="decline_quest"),
    define_action(
        "choose-quest-branch",
        ("quest_id", "branch"),
        tool_name="choose_quest_branch",
    ),
    define_action("persuade", ("target_id", "amount"), tool_name="persuade"),
    define_action("surrender", ("target_id", "reason"), tool_name="surrender"),
    define_action(
        "report-crime",
        ("criminal_id", "faction_id", "bounty"),
        tool_name="report_crime",
    ),
    define_action("recover-magic", ("amount",), tool_name="recover_magic"),
    define_action(
        "appease-ancient-beast",
        ("beast_id", "method"),
        tool_name="appease_ancient_beast",
    ),
    define_action("ask-for-work", ("template_id",), tool_name="ask_for_work"),
    define_action("accept-generated-quest", ("quest_id",), tool_name="accept_generated_quest"),
    define_action("complete-generated-quest", ("quest_id",), tool_name="complete_generated_quest"),
    define_action(
        "refuse-generated-quest",
        ("quest_id",),
        tool_name="refuse_generated_quest",
    ),
    define_action(
        "abandon-generated-quest",
        ("quest_id",),
        tool_name="abandon_generated_quest",
    ),
    define_action(
        "extend-generated-quest",
        ("quest_id", "seconds"),
        tool_name="extend_generated_quest",
    ),
    define_action(
        "lie-about-quest",
        ("quest_id", "lie"),
        tool_name="lie_about_quest",
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
