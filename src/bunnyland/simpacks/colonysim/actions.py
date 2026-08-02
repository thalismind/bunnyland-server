"""Action metadata owned by bunnyland.colonysim."""

from ...core.actions import (
    EPIC_ACTION_COST,
    EXTENDED_ACTION_COST,
    MAJOR_ACTION_COST,
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "reserve",
        ("target_id",),
        tool_name="reserve",
        description=(
            "Reserve a nearby item, resource node, or object so other colonists cannot "
            "claim or work it while you do. Reach the target first, and release the "
            "reservation when you are done."
        ),
    ),
    define_action(
        "release-reservation",
        ("target_id",),
        tool_name="release_reservation",
        description=(
            "Release a reservation you hold on an item or resource node, freeing it for "
            "other colonists to use."
        ),
    ),
    define_action(
        "gather-resource",
        ("node_id", "quantity"),
        tool_name="gather_resource",
        description=(
            "Harvest a quantity from a nearby resource node into your inventory as a "
            "stack. Reserve the node first if you want to keep others off it."
        ),
    ),
    define_action(
        "create-stockpile",
        ("name", "capacity", "allowed_types"),
        tool_name="create_stockpile",
        cost=EXTENDED_ACTION_COST,
        description=(
            "Set up a storage stockpile in your current room to collect hauled items. "
            "Optionally cap its capacity and restrict which resource types it accepts."
        ),
    ),
    define_action(
        "set-storage-filter",
        ("stockpile_id", "allowed_types"),
        tool_name="set_storage_filter",
        description=(
            "Restrict which resource types a reachable stockpile will accept, or clear "
            "the filter to let it hold anything."
        ),
    ),
    define_action(
        "forbid-item",
        ("item_id",),
        tool_name="forbid_item",
        description=(
            "Mark a reachable item as forbidden so it will not be hauled or used. Allow "
            "it again later to make it available."
        ),
    ),
    define_action(
        "allow-item",
        ("item_id",),
        tool_name="allow_item",
        description=(
            "Clear the forbidden mark on an item so it can be hauled and used again. "
            "Only works on items that are currently forbidden."
        ),
    ),
    define_action(
        "haul-item",
        ("item_id", "target_container_id"),
        tool_name="haul_item",
        description=(
            "Move a reachable item into a container or stockpile, respecting the "
            "stockpile's storage filter and capacity. Forbidden items cannot be hauled."
        ),
    ),
    define_action(
        "split-stack",
        ("item_id", "quantity"),
        tool_name="split_stack",
        description=(
            "Split a quantity off a resource stack into a new separate stack beside it. "
            "The amount must be smaller than the stack's total."
        ),
    ),
    define_action(
        "merge-stack",
        ("source_id", "target_id"),
        tool_name="merge_stack",
        description=(
            "Combine two reachable resource stacks of the same type into one. The source "
            "stack is emptied into the target."
        ),
    ),
    define_action(
        "craft",
        ("recipe_id",),
        tool_name="craft",
        cost=EXTENDED_ACTION_COST,
        description=(
            "Craft a recipe you know, consuming its input resources from your inventory "
            "and producing the outputs. Some recipes require a reachable workstation."
        ),
    ),
    define_action(
        "bake",
        ("recipe_id",),
        tool_name="bake",
        cost=EXTENDED_ACTION_COST,
        patterns=("bake {recipe_id}",),
        description=(
            "Bake a recipe at a stove or oven, consuming its ingredients and producing "
            "the finished food. Works like crafting, tuned for cooking."
        ),
    ),
    define_action(
        "set-work-priority",
        ("work_type", "priority"),
        tool_name="set_work_priority",
        description=(
            "Set your priority from 1 to 4 for a type of work, or 0 to stop doing it. "
            "Shapes which jobs you pick up first."
        ),
    ),
    define_action(
        "set-allowed-area",
        ("room_ids",),
        tool_name="set_allowed_area",
        description=(
            "Confine yourself to a set of rooms as your work area, replacing any previous "
            "allowed area. Pass valid room ids to bound where you roam."
        ),
    ),
    define_action(
        "update-pawn-profile",
        ("backstory", "passions", "expectations"),
        tool_name="update_pawn_profile",
        description=(
            "Update your colonist profile: backstory, work passions, and expectations. "
            "Passions mark the kinds of work you are drawn to."
        ),
    ),
    define_action(
        "progress-job-bill",
        ("bill_id", "work"),
        tool_name="progress_job_bill",
        description=(
            "Put work toward a nearby job bill, advancing it toward completion. Suspended "
            "or already-finished bills cannot be progressed."
        ),
    ),
    define_action(
        "set-prisoner-policy",
        ("prisoner_id", "policy"),
        tool_name="set_prisoner_policy",
        description=(
            "Set how a prisoner is handled: hold, recruit, or release. Set the policy to "
            "recruit before working to win them over."
        ),
    ),
    define_action(
        "recruit-prisoner",
        ("prisoner_id", "progress"),
        tool_name="recruit_prisoner",
        description=(
            "Spend effort recruiting a present prisoner toward joining your colony. The "
            "prisoner must be set to the recruit policy first."
        ),
    ),
    define_action(
        "research-project",
        ("project_id", "work"),
        tool_name="research_project",
        cost=EXTENDED_ACTION_COST,
        description=(
            "Put work into a research project, advancing it until it unlocks its "
            "technology. Projects already unlocked cannot be researched further."
        ),
    ),
    define_action(
        "complete-trade",
        ("offer_id",),
        tool_name="complete_trade",
        description=(
            "Complete a faction trade offer, handing over the goods it wants and "
            "receiving what it gives. You must carry everything the offer requires."
        ),
    ),
    define_action(
        "form-caravan",
        ("destination", "cargo", "member_ids"),
        tool_name="form_caravan",
        cost=MAJOR_ACTION_COST,
        description=(
            "Assemble a caravan bound for a destination, loading cargo from your "
            "inventory and enrolling member colonists. A major effort that sends them off."
        ),
    ),
    define_action(
        "visit-settlement",
        ("caravan_id",),
        tool_name="visit_settlement",
        description=(
            "Mark an arrived caravan's destination as visited, opening settlement trade "
            "and quest hooks. You must be enrolled in the caravan."
        ),
    ),
    define_action(
        "return-caravan",
        ("caravan_id",),
        tool_name="return_caravan",
        description=(
            "Send a visiting caravan back to its origin along the current live route. "
            "The caravan and its co-located members travel together."
        ),
    ),
    define_action(
        "perform-surgery",
        ("patient_id", "surgery_id"),
        tool_name="perform_surgery",
        cost=EXTENDED_ACTION_COST,
        description=(
            "Carry out a surgery bill on a reachable patient, completing the operation "
            "such as amputating, healing, or installing a prosthetic body part."
        ),
    ),
    define_action(
        "tend-wound",
        ("patient_id", "injury_id", "medicine_id"),
        tool_name="tend_wound",
        description=(
            "Treat a patient's injury to ease its pain and slow its bleeding, using "
            "medicine for a stronger result. Reach the patient; the injury must be theirs."
        ),
    ),
    define_action(
        "rescue-to-bed",
        ("patient_id", "bed_id"),
        tool_name="rescue_to_bed",
        description=(
            "Carry a downed character to a reachable medical bed and lay them down to "
            "recover. The patient must be downed and the bed must be a medical bed."
        ),
    ),
    define_action(
        "assign-job",
        ("job_id",),
        tool_name="assign_job",
        description=(
            "Take on an available job by assigning it to yourself so you can work and "
            "complete it. Jobs already claimed by someone else are off limits."
        ),
    ),
    define_action(
        "complete-job",
        ("job_id",),
        tool_name="complete_job",
        description=(
            "Mark a job assigned to you as finished. You must be the worker it is "
            "currently assigned to."
        ),
    ),
    define_action(
        "claim-ownership",
        ("target_id",),
        tool_name="claim_ownership",
        patterns=("claim {target_id}",),
        description=(
            "Claim personal ownership of a reachable item or furnishing, such as a bed, "
            "so it becomes yours. Only unowned targets can be claimed."
        ),
    ),
    define_action(
        "release-ownership",
        ("target_id",),
        tool_name="release_ownership",
        patterns=("release ownership {target_id}",),
        description=(
            "Give up ownership of something you own, making it available for others to "
            "claim."
        ),
    ),
    define_action(
        "resolve-colony-incident",
        ("incident_id",),
        tool_name="resolve_colony_incident",
        cost=EPIC_ACTION_COST,
        description=(
            "Resolve an active colony incident, marking it settled once the threat or "
            "event has been dealt with. Already-resolved incidents cannot be resolved."
        ),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
