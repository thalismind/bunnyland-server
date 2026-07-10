"""Action metadata owned by bunnyland.voidsim."""

from ...core.actions import (
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action("open-airlock", ("airlock_id",), tool_name="open_airlock"),
    define_action("cycle-airlock", ("airlock_id",), tool_name="cycle_airlock"),
    define_action("seal-bulkhead", ("bulkhead_id",), tool_name="seal_bulkhead"),
    define_action("repair-system", ("system_id",), tool_name="repair_system"),
    define_action("reroute-power", ("grid_id", "system_id", "amount"), tool_name="reroute_power"),
    define_action("fabricate", ("fabricator_id", "blueprint_id"), tool_name="fabricate"),
    define_action("install-upgrade", ("upgrade_id", "system_id"), tool_name="install_upgrade"),
    define_action("accept-contract", ("contract_id",), tool_name="accept_contract"),
    define_action("load-cargo", ("contract_id", "cargo_id", "ship_id"), tool_name="load_cargo"),
    define_action(
        "deliver-cargo",
        ("contract_id", "cargo_id", "ship_id"),
        tool_name="deliver_cargo",
    ),
    define_action("claim-salvage", ("claim_id", "contract_id"), tool_name="claim_salvage"),
    define_action("initiate-contact", ("contact_id",), tool_name="initiate_contact"),
    define_action(
        "attempt-translation",
        ("matrix_id", "progress"),
        tool_name="attempt_translation",
    ),
    define_action("quarantine-sample", ("target_id", "reason"), tool_name="quarantine_sample"),
    define_action(
        "negotiate-alien",
        ("mission_id", "standing_delta"),
        tool_name="negotiate_alien",
    ),
    define_action(
        "study-alien-artifact",
        ("artifact_id",),
        tool_name="study_alien_artifact",
    ),
    define_action("dock", ("ship_id", "station_id", "port"), tool_name="dock"),
    define_action("undock", ("ship_id", "station_id"), tool_name="undock"),
    define_action("evacuate-module", ("module_id", "destination_id"), tool_name="evacuate_module"),
    define_action("plot-course", ("ship_id", "destination_id"), tool_name="plot_course"),
    define_action("jump", ("ship_id",), tool_name="jump"),
    define_action("scan", ("ship_id",), tool_name="scan"),
    define_action("answer-distress-signal", ("signal_id",), tool_name="answer_distress_signal"),
    define_action("refuel", ("ship_id", "amount"), tool_name="refuel"),
    define_action(
        "assign-crew-shift",
        ("shift_id", "station"),
        tool_name="assign_crew_shift",
        patterns=("take watch {shift_id}",),
    ),
    define_action(
        "relieve-crew-shift",
        ("shift_id",),
        tool_name="relieve_crew_shift",
        patterns=("stand down from watch {shift_id}",),
    ),
    define_action("deploy-away-team", ("team_id",), tool_name="deploy_away_team"),
    define_action("boost-morale", ("amount",), tool_name="boost_morale"),
    define_action("start-mutiny", tool_name="start_mutiny"),
    define_action("command-drone", ("drone_id", "task"), tool_name="command_drone"),
    define_action("hack-ship-ai", ("ai_id",), tool_name="hack_ship_ai"),
    define_action("salvage-data", ("data_id",), tool_name="salvage_data"),
    define_action(
        "study-xenobiology",
        ("sample_id",),
        tool_name="study_xenobiology",
    ),
    define_action(
        "accept-trade-protocol",
        ("protocol_id",),
        tool_name="accept_trade_protocol",
    ),
    define_action("resolve-emergency", ("emergency_id",), tool_name="resolve_emergency"),
    define_action(
        "stabilize-reactor",
        ("reactor_id", "amount"),
        tool_name="stabilize_reactor",
    ),
    define_action(
        "adjust-gravity",
        ("gravity_id", "enabled", "strength"),
        tool_name="adjust_gravity",
    ),
    define_action("repel-boarders", ("threat_id",), tool_name="repel_boarders"),
    define_action("deliver-passenger", ("passenger_id",), tool_name="deliver_passenger"),
    define_action("survey-site", ("site_id",), tool_name="survey_site"),
    define_action(
        "mine-asteroid",
        ("site_id", "quantity"),
        tool_name="mine_asteroid",
    ),
    define_action(
        "search-smuggling-compartment",
        ("compartment_id",),
        tool_name="search_smuggling_compartment",
    ),
    define_action("claim-insurance", ("policy_id",), tool_name="claim_insurance"),
    define_action("pay-mortgage", ("mortgage_id", "amount"), tool_name="pay_mortgage"),
    define_action("enter-orbit", ("ship_id", "body_id"), tool_name="enter_orbit"),
    define_action("leave-orbit", ("ship_id",), tool_name="leave_orbit"),
    define_action("land", ("ship_id",), tool_name="land"),
    define_action("launch", ("ship_id",), tool_name="launch"),
)

__all__ = ["ACTION_DEFINITIONS"]
