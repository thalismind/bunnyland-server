"""Action metadata owned by bunnyland.neonsim."""

from ...core.actions import (
    EXTENDED_ACTION_COST,
    MAJOR_ACTION_COST,
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "enter-district",
        ("target_id",),
        tool_name="enter_district",
        patterns=("enter {target_id}", "sneak into {target_id}"),
    ),
    define_action(
        "show-credentials",
        ("target_id",),
        tool_name="show_credentials",
        patterns=("show credentials at {target_id}",),
    ),
    define_action(
        "claim-safehouse", ("target_id",), tool_name="claim_safehouse", cost=MAJOR_ACTION_COST
    ),
    define_action(
        "case-location",
        ("target_id",),
        tool_name="case_location",
        patterns=("case {target_id}", "scope out {target_id}"),
    ),
    define_action(
        "disable-camera",
        ("target_id",),
        tool_name="disable_camera",
        patterns=("disable camera {target_id}",),
    ),
    define_action(
        "loop-camera",
        ("target_id",),
        tool_name="loop_camera",
        patterns=("loop camera {target_id}", "loop the feed on {target_id}"),
    ),
    define_action(
        "jam-sensor",
        ("target_id",),
        tool_name="jam_sensor",
        patterns=("jam sensor {target_id}",),
    ),
    define_action(
        "deploy-drone",
        ("target_id",),
        tool_name="deploy_drone",
        patterns=("deploy drone {target_id}",),
    ),
    define_action(
        "wipe-evidence",
        ("target_id",),
        tool_name="wipe_evidence",
        patterns=("wipe evidence {target_id}", "erase the footage {target_id}"),
    ),
    define_action("scan-network", ("target_id",), tool_name="scan_network"),
    define_action("trace-network", ("target_id",), tool_name="trace_network"),
    define_action(
        "run-exploit",
        ("target_id",),
        tool_name="run_exploit",
        patterns=("run exploit on {target_id}", "hack {target_id}"),
    ),
    define_action("use-credential", ("target_id",), tool_name="use_credential"),
    define_action("access-terminal", ("target_id",), tool_name="access_terminal"),
    define_action(
        "escalate-privileges",
        ("target_id",),
        tool_name="escalate_privileges",
        patterns=("escalate privileges on {target_id}",),
    ),
    define_action(
        "install-backdoor", ("target_id",), tool_name="install_backdoor", cost=EXTENDED_ACTION_COST
    ),
    define_action(
        "exfiltrate-data",
        ("target_id",),
        tool_name="exfiltrate_data",
        patterns=("exfiltrate data from {target_id}", "steal data from {target_id}"),
    ),
    define_action(
        "sabotage-system",
        ("target_id",),
        tool_name="sabotage_system",
        cost=EXTENDED_ACTION_COST,
        patterns=("sabotage {target_id}",),
    ),
    define_action("evade-trace", (), tool_name="evade_trace", patterns=("evade the trace",)),
    define_action("spoof-identity", (), tool_name="spoof_identity", patterns=("spoof your id",)),
    define_action(
        "buy-contraband",
        ("target_id",),
        tool_name="buy_contraband",
        patterns=("buy contraband from {target_id}",),
    ),
    define_action(
        "sell-data",
        ("broker_id", "data_id"),
        tool_name="sell_data",
        patterns=("sell {data_id} to {broker_id}",),
    ),
    define_action(
        "call-favor",
        ("target_id",),
        tool_name="call_favor",
        patterns=("call in a favor from {target_id}",),
    ),
    define_action("pay-debt", (), tool_name="pay_debt", patterns=("pay off your debt",)),
    define_action("hide-from-law", (), tool_name="hide_from_law", patterns=("lay low",)),
    define_action("clear-warrant", (), tool_name="clear_warrant", patterns=("clear your warrant",)),
    define_action(
        "post-bounty",
        ("target_id", "amount"),
        tool_name="post_bounty",
        patterns=("post a bounty on {target_id}",),
    ),
    define_action(
        "turn-informant",
        ("target_id",),
        tool_name="turn_informant",
        patterns=("turn {target_id} into an informant",),
    ),
    define_action(
        "install-implant",
        ("implant_id", "clinic_id"),
        tool_name="install_implant",
        cost=EXTENDED_ACTION_COST,
        patterns=("install {implant_id} at {clinic_id}",),
    ),
    define_action(
        "remove-implant",
        ("implant_id",),
        tool_name="remove_implant",
        patterns=("remove implant {implant_id}",),
    ),
    define_action(
        "service-implant",
        ("implant_id", "clinic_id"),
        tool_name="service_implant",
        patterns=("service {implant_id} at {clinic_id}",),
    ),
    define_action(
        "overclock-implant",
        ("implant_id",),
        tool_name="overclock_implant",
        patterns=("overclock {implant_id}",),
    ),
    define_action(
        "disable-implant",
        ("implant_id",),
        tool_name="disable_implant",
        patterns=("disable implant {implant_id}",),
    ),
    define_action(
        "license-implant",
        ("implant_id",),
        tool_name="license_implant",
        patterns=("license {implant_id}",),
    ),
    define_action(
        "scan-implant",
        ("target_id",),
        tool_name="scan_implant",
        patterns=("scan {target_id} for implants",),
    ),
    define_action(
        "exploit-implant",
        ("target_id",),
        tool_name="exploit_implant",
        patterns=("exploit the implants of {target_id}",),
    ),
    define_action(
        "take-fixer-job",
        ("target_id",),
        tool_name="take_fixer_job",
        patterns=("take the job {target_id}",),
    ),
    define_action(
        "meet-handler",
        ("target_id",),
        tool_name="meet_handler",
        patterns=("meet handler {target_id}",),
    ),
    define_action(
        "deliver-data",
        ("contract_id", "data_id"),
        tool_name="deliver_data",
        patterns=("deliver {data_id} for {contract_id}",),
    ),
    define_action(
        "collect-payout",
        ("target_id",),
        tool_name="collect_payout",
        patterns=("collect payout for {target_id}",),
    ),
    define_action(
        "burn-contact",
        ("target_id",),
        tool_name="burn_contact",
        patterns=("burn {target_id}",),
    ),
    define_action(
        "plant-evidence",
        ("target_id",),
        tool_name="plant_evidence",
        patterns=("plant evidence on {target_id}",),
    ),
    define_action(
        "blackmail-target",
        ("target_id", "file_id"),
        tool_name="blackmail_target",
        patterns=("blackmail {target_id} with {file_id}",),
    ),
    define_action(
        "leak-file",
        ("target_id",),
        tool_name="leak_file",
        patterns=("leak {target_id}",),
    ),
    define_action(
        "extract-asset",
        ("target_id",),
        tool_name="extract_asset",
        patterns=("extract {target_id}",),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
