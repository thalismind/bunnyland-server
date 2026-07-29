"""Action metadata owned by bunnyland.voidsim."""

from ...core.actions import (
    EPIC_ACTION_COST,
    EXTENDED_ACTION_COST,
    MAJOR_ACTION_COST,
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "open-airlock",
        ("airlock_id",),
        tool_name="open_airlock",
        description=(
            "Open a nearby airlock so crew or cargo can pass through. If the airlock "
            "exposes vacuum, opening it depressurizes the connected module to zero, so "
            "clear the space first."
        ),
    ),
    define_action(
        "cycle-airlock",
        ("airlock_id",),
        tool_name="cycle_airlock",
        description=(
            "Cycle an open airlock back to a sealed state, closing it behind you. "
            "Use this to secure a hatch after moving through it."
        ),
    ),
    define_action(
        "seal-bulkhead",
        ("bulkhead_id",),
        tool_name="seal_bulkhead",
        description=(
            "Seal a bulkhead shut to wall off a section from fire, a hull breach, or "
            "spreading hazards. Only works on a bulkhead that is not already sealed."
        ),
    ),
    define_action(
        "repair-system",
        ("system_id",),
        tool_name="repair_system",
        description=(
            "Repair a damaged or offline ship system, restoring it to full integrity "
            "and bringing it back online. Inspect a system first to see if it needs work."
        ),
    ),
    define_action(
        "reroute-power",
        ("grid_id", "system_id", "amount"),
        tool_name="reroute_power",
        description=(
            "Draw power from a grid and route it to a ship system to bring it online. "
            "The grid must have enough available power for the amount you request."
        ),
    ),
    define_action(
        "fabricate",
        ("fabricator_id", "blueprint_id"),
        tool_name="fabricate",
        description=(
            "Build an upgrade part from a blueprint at an online fabricator, consuming "
            "the blueprint's resource inputs from your inventory. The blueprint's "
            "required technology must already be researched."
        ),
        cost=EXTENDED_ACTION_COST,
    ),
    define_action(
        "install-upgrade",
        ("upgrade_id", "system_id"),
        tool_name="install_upgrade",
        description=(
            "Install an upgrade onto a matching ship system, boosting its integrity and "
            "bringing it online. The upgrade must fit the system's type and not already "
            "be installed."
        ),
        cost=EXTENDED_ACTION_COST,
    ),
    define_action(
        "accept-contract",
        ("contract_id",),
        tool_name="accept_contract",
        description=(
            "Accept an offered contract, taking it into your inventory and marking it "
            "active. Look for available contracts at stations before hauling or salvaging."
        ),
    ),
    define_action(
        "load-cargo",
        ("contract_id", "cargo_id", "ship_id"),
        tool_name="load_cargo",
        description=(
            "Load a haul contract's cargo aboard a ship so you can carry it. The cargo "
            "contract must be active and the cargo must match it and not yet be loaded."
        ),
    ),
    define_action(
        "deliver-cargo",
        ("contract_id", "cargo_id", "ship_id"),
        tool_name="deliver_cargo",
        description=(
            "Unload cargo at the contract's destination to complete the haul and earn "
            "its reward. Plot a course and jump the loaded ship to the destination first."
        ),
    ),
    define_action(
        "claim-salvage",
        ("claim_id", "contract_id"),
        tool_name="claim_salvage",
        description=(
            "Claim an unclaimed salvage site, collecting its resources into your "
            "inventory. Some salvage requires that you hold the matching rights contract."
        ),
    ),
    define_action(
        "initiate-contact",
        ("contact_id",),
        tool_name="initiate_contact",
        description=(
            "Make first contact with an alien species you have encountered, opening the "
            "door to diplomacy and translation. Each character can initiate contact once."
        ),
    ),
    define_action(
        "attempt-translation",
        ("matrix_id", "progress"),
        tool_name="attempt_translation",
        description=(
            "Work on a translation matrix to decode an alien language, advancing its "
            "progress. Keep at it until the matrix reaches completion."
        ),
    ),
    define_action(
        "quarantine-sample",
        ("target_id", "reason"),
        tool_name="quarantine_sample",
        description=(
            "Place a reachable organism, sample, or object under quarantine with a "
            "stated reason. Use it to flag a possible contamination or biohazard."
        ),
    ),
    define_action(
        "negotiate-alien",
        ("mission_id", "standing_delta"),
        tool_name="negotiate_alien",
        description=(
            "Negotiate on a diplomatic mission to shift your standing with an alien "
            "species up or down. Use a positive change to build goodwill."
        ),
    ),
    define_action(
        "study-alien-artifact",
        ("artifact_id",),
        tool_name="study_alien_artifact",
        description=(
            "Study a reachable alien artifact to draw out its insight about the species "
            "that made it. Each character can study a given artifact only once."
        ),
    ),
    define_action(
        "dock",
        ("ship_id", "station_id", "port"),
        tool_name="dock",
        description=(
            "Dock a ship at a station's port so crew and cargo can transfer. The ship "
            "must not already be docked there."
        ),
    ),
    define_action(
        "undock",
        ("ship_id", "station_id"),
        tool_name="undock",
        description=(
            "Release a ship from the station it is docked at so it can maneuver or "
            "travel. The ship must currently be docked there."
        ),
    ),
    define_action(
        "evacuate-module",
        ("module_id", "destination_id"),
        tool_name="evacuate_module",
        description=(
            "Move every crew member out of a habitat module to a safer destination. "
            "Reach for this when a module loses pressure, catches fire, or is breached."
        ),
    ),
    define_action(
        "plot-course",
        ("ship_id", "destination_id"),
        tool_name="plot_course",
        description=(
            "Plot a jump course from the ship's current star system to a destination "
            "system along a known jump route. Scan or check the map for reachable systems."
        ),
    ),
    define_action(
        "jump",
        ("ship_id",),
        tool_name="jump",
        description=(
            "Fire the jump drive to travel a plotted course, burning fuel and arriving "
            "after a delay. Requires a charged drive and enough fuel; low astrogation "
            "skill risks hazards along the way."
        ),
    ),
    define_action(
        "scan",
        ("ship_id",),
        tool_name="scan",
        description=(
            "Sweep the current star system with the ship's sensors to detect distress "
            "signals and other hidden contacts. Scan before answering any signal."
        ),
    ),
    define_action(
        "answer-distress-signal",
        ("signal_id",),
        tool_name="answer_distress_signal",
        description=(
            "Respond to a distress signal you have already detected, marking it "
            "answered. Scan the system first to pick up signals worth answering."
        ),
    ),
    define_action(
        "refuel",
        ("ship_id", "amount"),
        tool_name="refuel",
        description=(
            "Refill a ship's fuel tank, either to the brim or by a set amount. Top off "
            "before a long jump so you do not strand the ship."
        ),
    ),
    define_action(
        "assign-crew-shift",
        ("shift_id", "station"),
        tool_name="assign_crew_shift",
        description=(
            "Take up a duty shift at an assigned station so you stand watch during its "
            "hours. You cannot join a shift you are already assigned to."
        ),
        patterns=("take watch {shift_id}",),
    ),
    define_action(
        "relieve-crew-shift",
        ("shift_id",),
        tool_name="relieve_crew_shift",
        description=(
            "Stand down from a duty shift you are assigned to, dropping the watch. You "
            "must currently hold that shift."
        ),
        patterns=("stand down from watch {shift_id}",),
    ),
    define_action(
        "deploy-away-team",
        ("team_id",),
        tool_name="deploy_away_team",
        description=(
            "Send an away team out on its mission to a surface, wreck, or station. The "
            "team must not already be deployed."
        ),
        cost=MAJOR_ACTION_COST,
    ),
    define_action(
        "boost-morale",
        ("amount",),
        tool_name="boost_morale",
        description=(
            "Rally your own spirits, raising your morale by the given amount. Keep "
            "morale up to steady yourself through a hard voyage."
        ),
    ),
    define_action(
        "start-mutiny",
        tool_name="start_mutiny",
        description=(
            "Rise up against the ship's command, marking yourself as the ringleader of "
            "a mutiny. A drastic move when you have lost faith in the current captain."
        ),
    ),
    define_action(
        "hack-ship-ai",
        ("ai_id",),
        tool_name="hack_ship_ai",
        description=(
            "Break into a ship AI to seize control, flagging it hacked and nudging its "
            "trust in you. Use it to bend an uncooperative AI to your orders."
        ),
    ),
    define_action(
        "salvage-data",
        ("data_id",),
        tool_name="salvage_data",
        description=(
            "Decrypt and recover a salvaged data cache, pulling its contents for "
            "yourself. Look for data salvage aboard wrecks and derelicts."
        ),
    ),
    define_action(
        "study-xenobiology",
        ("sample_id",),
        tool_name="study_xenobiology",
        description=(
            "Examine a xenobiology sample to learn about alien life and gauge its "
            "contamination. Each character can study a given sample once."
        ),
    ),
    define_action(
        "accept-trade-protocol",
        ("protocol_id",),
        tool_name="accept_trade_protocol",
        description=(
            "Agree to an alien or station trade protocol, accepting its terms so trade "
            "can proceed. Review the terms before you commit."
        ),
    ),
    define_action(
        "resolve-emergency",
        ("emergency_id",),
        tool_name="resolve_emergency",
        description=(
            "Bring an active shipboard emergency under control and mark it resolved. "
            "Reach for this to clear fires, breaches, and other crises."
        ),
        cost=EPIC_ACTION_COST,
    ),
    define_action(
        "stabilize-reactor",
        ("reactor_id", "amount"),
        tool_name="stabilize_reactor",
        description=(
            "Tune a reactor to raise its stability and keep it online. Stabilize it "
            "before a runaway reaction endangers the ship."
        ),
    ),
    define_action(
        "adjust-gravity",
        ("gravity_id", "enabled", "strength"),
        tool_name="adjust_gravity",
        description=(
            "Set a gravity generator on or off and dial its strength. Use it to restore "
            "footing or float cargo free."
        ),
    ),
    define_action(
        "repel-boarders",
        ("threat_id",),
        tool_name="repel_boarders",
        description=(
            "Fight off a boarding party, marking the threat repelled. Act fast when "
            "hostiles breach the hull."
        ),
    ),
    define_action(
        "deliver-passenger",
        ("passenger_id",),
        tool_name="deliver_passenger",
        description=(
            "Drop off a passenger you are carrying at their destination, marking the "
            "fare delivered. Arrive at the destination before you deliver them."
        ),
    ),
    define_action(
        "survey-site",
        ("site_id",),
        tool_name="survey_site",
        description=(
            "Survey a site to identify the resource it holds and log your findings. "
            "Survey before committing crew or ships to mining it."
        ),
    ),
    define_action(
        "mine-asteroid",
        ("site_id", "quantity"),
        tool_name="mine_asteroid",
        description=(
            "Extract ore from a mining site into your inventory, depleting the site by "
            "what you take. A depleted site yields nothing more."
        ),
    ),
    define_action(
        "search-smuggling-compartment",
        ("compartment_id",),
        tool_name="search_smuggling_compartment",
        description=(
            "Search a smuggling compartment to uncover whatever is hidden inside. Use "
            "it during inspections to find contraband."
        ),
    ),
    define_action(
        "claim-insurance",
        ("policy_id",),
        tool_name="claim_insurance",
        description=(
            "File a claim against an insurance policy to collect its payout. Each "
            "policy can only be claimed once."
        ),
    ),
    define_action(
        "pay-mortgage",
        ("mortgage_id", "amount"),
        tool_name="pay_mortgage",
        description=(
            "Pay down a mortgage balance by the amount you specify. Keep up payments to "
            "hold onto a financed ship or station."
        ),
    ),
    define_action(
        "enter-orbit",
        ("ship_id", "body_id"),
        tool_name="enter_orbit",
        description=(
            "Bring a ship into orbit around a planet, moon, or other body. Orbit a "
            "landable body before attempting to land on it."
        ),
    ),
    define_action(
        "leave-orbit",
        ("ship_id",),
        tool_name="leave_orbit",
        description=(
            "Break a ship out of orbit so it can maneuver or travel elsewhere. The ship "
            "must currently be in orbit."
        ),
    ),
    define_action(
        "land",
        ("ship_id",),
        tool_name="land",
        description=(
            "Set an orbiting ship down on the surface of the body it orbits. The body "
            "must be landable and the ship must already be in orbit."
        ),
    ),
    define_action(
        "launch",
        ("ship_id",),
        tool_name="launch",
        description=(
            "Lift a landed ship off a surface and back into orbit. The ship must "
            "currently be sitting on a surface."
        ),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
