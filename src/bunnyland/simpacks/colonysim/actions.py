"""Action metadata owned by bunnyland.colonysim."""

from ...core.actions import (
    EPIC_ACTION_COST,
    EXTENDED_ACTION_COST,
    MAJOR_ACTION_COST,
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action("reserve", ("target_id",), tool_name="reserve"),
    define_action("release-reservation", ("target_id",), tool_name="release_reservation"),
    define_action("gather-resource", ("node_id", "quantity"), tool_name="gather_resource"),
    define_action(
        "create-stockpile",
        ("name", "capacity", "allowed_types"),
        tool_name="create_stockpile",
        cost=EXTENDED_ACTION_COST,
    ),
    define_action(
        "set-storage-filter",
        ("stockpile_id", "allowed_types"),
        tool_name="set_storage_filter",
    ),
    define_action("forbid-item", ("item_id",), tool_name="forbid_item"),
    define_action("allow-item", ("item_id",), tool_name="allow_item"),
    define_action(
        "haul-item",
        ("item_id", "target_container_id"),
        tool_name="haul_item",
    ),
    define_action("split-stack", ("item_id", "quantity"), tool_name="split_stack"),
    define_action("merge-stack", ("source_id", "target_id"), tool_name="merge_stack"),
    define_action("craft", ("recipe_id",), tool_name="craft", cost=EXTENDED_ACTION_COST),
    define_action(
        "bake",
        ("recipe_id",),
        tool_name="bake",
        cost=EXTENDED_ACTION_COST,
        patterns=("bake {recipe_id}",),
    ),
    define_action("set-work-priority", ("work_type", "priority"), tool_name="set_work_priority"),
    define_action("set-allowed-area", ("room_ids",), tool_name="set_allowed_area"),
    define_action(
        "update-pawn-profile",
        ("backstory", "passions", "expectations"),
        tool_name="update_pawn_profile",
    ),
    define_action("progress-job-bill", ("bill_id", "work"), tool_name="progress_job_bill"),
    define_action(
        "set-prisoner-policy",
        ("prisoner_id", "policy"),
        tool_name="set_prisoner_policy",
    ),
    define_action(
        "recruit-prisoner",
        ("prisoner_id", "progress"),
        tool_name="recruit_prisoner",
    ),
    define_action(
        "research-project",
        ("project_id", "work"),
        tool_name="research_project",
        cost=EXTENDED_ACTION_COST,
    ),
    define_action("complete-trade", ("offer_id",), tool_name="complete_trade"),
    define_action(
        "form-caravan",
        ("destination", "cargo", "member_ids"),
        tool_name="form_caravan",
        cost=MAJOR_ACTION_COST,
    ),
    define_action(
        "perform-surgery",
        ("patient_id", "surgery_id"),
        tool_name="perform_surgery",
        cost=EXTENDED_ACTION_COST,
    ),
    define_action("tend-wound", ("patient_id", "injury_id", "medicine_id"), tool_name="tend_wound"),
    define_action("rescue-to-bed", ("patient_id", "bed_id"), tool_name="rescue_to_bed"),
    define_action("assign-job", ("job_id",), tool_name="assign_job"),
    define_action("complete-job", ("job_id",), tool_name="complete_job"),
    define_action(
        "claim-ownership",
        ("target_id",),
        tool_name="claim_ownership",
        patterns=("claim {target_id}",),
    ),
    define_action(
        "release-ownership",
        ("target_id",),
        tool_name="release_ownership",
        patterns=("release ownership {target_id}",),
    ),
    define_action(
        "resolve-colony-incident",
        ("incident_id",),
        tool_name="resolve_colony_incident",
        cost=EPIC_ACTION_COST,
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
