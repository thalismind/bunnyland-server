"""Tests for neon-sim districts, sites, access control, and trespass (catalogue 10.1)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    HandlerContext,
    IdentityComponent,
    Lane,
    PortableComponent,
    RegionComponent,
    build_submitted_command,
    container_of,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.mechanics.colonysim import ResourceStackComponent
from bunnyland.mechanics.neonsim import (
    AccessDeniedEvent,
    AccessGrantedEvent,
    AccessLevelComponent,
    BlindSpotComponent,
    BribeCheckpointHandler,
    CameraComponent,
    CameraDisabledEvent,
    CameraLoopedEvent,
    CaseLocationHandler,
    CheckpointComponent,
    CheckpointPassedEvent,
    ClaimSafehouseHandler,
    CyberpunkSiteComponent,
    DeployDroneHandler,
    DeviceComponent,
    DeviceInspectedEvent,
    DisableCameraHandler,
    DistrictEnteredEvent,
    DroneComponent,
    DroneDeployedEvent,
    EnterDistrictHandler,
    EvidenceRecordedEvent,
    EvidenceWipedEvent,
    InsideZone,
    InspectDeviceHandler,
    JamSensorHandler,
    LocationCasedEvent,
    LoopCameraHandler,
    PublicAccessComponent,
    RecordedEvidenceComponent,
    RestrictedAreaComponent,
    SafehouseClaimedEvent,
    SafehouseComponent,
    SecurityZoneComponent,
    SensorJammedEvent,
    ShowCredentialsHandler,
    SneakCheckpointHandler,
    SurveillanceCoverageComponent,
    TrespassDetectedEvent,
    WipeEvidenceHandler,
    install_neonsim,
    neonsim_fragments,
)


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
    install_neonsim(actor)


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


# --- bribe-guard ---------------------------------------------------------------------


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

    await scenario.actor.submit(_cmd(scenario, "bribe-checkpoint", target_id=str(gate)))
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

    await scenario.actor.submit(_cmd(scenario, "bribe-checkpoint", target_id=str(gate)))
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

    await scenario.actor.submit(_cmd(scenario, "bribe-checkpoint", target_id=str(gate)))
    await scenario.actor.tick(1.0)

    gate_state = scenario.actor.world.get_entity(gate).get_component(CheckpointComponent)
    assert gate_state.alerted is False


# --- sneak-through-checkpoint --------------------------------------------------------


async def test_sneak_through_calm_checkpoint_succeeds():
    scenario = build_scenario()
    _install(scenario.actor)
    gate = _room_entity(
        scenario, "fence gap", "checkpoint", [CheckpointComponent(clearance_required=2)]
    )
    passed: list[CheckpointPassedEvent] = []
    scenario.actor.bus.subscribe(CheckpointPassedEvent, passed.append)

    await scenario.actor.submit(
        _cmd(scenario, "sneak-through-checkpoint", target_id=str(gate))
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


# --- error paths: invalid / missing / unreachable / wrong-kind ----------------------


def test_handlers_reject_invalid_character_ids_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    target = str(scenario.room_a)
    cases = [
        (EnterDistrictHandler(), "enter-district"),
        (ShowCredentialsHandler(), "show-credentials"),
        (BribeCheckpointHandler(), "bribe-checkpoint"),
        (SneakCheckpointHandler(), "sneak-through-checkpoint"),
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
    rejects = await _reject(scenario, _cmd(scenario, "bribe-checkpoint", target_id=str(site)))
    assert any("wrong kind" in event.reason for event in rejects)


async def test_bribe_guard_rejects_checkpoint_without_bribe_cost():
    scenario = build_scenario()
    _install(scenario.actor)
    gate = _room_entity(scenario, "gate", "checkpoint", [CheckpointComponent(bribe_cost=0)])
    rejects = await _reject(scenario, _cmd(scenario, "bribe-checkpoint", target_id=str(gate)))
    assert any("no guard to bribe" in event.reason for event in rejects)


async def test_bribe_guard_rejects_without_enough_scrip():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_scrip(scenario, 10)
    gate = _room_entity(scenario, "gate", "checkpoint", [CheckpointComponent(bribe_cost=30)])
    rejects = await _reject(scenario, _cmd(scenario, "bribe-checkpoint", target_id=str(gate)))
    assert any("not enough scrip" in event.reason for event in rejects)


async def test_bribe_guard_rejects_with_no_scrip_at_all():
    scenario = build_scenario()
    _install(scenario.actor)
    gate = _room_entity(scenario, "gate", "checkpoint", [CheckpointComponent(bribe_cost=30)])
    rejects = await _reject(scenario, _cmd(scenario, "bribe-checkpoint", target_id=str(gate)))
    assert any("not enough scrip" in event.reason for event in rejects)



async def test_sneak_rejects_non_checkpoint():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(scenario, "plaza", "site", [CyberpunkSiteComponent()])
    rejects = await _reject(
        scenario, _cmd(scenario, "sneak-through-checkpoint", target_id=str(site))
    )
    assert any("wrong kind" in event.reason for event in rejects)


async def test_sneak_rejects_alerted_checkpoint():
    scenario = build_scenario()
    _install(scenario.actor)
    gate = _room_entity(
        scenario, "gate", "checkpoint", [CheckpointComponent(clearance_required=2, alerted=True)]
    )
    rejects = await _reject(
        scenario, _cmd(scenario, "sneak-through-checkpoint", target_id=str(gate))
    )
    assert any("watching too closely" in event.reason for event in rejects)


async def test_sneak_rejects_when_already_cleared():
    scenario = build_scenario()
    _install(scenario.actor)
    _give_clearance(scenario, clearance=5)
    gate = _room_entity(scenario, "gate", "checkpoint", [CheckpointComponent(clearance_required=2)])
    rejects = await _reject(
        scenario, _cmd(scenario, "sneak-through-checkpoint", target_id=str(gate))
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
    rejects = await _reject(scenario, _cmd(scenario, "bribe-checkpoint", target_id=str(gate)))
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

    await scenario.actor.submit(_cmd(scenario, "inspect-device", target_id=str(cam)))
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
    assert entity.get_component(DroneComponent).deployed is True
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
        (InspectDeviceHandler(), "inspect-device"),
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
    rejects = await _reject(scenario, _cmd(scenario, "inspect-device", target_id=str(site)))
    assert any("wrong kind" in event.reason for event in rejects)


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
        [DeviceComponent(device_type="drone"), DroneComponent(deployed=True)],
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
