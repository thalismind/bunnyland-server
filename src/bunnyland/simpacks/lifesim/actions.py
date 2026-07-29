"""Action metadata owned by bunnyland.lifesim."""

from ...core.actions import (
    EXTENDED_FOCUS_COST,
    FOCUS_COST,
    MAJOR_FOCUS_COST,
    ActionDefinition,
    ActionPattern,
    define_action,
)
from ...core.commands import Lane

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "eat",
        ("item_id",),
        tool_name="eat",
        description=(
            "Eat a food item to relieve your hunger. The food must be in your "
            "inventory or on the floor of your room, and each bite may use it up."
        ),
        patterns=("eat {item_id}",),
    ),
    define_action(
        "bathe",
        ("target_id",),
        tool_name="bathe",
        description=(
            "Wash up to restore your hygiene more thoroughly than a quick clean. "
            "Bathe at a nearby tub, sink, or water source for an extra boost."
        ),
        patterns=("bathe", "bathe at {target_id}"),
    ),
    define_action(
        "clean-self",
        ("target_id",),
        tool_name="clean_self",
        description=(
            "Freshen up for a small hygiene boost when no proper washing spot is "
            "handy. Bathe instead when you can for a larger recovery."
        ),
        patterns=("clean self",),
    ),
    define_action(
        "play",
        ("target_id",),
        tool_name="play",
        description=(
            "Do something fun to raise your fun meter and stave off boredom. Play "
            "with a nearby toy or object for a bigger lift."
        ),
        patterns=("play", "play with {target_id}"),
    ),
    define_action(
        "relax",
        ("target_id",),
        tool_name="relax",
        description=(
            "Rest and unwind to recover your comfort. Relax on nearby furniture "
            "such as a chair or bed for extra relief."
        ),
        patterns=("relax", "relax on {target_id}"),
    ),
    define_action(
        "seek-privacy",
        ("target_id",),
        tool_name="seek_privacy",
        description=(
            "Find a quiet, private spot to recover your privacy after too much "
            "time around others."
        ),
        patterns=("seek privacy",),
    ),
    define_action(
        "seek-safety",
        ("target_id",),
        tool_name="seek_safety",
        description=(
            "Retreat somewhere you feel secure to restore your sense of safety."
        ),
        patterns=("seek safety",),
    ),
    define_action(
        "choose-aspiration",
        ("name", "milestones"),
        tool_name="choose_aspiration",
        description=(
            "Set a lifelong aspiration and the milestones you want to pursue, "
            "giving your character a long-term goal to work toward."
        ),
        lane=Lane.FOCUS,
        cost=EXTENDED_FOCUS_COST,
    ),
    define_action(
        "complete-milestone",
        ("milestone", "reward_name"),
        tool_name="complete_milestone",
        description=(
            "Mark one of your aspiration's milestones as done, optionally granting "
            "yourself a reward item. Choose an aspiration first."
        ),
        lane=Lane.FOCUS,
        cost=MAJOR_FOCUS_COST,
    ),
    define_action(
        "practice-skill",
        ("skill", "xp"),
        tool_name="practice_skill",
        description=(
            "Practice a skill on your own to earn experience and level it up over "
            "time. Sleeping in a home you own makes practice count for more."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
    ),
    define_action(
        "study-skill",
        ("skill", "xp"),
        tool_name="study_skill",
        description=(
            "Study a skill to gain experience, a steadier but slower way to "
            "improve than hands-on practice."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
    ),
    define_action(
        "mentor-skill",
        ("student_id", "skill", "xp"),
        tool_name="mentor_skill",
        description=(
            "Teach a skill to another character in the room, granting them "
            "experience boosted by your own mastery. They must be present with you."
        ),
    ),
    define_action(
        "update-profile",
        ("traits", "interests", "preferred_routine"),
        tool_name="update_profile",
        description=(
            "Set your character's traits, interests, and preferred routine so the "
            "world and other characters know who you are."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
    ),
    define_action(
        "add-whim",
        ("want", "reward_xp"),
        tool_name="add_whim",
        description=(
            "Record a short-term whim you want to fulfill, worth skill experience "
            "once you complete it."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
    ),
    define_action(
        "complete-whim",
        ("whim_id",),
        tool_name="complete_whim",
        description=(
            "Mark one of your whims as fulfilled and collect its experience "
            "reward. Check your current whims to find one to complete."
        ),
        lane=Lane.FOCUS,
        cost=EXTENDED_FOCUS_COST,
    ),
    define_action(
        "use-home-object",
        ("object_id",),
        tool_name="use_home_object",
        description=(
            "Use a nearby home object for its affordance, wearing down its "
            "cleanliness a little each time. It must be reachable and not broken."
        ),
    ),
    define_action(
        "maintain-home-object",
        ("object_id", "action"),
        tool_name="maintain_home_object",
        description=(
            "Tend a home object by cleaning, repairing, upgrading, or decorating "
            "it to restore or improve its condition. The object must be within reach."
        ),
    ),
    define_action(
        "invite-over",
        ("guest_id", "room_id"),
        tool_name="invite_over",
        description=(
            "Invite another character to visit a room you own, claim, or are "
            "currently in. Defaults to your current room when none is given."
        ),
    ),
    define_action(
        "configure-aging",
        (
            "natural_aging",
            "adult_age_seconds",
            "elder_age_seconds",
            "natural_death_age_seconds",
            "natural_death_checks",
        ),
        tool_name="configure_aging",
        description=(
            "Set the world's natural aging rules, including whether characters age "
            "and when they reach adulthood, elderhood, and natural death."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
    ),
    define_action(
        "find-job",
        (
            "title",
            "hourly_pay",
            "next_shift_epoch",
            "shift_duration_seconds",
            "shift_interval_seconds",
        ),
        tool_name="find_job",
        description=(
            "Take a job with a title, hourly pay, and a shift schedule, starting a "
            "career you can work for income."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
    ),
    define_action(
        "go-to-work",
        ("performance_gain",),
        tool_name="go_to_work",
        description=(
            "Work your scheduled shift to earn wages and build performance toward "
            "a promotion. Your next shift must already be due."
        ),
    ),
    define_action(
        "quit-job",
        tool_name="quit_job",
        description="Leave your current job, ending your active career.",
    ),
    define_action(
        "pay-wage",
        ("worker_id", "amount"),
        tool_name="pay_wage",
        description=(
            "Pay wages from your household funds to a worker in the room. They "
            "must be present and you must have enough funds."
        ),
    ),
    define_action(
        "assess-tax",
        ("amount", "reason", "due_epoch"),
        tool_name="assess_tax",
        description=(
            "Levy a tax as a bill against yourself, recording an amount owed by a "
            "due date."
        ),
    ),
    define_action(
        "charge-rent",
        ("tenant_id", "amount", "reason", "due_epoch"),
        tool_name="charge_rent",
        description=(
            "Bill a tenant in the room for rent, creating a debt they owe you by a "
            "due date. The tenant must be present."
        ),
        patterns=("charge rent {tenant_id} {amount}",),
    ),
    define_action(
        "pay-bill",
        ("bill_id",),
        tool_name="pay_bill",
        description=(
            "Pay an outstanding bill from your household funds, settling what you "
            "owe. Omit the bill to pay your first unpaid one."
        ),
        patterns=("pay bill {bill_id}", ActionPattern("pay bill", {})),
    ),
    define_action(
        "open-business",
        ("name", "default_price"),
        tool_name="open_business",
        description=(
            "Open a business under your ownership with a default price, so you can "
            "sell goods to customers for income."
        ),
        patterns=("open business {name}",),
    ),
    define_action(
        "buy-item",
        ("seller_id", "item_id", "business_id", "price"),
        tool_name="buy_item",
        description=(
            "Buy an item a nearby seller is offering, paying from your household "
            "funds. The seller must be reachable and you need enough funds."
        ),
        patterns=("buy {item_id} from {seller_id}",),
    ),
    define_action(
        "sell-item",
        ("item_id", "customer_id", "business_id", "price"),
        tool_name="sell_item",
        description=(
            "Sell an item from your inventory to a customer in the room, adding the "
            "price to your funds. The customer must be present and able to afford it."
        ),
        patterns=("sell {item_id} to {customer_id}",),
    ),
    define_action(
        "promote-business",
        ("business_id",),
        tool_name="promote_business",
        description="Promote one of your businesses to raise its profile.",
    ),
    define_action(
        "join-household",
        ("household_id", "name"),
        tool_name="join_household",
        description=(
            "Join or form a named household, linking your character to a shared "
            "home group."
        ),
        patterns=(
            ActionPattern(
                "join household {household_id}",
                argument_aliases={"name": "household_id"},
            ),
        ),
    ),
    define_action(
        "claim-home",
        ("room_id",),
        tool_name="claim_home",
        description=(
            "Claim a room as the home you own, which supports well-rested sleep "
            "and inviting guests. Defaults to your current room; a room has one owner."
        ),
        patterns=("claim home {room_id}", ActionPattern("claim home", {})),
    ),
    define_action(
        "claim-room",
        ("room_id",),
        tool_name="claim_room",
        description=(
            "Stake an active claim on a room without owning it. Defaults to your "
            "current room; a room can have only one active claimant."
        ),
        patterns=("claim room {room_id}", ActionPattern("claim room", {})),
    ),
    define_action(
        "set-routine",
        ("activity", "interval_seconds", "next_due_epoch"),
        tool_name="set_routine",
        description=(
            "Schedule a recurring routine activity that reminds you at a set "
            "interval."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
    ),
    define_action(
        "set-relationship-status",
        ("target_id", "status"),
        tool_name="set_relationship_status",
        description=(
            "Set how you regard another character in the room as friend, rival, "
            "romance, or acquaintance. They must be present."
        ),
    ),
    define_action(
        "spread-gossip",
        ("target_id", "text", "reputation_delta"),
        tool_name="spread_gossip",
        description=(
            "Spread gossip about another character in the room, shifting their "
            "reputation and what they are known for. They must be present."
        ),
    ),
    define_action(
        "witness-romance",
        ("partner_id", "rival_id", "intensity"),
        tool_name="witness_romance",
        description=(
            "React to catching your partner with a rival, making you jealous of "
            "the rival. All three must share the room and the partner must be yours."
        ),
    ),
    define_action(
        "start-partnership",
        ("target_id",),
        tool_name="start_partnership",
        description=(
            "Begin a romantic partnership with another character in the room. They "
            "must be present and not already your partner."
        ),
    ),
    define_action(
        "end-partnership",
        ("target_id",),
        tool_name="end_partnership",
        description=(
            "End your partnership with a character, dissolving the relationship on "
            "both sides."
        ),
    ),
    define_action(
        "start-pregnancy",
        ("co_parent_id", "due_in_seconds"),
        tool_name="start_pregnancy",
        description=(
            "Begin a pregnancy with a co-parent in the room, subject to "
            "reproductive compatibility and fertility. Both must be present and able."
        ),
    ),
    define_action(
        "resolve-birth",
        ("child_name",),
        tool_name="resolve_birth",
        description=(
            "Deliver your child once the pregnancy is due, adding a new character "
            "to your family. Wait until the birth is due."
        ),
    ),
    define_action(
        "adopt-child",
        ("child_id",),
        tool_name="adopt_child",
        description=(
            "Adopt a child present in the room as your own and become their "
            "parent. The target must be a child and not already yours."
        ),
        patterns=("adopt {child_id}",),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
