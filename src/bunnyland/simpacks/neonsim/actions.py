"""Action metadata owned by bunnyland.neonsim."""

from ...core.actions import (
    EXTENDED_ACTION_COST,
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "enter-district",
        ("target_id",),
        tool_name="enter_district",
        description=(
            "Enter a neon-district site such as a tower, club, or restricted zone. Secured "
            "zones demand clearance or a matching pass, so case the location first or slip in "
            "covertly and risk the patrols catching you."
        ),
        patterns=("enter {target_id}", "sneak into {target_id}"),
    ),
    define_action(
        "show-credentials",
        ("target_id",),
        tool_name="show_credentials",
        description=(
            "Present your clearance at a manned checkpoint to pass through legitimately. Only "
            "works when your clearance level or a held pass matches what the gate demands."
        ),
        patterns=("show credentials at {target_id}",),
    ),
    define_action(
        "case-location",
        ("target_id",),
        tool_name="case_location",
        description=(
            "Scout a site before you move, learning its required clearance, whether it is "
            "restricted, and if a checkpoint guards it. Do this first to plan a clean approach."
        ),
        patterns=("case {target_id}", "scope out {target_id}"),
    ),
    define_action(
        "disable-camera",
        ("target_id",),
        tool_name="disable_camera",
        description=(
            "Cut a camera offline so it stops watching and can record no evidence. Inspect a "
            "device first to confirm it is a camera that is not already disabled."
        ),
        patterns=("disable camera {target_id}",),
    ),
    define_action(
        "loop-camera",
        ("target_id",),
        tool_name="loop_camera",
        description=(
            "Feed a camera a looping signal so it keeps running but records nothing new. The "
            "camera must be powered and not already disabled or looped."
        ),
        patterns=("loop camera {target_id}", "loop the feed on {target_id}"),
    ),
    define_action(
        "jam-sensor",
        ("target_id",),
        tool_name="jam_sensor",
        description=(
            "Jam a security sensor so it stops detecting movement. The target must be a sensor "
            "device within reach that is not already jammed."
        ),
        patterns=("jam sensor {target_id}",),
    ),
    define_action(
        "deploy-drone",
        ("target_id",),
        tool_name="deploy_drone",
        description=(
            "Activate a drone so it powers up and starts operating. The drone must be reachable "
            "and not already deployed."
        ),
        patterns=("deploy drone {target_id}",),
    ),
    define_action(
        "wipe-evidence",
        ("target_id",),
        tool_name="wipe_evidence",
        description=(
            "Permanently destroy recorded footage before it can be used against you. Look in the "
            "room to find the recorded evidence you want erased."
        ),
        patterns=("wipe evidence {target_id}", "erase the footage {target_id}"),
    ),
    define_action(
        "scan-network",
        ("target_id",),
        tool_name="scan_network",
        description=(
            "Probe a networked device to read its security rating and whether it is already "
            "breached. Scan before deciding how to hack it."
        ),
    ),
    define_action(
        "trace-network",
        ("target_id",),
        tool_name="trace_network",
        description=(
            "Map the networked devices sharing a device's room, revealing how many hackable nodes "
            "surround it. Use it to find further targets."
        ),
    ),
    define_action(
        "run-exploit",
        ("target_id",),
        tool_name="run_exploit",
        description=(
            "Attack a device's security with the strongest exploit in your inventory to breach it. "
            "A success starts a counter-intrusion trace, and a failure trips the alarm, so carry "
            "an exploit powerful enough for the job."
        ),
        patterns=("run exploit on {target_id}", "hack {target_id}"),
    ),
    define_action(
        "use-credential",
        ("target_id",),
        tool_name="use_credential",
        description=(
            "Open a network device with a matching stolen credential instead of hacking it, "
            "gaining access without starting a trace. You must carry a credential for that "
            "system's owner."
        ),
    ),
    define_action(
        "access-terminal",
        ("target_id",),
        tool_name="access_terminal",
        description=(
            "Read and operate a terminal you have already breached or backdoored. Breach the "
            "system first if it is still locked."
        ),
    ),
    define_action(
        "escalate-privileges",
        ("target_id",),
        tool_name="escalate_privileges",
        description=(
            "Elevate your access on a breached system to admin, unlocking its most sensitive "
            "functions and data. Breach or backdoor the system first."
        ),
        patterns=("escalate privileges on {target_id}",),
    ),
    define_action(
        "install-backdoor",
        ("target_id",),
        tool_name="install_backdoor",
        cost=EXTENDED_ACTION_COST,
        description=(
            "Plant a persistent backdoor on a breached system so you can re-enter later without "
            "tripping a fresh trace. Breach the system first."
        ),
    ),
    define_action(
        "exfiltrate-data",
        ("target_id",),
        tool_name="exfiltrate_data",
        description=(
            "Copy a data payload off a breached system into your inventory to sell or deliver. "
            "Sensitive data requires admin privileges, so escalate first if you must."
        ),
        patterns=("exfiltrate data from {target_id}", "steal data from {target_id}"),
    ),
    define_action(
        "sabotage-system",
        ("target_id",),
        tool_name="sabotage_system",
        cost=EXTENDED_ACTION_COST,
        description=(
            "Wreck a breached system so it goes offline and stops functioning. Breach or backdoor "
            "it before you can sabotage it."
        ),
        patterns=("sabotage {target_id}",),
    ),
    define_action(
        "evade-trace",
        (),
        tool_name="evade_trace",
        description=(
            "Shake off an active counter-intrusion trace before it expires and raises the alarm. "
            "Only usable while a trace is actively hunting you."
        ),
        patterns=("evade the trace",),
    ),
    define_action(
        "spoof-identity",
        (),
        tool_name="spoof_identity",
        description=(
            "Buy time against an active trace by feeding it a false identity, pushing back the "
            "moment it expires. Reach for it when you cannot fully evade yet."
        ),
        patterns=("spoof your id",),
    ),
    define_action(
        "buy-contraband",
        ("target_id",),
        tool_name="buy_contraband",
        description=(
            "Purchase illicit goods from a black-market vendor for scrip, which adds heat that "
            "draws police attention. Find a vendor in the room first."
        ),
        patterns=("buy contraband from {target_id}",),
    ),
    define_action(
        "sell-data",
        ("broker_id", "data_id"),
        tool_name="sell_data",
        description=(
            "Fence a stolen data payload to a data broker for scrip, with sensitive data paying "
            "double. You must be carrying the data and standing with a broker."
        ),
        patterns=("sell {data_id} to {broker_id}",),
    ),
    define_action(
        "call-favor",
        ("target_id",),
        tool_name="call_favor",
        description=(
            "Cash in a favor a contact owes you. Only works on someone who actually owes you one, "
            "such as a mark you have blackmailed."
        ),
        patterns=("call in a favor from {target_id}",),
    ),
    define_action(
        "pay-debt",
        (),
        tool_name="pay_debt",
        description=(
            "Spend scrip to pay down what you owe, clearing the debt once it reaches zero. You "
            "need scrip on hand to make a payment."
        ),
        patterns=("pay off your debt",),
    ),
    define_action(
        "hide-from-law",
        (),
        tool_name="hide_from_law",
        description=(
            "Lay low in a safehouse you have claimed to shed police heat. Only works while you are "
            "being hunted and sheltering in your own safehouse."
        ),
        patterns=("lay low",),
    ),
    define_action(
        "clear-warrant",
        (),
        tool_name="clear_warrant",
        description=(
            "Buy off your outstanding warrant, wiping your wanted level and heat for a fee that "
            "scales with how wanted you are. Costs scrip you must have on hand."
        ),
        patterns=("clear your warrant",),
    ),
    define_action(
        "post-bounty",
        ("target_id", "amount"),
        tool_name="post_bounty",
        description=(
            "Put a scrip bounty on another character so hunters come after them. Costs the amount "
            "up front and stacks onto any existing bounty on that target."
        ),
        patterns=("post a bounty on {target_id}",),
    ),
    define_action(
        "turn-informant",
        ("target_id",),
        tool_name="turn_informant",
        description=(
            "Pay to flip an informant to your side so they feed you tips instead of the law. Costs "
            "scrip, and the target must actually be an informant."
        ),
        patterns=("turn {target_id} into an informant",),
    ),
    define_action(
        "install-implant",
        ("implant_id", "clinic_id"),
        tool_name="install_implant",
        cost=EXTENDED_ACTION_COST,
        description=(
            "Have a clinic or street surgeon fit a cybernetic implant you carry into a free "
            "augmentation slot. Licensed clinics refuse illegal implants, and back-alley jobs on "
            "illegal gear add heat."
        ),
        patterns=("install {implant_id} at {clinic_id}",),
    ),
    define_action(
        "remove-implant",
        ("implant_id",),
        tool_name="remove_implant",
        description=(
            "Surgically pull out one of your installed implants so it can be carried or dropped "
            "again. You must already have the implant installed."
        ),
        patterns=("remove implant {implant_id}",),
    ),
    define_action(
        "service-implant",
        ("implant_id", "clinic_id"),
        tool_name="service_implant",
        description=(
            "Pay a clinic to maintain one of your implants, resetting its upkeep clock so it stops "
            "misfiring. Only implants that need maintenance can be serviced."
        ),
        patterns=("service {implant_id} at {clinic_id}",),
    ),
    define_action(
        "overclock-implant",
        ("implant_id",),
        tool_name="overclock_implant",
        description=(
            "Push one of your implants past spec for extra power, at the cost of heavier draw and "
            "more frequent maintenance. You cannot overclock one that is already overclocked."
        ),
        patterns=("overclock {implant_id}",),
    ),
    define_action(
        "disable-implant",
        ("implant_id",),
        tool_name="disable_implant",
        description=(
            "Switch off one of your installed implants so it draws no power and stops running. "
            "Useful to shut down a misfiring or compromised augment."
        ),
        patterns=("disable implant {implant_id}",),
    ),
    define_action(
        "license-implant",
        ("implant_id",),
        tool_name="license_implant",
        description=(
            "Pay a fee to make one of your illegal implants legal, so licensed clinics will "
            "service it. Only works on an implant you already have that is currently illegal."
        ),
        patterns=("license {implant_id}",),
    ),
    define_action(
        "scan-implant",
        ("target_id",),
        tool_name="scan_implant",
        description=(
            "Scan another person to count the cybernetic implants wired into their body. Get "
            "within reach of your target first."
        ),
        patterns=("scan {target_id} for implants",),
    ),
    define_action(
        "exploit-implant",
        ("target_id",),
        tool_name="exploit_implant",
        description=(
            "Hack a vulnerable implant in another person's body to breach and shut it down. Needs "
            "an exploit strong enough to beat its security and a target with an unbreached, "
            "hackable implant."
        ),
        patterns=("exploit the implants of {target_id}",),
    ),
    define_action(
        "take-fixer-job",
        ("target_id",),
        tool_name="take_fixer_job",
        description=(
            "Accept a runner contract, committing you to its objective for the promised payout. "
            "The job must still be on offer."
        ),
        patterns=("take the job {target_id}",),
    ),
    define_action(
        "meet-handler",
        ("target_id",),
        tool_name="meet_handler",
        description=(
            "Rendezvous with a contract handler to make contact for a hand-off. Find the handler "
            "in the room first."
        ),
        patterns=("meet handler {target_id}",),
    ),
    define_action(
        "deliver-data",
        ("contract_id", "data_id"),
        tool_name="deliver_data",
        description=(
            "Hand over the data a runner contract demands, marking the job delivered and ready for "
            "payout. You must have accepted the contract and be carrying the right data."
        ),
        patterns=("deliver {data_id} for {contract_id}",),
    ),
    define_action(
        "collect-payout",
        ("target_id",),
        tool_name="collect_payout",
        description=(
            "Claim your scrip for a delivered contract. Beware a double-cross: it pays nothing and "
            "burns you with fresh heat instead."
        ),
        patterns=("collect payout for {target_id}",),
    ),
    define_action(
        "burn-contact",
        ("target_id",),
        tool_name="burn_contact",
        description=(
            "Sever ties with a fixer for good, marking them burned so you can no longer work "
            "together. You cannot burn one already burned."
        ),
        patterns=("burn {target_id}",),
    ),
    define_action(
        "plant-evidence",
        ("target_id",),
        tool_name="plant_evidence",
        description=(
            "Frame another character by planting an incriminating file in the room that names "
            "them. Get within reach of your mark first."
        ),
        patterns=("plant evidence on {target_id}",),
    ),
    define_action(
        "blackmail-target",
        ("target_id", "file_id"),
        tool_name="blackmail_target",
        description=(
            "Use an incriminating file to blackmail its subject, forcing them to owe you a favor. "
            "You must be carrying a file that is actually about that person."
        ),
        patterns=("blackmail {target_id} with {file_id}",),
    ),
    define_action(
        "leak-file",
        ("target_id",),
        tool_name="leak_file",
        description=(
            "Release an incriminating file publicly, piling police heat onto whoever it exposes. "
            "The file must be reachable and not already leaked."
        ),
        patterns=("leak {target_id}",),
    ),
    define_action(
        "extract-asset",
        ("target_id",),
        tool_name="extract_asset",
        description=(
            "Pull a person or asset out to safety, marking the extraction complete. The target "
            "must be an asset awaiting extraction."
        ),
        patterns=("extract {target_id}",),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
