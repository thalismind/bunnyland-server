"""Action metadata owned by bunnyland.dragonsim."""

from ...core.actions import (
    EXTENDED_ACTION_COST,
    EXTENDED_FOCUS_COST,
    FOCUS_COST,
    MAJOR_FOCUS_COST,
    ActionDefinition,
    ActionRequirement,
    define_action,
)
from ...core.commands import Lane

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "discover-location",
        ("location_id",),
        tool_name="discover_location",
        description=(
            "Discover a nearby point of interest, revealing it and recording you as one of "
            "its discoverers. Look around for undiscovered landmarks within reach first."
        ),
        patterns=("discover {location_id}",),
    ),
    define_action(
        "mark-map",
        ("location_id", "label"),
        tool_name="mark_map",
        description=(
            "Add a personal map marker to a mappable location so you can recognize it later. "
            "The location must be a discovered point of interest within reach."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("mark {location_id} on map",),
    ),
    define_action(
        "trigger-encounter",
        ("zone_id",),
        tool_name="trigger_encounter",
        description=(
            "Enter an active encounter zone to spring whatever awaits there. Reachable zones "
            "advertise their type and danger rating; inactive zones cannot be triggered."
        ),
        patterns=("enter encounter {zone_id}",),
    ),
    define_action(
        "accept-quest",
        ("quest_id",),
        tool_name="accept_quest",
        description=(
            "Accept an offered quest so you can work toward its objectives and rewards. "
            "Reference the quest by id or key; completed or already-accepted quests are refused."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("accept quest {quest_id}",),
    ),
    define_action(
        "complete-objective",
        ("objective_id",),
        tool_name="complete_objective",
        description=(
            "Mark a quest objective done; clearing the last objective completes the quest and "
            "delivers its rewards to your inventory. Accept the quest before finishing objectives."
        ),
        lane=Lane.FOCUS,
        cost=MAJOR_FOCUS_COST,
        patterns=("complete objective {objective_id}",),
    ),
    define_action(
        "unlock-perk",
        ("perk_id",),
        tool_name="unlock_perk",
        description=(
            "Unlock a perk once your matching skill is high enough, adding it to your abilities. "
            "Each perk lists the skill and minimum level it requires."
        ),
        lane=Lane.FOCUS,
        cost=MAJOR_FOCUS_COST,
        patterns=("unlock perk {perk_id}",),
    ),
    define_action(
        "absorb-great-soul",
        ("beast_id",),
        tool_name="absorb_great_soul",
        description=(
            "Absorb the great soul of a slain ancient beast, raising your soul count toward "
            "learning words of power. The beast must be dead, reachable, and not already drained."
        ),
        lane=Lane.FOCUS,
        cost=MAJOR_FOCUS_COST,
        patterns=("absorb great soul {beast_id}",),
    ),
    define_action(
        "learn-word-of-power",
        ("word_id",),
        tool_name="learn_word_of_power",
        description=(
            "Learn a word of power, which requires enough absorbed great souls and any gated "
            "skill level. Absorb great souls from slain ancient beasts first."
        ),
        lane=Lane.FOCUS,
        cost=EXTENDED_FOCUS_COST,
        patterns=("learn word {word_id}",),
    ),
    define_action(
        "speak-word-of-power",
        ("word_id",),
        tool_name="speak_word_of_power",
        description=(
            "Shout a word of power you have already learned, unleashing it aloud in your room. "
            "You must have learned the word before you can speak it."
        ),
        patterns=("speak word {word_id}",),
    ),
    define_action(
        "inscribe-voice-phrase",
        ("target_id", "word_id", "phrase"),
        tool_name="inscribe_voice_phrase",
        description=(
            "Carve or write a word-of-power phrase onto a nearby writable or carvable target, "
            "leaving it for others to study. The target needs enough remaining space."
        ),
        cost=EXTENDED_ACTION_COST,
        patterns=("inscribe {phrase} on {target_id}",),
    ),
    define_action(
        "study-voice-inscription",
        ("target_id",),
        tool_name="study_voice_inscription",
        description=(
            "Study a voice inscription on a nearby target to learn the word of power it encodes. "
            "Look for inscriptions you have not studied yet."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("study inscription on {target_id}",),
    ),
    define_action(
        "steal",
        ("target_id", "item_id"),
        tool_name="steal",
        description=(
            "Take an item another character in the room is carrying without paying. Awake "
            "faction witnesses who can see you will raise a bounty, including observers "
            "who detected your current hide attempt."
        ),
        patterns=("steal {item_id} from {target_id:word}",),
    ),
    define_action(
        "pay-bounty",
        ("faction_id",),
        tool_name="pay_bounty",
        description=(
            "Pay off your outstanding bounty with a faction, clearing your wanted status with "
            "them. Check your faction standings for bounties you owe."
        ),
        patterns=("pay bounty {faction_id}",),
    ),
    define_action(
        "change-faction-rank",
        ("faction_id", "rank"),
        tool_name="change_faction_rank",
        description=(
            "Change your rank within a faction you already belong to. Use it to promote or "
            "reassign your standing after joining."
        ),
    ),
    define_action(
        "serve-jail-time",
        tool_name="serve_jail_time",
        description=(
            "Serve out an active jail sentence, freeing yourself and clearing the related bounty. "
            "You must be jailed and past your release time."
        ),
    ),
    define_action(
        "pick-lock",
        ("lock_id",),
        tool_name="pick_lock",
        description=(
            "Pick a reachable lock open, earning lockpicking experience. Your lockpicking skill "
            "must meet the lock's difficulty."
        ),
        requirement=ActionRequirement(character_components=("SkillSetComponent",)),
    ),
    define_action(
        "read-lore-book",
        ("book_id",),
        tool_name="read_lore_book",
        description=(
            "Read a reachable lore or skill book; the first read of a skill book grants "
            "experience. Look for unread books nearby."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("read {book_id}",),
    ),
    define_action(
        "learn-spell",
        ("spell_id",),
        tool_name="learn_spell",
        description=(
            "Learn a reachable spell so you can cast it later. Some spells require a minimum "
            "magic skill level before you can learn them."
        ),
        lane=Lane.FOCUS,
        cost=EXTENDED_FOCUS_COST,
        requirement=ActionRequirement(character_components=("SkillSetComponent",)),
    ),
    define_action(
        "cast-dragon-spell",
        ("spell_id", "target_id"),
        tool_name="cast_dragon_spell",
        description=(
            "Cast a spell you have learned, spending magic and starting any cooldown. You need "
            "enough magic and the spell must be off cooldown; effects default to yourself."
        ),
        requirement=ActionRequirement(character_edges=("KnowsSpell",)),
    ),
    define_action(
        "brew-potion",
        ("recipe_id",),
        tool_name="brew_potion",
        description=(
            "Brew a potion from a reachable recipe, consuming the required ingredients from your "
            "inventory and adding the finished potion. Carry every listed ingredient first."
        ),
        cost=EXTENDED_ACTION_COST,
        requirement=ActionRequirement(character_components=("SkillSetComponent",)),
    ),
    define_action(
        "track-quest",
        ("quest_id",),
        tool_name="track_quest",
        description=(
            "Track a quest you have accepted so its stage and branch stay visible in your notes. "
            "Accept the quest before tracking it."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
    ),
    define_action(
        "decline-quest",
        ("quest_id",),
        tool_name="decline_quest",
        description=(
            "Decline an offered quest you have not accepted, marking it declined. Accepted or "
            "completed quests cannot be declined."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
    ),
    define_action(
        "choose-quest-branch",
        ("quest_id", "branch"),
        tool_name="choose_quest_branch",
        description=(
            "Choose a branch for an accepted quest, steering which path it follows. You must "
            "have accepted the quest before picking a branch."
        ),
        lane=Lane.FOCUS,
        cost=EXTENDED_FOCUS_COST,
    ),
    define_action(
        "persuade",
        ("target_id", "amount"),
        tool_name="persuade",
        description=(
            "Persuade a reachable character, raising their disposition toward you by the given "
            "amount. Use it to warm someone up before asking for help."
        ),
    ),
    define_action(
        "surrender",
        ("target_id", "reason"),
        tool_name="surrender",
        description=(
            "Surrender, optionally yielding to a specific character, and announce it to the "
            "room. Reach for this to end a losing fight on your terms."
        ),
    ),
    define_action(
        "report-crime",
        ("criminal_id", "faction_id", "bounty"),
        tool_name="report_crime",
        description=(
            "Report a reachable criminal to a faction, placing a bounty on them. The bounty "
            "must be positive and the target must be a real faction."
        ),
    ),
    define_action(
        "recover-magic",
        ("amount",),
        tool_name="recover_magic",
        description=(
            "Recover spent magic back toward your maximum by the given amount. Use it between "
            "spellcasting to top up your reserves."
        ),
    ),
    define_action(
        "appease-ancient-beast",
        ("beast_id", "method"),
        tool_name="appease_ancient_beast",
        description=(
            "Attempt to appease a reachable ancient beast by a chosen method instead of fighting "
            "it. Name the method, such as parley, to calm the beast."
        ),
    ),
    define_action(
        "ask-for-work",
        ("template_id",),
        tool_name="ask_for_work",
        description=(
            "Ask a quest-giver for work, generating a fresh quest from a reachable template with "
            "its own objective, reward, and deadline. Look for available work nearby."
        ),
    ),
    define_action(
        "accept-generated-quest",
        ("quest_id",),
        tool_name="accept_generated_quest",
        description=(
            "Accept a generated quest that is still on offer, starting its deadline clock. The "
            "quest must be reachable and not yet claimed."
        ),
    ),
    define_action(
        "complete-generated-quest",
        ("quest_id",),
        tool_name="complete_generated_quest",
        description=(
            "Turn in a generated quest you accepted before its deadline, claiming the reward "
            "item. Complete it while the quest is still active and on time."
        ),
    ),
    define_action(
        "refuse-generated-quest",
        ("quest_id",),
        tool_name="refuse_generated_quest",
        description=(
            "Refuse a generated quest while it is still merely offered, declining it outright. "
            "Use this instead of accepting work you do not want."
        ),
    ),
    define_action(
        "abandon-generated-quest",
        ("quest_id",),
        tool_name="abandon_generated_quest",
        description=(
            "Abandon a generated quest you accepted, dropping it mid-progress. Only active "
            "quests you have accepted can be abandoned."
        ),
    ),
    define_action(
        "extend-generated-quest",
        ("quest_id", "seconds"),
        tool_name="extend_generated_quest",
        description=(
            "Extend a generated quest's deadline by a number of seconds, buying more time to "
            "finish it. The quest must already have a deadline to extend."
        ),
    ),
    define_action(
        "lie-about-quest",
        ("quest_id", "lie"),
        tool_name="lie_about_quest",
        description=(
            "Lie about a generated quest, marking it falsely reported and announcing the "
            "deception to the room. Provide the lie you are telling."
        ),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
