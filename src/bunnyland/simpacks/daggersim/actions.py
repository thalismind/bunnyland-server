"""Action metadata owned by bunnyland.daggersim."""

from ...core.actions import (
    EXTENDED_FOCUS_COST,
    FOCUS_COST,
    FREE_COST,
    ActionDefinition,
    define_action,
)
from ...core.commands import Lane

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "expand-site",
        ("site_id", "generator_id", "trigger"),
        tool_name="expand_site",
        description=(
            "Bring an unrealized procedural site to life, turning a stubbed-out location "
            "into fully generated content. Inspect a nearby site first to confirm it is not "
            "already realized."
        ),
    ),
    define_action(
        "ask-rumor",
        ("rumor_id",),
        tool_name="ask_rumor",
        description=(
            "Ask about a rumor to hear its details and add it to what you know. Look around "
            "for rumors you have not heard, or leave the target blank to pick up the nearest one."
        ),
    ),
    define_action(
        "investigate-rumor",
        ("rumor_id",),
        tool_name="investigate_rumor",
        description=(
            "Look into a rumor you have already heard to prove or disprove it. Ask about the "
            "rumor first; verifying a true one can open a new site to explore."
        ),
    ),
    define_action(
        "plan-travel",
        ("destination_id",),
        tool_name="plan_travel",
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        description=(
            "Set out from your current travel hub toward a distant destination, starting a "
            "timed journey along a known route. Both ends must be travel hubs linked by a route, "
            "and starting the journey consumes one unit of travel supplies from your inventory."
        ),
    ),
    define_action(
        "join-institution",
        ("institution_id", "rank"),
        tool_name="join_institution",
        description=(
            "Join a nearby guild, order, or other institution as a member and earn standing "
            "with it. Find and inspect an institution in town before joining."
        ),
    ),
    define_action(
        "use-institution-service",
        ("service_id",),
        tool_name="use_institution_service",
        description=(
            "Use a service offered by an institution you belong to, such as receiving an item "
            "or unlocking access. You must be a member of sufficient rank, and some services "
            "require proven deeds."
        ),
    ),
    define_action(
        "promote-institution",
        ("institution_id", "rank"),
        tool_name="promote_institution",
        description=(
            "Advance to a higher rank within an institution you already belong to, raising "
            "your standing. You must be a member before you can be promoted."
        ),
    ),
    define_action(
        "pay-institution-dues",
        ("institution_id", "amount"),
        tool_name="pay_institution_dues",
        description=(
            "Pay the membership dues owed to an institution to keep in good standing. Only "
            "works while dues are outstanding and you have not already paid them."
        ),
    ),
    define_action(
        "open-bank-account",
        ("bank_id",),
        tool_name="open_bank_account",
        description=(
            "Open a new account at a nearby bank so you can deposit, withdraw, and borrow. "
            "Visit the bank in person; you can hold only one account per bank."
        ),
    ),
    define_action(
        "deposit",
        ("bank_id", "amount"),
        tool_name="deposit",
        description=(
            "Deposit money into your account at a bank where you already hold one, raising "
            "your balance. The amount must be positive."
        ),
    ),
    define_action(
        "withdraw",
        ("bank_id", "amount"),
        tool_name="withdraw",
        description=(
            "Withdraw money from your bank account, up to your available balance."
        ),
    ),
    define_action(
        "take-loan",
        ("bank_id", "amount", "duration_seconds"),
        tool_name="take_loan",
        description=(
            "Borrow money from your bank, credited to your account and repayable by a due "
            "date. Leave a loan unpaid past its term and it defaults into debt."
        ),
    ),
    define_action(
        "repay-loan",
        ("loan_id", "amount"),
        tool_name="repay_loan",
        description=(
            "Pay down an active loan using the balance in your bank account. Repay the full "
            "amount to clear the loan entirely."
        ),
    ),
    define_action(
        "issue-letter-of-credit",
        ("bank_id", "amount"),
        tool_name="issue_letter_of_credit",
        description=(
            "Convert part of your bank balance into a portable letter of credit you can carry "
            "and spend elsewhere. Requires enough funds on deposit."
        ),
    ),
    define_action(
        "store-safe-item",
        ("storage_id", "item_id"),
        tool_name="store_safe_item",
        description=(
            "Lock an item you are carrying into a safe or strongbox for keeping. The storage "
            "becomes yours the first time you use it, and only you can retrieve from it."
        ),
    ),
    define_action(
        "retrieve-safe-item",
        ("storage_id", "item_id"),
        tool_name="retrieve_safe_item",
        description=(
            "Take an item back out of your own safe storage and return it to your inventory."
        ),
    ),
    define_action(
        "send-debt-collector",
        ("debt_id",),
        tool_name="send_debt_collector",
        description=(
            "Send a debt collector after an outstanding debt, bringing the collector into "
            "your current room to pursue it. Target a debt record that has fallen due."
        ),
    ),
    define_action(
        "commit-crime",
        ("crime_type",),
        tool_name="commit_crime",
        description=(
            "Commit a crime in the current law region, earning a criminal record, a bounty, "
            "and a hit to your legal reputation. Only crimes the local law fines can be done."
        ),
    ),
    define_action(
        "pay-fine",
        ("crime_id",),
        tool_name="pay_fine",
        description=(
            "Pay the fine on an open crime record to clear the charge and lift its bounty. "
            "Requires a bank account with enough funds and a reachable crime record."
        ),
    ),
    define_action(
        "sentence-crime",
        ("crime_id", "sentence"),
        tool_name="sentence_crime",
        description=(
            "Pass a court sentence on a crime record, setting how the offense is punished. "
            "Used to adjudicate an existing charge."
        ),
    ),
    define_action(
        "rent-lodging",
        ("lodging_id", "duration_seconds"),
        tool_name="rent_lodging",
        description=(
            "Rent a room or bed at a nearby lodging for a stretch of time, claiming it as "
            "yours until the rental expires. The lodging must be free or already yours."
        ),
    ),
    define_action(
        "camp",
        ("risk",),
        tool_name="camp",
        description=(
            "Make camp in your current room to rest in the wild, choosing how much risk to "
            "accept. Safer camps stay calm; riskier ones invite trouble."
        ),
    ),
    define_action(
        "request-cure-quest",
        ("quest_id",),
        tool_name="request_cure_quest",
        description=(
            "Request a quest to cure your supernatural affliction, recording that you seek a "
            "remedy. You must already be afflicted before asking for a cure."
        ),
    ),
    define_action(
        "buy-travel-supplies",
        ("quantity",),
        tool_name="buy_travel_supplies",
        description=(
            "Buy travel supplies and add them to your inventory stack to sustain you on the "
            "road. Choose how many units to add."
        ),
    ),
    define_action(
        "resolve-travel-interruption",
        ("interruption_id",),
        tool_name="resolve_travel_interruption",
        description=(
            "Resolve a travel interruption that has stalled your journey, clearing the "
            "obstacle so you can carry on. Target the interruption blocking your route."
        ),
    ),
    define_action(
        "buy-property",
        ("property_id",),
        tool_name="buy_property",
        description=(
            "Buy an unowned property, paying from your bank account and taking its deed. The "
            "property must be reachable, unclaimed, and within your means."
        ),
    ),
    define_action(
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
        lane=Lane.FOCUS,
        cost=EXTENDED_FOCUS_COST,
        description=(
            "Design a custom character class from a class template, choosing its primary, "
            "major, and minor skills along with advantages and disadvantages. A one-time "
            "choice: you can hold only one custom class."
        ),
    ),
    define_action(
        "create-spell",
        ("template_id", "spell_name"),
        tool_name="create_spell",
        lane=Lane.FOCUS,
        cost=EXTENDED_FOCUS_COST,
        description=(
            "Craft a custom spell from a spell template, adding the finished spell to your "
            "inventory. Requires a reachable spell template to build from."
        ),
    ),
    define_action(
        "cast-spell",
        ("spell_id", "target_id"),
        tool_name="cast_spell",
        patterns=(
            "cast {spell_id} on {target_id}",
            "cast {spell_id} at {target_id}",
            "cast {spell_id}",
        ),
        examples=("cast moss charm on Juniper",),
        description=(
            "Cast one of your spells at a target to heal or harm it, defaulting to yourself "
            "when no target is named. The spell must be within reach in your possession."
        ),
    ),
    define_action(
        "enchant-item",
        ("item_id", "spell_id"),
        tool_name="enchant_item",
        patterns=("enchant {item_id} with {spell_id}",),
        examples=("enchant moss charm with Mend Moss",),
        description=(
            "Enchant one of your items with a spell, binding its effect into the object for "
            "later use. Keep both the item and the source spell within reach; the item itself "
            "cannot be a spell."
        ),
    ),
    define_action(
        "make-potion",
        ("maker_id",),
        tool_name="make_potion",
        description=(
            "Brew a potion at a reachable potion-making station, adding the finished potion "
            "to your inventory."
        ),
    ),
    define_action(
        "recharge-enchanted-item",
        ("item_id", "service_id"),
        tool_name="recharge_enchanted_item",
        description=(
            "Recharge an enchanted item at a recharge service to lower its casting cost and "
            "restore its power. Bring both the item and the service within reach."
        ),
    ),
    define_action(
        "attempt-pacify",
        ("target_id", "language"),
        tool_name="attempt_pacify",
        description=(
            "Try to calm a hostile creature by speaking its own language, ending its "
            "aggression if you succeed. You must know the creature's language well enough to "
            "overcome its wariness."
        ),
    ),
    define_action(
        "contract-affliction",
        ("affliction_type",),
        tool_name="contract_affliction",
        description=(
            "Contract a supernatural affliction such as lycanthropy or vampirism, taking on "
            "its curse and hunger. You can carry only one affliction at a time."
        ),
    ),
    define_action(
        "progress-affliction-incubation",
        ("target_id",),
        tool_name="progress_affliction_incubation",
        description=(
            "Advance your supernatural affliction to its next stage as the curse takes hold. "
            "Requires an affliction you have already contracted."
        ),
    ),
    define_action(
        "mark-affliction-stigma",
        ("target_id", "region_id", "severity"),
        tool_name="mark_affliction_stigma",
        description=(
            "Record a stigma against you in a region because of your affliction, tracking how "
            "strongly others shun you there. Severity must be positive."
        ),
    ),
    define_action(
        "transform",
        ("form_name",),
        tool_name="transform",
        description=(
            "Transform into the beast shape of your supernatural affliction, unleashing its "
            "form. You must be afflicted and not already transformed."
        ),
    ),
    define_action(
        "feed-on",
        ("target_id",),
        tool_name="feed_on",
        description=(
            "Feed on a nearby target to satisfy the hunger of your affliction, resetting your "
            "feeding need. You cannot feed on yourself."
        ),
    ),
    define_action(
        "end-transformation",
        tool_name="end_transformation",
        description=(
            "Revert from your beast form back to your normal shape, ending the transformation "
            "and settling the affliction dormant."
        ),
    ),
    define_action(
        "cure-affliction",
        tool_name="cure_affliction",
        description=(
            "Cure yourself of a supernatural affliction, shedding its curse, hunger, and any "
            "transformed form."
        ),
    ),
    define_action(
        "request-dungeon",
        ("dungeon_id",),
        tool_name="request_dungeon",
        description=(
            "Request that a nearby dungeon be generated so its rooms and dangers come into "
            "being. Inspect a dungeon entrance first; each can be generated only once."
        ),
    ),
    define_action(
        "enter-dungeon",
        ("dungeon_id",),
        tool_name="enter_dungeon",
        description=(
            "Step into a generated dungeon through its entry room, beginning the delve and "
            "revealing where you arrive. The dungeon must already be generated."
        ),
    ),
    define_action(
        "search-room",
        tool_name="search_room",
        description=(
            "Search your current dungeon room for hidden secret doors, objectives, and "
            "details a glance would miss. Only dungeon rooms reward a search."
        ),
    ),
    define_action(
        "open-secret-door",
        ("door_id",),
        tool_name="open_secret_door",
        description=(
            "Open a secret door you have already found, revealing the passage it hides and a "
            "new exit from the room. Search the room first to uncover the door."
        ),
    ),
    define_action(
        "mark-path",
        tool_name="mark_path",
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        description=(
            "Mark your current room on your dungeon map so you can find your way back to it "
            "later."
        ),
    ),
    define_action(
        "view-map",
        tool_name="view_map",
        lane=Lane.FOCUS,
        cost=FREE_COST,
        description=(
            "View your automap of the rooms you have explored so far. A map must have been "
            "started before there is anything to see."
        ),
    ),
    define_action(
        "set-recall",
        tool_name="set_recall",
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        description=(
            "Anchor a recall point to your current room so you can return to it later. "
            "Setting a new anchor replaces any previous one."
        ),
    ),
    define_action(
        "use-recall",
        tool_name="use_recall",
        description=(
            "Return instantly to the room where you set your recall anchor. Set an anchor "
            "first, and you must be somewhere other than the anchor itself."
        ),
    ),
    define_action(
        "leave-dungeon",
        ("dungeon_id",),
        tool_name="leave_dungeon",
        description=(
            "Leave a dungeon you have entered, marking your delve as ended. Only works while "
            "you are inside that dungeon."
        ),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
