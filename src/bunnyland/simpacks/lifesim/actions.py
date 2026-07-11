"""Action metadata owned by bunnyland.lifesim."""

from ...core.actions import (
    ActionDefinition,
    ActionPattern,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action("eat", ("item_id",), tool_name="eat", patterns=("eat {item_id}",)),
    define_action(
        "bathe",
        ("target_id",),
        tool_name="bathe",
        patterns=("bathe", "bathe at {target_id}"),
    ),
    define_action("clean-self", ("target_id",), tool_name="clean_self", patterns=("clean self",)),
    define_action(
        "play",
        ("target_id",),
        tool_name="play",
        patterns=("play", "play with {target_id}"),
    ),
    define_action(
        "relax",
        ("target_id",),
        tool_name="relax",
        patterns=("relax", "relax on {target_id}"),
    ),
    define_action(
        "seek-privacy",
        ("target_id",),
        tool_name="seek_privacy",
        patterns=("seek privacy",),
    ),
    define_action(
        "seek-safety", ("target_id",), tool_name="seek_safety", patterns=("seek safety",)
    ),
    define_action("choose-aspiration", ("name", "milestones"), tool_name="choose_aspiration"),
    define_action(
        "complete-milestone", ("milestone", "reward_name"), tool_name="complete_milestone"
    ),
    define_action("practice-skill", ("skill", "xp"), tool_name="practice_skill"),
    define_action("study-skill", ("skill", "xp"), tool_name="study_skill"),
    define_action("mentor-skill", ("student_id", "skill", "xp"), tool_name="mentor_skill"),
    define_action(
        "update-profile",
        ("traits", "interests", "preferred_routine"),
        tool_name="update_profile",
    ),
    define_action("add-whim", ("want", "reward_xp"), tool_name="add_whim"),
    define_action("complete-whim", ("whim_id",), tool_name="complete_whim"),
    define_action("use-home-object", ("object_id",), tool_name="use_home_object"),
    define_action(
        "maintain-home-object",
        ("object_id", "action"),
        tool_name="maintain_home_object",
    ),
    define_action("invite-over", ("guest_id", "room_id"), tool_name="invite_over"),
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
    ),
    define_action("go-to-work", ("performance_gain",), tool_name="go_to_work"),
    define_action("quit-job", tool_name="quit_job"),
    define_action("pay-wage", ("worker_id", "amount"), tool_name="pay_wage"),
    define_action("assess-tax", ("amount", "reason", "due_epoch"), tool_name="assess_tax"),
    define_action(
        "charge-rent",
        ("tenant_id", "amount", "reason", "due_epoch"),
        tool_name="charge_rent",
        patterns=("charge rent {tenant_id} {amount}",),
    ),
    define_action(
        "pay-bill",
        ("bill_id",),
        tool_name="pay_bill",
        patterns=("pay bill {bill_id}", ActionPattern("pay bill", {})),
    ),
    define_action(
        "open-business",
        ("name", "default_price"),
        tool_name="open_business",
        patterns=("open business {name}",),
    ),
    define_action(
        "buy-item",
        ("seller_id", "item_id", "business_id", "price"),
        tool_name="buy_item",
        patterns=("buy {item_id} from {seller_id}",),
    ),
    define_action(
        "sell-item",
        ("item_id", "customer_id", "business_id", "price"),
        tool_name="sell_item",
        patterns=("sell {item_id} to {customer_id}",),
    ),
    define_action("promote-business", ("business_id",), tool_name="promote_business"),
    define_action(
        "join-household",
        ("household_id", "name"),
        tool_name="join_household",
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
        patterns=("claim home {room_id}", ActionPattern("claim home", {})),
    ),
    define_action(
        "claim-room",
        ("room_id",),
        tool_name="claim_room",
        patterns=("claim room {room_id}", ActionPattern("claim room", {})),
    ),
    define_action(
        "set-routine", ("activity", "interval_seconds", "next_due_epoch"), tool_name="set_routine"
    ),
    define_action(
        "set-relationship-status", ("target_id", "status"), tool_name="set_relationship_status"
    ),
    define_action(
        "spread-gossip", ("target_id", "text", "reputation_delta"), tool_name="spread_gossip"
    ),
    define_action(
        "witness-romance", ("partner_id", "rival_id", "intensity"), tool_name="witness_romance"
    ),
    define_action("start-partnership", ("target_id",), tool_name="start_partnership"),
    define_action("end-partnership", ("target_id",), tool_name="end_partnership"),
    define_action(
        "start-pregnancy", ("co_parent_id", "due_in_seconds"), tool_name="start_pregnancy"
    ),
    define_action("resolve-birth", ("child_name",), tool_name="resolve_birth"),
    define_action(
        "adopt-child",
        ("child_id",),
        tool_name="adopt_child",
        patterns=("adopt {child_id}",),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
