"""Tests for neon-sim districts, sites, access control, and trespass (catalogue 10.1)."""

from __future__ import annotations

from dataclasses import replace

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    HandlerContext,
    IdentityComponent,
    Lane,
    LockableComponent,
    PortableComponent,
    RegionComponent,
    build_submitted_command,
    container_of,
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.mechanics.colonysim import ResourceStackComponent
from bunnyland.mechanics.daggersim import BountyComponent, BountyPostedEvent, DebtComponent
from bunnyland.mechanics.neonsim import (
    TRACE_SECONDS,
    AccessDeniedEvent,
    AccessGrantedEvent,
    AccessLevelComponent,
    AccessTerminalHandler,
    AlarmRaisedEvent,
    AssetExtractedEvent,
    AssetExtractionComponent,
    AugmentationSlotsComponent,
    BackdoorInstalledEvent,
    BlackmailAppliedEvent,
    BlackmailFileComponent,
    BlackmailTargetHandler,
    BlackMarketComponent,
    BlindSpotComponent,
    BribeCheckpointHandler,
    BurnContactHandler,
    BuyContrabandHandler,
    CallFavorHandler,
    CameraComponent,
    CameraDisabledEvent,
    CameraLoopedEvent,
    CaseLocationHandler,
    CheckpointComponent,
    CheckpointPassedEvent,
    ClaimSafehouseHandler,
    ClearWarrantHandler,
    ClinicComponent,
    CollectPayoutHandler,
    ContactBurnedEvent,
    ContrabandBoughtEvent,
    ContrabandComponent,
    CredentialComponent,
    CredentialUsedEvent,
    CyberpunkSiteComponent,
    DataBrokerComponent,
    DataDeliveredEvent,
    DataExfiltratedEvent,
    DataPayloadComponent,
    DataSoldEvent,
    DebtPaidEvent,
    DeliverDataHandler,
    DeployDroneHandler,
    DeviceComponent,
    DeviceInspectedEvent,
    DisableCameraHandler,
    DisableImplantHandler,
    DistrictEnteredEvent,
    DoorUnlockedEvent,
    DoubleCrossRevealedEvent,
    DroneDeployedEvent,
    EnterDistrictHandler,
    EscalatePrivilegesHandler,
    EvadeTraceHandler,
    EvidencePlantedEvent,
    EvidenceRecordedEvent,
    EvidenceWipedEvent,
    ExfiltrateDataHandler,
    ExploitComponent,
    ExploitImplantHandler,
    ExtractAssetHandler,
    FavorCalledEvent,
    FileLeakedEvent,
    FixerComponent,
    FixerJobAcceptedEvent,
    HackableComponent,
    HackFailedEvent,
    HackSucceededEvent,
    HandlerComponent,
    HandlerMetEvent,
    HasImplant,
    HeatChangedEvent,
    HeatComponent,
    HideFromLawHandler,
    IdentitySpoofedEvent,
    ImplantComponent,
    ImplantDisabledEvent,
    ImplantExploitedEvent,
    ImplantInstalledEvent,
    ImplantLicensedEvent,
    ImplantOverclockedEvent,
    ImplantRemovedEvent,
    ImplantScannedEvent,
    ImplantServicedEvent,
    InformantComponent,
    InformantTurnedEvent,
    InsideZone,
    InspectDeviceHandler,
    InstallBackdoorHandler,
    InstallImplantHandler,
    JamSensorHandler,
    LawResponseEvent,
    LeakFileHandler,
    LicenseImplantHandler,
    LocationCasedEvent,
    LoopCameraHandler,
    MeetHandlerHandler,
    NetworkScannedEvent,
    NetworkTracedEvent,
    OverclockImplantHandler,
    OwesFavor,
    PayDebtHandler,
    PayoutCollectedEvent,
    PlantEvidenceHandler,
    PostBountyHandler,
    PrivilegesEscalatedEvent,
    PublicAccessComponent,
    RecordedEvidenceComponent,
    RemoveImplantHandler,
    RestrictedAreaComponent,
    RunExploitHandler,
    RunnerContractComponent,
    SabotageSystemHandler,
    SafehouseClaimedEvent,
    SafehouseComponent,
    ScanImplantHandler,
    ScanNetworkHandler,
    SecurityZoneComponent,
    SellDataHandler,
    SensorJammedEvent,
    ServiceImplantHandler,
    ShowCredentialsHandler,
    SideEffectTriggeredEvent,
    SneakCheckpointHandler,
    SpoofIdentityHandler,
    SurveillanceCoverageComponent,
    SystemSabotagedEvent,
    TakeFixerJobHandler,
    TerminalAccessedEvent,
    TraceEvadedEvent,
    TraceNetworkHandler,
    TraceStartedEvent,
    TraceTimerComponent,
    TrespassDetectedEvent,
    TurnInformantHandler,
    UnlockDoorHandler,
    UseCredentialHandler,
    WantedLevelChangedEvent,
    WantedLevelComponent,
    WarrantClearedEvent,
    WipeEvidenceHandler,
    install_neonsim,
    neonsim_fragments,
)
from bunnyland.mechanics.voidsim import DroneComponent
from bunnyland.prompts import ComponentPromptContext, PromptPerspective


def _install(actor):
    actor.register_handler(EnterDistrictHandler())
    actor.register_handler(ShowCredentialsHandler())
    actor.register_handler(BribeCheckpointHandler())
    actor.register_handler(SneakCheckpointHandler())
    actor.register_handler(ClaimSafehouseHandler())
    actor.register_handler(CaseLocationHandler())
    actor.register_handler(InspectDeviceHandler())
    actor.register_handler(DisableCameraHandler())
    actor.register_handler(LoopCameraHandler())
    actor.register_handler(JamSensorHandler())
    actor.register_handler(DeployDroneHandler())
    actor.register_handler(WipeEvidenceHandler())
    actor.register_handler(ScanNetworkHandler())
    actor.register_handler(TraceNetworkHandler())
    actor.register_handler(RunExploitHandler())
    actor.register_handler(UseCredentialHandler())
    actor.register_handler(AccessTerminalHandler())
    actor.register_handler(EscalatePrivilegesHandler())
    actor.register_handler(InstallBackdoorHandler())
    actor.register_handler(ExfiltrateDataHandler())
    actor.register_handler(SabotageSystemHandler())
    actor.register_handler(UnlockDoorHandler())
    actor.register_handler(EvadeTraceHandler())
    actor.register_handler(SpoofIdentityHandler())
    actor.register_handler(BuyContrabandHandler())
    actor.register_handler(SellDataHandler())
    actor.register_handler(CallFavorHandler())
    actor.register_handler(PayDebtHandler())
    actor.register_handler(PostBountyHandler())
    actor.register_handler(TurnInformantHandler())
    actor.register_handler(HideFromLawHandler())
    actor.register_handler(ClearWarrantHandler())
    actor.register_handler(InstallImplantHandler())
    actor.register_handler(RemoveImplantHandler())
    actor.register_handler(ServiceImplantHandler())
    actor.register_handler(OverclockImplantHandler())
    actor.register_handler(DisableImplantHandler())
    actor.register_handler(LicenseImplantHandler())
    actor.register_handler(ScanImplantHandler())
    actor.register_handler(ExploitImplantHandler())
    actor.register_handler(TakeFixerJobHandler())
    actor.register_handler(MeetHandlerHandler())
    actor.register_handler(DeliverDataHandler())
    actor.register_handler(CollectPayoutHandler())
    actor.register_handler(BurnContactHandler())
    actor.register_handler(PlantEvidenceHandler())
    actor.register_handler(BlackmailTargetHandler())
    actor.register_handler(LeakFileHandler())
    actor.register_handler(ExtractAssetHandler())
    install_neonsim(actor)


def _contract(scenario, *, payout=100, status="offered", accepted_by=None, double_cross=False):
    return _room_entity(
        scenario,
        "data run",
        "contract",
        [
            RunnerContractComponent(
                payout=payout,
                status=status,
                accepted_by=accepted_by,
                double_cross=double_cross,
            )
        ],
    )


def _implant_item(scenario, name="cyberdeck", **kwargs):
    return _inventory_entity(scenario, name, "implant", [ImplantComponent(**kwargs)])


def _install_implant(scenario, *, components=(), slot="body"):
    """Spawn an implant already installed on the character via a HasImplant edge."""
    implant = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="installed aug", kind="implant"), *components],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        HasImplant(slot=slot), implant.id
    )
    return implant.id


def _clinic(scenario, *, licensed=True, install_cost=50, service_cost=20):
    return _room_entity(
        scenario,
        "ripperdoc" if not licensed else "med clinic",
        "clinic",
        [ClinicComponent(licensed=licensed, install_cost=install_cost, service_cost=service_cost)],
    )


def _other_character(scenario, *, room=None, components=()):
    entity = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Mox", kind="character"),
            CharacterComponent(species="bunny"),
            *components,
        ],
    )
    scenario.actor.world.get_entity(room if room is not None else scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity.id


def _hackable(scenario, name="terminal", *, security=1, owner="", breached=False,
              privilege="user", backdoored=False, device_type="terminal", extra=()):
    return _room_entity(
        scenario,
        name,
        "device",
        [
            DeviceComponent(device_type=device_type),
            HackableComponent(
                security=security,
                owner=owner,
                breached=breached,
                privilege=privilege,
                backdoored=backdoored,
            ),
            *extra,
        ],
    )


def _give_exploit(scenario, power, *, single_use=False):
    return _inventory_entity(
        scenario, "breach kit", "tool", [ExploitComponent(power=power, single_use=single_use)]
    )


def _give_credential(scenario, target_owner, *, privilege="user"):
    return _inventory_entity(
        scenario,
        "keycard",
        "credential",
        [CredentialComponent(target_owner=target_owner, privilege=privilege)],
    )


def _camera(scenario, name="cam", *, looped=False, disabled=False, powered=True):
    return _room_entity(
        scenario,
        name,
        "device",
        [
            DeviceComponent(device_type="camera", powered=powered, disabled=disabled),
            CameraComponent(looped=looped),
            SurveillanceCoverageComponent(),
        ],
    )


def _intruder_site(scenario, name="vault", components=()):
    site = _room_entity(scenario, name, "site", [CyberpunkSiteComponent(), *components])
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        InsideZone(authorized=False), site
    )
    return site


def _evidence_in_room(scenario):
    return [
        record
        for record in scenario.actor.world.query()
        .with_all([RecordedEvidenceComponent])
        .execute_entities()
    ]


def _cmd(scenario, command_type, *, character_id=None, **payload):
    return build_submitted_command(
        character_id=str(scenario.character) if character_id is None else character_id,
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def _room_entity(scenario, name, kind, components):
    entity = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind=kind), *components],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity.id


def _inventory_entity(scenario, name, kind, components):
    entity = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=name, kind=kind),
            PortableComponent(can_pick_up=True),
            *components,
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), entity.id
    )
    return entity.id


def _give_clearance(scenario, *, clearance=0, passes=()):
    scenario.actor.world.get_entity(scenario.character).add_component(
        AccessLevelComponent(clearance=clearance, passes=tuple(passes))
    )


def _give_scrip(scenario, quantity):
    return _inventory_entity(
        scenario,
        f"scrip x{quantity}",
        "resource",
        [ResourceStackComponent(resource_type="scrip", quantity=quantity)],
    )


def _far_entity(scenario, name, kind, components):
    entity = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind=kind), *components],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity.id


def _inside(scenario, site_id):
    character = scenario.actor.world.get_entity(scenario.character)
    for edge, target in character.get_relationships(InsideZone):
        if str(target) == str(site_id):
            return edge
    return None


async def _reject(scenario, command):
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)
    await scenario.actor.submit(command)
    await scenario.actor.tick(1.0)
    return rejects


# --- enter-district ------------------------------------------------------------------


async def test_enter_open_site_grants_access_and_records_district():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.world.get_entity(scenario.room_a).add_component(
        RegionComponent(name="Glass Spire", kind="district")
    )
    site = _room_entity(
        scenario,
        "neon plaza",
        "site",
        [CyberpunkSiteComponent(site_type="street market"), PublicAccessComponent()],
    )
    entered: list[DistrictEnteredEvent] = []
    granted: list[AccessGrantedEvent] = []
    scenario.actor.bus.subscribe(DistrictEnteredEvent, entered.append)
    scenario.actor.bus.subscribe(AccessGrantedEvent, granted.append)

    await scenario.actor.submit(_cmd(scenario, "enter-district", target_id=str(site)))
    await scenario.actor.tick(1.0)

    assert entered[0].site_type == "street market"
    assert entered[0].district == "Glass Spire"
    assert granted[0].method == "public"
    assert _inside(scenario, site).authorized is True


async def test_secured_site_denies_without_clearance():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(
        scenario,
        "corp lobby",
        "site",
        [
            CyberpunkSiteComponent(site_type="corp campus"),
            SecurityZoneComponent(clearance_required=3),
        ],
    )
    denied: list[AccessDeniedEvent] = []
    scenario.actor.bus.subscribe(AccessDeniedEvent, denied.append)

    await scenario.actor.submit(_cmd(scenario, "enter-district", target_id=str(site)))
    await scenario.actor.tick(1.0)

    assert denied[0].requirement == 3
    assert _inside(scenario, site) is None


async def test_clearance_level_grants_secured_site():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_clearance(scenario, clearance=3)
    site = _room_entity(
        scenario,
        "corp lobby",
        "site",
        [CyberpunkSiteComponent(), SecurityZoneComponent(clearance_required=3)],
    )
    granted: list[AccessGrantedEvent] = []
    scenario.actor.bus.subscribe(AccessGrantedEvent, granted.append)

    await scenario.actor.submit(_cmd(scenario, "enter-district", target_id=str(site)))
    await scenario.actor.tick(1.0)

    assert granted[0].method == "clearance"
    assert _inside(scenario, site).authorized is True


async def test_zone_pass_grants_secured_site_below_clearance():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_clearance(scenario, clearance=0, passes=("arasaka",))
    site = _room_entity(
        scenario,
        "arasaka wing",
        "site",
        [
            CyberpunkSiteComponent(),
            SecurityZoneComponent(clearance_required=5, controller="arasaka"),
        ],
    )
    granted: list[AccessGrantedEvent] = []
    scenario.actor.bus.subscribe(AccessGrantedEvent, granted.append)

    await scenario.actor.submit(_cmd(scenario, "enter-district", target_id=str(site)))
    await scenario.actor.tick(1.0)

    assert _inside(scenario, site).authorized is True
    assert granted[0].method == "clearance"


async def test_entering_a_new_site_clears_prior_inside_zone():
    scenario = build_scenario()
    _install(scenario.actor)
    first = _room_entity(scenario, "plaza", "site", [CyberpunkSiteComponent()])
    second = _room_entity(scenario, "alley", "site", [CyberpunkSiteComponent()])

    await scenario.actor.submit(_cmd(scenario, "enter-district", target_id=str(first)))
    await scenario.actor.tick(1.0)
    await scenario.actor.submit(_cmd(scenario, "enter-district", target_id=str(second)))
    await scenario.actor.tick(1.0)

    assert _inside(scenario, first) is None
    assert _inside(scenario, second) is not None


# --- trespass detection --------------------------------------------------------------


async def test_covert_entry_into_patrolled_restricted_area_is_detected_once():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(
        scenario,
        "server vault",
        "site",
        [
            CyberpunkSiteComponent(site_type="data center"),
            SecurityZoneComponent(clearance_required=4),
            RestrictedAreaComponent(patrol=True),
        ],
    )
    trespass: list[TrespassDetectedEvent] = []
    scenario.actor.bus.subscribe(TrespassDetectedEvent, trespass.append)

    await scenario.actor.submit(
        _cmd(scenario, "enter-district", target_id=str(site), covert=True)
    )
    await scenario.actor.tick(1.0)
    await scenario.actor.tick(1.0)

    assert len(trespass) == 1
    assert trespass[0].site_type == "data center"
    zone = scenario.actor.world.get_entity(site).get_component(SecurityZoneComponent)
    assert zone.alarm_raised is True
    assert _inside(scenario, site) is None


async def test_authorized_presence_is_not_trespass():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_clearance(scenario, clearance=5)
    site = _room_entity(
        scenario,
        "server vault",
        "site",
        [
            CyberpunkSiteComponent(),
            SecurityZoneComponent(clearance_required=4),
            RestrictedAreaComponent(patrol=True),
        ],
    )
    trespass: list[TrespassDetectedEvent] = []
    scenario.actor.bus.subscribe(TrespassDetectedEvent, trespass.append)

    await scenario.actor.submit(_cmd(scenario, "enter-district", target_id=str(site)))
    await scenario.actor.tick(1.0)
    await scenario.actor.tick(1.0)

    assert trespass == []
    assert _inside(scenario, site).authorized is True


async def test_covert_entry_without_patrol_escapes_detection():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(
        scenario,
        "quiet annex",
        "site",
        [
            CyberpunkSiteComponent(),
            SecurityZoneComponent(clearance_required=4),
            RestrictedAreaComponent(patrol=False),
        ],
    )
    trespass: list[TrespassDetectedEvent] = []
    scenario.actor.bus.subscribe(TrespassDetectedEvent, trespass.append)

    await scenario.actor.submit(
        _cmd(scenario, "enter-district", target_id=str(site), covert=True)
    )
    await scenario.actor.tick(1.0)
    await scenario.actor.tick(1.0)

    assert trespass == []
    assert _inside(scenario, site).authorized is False


async def test_covert_entry_into_unrestricted_secured_site_is_not_detected():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(
        scenario,
        "secured lobby",
        "site",
        [CyberpunkSiteComponent(), SecurityZoneComponent(clearance_required=4)],
    )
    trespass: list[TrespassDetectedEvent] = []
    scenario.actor.bus.subscribe(TrespassDetectedEvent, trespass.append)

    await scenario.actor.submit(
        _cmd(scenario, "enter-district", target_id=str(site), covert=True)
    )
    await scenario.actor.tick(1.0)
    await scenario.actor.tick(1.0)

    assert trespass == []
    assert _inside(scenario, site).authorized is False


# --- show-credentials ----------------------------------------------------------------


async def test_show_credentials_passes_with_clearance():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_clearance(scenario, clearance=2)
    gate = _room_entity(
        scenario, "skybridge gate", "checkpoint", [CheckpointComponent(clearance_required=2)]
    )
    passed: list[CheckpointPassedEvent] = []
    granted: list[AccessGrantedEvent] = []
    scenario.actor.bus.subscribe(CheckpointPassedEvent, passed.append)
    scenario.actor.bus.subscribe(AccessGrantedEvent, granted.append)

    await scenario.actor.submit(_cmd(scenario, "show-credentials", target_id=str(gate)))
    await scenario.actor.tick(1.0)

    assert passed[0].method == "credentials"
    assert granted[0].method == "credentials"


async def test_show_credentials_denied_without_clearance():
    scenario = build_scenario()
    _install(scenario.actor)
    gate = _room_entity(
        scenario, "skybridge gate", "checkpoint", [CheckpointComponent(clearance_required=2)]
    )
    denied: list[AccessDeniedEvent] = []
    scenario.actor.bus.subscribe(AccessDeniedEvent, denied.append)

    await scenario.actor.submit(_cmd(scenario, "show-credentials", target_id=str(gate)))
    await scenario.actor.tick(1.0)

    assert denied[0].requirement == 2


# --- bribe ---------------------------------------------------------------------


async def test_bribe_guard_spends_scrip_and_passes():
    scenario = build_scenario()
    _install(scenario.actor)
    scrip = _give_scrip(scenario, 50)
    gate = _room_entity(
        scenario,
        "toll booth",
        "checkpoint",
        [CheckpointComponent(clearance_required=3, bribe_cost=30)],
    )
    passed: list[CheckpointPassedEvent] = []
    scenario.actor.bus.subscribe(CheckpointPassedEvent, passed.append)

    await scenario.actor.submit(_cmd(scenario, "bribe", target_id=str(gate)))
    await scenario.actor.tick(1.0)

    assert passed[0].method == "bribe"
    stack = scenario.actor.world.get_entity(scrip).get_component(ResourceStackComponent)
    assert stack.quantity == 20


async def test_bribe_guard_consumes_full_scrip_stack():
    scenario = build_scenario()
    _install(scenario.actor)
    scrip = _give_scrip(scenario, 30)
    gate = _room_entity(
        scenario, "toll booth", "checkpoint", [CheckpointComponent(bribe_cost=30)]
    )

    await scenario.actor.submit(_cmd(scenario, "bribe", target_id=str(gate)))
    await scenario.actor.tick(1.0)

    assert container_of(scenario.actor.world.get_entity(scrip)) is None


async def test_bribe_guard_clears_alert():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 30)
    gate = _room_entity(
        scenario,
        "toll booth",
        "checkpoint",
        [CheckpointComponent(bribe_cost=30, alerted=True)],
    )

    await scenario.actor.submit(_cmd(scenario, "bribe", target_id=str(gate)))
    await scenario.actor.tick(1.0)

    gate_state = scenario.actor.world.get_entity(gate).get_component(CheckpointComponent)
    assert gate_state.alerted is False


# --- sneak --------------------------------------------------------


async def test_sneak_through_calm_checkpoint_succeeds():
    scenario = build_scenario()
    _install(scenario.actor)
    gate = _room_entity(
        scenario, "fence gap", "checkpoint", [CheckpointComponent(clearance_required=2)]
    )
    passed: list[CheckpointPassedEvent] = []
    scenario.actor.bus.subscribe(CheckpointPassedEvent, passed.append)

    await scenario.actor.submit(
        _cmd(scenario, "sneak", target_id=str(gate))
    )
    await scenario.actor.tick(1.0)

    assert passed[0].method == "stealth"


# --- claim-safehouse -----------------------------------------------------------------


async def test_claim_unclaimed_safehouse():
    scenario = build_scenario()
    _install(scenario.actor)
    house = _room_entity(scenario, "back room", "safehouse", [SafehouseComponent()])
    claimed: list[SafehouseClaimedEvent] = []
    scenario.actor.bus.subscribe(SafehouseClaimedEvent, claimed.append)

    await scenario.actor.submit(_cmd(scenario, "claim-safehouse", target_id=str(house)))
    await scenario.actor.tick(1.0)

    assert claimed[0].safehouse_id == str(house)
    state = scenario.actor.world.get_entity(house).get_component(SafehouseComponent)
    assert state.claimed_by == str(scenario.character)


# --- case-location -------------------------------------------------------------------


async def test_case_location_reveals_security_profile():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(
        scenario,
        "data center",
        "site",
        [
            CyberpunkSiteComponent(),
            SecurityZoneComponent(clearance_required=4),
            RestrictedAreaComponent(),
        ],
    )
    _room_entity(scenario, "gate", "checkpoint", [CheckpointComponent(clearance_required=4)])
    cased: list[LocationCasedEvent] = []
    scenario.actor.bus.subscribe(LocationCasedEvent, cased.append)

    await scenario.actor.submit(_cmd(scenario, "case-location", target_id=str(site)))
    await scenario.actor.tick(1.0)

    assert cased[0].clearance_required == 4
    assert cased[0].restricted is True
    assert cased[0].has_checkpoint is True


# --- prompt fragments ----------------------------------------------------------------


async def test_fragments_describe_access_and_sites():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_clearance(scenario, clearance=2, passes=("arasaka",))
    _room_entity(
        scenario,
        "corp lobby",
        "site",
        [
            CyberpunkSiteComponent(site_type="corp campus"),
            SecurityZoneComponent(clearance_required=3),
            RestrictedAreaComponent(),
        ],
    )
    _room_entity(
        scenario, "gate", "checkpoint", [CheckpointComponent(clearance_required=3, bribe_cost=10)]
    )
    _room_entity(scenario, "den", "safehouse", [SafehouseComponent()])

    fragments = neonsim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )

    joined = "\n".join(fragments)
    assert "Security clearance: level 2, passes: arasaka." in joined
    assert "Site corp lobby: corp campus (clearance 3, restricted)." in joined
    assert "Checkpoint gate: clearance 3, calm, bribe 10 scrip." in joined
    assert "Safehouse den: unclaimed." in joined


def test_component_prompt_fragments_cover_site_device_and_implant_context():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    site_id = _room_entity(
        scenario,
        "vault",
        "site",
        [
            CyberpunkSiteComponent(site_type="data center"),
            SecurityZoneComponent(clearance_required=4, alarm_raised=True),
            RestrictedAreaComponent(),
        ],
    )
    device_id = _room_entity(
        scenario,
        "camera node",
        "device",
        [
            DeviceComponent(device_type="camera"),
            CameraComponent(looped=True),
            HackableComponent(security=3, breached=True, privilege="admin"),
        ],
    )
    implant_id = _inventory_entity(
        scenario,
        "wire reflex",
        "implant",
        [ImplantComponent(implant_type="reflex booster", legal=False, overclocked=True)],
    )
    character.add_relationship(InsideZone(authorized=False), site_id)
    character.remove_relationship(Contains, implant_id)
    character.add_relationship(HasImplant(slot="body"), implant_id)

    site = world.get_entity(site_id)
    device = world.get_entity(device_id)
    implant = world.get_entity(implant_id)
    site_ctx = ComponentPromptContext.for_entity(world, site, target=character)
    device_ctx = ComponentPromptContext.for_entity(world, device, target=character)
    implant_ctx = ComponentPromptContext.for_entity(world, implant, target=character)

    assert site.get_component(CyberpunkSiteComponent).prompt_fragments(site_ctx) == (
        "Site vault: data center (clearance 4, ALARM, restricted, you are inside).",
    )
    assert device.get_component(DeviceComponent).prompt_fragments(device_ctx) == (
        "Device camera node: camera (looped, breached/admin).",
    )
    assert implant.get_component(ImplantComponent).prompt_fragments(implant_ctx) == (
        "Implant wire reflex: reflex booster (body, overclocked, illegal).",
    )


def test_component_prompt_fragments_cover_suppressed_and_alternate_neon_branches():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)

    plain_site_id = _room_entity(
        scenario, "alley", "site", [CyberpunkSiteComponent(site_type="back alley")]
    )
    watched_device_id = _room_entity(
        scenario,
        "watcher",
        "device",
        [DeviceComponent(device_type="sensor"), SurveillanceCoverageComponent()],
    )
    secured_device_id = _room_entity(
        scenario,
        "terminal",
        "device",
        [
            DeviceComponent(device_type="terminal", powered=False, disabled=True),
            HackableComponent(security=5, backdoored=True),
        ],
    )
    wiped_evidence_id = _room_entity(
        scenario,
        "old tape",
        "evidence",
        [RecordedEvidenceComponent(subject_id=str(character.id), device_id="device", wiped=True)],
    )
    sale_implant_id = _room_entity(
        scenario,
        "optic",
        "implant",
        [ImplantComponent(implant_type="optic", legal=True)],
    )

    plain_site = world.get_entity(plain_site_id)
    watched_device = world.get_entity(watched_device_id)
    secured_device = world.get_entity(secured_device_id)
    wiped_evidence = world.get_entity(wiped_evidence_id)
    sale_implant = world.get_entity(sale_implant_id)
    third_person = ComponentPromptContext.for_entity(
        world, character, perspective=PromptPerspective(viewer=plain_site)
    )
    entity_ctx = ComponentPromptContext.for_entity(world, plain_site, target=character)

    assert AccessLevelComponent().prompt_fragments(entity_ctx) == ()
    assert plain_site.get_component(CyberpunkSiteComponent).prompt_fragments(entity_ctx) == (
        "Site alley: back alley.",
    )
    assert watched_device.get_component(DeviceComponent).prompt_fragments(
        ComponentPromptContext.for_entity(world, watched_device, target=character)
    ) == ("Device watcher: sensor (watching).",)
    assert secured_device.get_component(DeviceComponent).prompt_fragments(
        ComponentPromptContext.for_entity(world, secured_device, target=character)
    ) == ("Device terminal: terminal (unpowered, disabled, security 5, backdoored).",)
    assert wiped_evidence.get_component(RecordedEvidenceComponent).prompt_fragments(
        ComponentPromptContext.for_entity(world, wiped_evidence, target=character)
    ) == ()
    assert sale_implant.get_component(ImplantComponent).prompt_fragments(
        ComponentPromptContext.for_entity(world, sale_implant, target=character)
    ) == ("Implant for sale: optic (optic, legal).",)
    assert HeatComponent(amount=0.0).prompt_fragments(entity_ctx) == ()
    assert TraceTimerComponent(remaining=30.0).prompt_fragments(third_person) == ()
    assert WantedLevelComponent(level=2).prompt_fragments(third_person) == ()


# --- error paths: invalid / missing / unreachable / wrong-kind ----------------------


def test_handlers_reject_invalid_character_ids_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    target = str(scenario.room_a)
    cases = [
        (EnterDistrictHandler(), "enter-district"),
        (ShowCredentialsHandler(), "show-credentials"),
        (BribeCheckpointHandler(), "bribe"),
        (SneakCheckpointHandler(), "sneak"),
        (ClaimSafehouseHandler(), "claim-safehouse"),
        (CaseLocationHandler(), "case-location"),
    ]
    for handler, command_type in cases:
        result = handler.execute(
            ctx, _cmd(scenario, command_type, character_id="not-an-id", target_id=target)
        )
        assert result.ok is False
        assert result.reason == "invalid character id"


async def test_enter_district_rejects_missing_target():
    scenario = build_scenario()
    _install(scenario.actor)
    rejects = await _reject(scenario, _cmd(scenario, "enter-district", target_id="999999"))
    assert any("does not exist" in event.reason for event in rejects)


async def test_enter_district_rejects_unreachable_target():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _far_entity(scenario, "distant plaza", "site", [CyberpunkSiteComponent()])
    rejects = await _reject(scenario, _cmd(scenario, "enter-district", target_id=str(site)))
    assert any("not reachable" in event.reason for event in rejects)


async def test_enter_district_rejects_wrong_kind():
    scenario = build_scenario()
    _install(scenario.actor)
    house = _room_entity(scenario, "den", "safehouse", [SafehouseComponent()])
    rejects = await _reject(scenario, _cmd(scenario, "enter-district", target_id=str(house)))
    assert any("wrong kind" in event.reason for event in rejects)



async def test_show_credentials_rejects_non_checkpoint():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(scenario, "plaza", "site", [CyberpunkSiteComponent()])
    rejects = await _reject(scenario, _cmd(scenario, "show-credentials", target_id=str(site)))
    assert any("wrong kind" in event.reason for event in rejects)



async def test_bribe_guard_rejects_non_checkpoint():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(scenario, "plaza", "site", [CyberpunkSiteComponent()])
    rejects = await _reject(scenario, _cmd(scenario, "bribe", target_id=str(site)))
    assert any("no handler accepted bribe" in event.reason for event in rejects)


async def test_bribe_guard_rejects_checkpoint_without_bribe_cost():
    scenario = build_scenario()
    _install(scenario.actor)
    gate = _room_entity(scenario, "gate", "checkpoint", [CheckpointComponent(bribe_cost=0)])
    rejects = await _reject(scenario, _cmd(scenario, "bribe", target_id=str(gate)))
    assert any("no guard to bribe" in event.reason for event in rejects)


async def test_bribe_guard_rejects_without_enough_scrip():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 10)
    gate = _room_entity(scenario, "gate", "checkpoint", [CheckpointComponent(bribe_cost=30)])
    rejects = await _reject(scenario, _cmd(scenario, "bribe", target_id=str(gate)))
    assert any("not enough scrip" in event.reason for event in rejects)


async def test_bribe_guard_rejects_with_no_scrip_at_all():
    scenario = build_scenario()
    _install(scenario.actor)
    gate = _room_entity(scenario, "gate", "checkpoint", [CheckpointComponent(bribe_cost=30)])
    rejects = await _reject(scenario, _cmd(scenario, "bribe", target_id=str(gate)))
    assert any("not enough scrip" in event.reason for event in rejects)



async def test_sneak_rejects_non_checkpoint():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(scenario, "plaza", "site", [CyberpunkSiteComponent()])
    rejects = await _reject(
        scenario, _cmd(scenario, "sneak", target_id=str(site))
    )
    assert any("no handler accepted sneak" in event.reason for event in rejects)


async def test_sneak_rejects_alerted_checkpoint():
    scenario = build_scenario()
    _install(scenario.actor)
    gate = _room_entity(
        scenario, "gate", "checkpoint", [CheckpointComponent(clearance_required=2, alerted=True)]
    )
    rejects = await _reject(
        scenario, _cmd(scenario, "sneak", target_id=str(gate))
    )
    assert any("watching too closely" in event.reason for event in rejects)


async def test_sneak_rejects_when_already_cleared():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_clearance(scenario, clearance=5)
    gate = _room_entity(scenario, "gate", "checkpoint", [CheckpointComponent(clearance_required=2)])
    rejects = await _reject(
        scenario, _cmd(scenario, "sneak", target_id=str(gate))
    )
    assert any("show credentials" in event.reason for event in rejects)



async def test_claim_safehouse_rejects_non_safehouse():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(scenario, "plaza", "site", [CyberpunkSiteComponent()])
    rejects = await _reject(scenario, _cmd(scenario, "claim-safehouse", target_id=str(site)))
    assert any("wrong kind" in event.reason for event in rejects)


async def test_claim_safehouse_rejects_when_claimed_by_other():
    scenario = build_scenario()
    _install(scenario.actor)
    house = _room_entity(
        scenario, "den", "safehouse", [SafehouseComponent(claimed_by="someone-else")]
    )
    rejects = await _reject(scenario, _cmd(scenario, "claim-safehouse", target_id=str(house)))
    assert any("already claimed" in event.reason for event in rejects)


async def test_claim_safehouse_rejects_when_already_yours():
    scenario = build_scenario()
    _install(scenario.actor)
    house = _room_entity(
        scenario, "den", "safehouse", [SafehouseComponent(claimed_by=str(scenario.character))]
    )
    rejects = await _reject(scenario, _cmd(scenario, "claim-safehouse", target_id=str(house)))
    assert any("already hold this safehouse" in event.reason for event in rejects)



async def test_case_location_rejects_non_site():
    scenario = build_scenario()
    _install(scenario.actor)
    gate = _room_entity(scenario, "gate", "checkpoint", [CheckpointComponent()])
    rejects = await _reject(scenario, _cmd(scenario, "case-location", target_id=str(gate)))
    assert any("wrong kind" in event.reason for event in rejects)


# --- coverage: flag parsing, scrip scanning, and fragment branches -------------------


async def test_covert_flag_accepts_string_true():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(
        scenario,
        "server vault",
        "site",
        [
            CyberpunkSiteComponent(),
            SecurityZoneComponent(clearance_required=4),
            RestrictedAreaComponent(patrol=True),
        ],
    )
    trespass: list[TrespassDetectedEvent] = []
    scenario.actor.bus.subscribe(TrespassDetectedEvent, trespass.append)

    await scenario.actor.submit(
        _cmd(scenario, "enter-district", target_id=str(site), covert="true")
    )
    await scenario.actor.tick(1.0)
    await scenario.actor.tick(1.0)

    assert len(trespass) == 1


async def test_bribe_skips_non_scrip_inventory_items():
    scenario = build_scenario()
    _install(scenario.actor)
    _inventory_entity(
        scenario, "ammo x5", "resource", [ResourceStackComponent(resource_type="ammo", quantity=5)]
    )
    gate = _room_entity(scenario, "gate", "checkpoint", [CheckpointComponent(bribe_cost=10)])
    rejects = await _reject(scenario, _cmd(scenario, "bribe", target_id=str(gate)))
    assert any("not enough scrip" in event.reason for event in rejects)


def test_fragments_report_alarm_inside_alerted_and_claimed_states():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    site = _room_entity(
        scenario,
        "vault",
        "site",
        [
            CyberpunkSiteComponent(site_type="data center"),
            SecurityZoneComponent(clearance_required=4, alarm_raised=True),
            PublicAccessComponent(),
        ],
    )
    character.add_relationship(InsideZone(authorized=False), site)
    _room_entity(
        scenario, "gate", "checkpoint", [CheckpointComponent(clearance_required=4, alerted=True)]
    )
    _room_entity(
        scenario, "den", "safehouse", [SafehouseComponent(claimed_by=str(scenario.character))]
    )

    joined = "\n".join(neonsim_fragments(scenario.actor.world, character))

    assert "ALARM" in joined
    assert "public" in joined
    assert "you are inside" in joined
    assert "Checkpoint gate: clearance 4, alerted." in joined
    assert "Safehouse den: claimed." in joined


def test_fragments_handle_site_without_identity():
    scenario = build_scenario()
    _install(scenario.actor)
    site = spawn_entity(scenario.actor.world, [CyberpunkSiteComponent(site_type="back alley")])
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), site.id
    )

    joined = "\n".join(
        neonsim_fragments(scenario.actor.world, scenario.actor.world.get_entity(scenario.character))
    )

    assert f"Site {site.id}: back alley." in joined


# --- devices & surveillance (10.2) ---------------------------------------------------


async def test_inspect_device_reports_state():
    scenario = build_scenario()
    _install(scenario.actor)
    cam = _camera(scenario, "lobby cam")
    seen: list[DeviceInspectedEvent] = []
    scenario.actor.bus.subscribe(DeviceInspectedEvent, seen.append)

    await scenario.actor.submit(_cmd(scenario, "inspect", target_id=str(cam)))
    await scenario.actor.tick(1.0)

    assert seen[0].device_type == "camera"
    assert seen[0].powered is True
    assert seen[0].disabled is False


async def test_disable_camera_stops_recording():
    scenario = build_scenario()
    _install(scenario.actor)
    cam = _camera(scenario, "lobby cam")
    _intruder_site(scenario)
    disabled: list[CameraDisabledEvent] = []
    recorded: list[EvidenceRecordedEvent] = []
    scenario.actor.bus.subscribe(CameraDisabledEvent, disabled.append)
    scenario.actor.bus.subscribe(EvidenceRecordedEvent, recorded.append)

    await scenario.actor.submit(_cmd(scenario, "disable-camera", target_id=str(cam)))
    await scenario.actor.tick(1.0)

    assert disabled[0].device_id == str(cam)
    assert scenario.actor.world.get_entity(cam).get_component(DeviceComponent).disabled is True
    assert recorded == []
    assert _evidence_in_room(scenario) == []


async def test_loop_camera_stops_recording():
    scenario = build_scenario()
    _install(scenario.actor)
    cam = _camera(scenario, "lobby cam")
    _intruder_site(scenario)
    looped: list[CameraLoopedEvent] = []
    recorded: list[EvidenceRecordedEvent] = []
    scenario.actor.bus.subscribe(CameraLoopedEvent, looped.append)
    scenario.actor.bus.subscribe(EvidenceRecordedEvent, recorded.append)

    await scenario.actor.submit(_cmd(scenario, "loop-camera", target_id=str(cam)))
    await scenario.actor.tick(1.0)

    assert looped[0].device_id == str(cam)
    assert scenario.actor.world.get_entity(cam).get_component(CameraComponent).looped is True
    assert recorded == []


async def test_jam_sensor_disables_it():
    scenario = build_scenario()
    _install(scenario.actor)
    sensor = _room_entity(
        scenario, "motion sensor", "device", [DeviceComponent(device_type="sensor")]
    )
    jammed: list[SensorJammedEvent] = []
    scenario.actor.bus.subscribe(SensorJammedEvent, jammed.append)

    await scenario.actor.submit(_cmd(scenario, "jam-sensor", target_id=str(sensor)))
    await scenario.actor.tick(1.0)

    assert jammed[0].device_id == str(sensor)
    assert scenario.actor.world.get_entity(sensor).get_component(DeviceComponent).disabled is True


async def test_deploy_drone_activates_and_powers_it():
    scenario = build_scenario()
    _install(scenario.actor)
    drone = _room_entity(
        scenario,
        "recon drone",
        "device",
        [DeviceComponent(device_type="drone", powered=False), DroneComponent()],
    )
    deployed: list[DroneDeployedEvent] = []
    scenario.actor.bus.subscribe(DroneDeployedEvent, deployed.append)

    await scenario.actor.submit(_cmd(scenario, "deploy-drone", target_id=str(drone)))
    await scenario.actor.tick(1.0)

    assert deployed[0].device_id == str(drone)
    entity = scenario.actor.world.get_entity(drone)
    assert entity.get_component(DroneComponent).active is True
    assert entity.get_component(DeviceComponent).powered is True


async def test_camera_records_evidence_of_intruder():
    scenario = build_scenario()
    _install(scenario.actor)
    cam = _camera(scenario, "lobby cam")
    _intruder_site(scenario)
    recorded: list[EvidenceRecordedEvent] = []
    scenario.actor.bus.subscribe(EvidenceRecordedEvent, recorded.append)

    await scenario.actor.tick(1.0)

    assert len(recorded) == 1
    assert recorded[0].character_id == str(scenario.character)
    assert recorded[0].device_id == str(cam)
    evidence = _evidence_in_room(scenario)
    assert len(evidence) == 1
    subject = evidence[0].get_component(RecordedEvidenceComponent).subject_id
    assert subject == str(scenario.character)


async def test_camera_does_not_record_authorized_presence():
    scenario = build_scenario()
    _install(scenario.actor)
    _camera(scenario, "lobby cam")
    site = _room_entity(scenario, "vault", "site", [CyberpunkSiteComponent()])
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        InsideZone(authorized=True), site
    )
    recorded: list[EvidenceRecordedEvent] = []
    scenario.actor.bus.subscribe(EvidenceRecordedEvent, recorded.append)

    await scenario.actor.tick(1.0)

    assert recorded == []


async def test_unpowered_camera_does_not_record():
    scenario = build_scenario()
    _install(scenario.actor)
    _camera(scenario, "dead cam", powered=False)
    _intruder_site(scenario)
    recorded: list[EvidenceRecordedEvent] = []
    scenario.actor.bus.subscribe(EvidenceRecordedEvent, recorded.append)

    await scenario.actor.tick(1.0)

    assert recorded == []


async def test_blind_spot_site_shelters_intruder():
    scenario = build_scenario()
    _install(scenario.actor)
    _camera(scenario, "lobby cam")
    _intruder_site(scenario, "maintenance crawlspace", [BlindSpotComponent()])
    recorded: list[EvidenceRecordedEvent] = []
    scenario.actor.bus.subscribe(EvidenceRecordedEvent, recorded.append)

    await scenario.actor.tick(1.0)

    assert recorded == []


async def test_camera_records_each_intruder_only_once():
    scenario = build_scenario()
    _install(scenario.actor)
    _camera(scenario, "lobby cam")
    # No RestrictedAreaComponent, so trespass detection leaves the edge in place and the
    # camera sees the intruder across multiple ticks; dedup must still record once.
    _intruder_site(scenario)
    recorded: list[EvidenceRecordedEvent] = []
    scenario.actor.bus.subscribe(EvidenceRecordedEvent, recorded.append)

    await scenario.actor.tick(1.0)
    await scenario.actor.tick(1.0)

    assert len(recorded) == 1
    assert len(_evidence_in_room(scenario)) == 1


async def test_wipe_evidence_removes_the_record():
    scenario = build_scenario()
    _install(scenario.actor)
    _camera(scenario, "lobby cam")
    _intruder_site(scenario)
    await scenario.actor.tick(1.0)
    evidence = _evidence_in_room(scenario)[0]
    wiped: list[EvidenceWipedEvent] = []
    scenario.actor.bus.subscribe(EvidenceWipedEvent, wiped.append)

    await scenario.actor.submit(_cmd(scenario, "wipe-evidence", target_id=str(evidence.id)))
    await scenario.actor.tick(1.0)

    assert wiped[0].evidence_id == str(evidence.id)
    assert not scenario.actor.world.has_entity(evidence.id)


def test_device_fragments_describe_devices_and_evidence():
    scenario = build_scenario()
    _install(scenario.actor)
    _camera(scenario, "lobby cam", looped=True)
    _room_entity(
        scenario,
        "motion sensor",
        "device",
        [DeviceComponent(device_type="sensor"), SurveillanceCoverageComponent()],
    )
    _room_entity(
        scenario,
        "footage",
        "evidence",
        [RecordedEvidenceComponent(subject_id="x", device_id="y", device_type="camera")],
    )

    joined = "\n".join(
        neonsim_fragments(scenario.actor.world, scenario.actor.world.get_entity(scenario.character))
    )

    assert "Device lobby cam: camera (looped)." in joined
    assert "Device motion sensor: sensor (watching)." in joined
    assert "Recorded evidence: footage (camera)." in joined


# --- error paths: devices ------------------------------------------------------------


def test_device_handlers_reject_invalid_character_ids_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    target = str(scenario.room_a)
    cases = [
        (InspectDeviceHandler(), "inspect"),
        (DisableCameraHandler(), "disable-camera"),
        (LoopCameraHandler(), "loop-camera"),
        (JamSensorHandler(), "jam-sensor"),
        (DeployDroneHandler(), "deploy-drone"),
        (WipeEvidenceHandler(), "wipe-evidence"),
    ]
    for handler, command_type in cases:
        result = handler.execute(
            ctx, _cmd(scenario, command_type, character_id="not-an-id", target_id=target)
        )
        assert result.ok is False
        assert result.reason == "invalid character id"


async def test_inspect_device_rejects_non_device():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(scenario, "plaza", "site", [CyberpunkSiteComponent()])
    rejects = await _reject(scenario, _cmd(scenario, "inspect", target_id=str(site)))
    assert any("no handler accepted inspect" in event.reason for event in rejects)


async def test_disable_camera_rejects_non_camera():
    scenario = build_scenario()
    _install(scenario.actor)
    sensor = _room_entity(scenario, "sensor", "device", [DeviceComponent(device_type="sensor")])
    rejects = await _reject(scenario, _cmd(scenario, "disable-camera", target_id=str(sensor)))
    assert any("wrong kind" in event.reason for event in rejects)


async def test_disable_camera_rejects_when_already_disabled():
    scenario = build_scenario()
    _install(scenario.actor)
    cam = _camera(scenario, "cam", disabled=True)
    rejects = await _reject(scenario, _cmd(scenario, "disable-camera", target_id=str(cam)))
    assert any("already disabled" in event.reason for event in rejects)


async def test_loop_camera_rejects_offline_camera():
    scenario = build_scenario()
    _install(scenario.actor)
    cam = _camera(scenario, "cam", disabled=True)
    rejects = await _reject(scenario, _cmd(scenario, "loop-camera", target_id=str(cam)))
    assert any("offline" in event.reason for event in rejects)


async def test_loop_camera_rejects_when_already_looped():
    scenario = build_scenario()
    _install(scenario.actor)
    cam = _camera(scenario, "cam", looped=True)
    rejects = await _reject(scenario, _cmd(scenario, "loop-camera", target_id=str(cam)))
    assert any("already looped" in event.reason for event in rejects)


async def test_jam_sensor_rejects_non_sensor():
    scenario = build_scenario()
    _install(scenario.actor)
    cam = _camera(scenario, "cam")
    rejects = await _reject(scenario, _cmd(scenario, "jam-sensor", target_id=str(cam)))
    assert any("not a sensor" in event.reason for event in rejects)


async def test_jam_sensor_rejects_when_already_jammed():
    scenario = build_scenario()
    _install(scenario.actor)
    sensor = _room_entity(
        scenario, "sensor", "device", [DeviceComponent(device_type="sensor", disabled=True)]
    )
    rejects = await _reject(scenario, _cmd(scenario, "jam-sensor", target_id=str(sensor)))
    assert any("already jammed" in event.reason for event in rejects)


async def test_deploy_drone_rejects_non_drone():
    scenario = build_scenario()
    _install(scenario.actor)
    cam = _camera(scenario, "cam")
    rejects = await _reject(scenario, _cmd(scenario, "deploy-drone", target_id=str(cam)))
    assert any("wrong kind" in event.reason for event in rejects)


async def test_deploy_drone_rejects_when_already_deployed():
    scenario = build_scenario()
    _install(scenario.actor)
    drone = _room_entity(
        scenario,
        "drone",
        "device",
        [DeviceComponent(device_type="drone"), DroneComponent(active=True)],
    )
    rejects = await _reject(scenario, _cmd(scenario, "deploy-drone", target_id=str(drone)))
    assert any("already deployed" in event.reason for event in rejects)


async def test_wipe_evidence_rejects_non_evidence():
    scenario = build_scenario()
    _install(scenario.actor)
    cam = _camera(scenario, "cam")
    rejects = await _reject(scenario, _cmd(scenario, "wipe-evidence", target_id=str(cam)))
    assert any("wrong kind" in event.reason for event in rejects)


async def test_wipe_evidence_rejects_when_already_wiped():
    scenario = build_scenario()
    _install(scenario.actor)
    record = _room_entity(
        scenario,
        "old footage",
        "evidence",
        [RecordedEvidenceComponent(subject_id="x", device_id="y", wiped=True)],
    )
    rejects = await _reject(scenario, _cmd(scenario, "wipe-evidence", target_id=str(record)))
    assert any("already wiped" in event.reason for event in rejects)


# --- coverage: device fragment states, orphan camera, off-room characters ------------


def test_device_fragments_report_unpowered_and_disabled():
    scenario = build_scenario()
    _install(scenario.actor)
    _room_entity(
        scenario,
        "broken cam",
        "device",
        [DeviceComponent(device_type="camera", powered=False, disabled=True)],
    )
    _room_entity(
        scenario,
        "wiped footage",
        "evidence",
        [RecordedEvidenceComponent(subject_id="x", device_id="y", wiped=True)],
    )

    joined = "\n".join(
        neonsim_fragments(scenario.actor.world, scenario.actor.world.get_entity(scenario.character))
    )

    assert "Device broken cam: camera (unpowered, disabled)." in joined
    assert "wiped footage" not in joined


async def test_disable_camera_without_device_component_is_rejected():
    scenario = build_scenario()
    _install(scenario.actor)
    bare = _room_entity(scenario, "phantom cam", "device", [CameraComponent()])
    rejects = await _reject(scenario, _cmd(scenario, "disable-camera", target_id=str(bare)))
    assert any("not a camera" in event.reason for event in rejects)


async def test_loop_camera_without_device_component_succeeds():
    scenario = build_scenario()
    _install(scenario.actor)
    bare = _room_entity(scenario, "phantom cam", "device", [CameraComponent()])
    looped: list[CameraLoopedEvent] = []
    scenario.actor.bus.subscribe(CameraLoopedEvent, looped.append)

    await scenario.actor.submit(_cmd(scenario, "loop-camera", target_id=str(bare)))
    await scenario.actor.tick(1.0)

    assert looped[0].device_id == str(bare)


async def test_orphan_camera_and_off_room_intruder_are_skipped():
    scenario = build_scenario()
    _install(scenario.actor)
    # Camera with surveillance coverage but no room: must be skipped, not crash.
    spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="loose cam", kind="device"),
            DeviceComponent(device_type="camera"),
            SurveillanceCoverageComponent(),
        ],
    )
    # A real camera in room_a, but the only intruder sits in room_b out of view.
    _camera(scenario, "lobby cam")
    far_site = _far_entity(scenario, "far vault", "site", [CyberpunkSiteComponent()])
    other = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Mox", kind="character"), CharacterComponent(species="bunny")],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), other.id
    )
    other.add_relationship(InsideZone(authorized=False), far_site)
    recorded: list[EvidenceRecordedEvent] = []
    scenario.actor.bus.subscribe(EvidenceRecordedEvent, recorded.append)

    await scenario.actor.tick(1.0)

    assert recorded == []


# --- hacking & intrusion (10.3) ------------------------------------------------------


async def test_scan_network_reports_security():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk", security=3)
    scanned: list[NetworkScannedEvent] = []
    scenario.actor.bus.subscribe(NetworkScannedEvent, scanned.append)

    await scenario.actor.submit(_cmd(scenario, "scan-network", target_id=str(term)))
    await scenario.actor.tick(1.0)

    assert scanned[0].security == 3
    assert scanned[0].breached is False


async def test_trace_network_counts_nodes_in_room():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk")
    _hackable(scenario, "server", device_type="server")
    traced: list[NetworkTracedEvent] = []
    scenario.actor.bus.subscribe(NetworkTracedEvent, traced.append)

    await scenario.actor.submit(_cmd(scenario, "trace-network", target_id=str(term)))
    await scenario.actor.tick(1.0)

    assert traced[0].node_count == 2


async def test_run_exploit_breaches_and_starts_trace():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk", security=2)
    _give_exploit(scenario, 3)
    succeeded: list[HackSucceededEvent] = []
    traces: list[TraceStartedEvent] = []
    scenario.actor.bus.subscribe(HackSucceededEvent, succeeded.append)
    scenario.actor.bus.subscribe(TraceStartedEvent, traces.append)

    await scenario.actor.submit(_cmd(scenario, "run-exploit", target_id=str(term)))
    await scenario.actor.tick(1.0)

    assert succeeded[0].device_id == str(term)
    assert traces[0].seconds == TRACE_SECONDS
    assert scenario.actor.world.get_entity(term).get_component(HackableComponent).breached is True
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_component(TraceTimerComponent)


async def test_run_exploit_consumes_single_use_exploit():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk", security=1)
    kit = _give_exploit(scenario, 2, single_use=True)

    await scenario.actor.submit(_cmd(scenario, "run-exploit", target_id=str(term)))
    await scenario.actor.tick(1.0)

    assert not scenario.actor.world.has_entity(kit)


async def test_run_exploit_fails_and_raises_alarm():
    scenario = build_scenario()
    _install(scenario.actor)
    zone_site = _room_entity(
        scenario, "vault site", "site", [CyberpunkSiteComponent(), SecurityZoneComponent()]
    )
    term = _hackable(scenario, "hard server", security=5)
    _give_exploit(scenario, 1)
    failed: list[HackFailedEvent] = []
    alarms: list[AlarmRaisedEvent] = []
    scenario.actor.bus.subscribe(HackFailedEvent, failed.append)
    scenario.actor.bus.subscribe(AlarmRaisedEvent, alarms.append)

    await scenario.actor.submit(_cmd(scenario, "run-exploit", target_id=str(term)))
    await scenario.actor.tick(1.0)

    assert failed[0].device_id == str(term)
    assert alarms[0].source == "failed hack"
    assert scenario.actor.world.get_entity(term).get_component(HackableComponent).breached is False
    zone = scenario.actor.world.get_entity(zone_site).get_component(SecurityZoneComponent)
    assert zone.alarm_raised is True


async def test_use_credential_breaches_cleanly():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "corp node", security=4, owner="arasaka")
    _give_credential(scenario, "arasaka", privilege="admin")
    used: list[CredentialUsedEvent] = []
    traces: list[TraceStartedEvent] = []
    scenario.actor.bus.subscribe(CredentialUsedEvent, used.append)
    scenario.actor.bus.subscribe(TraceStartedEvent, traces.append)

    await scenario.actor.submit(_cmd(scenario, "use-credential", target_id=str(term)))
    await scenario.actor.tick(1.0)

    assert used[0].privilege == "admin"
    hack = scenario.actor.world.get_entity(term).get_component(HackableComponent)
    assert hack.breached is True
    assert hack.privilege == "admin"
    assert traces == []  # clean entry leaves no trace


async def test_access_terminal_requires_breach():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk", breached=True)
    accessed: list[TerminalAccessedEvent] = []
    scenario.actor.bus.subscribe(TerminalAccessedEvent, accessed.append)

    await scenario.actor.submit(_cmd(scenario, "access-terminal", target_id=str(term)))
    await scenario.actor.tick(1.0)

    assert accessed[0].device_id == str(term)


async def test_escalate_privileges_to_admin():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk", breached=True)
    escalated: list[PrivilegesEscalatedEvent] = []
    scenario.actor.bus.subscribe(PrivilegesEscalatedEvent, escalated.append)

    await scenario.actor.submit(_cmd(scenario, "escalate-privileges", target_id=str(term)))
    await scenario.actor.tick(1.0)

    assert escalated[0].privilege == "admin"
    hack = scenario.actor.world.get_entity(term).get_component(HackableComponent)
    assert hack.privilege == "admin"


async def test_install_backdoor_enables_future_auto_breach():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk", security=9, breached=True)
    installed: list[BackdoorInstalledEvent] = []
    scenario.actor.bus.subscribe(BackdoorInstalledEvent, installed.append)

    await scenario.actor.submit(_cmd(scenario, "install-backdoor", target_id=str(term)))
    await scenario.actor.tick(1.0)
    assert installed[0].device_id == str(term)

    # Reset breached so a fresh exploit must rely on the backdoor (no exploit tool held).
    world = scenario.actor.world
    hack = world.get_entity(term).get_component(HackableComponent)
    replace_component(world.get_entity(term), replace(hack, breached=False))
    succeeded: list[HackSucceededEvent] = []
    traces: list[TraceStartedEvent] = []
    scenario.actor.bus.subscribe(HackSucceededEvent, succeeded.append)
    scenario.actor.bus.subscribe(TraceStartedEvent, traces.append)

    await scenario.actor.submit(_cmd(scenario, "run-exploit", target_id=str(term)))
    await scenario.actor.tick(1.0)

    assert succeeded[0].device_id == str(term)
    assert traces == []  # backdoor breach is silent


async def test_exfiltrate_data_into_inventory():
    scenario = build_scenario()
    _install(scenario.actor)
    server = _hackable(
        scenario,
        "data server",
        device_type="server",
        breached=True,
        extra=[DataPayloadComponent(name="payroll db")],
    )
    exfil: list[DataExfiltratedEvent] = []
    scenario.actor.bus.subscribe(DataExfiltratedEvent, exfil.append)

    await scenario.actor.submit(_cmd(scenario, "exfiltrate-data", target_id=str(server)))
    await scenario.actor.tick(1.0)

    assert exfil[0].name == "payroll db"
    data_id = parse_entity_id(exfil[0].data_id)
    assert container_of(scenario.actor.world.get_entity(data_id)) == scenario.character
    payload = scenario.actor.world.get_entity(server).get_component(DataPayloadComponent)
    assert payload.exfiltrated is True


async def test_exfiltrate_sensitive_data_requires_admin():
    scenario = build_scenario()
    _install(scenario.actor)
    server = _hackable(
        scenario,
        "secure server",
        device_type="server",
        breached=True,
        privilege="user",
        extra=[DataPayloadComponent(name="black files", sensitive=True)],
    )
    rejects = await _reject(scenario, _cmd(scenario, "exfiltrate-data", target_id=str(server)))
    assert any("admin privileges" in event.reason for event in rejects)


async def test_sabotage_system_disables_device():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "pump controller", breached=True)
    sabotaged: list[SystemSabotagedEvent] = []
    scenario.actor.bus.subscribe(SystemSabotagedEvent, sabotaged.append)

    await scenario.actor.submit(_cmd(scenario, "sabotage-system", target_id=str(term)))
    await scenario.actor.tick(1.0)

    assert sabotaged[0].device_id == str(term)
    assert scenario.actor.world.get_entity(term).get_component(DeviceComponent).disabled is True


async def test_unlock_door_after_breach():
    scenario = build_scenario()
    _install(scenario.actor)
    door = _hackable(
        scenario,
        "mag lock",
        device_type="lock",
        breached=True,
        extra=[LockableComponent(locked=True)],
    )
    unlocked: list[DoorUnlockedEvent] = []
    scenario.actor.bus.subscribe(DoorUnlockedEvent, unlocked.append)

    await scenario.actor.submit(_cmd(scenario, "unlock", target_id=str(door)))
    await scenario.actor.tick(1.0)

    assert unlocked[0].device_id == str(door)
    assert scenario.actor.world.get_entity(door).get_component(LockableComponent).locked is False


async def test_trace_expires_and_raises_alarm():
    scenario = build_scenario()
    _install(scenario.actor)
    zone_site = _room_entity(
        scenario, "vault site", "site", [CyberpunkSiteComponent(), SecurityZoneComponent()]
    )
    term = _hackable(scenario, "kiosk", security=1)
    _give_exploit(scenario, 2)
    alarms: list[AlarmRaisedEvent] = []
    scenario.actor.bus.subscribe(AlarmRaisedEvent, alarms.append)

    await scenario.actor.submit(_cmd(scenario, "run-exploit", target_id=str(term)))
    await scenario.actor.tick(1.0)
    await scenario.actor.tick(TRACE_SECONDS)

    assert any(event.source == "trace" for event in alarms)
    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(TraceTimerComponent)
    zone = scenario.actor.world.get_entity(zone_site).get_component(SecurityZoneComponent)
    assert zone.alarm_raised is True


async def test_evade_trace_clears_it_before_expiry():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk", security=1)
    _give_exploit(scenario, 2)
    evaded: list[TraceEvadedEvent] = []
    alarms: list[AlarmRaisedEvent] = []
    scenario.actor.bus.subscribe(TraceEvadedEvent, evaded.append)
    scenario.actor.bus.subscribe(AlarmRaisedEvent, alarms.append)

    await scenario.actor.submit(_cmd(scenario, "run-exploit", target_id=str(term)))
    await scenario.actor.tick(1.0)
    await scenario.actor.submit(_cmd(scenario, "evade-trace"))
    await scenario.actor.tick(1.0)
    await scenario.actor.tick(TRACE_SECONDS)

    assert len(evaded) == 1
    assert alarms == []
    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(TraceTimerComponent)


async def test_spoof_identity_extends_the_trace():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk", security=1)
    _give_exploit(scenario, 2)
    spoofed: list[IdentitySpoofedEvent] = []
    scenario.actor.bus.subscribe(IdentitySpoofedEvent, spoofed.append)

    await scenario.actor.submit(_cmd(scenario, "run-exploit", target_id=str(term)))
    await scenario.actor.tick(1.0)
    await scenario.actor.submit(_cmd(scenario, "spoof-identity"))
    await scenario.actor.tick(1.0)

    assert spoofed[0].seconds > 0
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(TraceTimerComponent).remaining > TRACE_SECONDS


def test_hacking_fragments_describe_devices_and_trace():
    scenario = build_scenario()
    _install(scenario.actor)
    _hackable(scenario, "open node", breached=True, privilege="admin", backdoored=True)
    _hackable(scenario, "locked node", security=4)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        TraceTimerComponent(remaining=120.0, source_id="x", last_updated_epoch=0)
    )

    joined = "\n".join(neonsim_fragments(scenario.actor.world, character))

    assert "Device open node: terminal (breached/admin, backdoored)." in joined
    assert "Device locked node: terminal (security 4)." in joined
    assert "Counter-intrusion trace closing in: 120s left." in joined


# --- error paths: hacking ------------------------------------------------------------


def test_hacking_handlers_reject_invalid_character_ids_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    target = str(scenario.room_a)
    cases = [
        (ScanNetworkHandler(), "scan-network"),
        (TraceNetworkHandler(), "trace-network"),
        (RunExploitHandler(), "run-exploit"),
        (UseCredentialHandler(), "use-credential"),
        (AccessTerminalHandler(), "access-terminal"),
        (EscalatePrivilegesHandler(), "escalate-privileges"),
        (InstallBackdoorHandler(), "install-backdoor"),
        (ExfiltrateDataHandler(), "exfiltrate-data"),
        (SabotageSystemHandler(), "sabotage-system"),
        (UnlockDoorHandler(), "unlock"),
        (EvadeTraceHandler(), "evade-trace"),
        (SpoofIdentityHandler(), "spoof-identity"),
    ]
    for handler, command_type in cases:
        result = handler.execute(
            ctx, _cmd(scenario, command_type, character_id="not-an-id", target_id=target)
        )
        assert result.ok is False
        assert result.reason == "invalid character id"


async def test_run_exploit_rejects_already_breached():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk", breached=True)
    rejects = await _reject(scenario, _cmd(scenario, "run-exploit", target_id=str(term)))
    assert any("already breached" in event.reason for event in rejects)


async def test_use_credential_rejects_without_match():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "corp node", owner="arasaka")
    _give_credential(scenario, "militech")
    rejects = await _reject(scenario, _cmd(scenario, "use-credential", target_id=str(term)))
    assert any("no credential matches" in event.reason for event in rejects)


async def test_access_terminal_rejects_when_locked():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk")
    rejects = await _reject(scenario, _cmd(scenario, "access-terminal", target_id=str(term)))
    assert any("breach it first" in event.reason for event in rejects)


async def test_escalate_privileges_rejects_when_not_breached():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk")
    rejects = await _reject(scenario, _cmd(scenario, "escalate-privileges", target_id=str(term)))
    assert any("breach the system first" in event.reason for event in rejects)


async def test_escalate_privileges_rejects_when_already_admin():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk", breached=True, privilege="admin")
    rejects = await _reject(scenario, _cmd(scenario, "escalate-privileges", target_id=str(term)))
    assert any("already running as admin" in event.reason for event in rejects)


async def test_install_backdoor_rejects_when_not_breached():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk")
    rejects = await _reject(scenario, _cmd(scenario, "install-backdoor", target_id=str(term)))
    assert any("breach the system first" in event.reason for event in rejects)


async def test_install_backdoor_rejects_when_already_installed():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk", breached=True, backdoored=True)
    rejects = await _reject(scenario, _cmd(scenario, "install-backdoor", target_id=str(term)))
    assert any("already installed" in event.reason for event in rejects)


async def test_exfiltrate_rejects_when_not_breached():
    scenario = build_scenario()
    _install(scenario.actor)
    server = _hackable(
        scenario, "server", device_type="server", extra=[DataPayloadComponent(name="db")]
    )
    rejects = await _reject(scenario, _cmd(scenario, "exfiltrate-data", target_id=str(server)))
    assert any("breach the system first" in event.reason for event in rejects)


async def test_exfiltrate_rejects_without_data():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk", breached=True)
    rejects = await _reject(scenario, _cmd(scenario, "exfiltrate-data", target_id=str(term)))
    assert any("holds no data" in event.reason for event in rejects)


async def test_exfiltrate_rejects_when_already_taken():
    scenario = build_scenario()
    _install(scenario.actor)
    server = _hackable(
        scenario,
        "server",
        device_type="server",
        breached=True,
        extra=[DataPayloadComponent(name="db", exfiltrated=True)],
    )
    rejects = await _reject(scenario, _cmd(scenario, "exfiltrate-data", target_id=str(server)))
    assert any("already been exfiltrated" in event.reason for event in rejects)


async def test_sabotage_rejects_when_not_breached():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk")
    rejects = await _reject(scenario, _cmd(scenario, "sabotage-system", target_id=str(term)))
    assert any("breach the system first" in event.reason for event in rejects)


async def test_unlock_door_rejects_when_already_unlocked():
    scenario = build_scenario()
    _install(scenario.actor)
    door = _hackable(
        scenario,
        "mag lock",
        device_type="lock",
        breached=True,
        extra=[LockableComponent(locked=False)],
    )
    rejects = await _reject(scenario, _cmd(scenario, "unlock", target_id=str(door)))
    assert any("already unlocked" in event.reason for event in rejects)


async def test_unlock_door_rejects_non_network_lock():
    scenario = build_scenario()
    _install(scenario.actor)
    chest = _room_entity(scenario, "footlocker", "container", [LockableComponent(locked=True)])
    rejects = await _reject(scenario, _cmd(scenario, "unlock", target_id=str(chest)))
    assert any("no handler accepted unlock" in event.reason for event in rejects)


async def test_evade_trace_rejects_without_active_trace():
    scenario = build_scenario()
    _install(scenario.actor)
    rejects = await _reject(scenario, _cmd(scenario, "evade-trace"))
    assert any("no active trace" in event.reason for event in rejects)


async def test_spoof_identity_rejects_without_active_trace():
    scenario = build_scenario()
    _install(scenario.actor)
    rejects = await _reject(scenario, _cmd(scenario, "spoof-identity"))
    assert any("no active trace" in event.reason for event in rejects)


async def test_device_and_hacking_handlers_reject_wrong_kind_targets():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(scenario, "plaza", "site", [CyberpunkSiteComponent()])
    target = str(site)
    cases = {
        "loop-camera": "wrong kind",
        "scan-network": "wrong kind",
        "trace-network": "wrong kind",
        "run-exploit": "wrong kind",
        "use-credential": "wrong kind",
        "access-terminal": "wrong kind",
        "escalate-privileges": "wrong kind",
        "install-backdoor": "wrong kind",
        "exfiltrate-data": "wrong kind",
        "sabotage-system": "wrong kind",
        "unlock": "no handler accepted unlock",
    }
    for command_type, fragment in cases.items():
        rejects = await _reject(scenario, _cmd(scenario, command_type, target_id=target))
        assert any(fragment in event.reason for event in rejects), command_type


async def test_sabotage_rejects_when_already_sabotaged():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _room_entity(
        scenario,
        "fried controller",
        "device",
        [DeviceComponent(device_type="terminal", disabled=True), HackableComponent(breached=True)],
    )
    rejects = await _reject(scenario, _cmd(scenario, "sabotage-system", target_id=str(term)))
    assert any("already sabotaged" in event.reason for event in rejects)


async def test_trace_partially_decrements_without_alarm():
    scenario = build_scenario()
    _install(scenario.actor)
    term = _hackable(scenario, "kiosk", security=1)
    _give_exploit(scenario, 2)
    alarms: list[AlarmRaisedEvent] = []
    scenario.actor.bus.subscribe(AlarmRaisedEvent, alarms.append)

    await scenario.actor.submit(_cmd(scenario, "run-exploit", target_id=str(term)))
    await scenario.actor.tick(1.0)
    await scenario.actor.tick(60.0)

    assert alarms == []
    timer = scenario.actor.world.get_entity(scenario.character).get_component(TraceTimerComponent)
    assert 0 < timer.remaining < TRACE_SECONDS


# --- systematic error-path coverage across every target-taking handler ---------------

TARGET_COMMANDS = (
    "enter-district",
    "show-credentials",
    "bribe",
    "sneak",
    "claim-safehouse",
    "case-location",
    "inspect",
    "disable-camera",
    "loop-camera",
    "jam-sensor",
    "deploy-drone",
    "wipe-evidence",
    "scan-network",
    "trace-network",
    "run-exploit",
    "use-credential",
    "access-terminal",
    "escalate-privileges",
    "install-backdoor",
    "exfiltrate-data",
    "sabotage-system",
    "unlock",
    "buy-contraband",
    "call-favor",
    "post-bounty",
    "turn-informant",
)


async def test_all_target_handlers_reject_missing_targets():
    for command_type in TARGET_COMMANDS:
        scenario = build_scenario()
        _install(scenario.actor)
        rejects = await _reject(scenario, _cmd(scenario, command_type, target_id="999999"))
        assert any("does not exist" in event.reason for event in rejects), command_type


async def test_all_target_handlers_reject_unreachable_targets():
    for command_type in TARGET_COMMANDS:
        scenario = build_scenario()
        _install(scenario.actor)
        far = _far_entity(scenario, "distant rig", "device", [CyberpunkSiteComponent()])
        rejects = await _reject(scenario, _cmd(scenario, command_type, target_id=str(far)))
        assert any("not reachable" in event.reason for event in rejects), command_type


def test_zero_clearance_access_level_omits_clearance_line():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_clearance(scenario, clearance=0)

    joined = "\n".join(
        neonsim_fragments(scenario.actor.world, scenario.actor.world.get_entity(scenario.character))
    )

    assert "Security clearance" not in joined


async def test_bribe_skips_stale_inventory_edge():
    scenario = build_scenario()
    _install(scenario.actor)
    scrip = _give_scrip(scenario, 50)
    # Remove the scrip entity but leave the dangling inventory edge: _spend_scrip must
    # skip the stale edge and still find no spendable scrip.
    scenario.actor.world.remove(scrip)
    gate = _room_entity(scenario, "gate", "checkpoint", [CheckpointComponent(bribe_cost=30)])
    rejects = await _reject(scenario, _cmd(scenario, "bribe", target_id=str(gate)))
    assert any("not enough scrip" in event.reason for event in rejects)


async def test_hacking_ignores_unrelated_inventory_items():
    scenario = build_scenario()
    _install(scenario.actor)
    # Carry junk that is neither an exploit nor a credential; the lookups must skip it.
    _give_scrip(scenario, 5)
    _give_exploit(scenario, 3)
    _give_credential(scenario, "arasaka")
    term = _hackable(scenario, "kiosk", security=2, owner="arasaka")
    succeeded: list[HackSucceededEvent] = []
    scenario.actor.bus.subscribe(HackSucceededEvent, succeeded.append)

    await scenario.actor.submit(_cmd(scenario, "run-exploit", target_id=str(term)))
    await scenario.actor.tick(1.0)

    assert succeeded[0].device_id == str(term)


# --- street economy, heat & wanted (10.5) --------------------------------------------


def _scrip_quantity(scenario):
    for edge, item_id in scenario.actor.world.get_entity(scenario.character).get_relationships(
        Contains
    ):
        if edge.mode != ContainmentMode.INVENTORY or not scenario.actor.world.has_entity(item_id):
            continue
        item = scenario.actor.world.get_entity(item_id)
        if (
            item.has_component(ResourceStackComponent)
            and item.get_component(ResourceStackComponent).resource_type == "scrip"
        ):
            return item.get_component(ResourceStackComponent).quantity
    return 0


async def test_buy_contraband_spends_scrip_and_adds_heat():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 50)
    vendor = _room_entity(
        scenario,
        "fixer stall",
        "vendor",
        [BlackMarketComponent(price=20, contraband_name="chrome", contraband_heat=3.0)],
    )
    bought: list[ContrabandBoughtEvent] = []
    heat: list[HeatChangedEvent] = []
    scenario.actor.bus.subscribe(ContrabandBoughtEvent, bought.append)
    scenario.actor.bus.subscribe(HeatChangedEvent, heat.append)

    await scenario.actor.submit(_cmd(scenario, "buy-contraband", target_id=str(vendor)))
    await scenario.actor.tick(1.0)

    assert bought[0].price == 20
    assert _scrip_quantity(scenario) == 30
    item = scenario.actor.world.get_entity(parse_entity_id(bought[0].item_id))
    assert item.has_component(ContrabandComponent)
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(HeatComponent).amount == 3.0


async def test_sell_data_pays_scrip_and_consumes_item():
    scenario = build_scenario()
    _install(scenario.actor)
    broker = _room_entity(scenario, "fence", "broker", [DataBrokerComponent(rate=50)])
    data = _inventory_entity(
        scenario, "payroll db", "data", [DataPayloadComponent(name="payroll db", sensitive=True)]
    )
    sold: list[DataSoldEvent] = []
    scenario.actor.bus.subscribe(DataSoldEvent, sold.append)

    await scenario.actor.submit(
        _cmd(scenario, "sell-data", broker_id=str(broker), data_id=str(data))
    )
    await scenario.actor.tick(1.0)

    assert sold[0].price == 100  # sensitive data pays double
    assert not scenario.actor.world.has_entity(data)
    assert _scrip_quantity(scenario) == 100


async def test_call_favor_consumes_the_favor():
    scenario = build_scenario()
    _install(scenario.actor)
    contact = _other_character(scenario)
    scenario.actor.world.get_entity(contact).add_relationship(
        OwesFavor(reason="you saved them"), scenario.character
    )
    called: list[FavorCalledEvent] = []
    scenario.actor.bus.subscribe(FavorCalledEvent, called.append)

    await scenario.actor.submit(_cmd(scenario, "call-favor", target_id=str(contact)))
    await scenario.actor.tick(1.0)

    assert called[0].contact_id == str(contact)
    assert not scenario.actor.world.get_entity(contact).has_relationship(
        OwesFavor, scenario.character
    )


async def test_pay_debt_reduces_and_clears_it():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 40)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(DebtComponent(amount=100, defaulted_at_epoch=0))
    paid: list[DebtPaidEvent] = []
    scenario.actor.bus.subscribe(DebtPaidEvent, paid.append)

    await scenario.actor.submit(_cmd(scenario, "pay-debt"))
    await scenario.actor.tick(1.0)

    assert paid[0].amount == 40
    assert paid[0].remaining == 60
    debt = scenario.actor.world.get_entity(scenario.character).get_component(DebtComponent)
    assert debt.amount == 60


async def test_pay_debt_clears_when_fully_paid():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 200)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(DebtComponent(amount=100, defaulted_at_epoch=0))

    await scenario.actor.submit(_cmd(scenario, "pay-debt"))
    await scenario.actor.tick(1.0)

    assert not scenario.actor.world.get_entity(scenario.character).has_component(DebtComponent)
    assert _scrip_quantity(scenario) == 100


async def test_post_bounty_uses_daggersim_bounty_state_and_event():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 500)
    target = _other_character(scenario)
    posted: list[BountyPostedEvent] = []
    scenario.actor.bus.subscribe(BountyPostedEvent, posted.append)

    await scenario.actor.submit(
        _cmd(scenario, "post-bounty", target_id=str(target), amount=300)
    )
    await scenario.actor.tick(1.0)

    assert posted[0].amount == 300
    assert posted[0].crime_id == ""
    bounty = scenario.actor.world.get_entity(target).get_component(BountyComponent)
    assert bounty.amount == 300


async def test_turn_informant_flips_and_spends_scrip():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 50)
    snitch = _room_entity(
        scenario, "rat", "informant", [InformantComponent(faction="police", flip_cost=30)]
    )
    turned: list[InformantTurnedEvent] = []
    scenario.actor.bus.subscribe(InformantTurnedEvent, turned.append)

    await scenario.actor.submit(_cmd(scenario, "turn-informant", target_id=str(snitch)))
    await scenario.actor.tick(1.0)

    assert turned[0].informant_id == str(snitch)
    flipped = scenario.actor.world.get_entity(snitch).get_component(InformantComponent).flipped
    assert flipped is True
    assert _scrip_quantity(scenario) == 20


async def test_hide_from_law_reduces_heat_in_safehouse():
    scenario = build_scenario()
    _install(scenario.actor)
    _room_entity(
        scenario, "den", "safehouse", [SafehouseComponent(claimed_by=str(scenario.character))]
    )
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HeatComponent(amount=10.0, last_updated_epoch=0))
    heat: list[HeatChangedEvent] = []
    scenario.actor.bus.subscribe(HeatChangedEvent, heat.append)

    await scenario.actor.submit(_cmd(scenario, "hide-from-law"))
    await scenario.actor.tick(1.0)

    assert heat[0].amount == 2.0  # 10 - 8 reduction


async def test_heat_escalates_to_wanted_and_triggers_law_response():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 200)
    _room_entity(
        scenario, "vault site", "site", [CyberpunkSiteComponent(), SecurityZoneComponent()]
    )
    vendor = _room_entity(
        scenario,
        "fixer stall",
        "vendor",
        [BlackMarketComponent(price=1, contraband_heat=12.0)],
    )
    wanted: list[WantedLevelChangedEvent] = []
    law: list[LawResponseEvent] = []
    scenario.actor.bus.subscribe(WantedLevelChangedEvent, wanted.append)
    scenario.actor.bus.subscribe(LawResponseEvent, law.append)

    await scenario.actor.submit(_cmd(scenario, "buy-contraband", target_id=str(vendor)))
    await scenario.actor.tick(1.0)

    assert wanted[-1].level == 1
    assert law[-1].level == 1
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(WantedLevelComponent).level == 1


async def test_heat_decays_and_lowers_wanted_over_time():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HeatComponent(amount=11.0, last_updated_epoch=0))
    wanted: list[WantedLevelChangedEvent] = []
    scenario.actor.bus.subscribe(WantedLevelChangedEvent, wanted.append)

    await scenario.actor.tick(1.0)  # wanted becomes 1
    assert character.get_component(WantedLevelComponent).level == 1
    await scenario.actor.tick(2 * 3600.0)  # decay 2 heat -> below threshold

    assert wanted[-1].level == 0
    assert not scenario.actor.world.get_entity(scenario.character).has_component(
        WantedLevelComponent
    )


async def test_clear_warrant_removes_wanted_and_heat():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 200)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(WantedLevelComponent(level=2))
    character.add_component(HeatComponent(amount=30.0, last_updated_epoch=0))
    cleared: list[WarrantClearedEvent] = []
    scenario.actor.bus.subscribe(WarrantClearedEvent, cleared.append)

    await scenario.actor.submit(_cmd(scenario, "clear-warrant"))
    await scenario.actor.tick(1.0)

    assert cleared
    fresh = scenario.actor.world.get_entity(scenario.character)
    assert not fresh.has_component(WantedLevelComponent)
    assert fresh.get_component(HeatComponent).amount == 0.0
    assert _scrip_quantity(scenario) == 120  # 200 - 2*40


def test_street_economy_fragments():
    scenario = build_scenario()
    _install(scenario.actor)
    _room_entity(
        scenario,
        "fixer stall",
        "vendor",
        [BlackMarketComponent(price=15, contraband_name="chrome")],
    )
    _room_entity(scenario, "fence", "broker", [DataBrokerComponent()])
    _room_entity(scenario, "rat", "informant", [InformantComponent(faction="corp")])
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HeatComponent(amount=12.0, last_updated_epoch=0))
    character.add_component(WantedLevelComponent(level=1))
    character.add_component(DebtComponent(amount=250, defaulted_at_epoch=0))

    joined = "\n".join(neonsim_fragments(scenario.actor.world, character))

    assert "Black market fixer stall: chrome for 15 scrip." in joined
    assert "Data broker fence buying data here." in joined
    assert "Informant rat (corp): available." in joined
    assert "Police heat: 12." in joined
    assert "Wanted level: 1." in joined
    assert "Outstanding debt: 250 scrip." in joined


# --- error paths: street economy -----------------------------------------------------


def test_street_handlers_reject_invalid_character_ids_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    target = str(scenario.room_a)
    cases = [
        (BuyContrabandHandler(), "buy-contraband"),
        (SellDataHandler(), "sell-data"),
        (CallFavorHandler(), "call-favor"),
        (PayDebtHandler(), "pay-debt"),
        (PostBountyHandler(), "post-bounty"),
        (TurnInformantHandler(), "turn-informant"),
        (HideFromLawHandler(), "hide-from-law"),
        (ClearWarrantHandler(), "clear-warrant"),
    ]
    for handler, command_type in cases:
        result = handler.execute(
            ctx, _cmd(scenario, command_type, character_id="not-an-id", target_id=target)
        )
        assert result.ok is False
        assert result.reason == "invalid character id"


async def test_buy_contraband_rejects_without_scrip():
    scenario = build_scenario()
    _install(scenario.actor)
    vendor = _room_entity(scenario, "stall", "vendor", [BlackMarketComponent(price=20)])
    rejects = await _reject(scenario, _cmd(scenario, "buy-contraband", target_id=str(vendor)))
    assert any("not enough scrip" in event.reason for event in rejects)


async def test_sell_data_rejects_non_broker():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(scenario, "plaza", "site", [CyberpunkSiteComponent()])
    data = _inventory_entity(scenario, "db", "data", [DataPayloadComponent(name="db")])
    rejects = await _reject(
        scenario, _cmd(scenario, "sell-data", broker_id=str(site), data_id=str(data))
    )
    assert any("wrong kind" in event.reason for event in rejects)


async def test_sell_data_rejects_without_the_data():
    scenario = build_scenario()
    _install(scenario.actor)
    broker = _room_entity(scenario, "fence", "broker", [DataBrokerComponent()])
    rejects = await _reject(
        scenario, _cmd(scenario, "sell-data", broker_id=str(broker), data_id="999999")
    )
    assert any("not carrying that data" in event.reason for event in rejects)


async def test_call_favor_rejects_without_favor():
    scenario = build_scenario()
    _install(scenario.actor)
    contact = _other_character(scenario)
    rejects = await _reject(scenario, _cmd(scenario, "call-favor", target_id=str(contact)))
    assert any("owe you no favor" in event.reason for event in rejects)


async def test_pay_debt_rejects_without_debt():
    scenario = build_scenario()
    _install(scenario.actor)
    rejects = await _reject(scenario, _cmd(scenario, "pay-debt"))
    assert any("no debt" in event.reason for event in rejects)


async def test_pay_debt_rejects_without_scrip():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.world.get_entity(scenario.character).add_component(
        DebtComponent(amount=50, defaulted_at_epoch=0)
    )
    rejects = await _reject(scenario, _cmd(scenario, "pay-debt"))
    assert any("not enough scrip" in event.reason for event in rejects)


async def test_post_bounty_rejects_non_positive_amount():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _other_character(scenario)
    rejects = await _reject(
        scenario, _cmd(scenario, "post-bounty", target_id=str(target), amount=0)
    )
    assert any("must be positive" in event.reason for event in rejects)


async def test_post_bounty_rejects_invalid_amount():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _other_character(scenario)
    rejects = await _reject(
        scenario, _cmd(scenario, "post-bounty", target_id=str(target), amount="lots")
    )
    assert any("invalid bounty amount" in event.reason for event in rejects)


async def test_post_bounty_rejects_without_scrip():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _other_character(scenario)
    rejects = await _reject(
        scenario, _cmd(scenario, "post-bounty", target_id=str(target), amount=100)
    )
    assert any("not enough scrip" in event.reason for event in rejects)


async def test_turn_informant_rejects_when_already_turned():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 100)
    snitch = _room_entity(scenario, "rat", "informant", [InformantComponent(flipped=True)])
    rejects = await _reject(scenario, _cmd(scenario, "turn-informant", target_id=str(snitch)))
    assert any("already turned" in event.reason for event in rejects)


async def test_turn_informant_rejects_without_scrip():
    scenario = build_scenario()
    _install(scenario.actor)
    snitch = _room_entity(scenario, "rat", "informant", [InformantComponent(flip_cost=30)])
    rejects = await _reject(scenario, _cmd(scenario, "turn-informant", target_id=str(snitch)))
    assert any("not enough scrip" in event.reason for event in rejects)


async def test_hide_from_law_rejects_when_not_hunted():
    scenario = build_scenario()
    _install(scenario.actor)
    _room_entity(
        scenario, "den", "safehouse", [SafehouseComponent(claimed_by=str(scenario.character))]
    )
    rejects = await _reject(scenario, _cmd(scenario, "hide-from-law"))
    assert any("not being hunted" in event.reason for event in rejects)


async def test_hide_from_law_rejects_outside_safehouse():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.world.get_entity(scenario.character).add_component(
        HeatComponent(amount=10.0, last_updated_epoch=0)
    )
    rejects = await _reject(scenario, _cmd(scenario, "hide-from-law"))
    assert any("safehouse you have claimed" in event.reason for event in rejects)


async def test_clear_warrant_rejects_without_warrant():
    scenario = build_scenario()
    _install(scenario.actor)
    rejects = await _reject(scenario, _cmd(scenario, "clear-warrant"))
    assert any("no warrant" in event.reason for event in rejects)


async def test_clear_warrant_rejects_without_scrip():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.world.get_entity(scenario.character).add_component(WantedLevelComponent(level=2))
    rejects = await _reject(scenario, _cmd(scenario, "clear-warrant"))
    assert any("not enough scrip" in event.reason for event in rejects)


async def test_sell_data_rejects_missing_broker():
    scenario = build_scenario()
    _install(scenario.actor)
    rejects = await _reject(
        scenario, _cmd(scenario, "sell-data", broker_id="999999", data_id="999999")
    )
    assert any("does not exist" in event.reason for event in rejects)


async def test_payout_stacks_onto_existing_scrip():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 10)
    broker = _room_entity(scenario, "fence", "broker", [DataBrokerComponent(rate=40)])
    data = _inventory_entity(scenario, "logs", "data", [DataPayloadComponent(name="logs")])

    await scenario.actor.submit(
        _cmd(scenario, "sell-data", broker_id=str(broker), data_id=str(data))
    )
    await scenario.actor.tick(1.0)

    assert _scrip_quantity(scenario) == 50  # 10 existing + 40 payout stacked


async def test_hide_from_law_ignores_safehouse_claimed_by_others():
    scenario = build_scenario()
    _install(scenario.actor)
    _room_entity(scenario, "their den", "safehouse", [SafehouseComponent(claimed_by="someone")])
    scenario.actor.world.get_entity(scenario.character).add_component(
        HeatComponent(amount=10.0, last_updated_epoch=0)
    )
    rejects = await _reject(scenario, _cmd(scenario, "hide-from-law"))
    assert any("safehouse you have claimed" in event.reason for event in rejects)


async def test_unlock_door_rejects_when_not_breached():
    scenario = build_scenario()
    _install(scenario.actor)
    door = _hackable(
        scenario, "mag lock", device_type="lock", extra=[LockableComponent(locked=True)]
    )
    rejects = await _reject(scenario, _cmd(scenario, "unlock", target_id=str(door)))
    assert any("breach the system first" in event.reason for event in rejects)


async def test_sell_data_rejects_data_not_in_inventory():
    scenario = build_scenario()
    _install(scenario.actor)
    broker = _room_entity(scenario, "fence", "broker", [DataBrokerComponent()])
    loose_data = _room_entity(scenario, "loose drive", "data", [DataPayloadComponent(name="db")])
    rejects = await _reject(
        scenario, _cmd(scenario, "sell-data", broker_id=str(broker), data_id=str(loose_data))
    )
    assert any("not carrying that data" in event.reason for event in rejects)


# --- cybernetics & implants (10.6) ---------------------------------------------------


async def test_install_implant_consumes_scrip_and_links_it():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 100)
    clinic = _clinic(scenario, install_cost=50)
    implant = _implant_item(scenario, "reflex booster", implant_type="reflex", slot="neural")
    installed: list[ImplantInstalledEvent] = []
    scenario.actor.bus.subscribe(ImplantInstalledEvent, installed.append)

    await scenario.actor.submit(
        _cmd(scenario, "install-implant", implant_id=str(implant), clinic_id=str(clinic))
    )
    await scenario.actor.tick(1.0)

    assert installed[0].implant_type == "reflex"
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_relationship(HasImplant, implant)
    assert not character.has_relationship(Contains, implant)
    assert _scrip_quantity(scenario) == 50


async def test_illegal_implant_from_street_surgeon_adds_heat():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 100)
    surgeon = _clinic(scenario, licensed=False, install_cost=40)
    implant = _implant_item(
        scenario, "wired claws", implant_type="claws", legal=False, install_heat=5.0
    )
    heat: list[HeatChangedEvent] = []
    scenario.actor.bus.subscribe(HeatChangedEvent, heat.append)

    await scenario.actor.submit(
        _cmd(scenario, "install-implant", implant_id=str(implant), clinic_id=str(surgeon))
    )
    await scenario.actor.tick(1.0)

    assert heat[0].amount == 5.0
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(HeatComponent).amount == 5.0


async def test_remove_implant_returns_it_to_inventory():
    scenario = build_scenario()
    _install(scenario.actor)
    implant = _install_implant(scenario, components=[ImplantComponent(implant_type="eye")])
    removed: list[ImplantRemovedEvent] = []
    scenario.actor.bus.subscribe(ImplantRemovedEvent, removed.append)

    await scenario.actor.submit(_cmd(scenario, "remove-implant", implant_id=str(implant)))
    await scenario.actor.tick(1.0)

    assert removed[0].implant_id == str(implant)
    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_relationship(HasImplant, implant)
    assert character.has_relationship(Contains, implant)


async def test_service_implant_resets_maintenance():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 50)
    clinic = _clinic(scenario, service_cost=20)
    implant = _install_implant(
        scenario,
        components=[
            ImplantComponent(
                implant_type="liver", maintenance_interval=3600.0, side_effect="nausea"
            )
        ],
    )
    serviced: list[ImplantServicedEvent] = []
    scenario.actor.bus.subscribe(ImplantServicedEvent, serviced.append)

    await scenario.actor.submit(
        _cmd(scenario, "service-implant", implant_id=str(implant), clinic_id=str(clinic))
    )
    await scenario.actor.tick(1.0)

    assert serviced[0].implant_id == str(implant)
    assert _scrip_quantity(scenario) == 30


async def test_overclock_implant_increases_power_and_risk():
    scenario = build_scenario()
    _install(scenario.actor)
    implant = _install_implant(
        scenario,
        components=[
            ImplantComponent(implant_type="cortex", power_draw=2.0, maintenance_interval=4000.0)
        ],
    )
    overclocked: list[ImplantOverclockedEvent] = []
    scenario.actor.bus.subscribe(ImplantOverclockedEvent, overclocked.append)

    await scenario.actor.submit(_cmd(scenario, "overclock-implant", implant_id=str(implant)))
    await scenario.actor.tick(1.0)

    assert overclocked[0].implant_id == str(implant)
    comp = scenario.actor.world.get_entity(implant).get_component(ImplantComponent)
    assert comp.overclocked is True
    assert comp.power_draw == 3.0
    assert comp.maintenance_interval == 2000.0


async def test_disable_implant_stops_it():
    scenario = build_scenario()
    _install(scenario.actor)
    implant = _install_implant(scenario, components=[ImplantComponent(implant_type="optic")])
    disabled: list[ImplantDisabledEvent] = []
    scenario.actor.bus.subscribe(ImplantDisabledEvent, disabled.append)

    await scenario.actor.submit(_cmd(scenario, "disable-implant", implant_id=str(implant)))
    await scenario.actor.tick(1.0)

    assert disabled[0].implant_id == str(implant)
    assert scenario.actor.world.get_entity(implant).get_component(ImplantComponent).active is False


async def test_license_implant_makes_it_legal():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 100)
    implant = _install_implant(
        scenario, components=[ImplantComponent(implant_type="smartlink", legal=False)]
    )
    licensed: list[ImplantLicensedEvent] = []
    scenario.actor.bus.subscribe(ImplantLicensedEvent, licensed.append)

    await scenario.actor.submit(
        _cmd(scenario, "license-implant", implant_id=str(implant), fee=40)
    )
    await scenario.actor.tick(1.0)

    assert licensed[0].implant_id == str(implant)
    assert scenario.actor.world.get_entity(implant).get_component(ImplantComponent).legal is True
    assert _scrip_quantity(scenario) == 60


async def test_scan_implant_counts_targets_augs():
    scenario = build_scenario()
    _install(scenario.actor)
    other = _other_character(scenario)
    aug = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="aug", kind="implant"), ImplantComponent(implant_type="arm")],
    )
    scenario.actor.world.get_entity(other).add_relationship(HasImplant(), aug.id)
    scanned: list[ImplantScannedEvent] = []
    scenario.actor.bus.subscribe(ImplantScannedEvent, scanned.append)

    await scenario.actor.submit(_cmd(scenario, "scan-implant", target_id=str(other)))
    await scenario.actor.tick(1.0)

    assert scanned[0].implant_count == 1


async def test_exploit_implant_breaches_and_disables_it():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_exploit(scenario, 5)
    other = _other_character(scenario)
    aug = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="netdriver", kind="implant"),
            ImplantComponent(implant_type="neural"),
            HackableComponent(security=3),
        ],
    )
    scenario.actor.world.get_entity(other).add_relationship(HasImplant(), aug.id)
    exploited: list[ImplantExploitedEvent] = []
    scenario.actor.bus.subscribe(ImplantExploitedEvent, exploited.append)

    await scenario.actor.submit(_cmd(scenario, "exploit-implant", target_id=str(other)))
    await scenario.actor.tick(1.0)

    assert exploited[0].implant_id == str(aug.id)
    assert scenario.actor.world.get_entity(aug.id).get_component(HackableComponent).breached is True
    assert scenario.actor.world.get_entity(aug.id).get_component(ImplantComponent).active is False


async def test_exploit_implant_fails_with_weak_exploit():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_exploit(scenario, 1)
    other = _other_character(scenario)
    aug = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="netdriver", kind="implant"),
            ImplantComponent(implant_type="neural"),
            HackableComponent(security=5),
        ],
    )
    scenario.actor.world.get_entity(other).add_relationship(HasImplant(), aug.id)
    failed: list[HackFailedEvent] = []
    scenario.actor.bus.subscribe(HackFailedEvent, failed.append)

    await scenario.actor.submit(_cmd(scenario, "exploit-implant", target_id=str(other)))
    await scenario.actor.tick(1.0)

    assert failed[0].device_id == str(aug.id)
    hack = scenario.actor.world.get_entity(aug.id).get_component(HackableComponent)
    assert hack.breached is False


async def test_neglected_implant_triggers_side_effect():
    scenario = build_scenario()
    _install(scenario.actor)
    _install_implant(
        scenario,
        components=[
            ImplantComponent(
                implant_type="liver",
                maintenance_interval=3600.0,
                side_effect="toxin buildup",
                maintenance_due_epoch=0,
            )
        ],
    )
    effects: list[SideEffectTriggeredEvent] = []
    scenario.actor.bus.subscribe(SideEffectTriggeredEvent, effects.append)

    await scenario.actor.tick(3600.0)

    assert any(event.side_effect == "toxin buildup" for event in effects)


async def test_disabled_implant_does_not_misfire():
    scenario = build_scenario()
    _install(scenario.actor)
    _install_implant(
        scenario,
        components=[
            ImplantComponent(
                implant_type="liver",
                maintenance_interval=3600.0,
                side_effect="toxin",
                active=False,
            )
        ],
    )
    effects: list[SideEffectTriggeredEvent] = []
    scenario.actor.bus.subscribe(SideEffectTriggeredEvent, effects.append)

    await scenario.actor.tick(3600.0)

    assert effects == []


def test_implant_fragments_describe_clinics_and_augs():
    scenario = build_scenario()
    _install(scenario.actor)
    _clinic(scenario, licensed=False, install_cost=40)
    _implant_item(scenario, "spare optic", implant_type="optic", legal=False)
    _install_implant(
        scenario,
        components=[ImplantComponent(implant_type="reflex", slot="neural", overclocked=True)],
    )

    joined = "\n".join(
        neonsim_fragments(scenario.actor.world, scenario.actor.world.get_entity(scenario.character))
    )

    assert "Street surgeon ripperdoc: install 40 scrip." in joined
    assert "Implant for sale: spare optic (optic, ILLEGAL)." in joined
    assert "Implant installed aug: reflex (neural, overclocked)." in joined


def test_offline_illegal_implant_fragment_tags():
    scenario = build_scenario()
    _install(scenario.actor)
    _install_implant(
        scenario,
        components=[ImplantComponent(implant_type="bootleg", active=False, legal=False)],
    )

    joined = "\n".join(
        neonsim_fragments(scenario.actor.world, scenario.actor.world.get_entity(scenario.character))
    )

    assert "Implant installed aug: bootleg (body, offline, illegal)." in joined


# --- error paths: cybernetics --------------------------------------------------------


def test_implant_handlers_reject_invalid_character_ids_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    target = str(scenario.room_a)
    cases = [
        (InstallImplantHandler(), "install-implant"),
        (RemoveImplantHandler(), "remove-implant"),
        (ServiceImplantHandler(), "service-implant"),
        (OverclockImplantHandler(), "overclock-implant"),
        (DisableImplantHandler(), "disable-implant"),
        (LicenseImplantHandler(), "license-implant"),
        (ScanImplantHandler(), "scan-implant"),
        (ExploitImplantHandler(), "exploit-implant"),
    ]
    for handler, command_type in cases:
        result = handler.execute(
            ctx,
            _cmd(scenario, command_type, character_id="not-an-id", target_id=target),
        )
        assert result.ok is False
        assert result.reason == "invalid character id"


async def test_install_implant_rejects_non_clinic():
    scenario = build_scenario()
    _install(scenario.actor)
    implant = _implant_item(scenario)
    site = _room_entity(scenario, "plaza", "site", [CyberpunkSiteComponent()])
    rejects = await _reject(
        scenario, _cmd(scenario, "install-implant", implant_id=str(implant), clinic_id=str(site))
    )
    assert any("wrong kind" in event.reason for event in rejects)


async def test_install_implant_rejects_missing_implant():
    scenario = build_scenario()
    _install(scenario.actor)
    clinic = _clinic(scenario)
    rejects = await _reject(
        scenario, _cmd(scenario, "install-implant", implant_id="999999", clinic_id=str(clinic))
    )
    assert any("not carrying that implant" in event.reason for event in rejects)


async def test_install_implant_rejects_when_slots_full():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 200)
    clinic = _clinic(scenario)
    scenario.actor.world.get_entity(scenario.character).add_component(
        AugmentationSlotsComponent(capacity=1)
    )
    _install_implant(scenario, components=[ImplantComponent(slot_cost=1)])
    implant = _implant_item(scenario, "extra", slot_cost=1)
    rejects = await _reject(
        scenario, _cmd(scenario, "install-implant", implant_id=str(implant), clinic_id=str(clinic))
    )
    assert any("no free augmentation slots" in event.reason for event in rejects)


async def test_licensed_clinic_refuses_illegal_implant():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 200)
    clinic = _clinic(scenario, licensed=True)
    implant = _implant_item(scenario, "wired claws", legal=False)
    rejects = await _reject(
        scenario, _cmd(scenario, "install-implant", implant_id=str(implant), clinic_id=str(clinic))
    )
    assert any("will not fit an illegal implant" in event.reason for event in rejects)


async def test_install_implant_rejects_without_scrip():
    scenario = build_scenario()
    _install(scenario.actor)
    clinic = _clinic(scenario, install_cost=50)
    implant = _implant_item(scenario)
    rejects = await _reject(
        scenario, _cmd(scenario, "install-implant", implant_id=str(implant), clinic_id=str(clinic))
    )
    assert any("not enough scrip" in event.reason for event in rejects)


async def test_remove_implant_rejects_unknown_implant():
    scenario = build_scenario()
    _install(scenario.actor)
    rejects = await _reject(scenario, _cmd(scenario, "remove-implant", implant_id="999999"))
    assert any("no such implant" in event.reason for event in rejects)


async def test_service_implant_rejects_when_no_maintenance():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 50)
    clinic = _clinic(scenario)
    implant = _install_implant(
        scenario, components=[ImplantComponent(maintenance_interval=0.0)]
    )
    rejects = await _reject(
        scenario, _cmd(scenario, "service-implant", implant_id=str(implant), clinic_id=str(clinic))
    )
    assert any("needs no maintenance" in event.reason for event in rejects)


async def test_overclock_implant_rejects_when_already_overclocked():
    scenario = build_scenario()
    _install(scenario.actor)
    implant = _install_implant(scenario, components=[ImplantComponent(overclocked=True)])
    rejects = await _reject(scenario, _cmd(scenario, "overclock-implant", implant_id=str(implant)))
    assert any("already overclocked" in event.reason for event in rejects)


async def test_disable_implant_rejects_when_already_disabled():
    scenario = build_scenario()
    _install(scenario.actor)
    implant = _install_implant(scenario, components=[ImplantComponent(active=False)])
    rejects = await _reject(scenario, _cmd(scenario, "disable-implant", implant_id=str(implant)))
    assert any("already disabled" in event.reason for event in rejects)


async def test_license_implant_rejects_when_already_legal():
    scenario = build_scenario()
    _install(scenario.actor)
    implant = _install_implant(scenario, components=[ImplantComponent(legal=True)])
    rejects = await _reject(scenario, _cmd(scenario, "license-implant", implant_id=str(implant)))
    assert any("already licensed" in event.reason for event in rejects)


async def test_exploit_implant_rejects_without_exploitable_implant():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_exploit(scenario, 5)
    other = _other_character(scenario)
    rejects = await _reject(scenario, _cmd(scenario, "exploit-implant", target_id=str(other)))
    assert any("no exploitable implant" in event.reason for event in rejects)


async def test_implant_target_handlers_reject_missing_and_unreachable():
    for command_type, key in (("scan-implant", "target_id"), ("exploit-implant", "target_id")):
        scenario = build_scenario()
        _install(scenario.actor)
        missing = await _reject(scenario, _cmd(scenario, command_type, **{key: "999999"}))
        assert any("does not exist" in event.reason for event in missing), command_type
        far = _far_entity(scenario, "distant mark", "person", [CharacterComponent(species="bunny")])
        unreachable = await _reject(scenario, _cmd(scenario, command_type, **{key: str(far)}))
        assert any("not reachable" in event.reason for event in unreachable), command_type


async def test_own_implant_handlers_reject_unknown_implant():
    for command_type in (
        "remove-implant",
        "overclock-implant",
        "disable-implant",
        "license-implant",
    ):
        scenario = build_scenario()
        _install(scenario.actor)
        rejects = await _reject(scenario, _cmd(scenario, command_type, implant_id="999999"))
        assert any("no such implant" in event.reason for event in rejects), command_type


async def test_install_and_service_reject_missing_clinic():
    for command_type in ("install-implant", "service-implant"):
        scenario = build_scenario()
        _install(scenario.actor)
        rejects = await _reject(
            scenario,
            _cmd(scenario, command_type, implant_id="999999", clinic_id="999999"),
        )
        assert any("does not exist" in event.reason for event in rejects), command_type


async def test_service_implant_rejects_unknown_implant():
    scenario = build_scenario()
    _install(scenario.actor)
    clinic = _clinic(scenario)
    rejects = await _reject(
        scenario, _cmd(scenario, "service-implant", implant_id="999999", clinic_id=str(clinic))
    )
    assert any("no such implant" in event.reason for event in rejects)


async def test_service_implant_rejects_without_scrip():
    scenario = build_scenario()
    _install(scenario.actor)
    clinic = _clinic(scenario, service_cost=20)
    implant = _install_implant(
        scenario, components=[ImplantComponent(maintenance_interval=3600.0)]
    )
    rejects = await _reject(
        scenario, _cmd(scenario, "service-implant", implant_id=str(implant), clinic_id=str(clinic))
    )
    assert any("not enough scrip for the service" in event.reason for event in rejects)


async def test_license_implant_rejects_without_scrip():
    scenario = build_scenario()
    _install(scenario.actor)
    implant = _install_implant(scenario, components=[ImplantComponent(legal=False)])
    rejects = await _reject(
        scenario, _cmd(scenario, "license-implant", implant_id=str(implant), fee=100)
    )
    assert any("not enough scrip for the license fee" in event.reason for event in rejects)


async def test_license_implant_tolerates_non_numeric_fee():
    scenario = build_scenario()
    _install(scenario.actor)
    implant = _install_implant(scenario, components=[ImplantComponent(legal=False)])
    licensed: list[ImplantLicensedEvent] = []
    scenario.actor.bus.subscribe(ImplantLicensedEvent, licensed.append)

    await scenario.actor.submit(
        _cmd(scenario, "license-implant", implant_id=str(implant), fee="free")
    )
    await scenario.actor.tick(1.0)

    assert licensed  # bad fee parses to 0 and the licensing still completes


# --- fixers, missions & corporate intrigue (10.4) ------------------------------------


async def test_take_fixer_job_accepts_contract():
    scenario = build_scenario()
    _install(scenario.actor)
    contract = _contract(scenario, payout=250)
    accepted: list[FixerJobAcceptedEvent] = []
    scenario.actor.bus.subscribe(FixerJobAcceptedEvent, accepted.append)

    await scenario.actor.submit(_cmd(scenario, "take-fixer-job", target_id=str(contract)))
    await scenario.actor.tick(1.0)

    assert accepted[0].payout == 250
    state = scenario.actor.world.get_entity(contract).get_component(RunnerContractComponent)
    assert state.status == "accepted"
    assert state.accepted_by == str(scenario.character)


async def test_meet_handler_emits_event():
    scenario = build_scenario()
    _install(scenario.actor)
    handler = _room_entity(scenario, "the broker", "handler", [HandlerComponent()])
    met: list[HandlerMetEvent] = []
    scenario.actor.bus.subscribe(HandlerMetEvent, met.append)

    await scenario.actor.submit(_cmd(scenario, "meet-handler", target_id=str(handler)))
    await scenario.actor.tick(1.0)

    assert met[0].handler_id == str(handler)


async def test_deliver_data_completes_contract():
    scenario = build_scenario()
    _install(scenario.actor)
    contract = _contract(scenario, status="accepted", accepted_by=str(scenario.character))
    data = _inventory_entity(
        scenario, "the goods", "data", [DataPayloadComponent(name="schematics")]
    )
    delivered: list[DataDeliveredEvent] = []
    scenario.actor.bus.subscribe(DataDeliveredEvent, delivered.append)

    await scenario.actor.submit(
        _cmd(scenario, "deliver-data", contract_id=str(contract), data_id=str(data))
    )
    await scenario.actor.tick(1.0)

    assert delivered[0].contract_id == str(contract)
    assert not scenario.actor.world.has_entity(data)
    state = scenario.actor.world.get_entity(contract).get_component(RunnerContractComponent)
    assert state.status == "delivered"


async def test_collect_payout_pays_scrip():
    scenario = build_scenario()
    _install(scenario.actor)
    contract = _contract(
        scenario, payout=300, status="delivered", accepted_by=str(scenario.character)
    )
    paid: list[PayoutCollectedEvent] = []
    scenario.actor.bus.subscribe(PayoutCollectedEvent, paid.append)

    await scenario.actor.submit(_cmd(scenario, "collect-payout", target_id=str(contract)))
    await scenario.actor.tick(1.0)

    assert paid[0].amount == 300
    assert _scrip_quantity(scenario) == 300


async def test_collect_payout_double_cross_burns_and_heats():
    scenario = build_scenario()
    _install(scenario.actor)
    contract = _contract(
        scenario,
        payout=300,
        status="delivered",
        accepted_by=str(scenario.character),
        double_cross=True,
    )
    crossed: list[DoubleCrossRevealedEvent] = []
    scenario.actor.bus.subscribe(DoubleCrossRevealedEvent, crossed.append)

    await scenario.actor.submit(_cmd(scenario, "collect-payout", target_id=str(contract)))
    await scenario.actor.tick(1.0)

    assert crossed[0].contract_id == str(contract)
    assert _scrip_quantity(scenario) == 0  # no payout on a double-cross
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(HeatComponent).amount == 5.0
    state = scenario.actor.world.get_entity(contract).get_component(RunnerContractComponent)
    assert state.status == "burned"


async def test_burn_contact_marks_fixer_burned():
    scenario = build_scenario()
    _install(scenario.actor)
    fixer = _room_entity(scenario, "padre", "fixer", [FixerComponent(name="padre")])
    burned: list[ContactBurnedEvent] = []
    scenario.actor.bus.subscribe(ContactBurnedEvent, burned.append)

    await scenario.actor.submit(_cmd(scenario, "burn-contact", target_id=str(fixer)))
    await scenario.actor.tick(1.0)

    assert burned[0].contact_id == str(fixer)
    assert scenario.actor.world.get_entity(fixer).get_component(FixerComponent).burned is True


async def test_plant_evidence_creates_a_blackmail_file():
    scenario = build_scenario()
    _install(scenario.actor)
    mark = _other_character(scenario)
    planted: list[EvidencePlantedEvent] = []
    scenario.actor.bus.subscribe(EvidencePlantedEvent, planted.append)

    await scenario.actor.submit(_cmd(scenario, "plant-evidence", target_id=str(mark)))
    await scenario.actor.tick(1.0)

    assert planted[0].target_id == str(mark)
    file_entity = scenario.actor.world.get_entity(parse_entity_id(planted[0].file_id))
    assert file_entity.get_component(BlackmailFileComponent).target_id == str(mark)


async def test_blackmail_target_extracts_a_favor():
    scenario = build_scenario()
    _install(scenario.actor)
    mark = _other_character(scenario)
    file = _inventory_entity(
        scenario, "the photos", "evidence", [BlackmailFileComponent(target_id=str(mark))]
    )
    applied: list[BlackmailAppliedEvent] = []
    scenario.actor.bus.subscribe(BlackmailAppliedEvent, applied.append)

    await scenario.actor.submit(
        _cmd(scenario, "blackmail-target", target_id=str(mark), file_id=str(file))
    )
    await scenario.actor.tick(1.0)

    assert applied[0].target_id == str(mark)
    assert scenario.actor.world.get_entity(mark).has_relationship(OwesFavor, scenario.character)
    assert scenario.actor.world.get_entity(file).get_component(BlackmailFileComponent).used is True


async def test_leak_file_burns_the_target():
    scenario = build_scenario()
    _install(scenario.actor)
    mark = _other_character(scenario)
    file = _room_entity(
        scenario, "leaked dossier", "evidence", [BlackmailFileComponent(target_id=str(mark))]
    )
    leaked: list[FileLeakedEvent] = []
    scenario.actor.bus.subscribe(FileLeakedEvent, leaked.append)

    await scenario.actor.submit(_cmd(scenario, "leak-file", target_id=str(file)))
    await scenario.actor.tick(1.0)

    assert leaked[0].file_id == str(file)
    file_state = scenario.actor.world.get_entity(file).get_component(BlackmailFileComponent)
    assert file_state.leaked is True
    assert scenario.actor.world.get_entity(mark).get_component(HeatComponent).amount == 4.0


async def test_extract_asset_marks_it_extracted():
    scenario = build_scenario()
    _install(scenario.actor)
    asset = _room_entity(scenario, "defector", "asset", [AssetExtractionComponent()])
    extracted: list[AssetExtractedEvent] = []
    scenario.actor.bus.subscribe(AssetExtractedEvent, extracted.append)

    await scenario.actor.submit(_cmd(scenario, "extract-asset", target_id=str(asset)))
    await scenario.actor.tick(1.0)

    assert extracted[0].asset_id == str(asset)
    assert scenario.actor.world.get_entity(asset).get_component(AssetExtractionComponent).extracted


def test_intrigue_fragments():
    scenario = build_scenario()
    _install(scenario.actor)
    _room_entity(scenario, "padre", "fixer", [FixerComponent(name="padre")])
    _room_entity(scenario, "the broker", "handler", [HandlerComponent()])
    _contract(scenario, payout=150)
    _room_entity(scenario, "dossier", "evidence", [BlackmailFileComponent(target_id="x")])
    _room_entity(scenario, "defector", "asset", [AssetExtractionComponent()])

    joined = "\n".join(
        neonsim_fragments(scenario.actor.world, scenario.actor.world.get_entity(scenario.character))
    )

    assert "Fixer padre: open for work." in joined
    assert "Handler the broker waiting for a hand-off." in joined
    assert "Contract data run: courier, 150 scrip (offered)." in joined
    assert "Blackmail file dossier: leverage." in joined
    assert "Asset defector: awaiting extraction." in joined


# --- error paths: intrigue -----------------------------------------------------------


def test_intrigue_handlers_reject_invalid_character_ids_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    target = str(scenario.room_a)
    cases = [
        (TakeFixerJobHandler(), "take-fixer-job"),
        (MeetHandlerHandler(), "meet-handler"),
        (DeliverDataHandler(), "deliver-data"),
        (CollectPayoutHandler(), "collect-payout"),
        (BurnContactHandler(), "burn-contact"),
        (PlantEvidenceHandler(), "plant-evidence"),
        (BlackmailTargetHandler(), "blackmail-target"),
        (LeakFileHandler(), "leak-file"),
        (ExtractAssetHandler(), "extract-asset"),
    ]
    for handler, command_type in cases:
        result = handler.execute(
            ctx, _cmd(scenario, command_type, character_id="not-an-id", target_id=target)
        )
        assert result.ok is False
        assert result.reason == "invalid character id"


async def test_take_fixer_job_rejects_unavailable_contract():
    scenario = build_scenario()
    _install(scenario.actor)
    contract = _contract(scenario, status="accepted", accepted_by="someone")
    rejects = await _reject(scenario, _cmd(scenario, "take-fixer-job", target_id=str(contract)))
    assert any("no longer available" in event.reason for event in rejects)


async def test_deliver_data_rejects_unowned_contract():
    scenario = build_scenario()
    _install(scenario.actor)
    contract = _contract(scenario, status="accepted", accepted_by="someone-else")
    data = _inventory_entity(scenario, "goods", "data", [DataPayloadComponent(name="db")])
    rejects = await _reject(
        scenario, _cmd(scenario, "deliver-data", contract_id=str(contract), data_id=str(data))
    )
    assert any("did not take this job" in event.reason for event in rejects)


async def test_deliver_data_rejects_when_not_awaiting_delivery():
    scenario = build_scenario()
    _install(scenario.actor)
    contract = _contract(scenario, status="delivered", accepted_by=str(scenario.character))
    data = _inventory_entity(scenario, "goods", "data", [DataPayloadComponent(name="db")])
    rejects = await _reject(
        scenario, _cmd(scenario, "deliver-data", contract_id=str(contract), data_id=str(data))
    )
    assert any("not awaiting delivery" in event.reason for event in rejects)


async def test_deliver_data_rejects_without_the_data():
    scenario = build_scenario()
    _install(scenario.actor)
    contract = _contract(scenario, status="accepted", accepted_by=str(scenario.character))
    rejects = await _reject(
        scenario, _cmd(scenario, "deliver-data", contract_id=str(contract), data_id="999999")
    )
    assert any("not carrying that data" in event.reason for event in rejects)


async def test_collect_payout_rejects_other_peoples_job():
    scenario = build_scenario()
    _install(scenario.actor)
    contract = _contract(scenario, status="delivered", accepted_by="someone")
    rejects = await _reject(scenario, _cmd(scenario, "collect-payout", target_id=str(contract)))
    assert any("not your job" in event.reason for event in rejects)


async def test_collect_payout_rejects_before_delivery():
    scenario = build_scenario()
    _install(scenario.actor)
    contract = _contract(scenario, status="accepted", accepted_by=str(scenario.character))
    rejects = await _reject(scenario, _cmd(scenario, "collect-payout", target_id=str(contract)))
    assert any("nothing to collect yet" in event.reason for event in rejects)


async def test_burn_contact_rejects_when_already_burned():
    scenario = build_scenario()
    _install(scenario.actor)
    fixer = _room_entity(scenario, "padre", "fixer", [FixerComponent(burned=True)])
    rejects = await _reject(scenario, _cmd(scenario, "burn-contact", target_id=str(fixer)))
    assert any("already burned" in event.reason for event in rejects)


async def test_blackmail_rejects_wrong_file():
    scenario = build_scenario()
    _install(scenario.actor)
    mark = _other_character(scenario)
    other = _other_character(scenario)
    file = _inventory_entity(
        scenario, "wrong photos", "evidence", [BlackmailFileComponent(target_id=str(other))]
    )
    rejects = await _reject(
        scenario, _cmd(scenario, "blackmail-target", target_id=str(mark), file_id=str(file))
    )
    assert any("not about them" in event.reason for event in rejects)


async def test_blackmail_rejects_without_file():
    scenario = build_scenario()
    _install(scenario.actor)
    mark = _other_character(scenario)
    rejects = await _reject(
        scenario, _cmd(scenario, "blackmail-target", target_id=str(mark), file_id="999999")
    )
    assert any("not holding that file" in event.reason for event in rejects)


async def test_blackmail_rejects_spent_file():
    scenario = build_scenario()
    _install(scenario.actor)
    mark = _other_character(scenario)
    file = _inventory_entity(
        scenario,
        "used photos",
        "evidence",
        [BlackmailFileComponent(target_id=str(mark), used=True)],
    )
    rejects = await _reject(
        scenario, _cmd(scenario, "blackmail-target", target_id=str(mark), file_id=str(file))
    )
    assert any("already spent" in event.reason for event in rejects)


async def test_leak_file_rejects_when_already_leaked():
    scenario = build_scenario()
    _install(scenario.actor)
    file = _room_entity(scenario, "old leak", "evidence", [BlackmailFileComponent(leaked=True)])
    rejects = await _reject(scenario, _cmd(scenario, "leak-file", target_id=str(file)))
    assert any("already leaked" in event.reason for event in rejects)


async def test_extract_asset_rejects_when_already_extracted():
    scenario = build_scenario()
    _install(scenario.actor)
    asset = _room_entity(scenario, "defector", "asset", [AssetExtractionComponent(extracted=True)])
    rejects = await _reject(scenario, _cmd(scenario, "extract-asset", target_id=str(asset)))
    assert any("already extracted" in event.reason for event in rejects)


async def test_intrigue_target_handlers_reject_missing_and_unreachable():
    commands = (
        ("take-fixer-job", "target_id"),
        ("meet-handler", "target_id"),
        ("collect-payout", "target_id"),
        ("burn-contact", "target_id"),
        ("plant-evidence", "target_id"),
        ("leak-file", "target_id"),
        ("extract-asset", "target_id"),
    )
    for command_type, key in commands:
        scenario = build_scenario()
        _install(scenario.actor)
        missing = await _reject(scenario, _cmd(scenario, command_type, **{key: "999999"}))
        assert any("does not exist" in event.reason for event in missing), command_type
        far = _far_entity(scenario, "distant", "thing", [CharacterComponent(species="bunny")])
        unreachable = await _reject(scenario, _cmd(scenario, command_type, **{key: str(far)}))
        assert any("not reachable" in event.reason for event in unreachable), command_type


async def test_deliver_data_rejects_missing_and_unreachable_contract():
    scenario = build_scenario()
    _install(scenario.actor)
    missing = await _reject(
        scenario, _cmd(scenario, "deliver-data", contract_id="999999", data_id="999999")
    )
    assert any("does not exist" in event.reason for event in missing)
    far = _far_entity(scenario, "far contract", "contract", [RunnerContractComponent()])
    unreachable = await _reject(
        scenario, _cmd(scenario, "deliver-data", contract_id=str(far), data_id="1")
    )
    assert any("not reachable" in event.reason for event in unreachable)


async def test_blackmail_rejects_missing_and_unreachable_target():
    scenario = build_scenario()
    _install(scenario.actor)
    missing = await _reject(
        scenario, _cmd(scenario, "blackmail-target", target_id="999999", file_id="1")
    )
    assert any("does not exist" in event.reason for event in missing)
    far = _far_entity(scenario, "far mark", "person", [CharacterComponent(species="bunny")])
    unreachable = await _reject(
        scenario, _cmd(scenario, "blackmail-target", target_id=str(far), file_id="1")
    )
    assert any("not reachable" in event.reason for event in unreachable)


async def test_leak_file_with_non_character_target_skips_heat():
    scenario = build_scenario()
    _install(scenario.actor)
    # A planted file with no real character behind target_id must leak without crashing.
    file = _room_entity(scenario, "anon leak", "evidence", [BlackmailFileComponent(target_id="")])
    leaked: list[FileLeakedEvent] = []
    scenario.actor.bus.subscribe(FileLeakedEvent, leaked.append)

    await scenario.actor.submit(_cmd(scenario, "leak-file", target_id=str(file)))
    await scenario.actor.tick(1.0)

    assert leaked[0].file_id == str(file)


# --- helper coverage: dangling/edge-case branches ------------------------------------

from bunnyland.mechanics import neonsim as _neon  # noqa: E402


def test_payload_entity_id_returns_none_when_no_key_matches():
    scenario = build_scenario()
    command = _cmd(scenario, "noop", other="x")
    # Neither requested key is in the payload -> falls through to None.
    assert _neon._payload_entity_id(command, "target_id", "device_id") is None


def test_can_handle_target_component_when_character_is_invalid():
    scenario = build_scenario()
    _install(scenario.actor)
    device = _hackable(scenario, security=1)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # An existing, reachable target but an unparseable character id: can_handle
    # short-circuits to True (the handler will reject with a clear reason later).
    command = _cmd(scenario, "unlock", target_id=str(device), character_id="not-an-id")
    assert UnlockDoorHandler().can_handle(ctx, command) is True


def test_can_handle_target_component_alias_key_is_handled():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # A non-"target_id" alias key present in the payload claims the command.
    command = _cmd(scenario, "unlock", device_id="anything")
    assert UnlockDoorHandler().can_handle(ctx, command) is True


def test_district_name_empty_when_room_has_no_region():
    scenario = build_scenario()
    # The starting room has no RegionComponent.
    assert _neon._district_name(scenario.actor.world, scenario.character) == ""


def test_spend_scrip_no_op_for_non_positive_amount():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    assert _neon._spend_scrip(character, scenario.actor.world, 0) is True


def test_spend_scrip_partial_leaves_unparented_stack_in_place():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    scrip = spawn_entity(
        world,
        [
            IdentityComponent(name="scrip x10", kind="resource"),
            ResourceStackComponent(resource_type="scrip", quantity=10),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), scrip.id)
    # Spend less than the stack: it is decremented and kept, container_of path runs
    # but the full-drain removal branch is not taken.
    assert _neon._spend_scrip(character, world, 4) is True
    stack = world.get_entity(scrip.id).get_component(ResourceStackComponent)
    assert stack.quantity == 6


def test_evidence_for_skips_wiped_and_mismatched_records():
    scenario = build_scenario()
    world = scenario.actor.world
    spawn_entity(
        world,
        [RecordedEvidenceComponent(subject_id="A", device_id="cam", wiped=True)],
    )
    spawn_entity(
        world,
        [RecordedEvidenceComponent(subject_id="other", device_id="cam", wiped=False)],
    )
    assert _neon._evidence_for(world, "A", "cam") is None


def test_best_exploit_ignores_non_inventory_and_weaker_items():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    # A stronger exploit sitting in the room (ROOM_CONTENT, not inventory) is ignored.
    room_exploit = spawn_entity(world, [_neon.ExploitComponent(power=9)])
    character.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), room_exploit.id)
    # Two inventory exploits: the weaker one must not displace the stronger.
    _inventory_entity(scenario, "weak", "tool", [_neon.ExploitComponent(power=2)])
    _inventory_entity(scenario, "strong", "tool", [_neon.ExploitComponent(power=5)])
    power, item = _neon._best_exploit(character, world)
    assert power == 5
    assert item is not None


def test_matching_credential_skips_non_inventory_relationships():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    cred = spawn_entity(world, [_neon.CredentialComponent(target_owner="arasaka")])
    # In the room, not the inventory: ignored by the inventory-only scan.
    character.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), cred.id)
    assert _neon._matching_credential(character, world, "arasaka") is None


def test_raise_local_alarm_leaves_already_raised_zone_untouched():
    scenario = build_scenario()
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    room.add_component(SecurityZoneComponent(clearance_required=1, alarm_raised=True))
    _neon._raise_local_alarm(world, scenario.character)
    assert room.get_component(SecurityZoneComponent).alarm_raised is True


def test_scrip_stack_skips_non_inventory_and_non_scrip_items():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    # Non-inventory scrip is skipped by the mode filter.
    room_scrip = spawn_entity(
        world, [ResourceStackComponent(resource_type="scrip", quantity=5)]
    )
    character.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), room_scrip.id)
    # Inventory item that is not scrip is skipped by the resource-type check.
    _inventory_entity(
        scenario, "ammo", "resource", [ResourceStackComponent(resource_type="ammo", quantity=3)]
    )
    assert _neon._scrip_stack(character, world) is None


def test_add_scrip_no_op_for_non_positive_amount():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    _neon._add_scrip(character, world, 0)
    assert _neon._scrip_stack(character, world) is None


def test_remove_item_handles_unparented_entity():
    scenario = build_scenario()
    world = scenario.actor.world
    orphan = spawn_entity(world, [IdentityComponent(name="loose", kind="item")])
    # No container relationship: the remove path skips the parent-detach branch.
    _neon._remove_item(world, orphan.id)
    assert not world.has_entity(orphan.id)


def test_installed_implants_skips_relationships_without_implant_component():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    # A HasImplant edge to an entity lacking ImplantComponent is filtered out.
    not_an_implant = spawn_entity(world, [IdentityComponent(name="bracket", kind="part")])
    character.add_relationship(HasImplant(slot="body"), not_an_implant.id)
    assert _neon._installed_implants(character, world) == []


def test_own_implant_returns_none_without_has_implant_edge():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    # Implant exists and is owned-by-inventory, but no HasImplant edge -> None.
    implant = _inventory_entity(scenario, "loose aug", "implant", [ImplantComponent()])
    assert _neon._own_implant(character, world, str(implant)) is None


def test_contraband_component_fragment_names_the_item():
    scenario = build_scenario()
    world = scenario.actor.world
    item = _room_entity(scenario, "red dust", "contraband", [ContrabandComponent(value=20)])
    ctx = ComponentPromptContext.for_entity(world, world.get_entity(item))
    assert world.get_entity(item).get_component(ContrabandComponent).prompt_fragments(ctx) == (
        "Contraband: red dust.",
    )


async def test_trespass_in_restricted_area_without_security_zone():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(
        scenario,
        "open vault",
        "site",
        [CyberpunkSiteComponent(site_type="vault"), RestrictedAreaComponent(patrol=True)],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        InsideZone(authorized=False), site
    )
    trespass: list[TrespassDetectedEvent] = []
    scenario.actor.bus.subscribe(TrespassDetectedEvent, trespass.append)

    await scenario.actor.tick(1.0)

    assert len(trespass) == 1
    # No SecurityZoneComponent to flag, but the InsideZone edge is still dropped.
    assert _inside(scenario, site) is None


async def test_deploy_drone_powers_a_powered_drone_without_double_toggle():
    scenario = build_scenario()
    _install(scenario.actor)
    drone = _room_entity(
        scenario,
        "recon drone",
        "device",
        [DeviceComponent(device_type="drone", powered=True), DroneComponent(active=False)],
    )
    deployed: list[DroneDeployedEvent] = []
    scenario.actor.bus.subscribe(DroneDeployedEvent, deployed.append)

    await scenario.actor.submit(_cmd(scenario, "deploy-drone", target_id=str(drone)))
    await scenario.actor.tick(1.0)

    assert deployed and deployed[0].device_id == str(drone)
    device = scenario.actor.world.get_entity(drone)
    assert device.get_component(DroneComponent).active is True
    assert device.get_component(DeviceComponent).powered is True


async def test_wipe_evidence_for_unparented_record():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    # Record reachable via the room, then detached so it has no container.
    record = _room_entity(
        scenario,
        "free tape",
        "evidence",
        [RecordedEvidenceComponent(subject_id="x", device_id="cam")],
    )
    # Keep it reachable for the handler by leaving it in the room; the parent
    # branch runs. Instead exercise the no-parent path via the helper directly.
    orphan = spawn_entity(
        world, [RecordedEvidenceComponent(subject_id="y", device_id="cam2")]
    )
    _neon._remove_item(world, orphan.id)
    assert not world.has_entity(orphan.id)
    assert world.has_entity(parse_entity_id(str(record)))


async def test_trace_network_on_uncontained_room_device():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    # Make the character's own (uncontained) room a hackable network device. Tracing
    # it finds no containing room, so the sibling scan is skipped (node_count stays 0).
    room = world.get_entity(scenario.room_a)
    room.add_component(DeviceComponent(device_type="terminal"))
    room.add_component(HackableComponent(security=1))
    traced: list[NetworkTracedEvent] = []
    scenario.actor.bus.subscribe(NetworkTracedEvent, traced.append)

    await scenario.actor.submit(_cmd(scenario, "trace-network", target_id=str(scenario.room_a)))
    await scenario.actor.tick(1.0)

    assert traced and traced[0].node_count == 0


async def test_run_exploit_consumes_single_use_inventory_exploit():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    device = _hackable(scenario, security=2)
    exploit = _give_exploit(scenario, power=5, single_use=True)
    succeeded: list = []
    scenario.actor.bus.subscribe(HackSucceededEvent, succeeded.append)

    await scenario.actor.submit(_cmd(scenario, "run-exploit", target_id=str(device)))
    await scenario.actor.tick(1.0)

    assert succeeded
    assert world.get_entity(device).get_component(HackableComponent).breached is True
    # Single-use exploit was consumed (removed via its inventory container).
    assert not world.has_entity(parse_entity_id(str(exploit)))


async def test_sabotage_system_without_device_component():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    # A breached HackableComponent with no DeviceComponent: the disable block is skipped.
    target = _room_entity(
        scenario,
        "raw node",
        "device",
        [HackableComponent(security=1, breached=True)],
    )
    sabotaged: list[SystemSabotagedEvent] = []
    scenario.actor.bus.subscribe(SystemSabotagedEvent, sabotaged.append)

    await scenario.actor.submit(_cmd(scenario, "sabotage-system", target_id=str(target)))
    await scenario.actor.tick(1.0)

    assert sabotaged and sabotaged[0].device_id == str(target)
    assert not world.get_entity(target).has_component(DeviceComponent)


async def test_unlock_lockable_that_is_not_a_network_device():
    scenario = build_scenario()
    _install(scenario.actor)
    # LockableComponent but no HackableComponent. can_handle() declines such targets,
    # so call execute() directly to reach the in-handler rejection.
    door = _room_entity(
        scenario,
        "manual gate",
        "device",
        [LockableComponent(locked=True)],
    )
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    result = UnlockDoorHandler().execute(ctx, _cmd(scenario, "unlock", target_id=str(door)))
    assert result.ok is False
    assert result.reason == "target is not a network device"


def test_pay_debt_rejects_when_spend_scrip_underdrains(monkeypatch):
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    character.add_component(DebtComponent(amount=50, defaulted_at_epoch=0))
    _give_scrip(scenario, 30)
    ctx = HandlerContext(world, scenario.actor.epoch)
    # Force the defensive double-check: _spend_scrip reports failure even though
    # _scrip_stack reported available funds.
    monkeypatch.setattr(_neon, "_spend_scrip", lambda *a, **k: False)
    result = PayDebtHandler().execute(ctx, _cmd(scenario, "pay-debt"))
    assert result.ok is False
    assert result.reason == "not enough scrip to pay the debt"


async def test_scan_implant_skips_already_breached_implants():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    subject = _other_character(scenario)
    subject_entity = world.get_entity(subject)
    # An installed implant that is hackable but already breached -> loop continues
    # past it without selecting a target.
    breached_implant = spawn_entity(
        world,
        [
            IdentityComponent(name="cracked deck", kind="implant"),
            ImplantComponent(),
            HackableComponent(security=1, breached=True),
        ],
    )
    subject_entity.add_relationship(HasImplant(slot="body"), breached_implant.id)
    rejects = await _reject(
        scenario, _cmd(scenario, "exploit-implant", target_id=str(subject))
    )
    assert rejects


def test_district_name_empty_when_character_has_no_room():
    scenario = build_scenario()
    world = scenario.actor.world
    # A character with no containing room: room_id is None.
    loner = spawn_entity(
        world, [IdentityComponent(name="drifter", kind="character"), CharacterComponent()]
    )
    assert _neon._district_name(world, loner.id) == ""


def test_best_exploit_keeps_first_when_later_is_weaker():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    _inventory_entity(scenario, "strong", "tool", [_neon.ExploitComponent(power=8)])
    _inventory_entity(scenario, "weak", "tool", [_neon.ExploitComponent(power=3)])
    power, _item = _neon._best_exploit(character, world)
    assert power == 8


def test_neonsim_fragments_dedup_when_installed_implant_is_also_reachable():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    # Implant in the room (reachable) AND installed via HasImplant -> reported once,
    # via the installed pass; the reachable pass skips it.
    implant = _room_entity(
        scenario, "reflex wire", "implant", [ImplantComponent(implant_type="reflex")]
    )
    character.add_relationship(HasImplant(slot="body"), implant)
    lines = _neon.neonsim_fragments(world, character)
    assert len([line for line in lines if "reflex" in line]) == 1


