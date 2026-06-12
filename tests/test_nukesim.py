"""Tests for nuke-sim radiation, mutations, scavenging, and scrapping."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    HandlerContext,
    IdentityComponent,
    Lane,
    PortableComponent,
    build_submitted_command,
    container_of,
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.mechanics.colonysim import ResourceStackComponent
from bunnyland.mechanics.nukesim import (
    AddictionComponent,
    ChemComponent,
    ChemTakenEvent,
    ContaminatedWaterDrunkEvent,
    DecontaminateHandler,
    DecontaminationAppliedEvent,
    DecontaminationComponent,
    DrinkContaminatedWaterHandler,
    IdentifyTechHandler,
    ItemScrappedEvent,
    JunkComponent,
    LootFoundEvent,
    LootTableComponent,
    MutationComponent,
    MutationManifestedEvent,
    OldWorldTechComponent,
    OldWorldTechIdentifiedEvent,
    OldWorldTechRestoredEvent,
    PurifyWaterHandler,
    RadiationDoseComponent,
    RadiationExposureEvent,
    RadiationScannedEvent,
    RadiationSicknessComponent,
    RadiationSourceComponent,
    RadiationSourceSealedEvent,
    RadMedicineComponent,
    RadProtectionComponent,
    RestoreTechHandler,
    ScanRadiationHandler,
    ScavengeHandler,
    ScavengeSiteComponent,
    ScrapItemHandler,
    SealRadiationSourceHandler,
    StabilizeMutationHandler,
    TakeChemHandler,
    TechLeadComponent,
    UseRadMedicineHandler,
    WaterPurifiedEvent,
    WaterPurityComponent,
    WithdrawalProgressedEvent,
    install_nukesim,
    nukesim_fragments,
)
from bunnyland.mechanics.voidsim import RadiationMutationPressureComponent

HOUR = 3600.0


def _install(actor):
    actor.register_handler(ScanRadiationHandler())
    actor.register_handler(SealRadiationSourceHandler())
    actor.register_handler(DecontaminateHandler())
    actor.register_handler(UseRadMedicineHandler())
    actor.register_handler(ScavengeHandler())
    actor.register_handler(ScrapItemHandler())
    actor.register_handler(StabilizeMutationHandler())
    actor.register_handler(IdentifyTechHandler())
    actor.register_handler(RestoreTechHandler())
    actor.register_handler(TakeChemHandler())
    actor.register_handler(PurifyWaterHandler())
    actor.register_handler(DrinkContaminatedWaterHandler())
    install_nukesim(actor)


def _cmd(scenario, command_type, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def _handler_cmd(scenario, command_type, *, character_id=None, **payload):
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


async def test_radiation_source_accumulates_dose_sickness_and_pressure():
    scenario = build_scenario()
    _install(scenario.actor)
    source = _room_entity(
        scenario,
        "isotope case",
        "radiation-source",
        [
            RadiationSourceComponent(
                source_type="isotope case",
                rads_per_hour=4.0,
                sickness_per_rad=0.5,
            )
        ],
    )
    exposed: list[RadiationExposureEvent] = []
    scenario.actor.bus.subscribe(RadiationExposureEvent, exposed.append)

    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert exposed[0].source_id == str(source)
    assert character.get_component(RadiationDoseComponent).amount == 4.0
    assert character.get_component(RadiationSicknessComponent).severity == 2.0
    assert character.get_component(RadiationMutationPressureComponent).amount == 4.0


async def test_rad_protection_reduces_exposure_rate():
    scenario = build_scenario()
    _install(scenario.actor)
    _room_entity(
        scenario,
        "hot cell",
        "radiation-source",
        [RadiationSourceComponent(rads_per_hour=4.0)],
    )
    scenario.actor.world.get_entity(scenario.character).add_component(
        RadProtectionComponent(rating=0.5)
    )

    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(RadiationDoseComponent).amount == 2.0


async def test_seal_radiation_source_stops_future_exposure_and_rejects_resealing():
    scenario = build_scenario()
    _install(scenario.actor)
    source = _room_entity(
        scenario,
        "isotope case",
        "radiation-source",
        [RadiationSourceComponent(source_type="isotope case", rads_per_hour=4.0)],
    )
    sealed: list[RadiationSourceSealedEvent] = []
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(RadiationSourceSealedEvent, sealed.append)
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "seal-radiation-source", target_id=str(source))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "seal-radiation-source", target_id=str(source))
    )
    await scenario.actor.tick(HOUR)

    source_state = scenario.actor.world.get_entity(source).get_component(RadiationSourceComponent)
    character = scenario.actor.world.get_entity(scenario.character)
    assert source_state.sealed is True
    assert character.get_component(RadiationDoseComponent).amount == 4.0
    assert sealed[0].source_type == "isotope case"
    assert any("already sealed" in event.reason for event in rejects)


async def test_scan_decontaminate_and_rad_medicine_reduce_radiation_state():
    scenario = build_scenario()
    _install(scenario.actor)
    source = _room_entity(
        scenario,
        "isotope case",
        "radiation-source",
        [RadiationSourceComponent(rads_per_hour=2.0, sealed=True)],
    )
    station = _room_entity(
        scenario,
        "decon arch",
        "decontamination",
        [
            DecontaminationComponent(
                dose_reduction=2.0,
                sickness_reduction=1.0,
                mutation_pressure_reduction=2.0,
            )
        ],
    )
    meds = _inventory_entity(
        scenario,
        "rad-away",
        "medicine",
        [RadMedicineComponent(dose_reduction=1.0, mutation_pressure_reduction=1.0)],
    )
    scanned: list[RadiationScannedEvent] = []
    decon: list[DecontaminationAppliedEvent] = []
    scenario.actor.bus.subscribe(RadiationScannedEvent, scanned.append)
    scenario.actor.bus.subscribe(DecontaminationAppliedEvent, decon.append)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(RadiationDoseComponent(amount=4.0))
    character.add_component(RadiationSicknessComponent(severity=3.0))
    character.add_component(RadiationMutationPressureComponent(amount=4.0))

    await scenario.actor.submit(_cmd(scenario, "scan-radiation", target_id=str(source)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "decontaminate",
            station_id=str(station),
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "use-rad-medicine", item_id=str(meds)))
    await scenario.actor.tick(HOUR)

    assert scanned[0].source_type == "fallout hotspot"
    assert decon[0].dose >= 0.0
    assert character.get_component(RadiationDoseComponent).amount == 1.0
    assert character.get_component(RadiationMutationPressureComponent).amount == 1.0


async def test_mutation_manifests_when_pressure_crosses_threshold_and_can_stabilize():
    scenario = build_scenario()
    _install(scenario.actor)
    _room_entity(
        scenario,
        "glowing barrel",
        "radiation-source",
        [RadiationSourceComponent(rads_per_hour=12.0)],
    )
    manifested: list[MutationManifestedEvent] = []
    scenario.actor.bus.subscribe(MutationManifestedEvent, manifested.append)

    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "stabilize-mutation", mutation_id="rad-adapted"))
    await scenario.actor.tick(HOUR)

    mutation = scenario.actor.world.get_entity(scenario.character).get_component(
        MutationComponent
    )
    assert manifested[0].label == "Rad-Adapted"
    assert mutation.stable is True


async def test_scavenge_adds_resource_stacks_and_applies_hazard():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(
        scenario,
        "pharmacy cache",
        "scavenge-site",
        [
            ScavengeSiteComponent(site_type="pharmacy", charges=1, hazard_rads=2.0),
            LootTableComponent(outputs={"scrap": 2, "cloth": 1}),
        ],
    )
    found: list[LootFoundEvent] = []
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(LootFoundEvent, found.append)
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "scavenge", site_id=str(site)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "scavenge", site_id=str(site)))
    await scenario.actor.tick(HOUR)

    assert {event.resource_type for event in found} == {"scrap", "cloth"}
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(RadiationDoseComponent).amount >= 2.0
    assert any("depleted" in event.reason for event in rejects)


async def test_scrap_item_converts_junk_to_resource_stacks():
    scenario = build_scenario()
    _install(scenario.actor)
    junk = _inventory_entity(
        scenario,
        "bent pressure cooker",
        "junk",
        [JunkComponent(outputs={"scrap": 2}, contaminated_rads=1.0)],
    )
    scrapped: list[ItemScrappedEvent] = []
    scenario.actor.bus.subscribe(ItemScrappedEvent, scrapped.append)

    await scenario.actor.submit(_cmd(scenario, "scrap-item", item_id=str(junk)))
    await scenario.actor.tick(HOUR)

    output = scenario.actor.world.get_entity(parse_entity_id(scrapped[0].output_ids[0]))
    assert output.get_component(ResourceStackComponent).resource_type == "scrap"
    assert output.get_component(ResourceStackComponent).quantity == 2


def test_nukesim_prompt_fragments_surface_local_wasteland_state():
    scenario = build_scenario()
    source = _room_entity(
        scenario,
        "isotope case",
        "radiation-source",
        [RadiationSourceComponent(rads_per_hour=4.0)],
    )
    del source
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(RadiationDoseComponent(amount=3.0))

    fragments = nukesim_fragments(scenario.actor.world, character)

    assert any("Radiation dose" in line for line in fragments)
    assert any("Radiation source" in line for line in fragments)


def test_nukesim_fragments_cover_radiation_status_and_reachable_supplies():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(RadiationDoseComponent(amount=0.0))
    character.add_component(RadiationSicknessComponent(severity=0.0))
    character.add_component(RadiationMutationPressureComponent(amount=0.0))
    character.add_component(MutationComponent(mutation_id="glow", label="Glow", stable=False))

    fragments = nukesim_fragments(scenario.actor.world, character)

    assert not any(line.startswith("Radiation dose:") for line in fragments)
    assert not any(line.startswith("Radiation sickness") for line in fragments)
    assert not any(line.startswith("Radiation mutation pressure") for line in fragments)
    assert "Mutation: Glow (unstable)." in fragments

    replace_component(character, RadiationDoseComponent(amount=2.5))
    replace_component(character, RadiationSicknessComponent(severity=1.5))
    replace_component(character, RadiationMutationPressureComponent(amount=3.0))
    replace_component(
        character,
        MutationComponent(mutation_id="glow", label="Glow", stable=True),
    )
    source = _room_entity(
        scenario,
        "sealed isotope",
        "radiation-source",
        [RadiationSourceComponent(source_type="isotope case", sealed=True)],
    )
    unnamed_site = spawn_entity(
        scenario.actor.world,
        [ScavengeSiteComponent(site_type="collapsed shelter", depleted=True)],
    )
    decon = _room_entity(
        scenario,
        "wash station",
        "decontamination",
        [DecontaminationComponent()],
    )
    medicine = _room_entity(
        scenario,
        "rad pills",
        "medicine",
        [RadMedicineComponent()],
    )
    junk = _room_entity(
        scenario,
        "bent panel",
        "junk",
        [JunkComponent(outputs={"scrap": 1})],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), unnamed_site.id)

    fragments = nukesim_fragments(scenario.actor.world, character)

    assert "Radiation dose: 2.5 rads." in fragments
    assert "Radiation sickness severity: 1.5." in fragments
    assert "Radiation mutation pressure: 3." in fragments
    assert "Mutation: Glow (stable)." in fragments
    assert "Radiation source sealed isotope: isotope case, sealed." in fragments
    assert f"Scavenge site {unnamed_site.id}: collapsed shelter, depleted." in fragments
    assert "Decontamination available: wash station." in fragments
    assert "Rad medicine available: rad pills." in fragments
    assert "Scrappable junk: bent panel." in fragments
    assert scenario.actor.world.has_entity(source)
    assert scenario.actor.world.has_entity(decon)
    assert scenario.actor.world.has_entity(medicine)
    assert scenario.actor.world.has_entity(junk)


def test_nukesim_handlers_reject_invalid_character_ids_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    cases = [
        (ScanRadiationHandler(), "scan-radiation", {"target_id": str(scenario.room_a)}),
        (
            SealRadiationSourceHandler(),
            "seal-radiation-source",
            {"target_id": str(scenario.room_a)},
        ),
        (DecontaminateHandler(), "decontaminate", {}),
        (UseRadMedicineHandler(), "use-rad-medicine", {"item_id": str(scenario.room_a)}),
        (ScavengeHandler(), "scavenge", {"site_id": str(scenario.room_a)}),
        (ScrapItemHandler(), "scrap-item", {"item_id": str(scenario.room_a)}),
        (StabilizeMutationHandler(), "stabilize-mutation", {}),
    ]

    for handler, command_type, payload in cases:
        result = handler.execute(
            ctx,
            _handler_cmd(
                scenario,
                command_type,
                character_id="not-an-id",
                **payload,
            ),
        )
        assert result.ok is False
        assert result.reason == "invalid character id"


def test_nukesim_handlers_reject_missing_and_wrong_kind_targets_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    cases = [
        (
            ScanRadiationHandler(),
            _handler_cmd(scenario, "scan-radiation", target_id="entity_999"),
            "target does not exist",
        ),
        (
            ScanRadiationHandler(),
            _handler_cmd(scenario, "scan-radiation", target_id=str(scenario.character)),
            "target is the wrong kind",
        ),
        (
            SealRadiationSourceHandler(),
            _handler_cmd(scenario, "seal-radiation-source", target_id="entity_999"),
            "target does not exist",
        ),
        (
            DecontaminateHandler(),
            _handler_cmd(scenario, "decontaminate", target_id="entity_999"),
            "target does not exist",
        ),
        (
            DecontaminateHandler(),
            _handler_cmd(scenario, "decontaminate", station_id=str(scenario.character)),
            "target is the wrong kind",
        ),
        (
            UseRadMedicineHandler(),
            _handler_cmd(scenario, "use-rad-medicine", item_id="entity_999"),
            "target does not exist",
        ),
        (
            ScavengeHandler(),
            _handler_cmd(scenario, "scavenge", site_id="entity_999"),
            "target does not exist",
        ),
        (
            ScrapItemHandler(),
            _handler_cmd(scenario, "scrap-item", item_id=str(scenario.character)),
            "target is the wrong kind",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


def test_nukesim_handlers_reject_unreachable_targets_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    distant_source = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant isotope", kind="radiation-source"),
            RadiationSourceComponent(),
        ],
    )
    distant_station = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant decon arch", kind="decontamination"),
            DecontaminationComponent(),
        ],
    )
    distant_meds = _inventory_entity(
        scenario,
        "rad-away",
        "medicine",
        [RadMedicineComponent()],
    )
    distant_site = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant cache", kind="scavenge-site"),
            ScavengeSiteComponent(),
            LootTableComponent(outputs={"scrap": 1}),
        ],
    )
    distant_junk = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant junk", kind="junk"),
            JunkComponent(outputs={"scrap": 1}),
        ],
    )
    distant_patient = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Clover", kind="character")],
    )
    room_b = scenario.actor.world.get_entity(scenario.room_b)
    room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_patient.id)
    room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_source.id)
    room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_station.id)
    room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_site.id)
    room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_junk.id)

    cases = [
        (
            ScanRadiationHandler(),
            _handler_cmd(scenario, "scan-radiation", target_id=str(distant_source.id)),
        ),
        (
            SealRadiationSourceHandler(),
            _handler_cmd(
                scenario,
                "seal-radiation-source",
                target_id=str(distant_source.id),
            ),
        ),
        (
            DecontaminateHandler(),
            _handler_cmd(
                scenario,
                "decontaminate",
                target_id=str(distant_patient.id),
                station_id=str(distant_meds),
            ),
        ),
        (
            UseRadMedicineHandler(),
            _handler_cmd(
                scenario,
                "use-rad-medicine",
                item_id=str(distant_meds),
                target_id=str(distant_patient.id),
            ),
        ),
        (
            ScavengeHandler(),
            _handler_cmd(scenario, "scavenge", site_id=str(distant_site.id)),
        ),
        (
            ScrapItemHandler(),
            _handler_cmd(scenario, "scrap-item", item_id=str(distant_junk.id)),
        ),
    ]

    for handler, command in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == "target is not reachable"


def test_nukesim_handlers_reject_spent_empty_and_invalid_states_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    spent_station = _room_entity(
        scenario,
        "spent decon arch",
        "decontamination",
        [DecontaminationComponent(uses=0)],
    )
    spent_meds = _inventory_entity(
        scenario,
        "empty rad-away",
        "medicine",
        [RadMedicineComponent(uses=0)],
    )
    depleted_site = _room_entity(
        scenario,
        "depleted cache",
        "scavenge-site",
        [ScavengeSiteComponent(depleted=True), LootTableComponent(outputs={"scrap": 1})],
    )
    empty_site = _room_entity(
        scenario,
        "empty cache",
        "scavenge-site",
        [ScavengeSiteComponent()],
    )
    character = scenario.actor.world.get_entity(scenario.character)

    cases = [
        (
            DecontaminateHandler(),
            _handler_cmd(scenario, "decontaminate", station_id=str(spent_station)),
            "decontamination station is spent",
        ),
        (
            UseRadMedicineHandler(),
            _handler_cmd(scenario, "use-rad-medicine", item_id=str(spent_meds)),
            "rad medicine is spent",
        ),
        (
            ScavengeHandler(),
            _handler_cmd(scenario, "scavenge", site_id=str(depleted_site)),
            "scavenge site is depleted",
        ),
        (
            ScavengeHandler(),
            _handler_cmd(scenario, "scavenge", site_id=str(empty_site)),
            "scavenge site has no loot",
        ),
        (
            StabilizeMutationHandler(),
            _handler_cmd(scenario, "stabilize-mutation"),
            "no mutation to stabilize",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    character.add_component(
        MutationComponent(mutation_id="rad-adapted", label="Rad-Adapted", stable=False)
    )
    result = StabilizeMutationHandler().execute(
        ctx,
        _handler_cmd(scenario, "stabilize-mutation", mutation_id="wrong"),
    )
    assert result.ok is False
    assert result.reason == "mutation does not match"

    character.remove_component(MutationComponent)
    character.add_component(
        MutationComponent(mutation_id="rad-adapted", label="Rad-Adapted", stable=True)
    )
    result = StabilizeMutationHandler().execute(
        ctx,
        _handler_cmd(scenario, "stabilize-mutation", mutation_id="rad-adapted"),
    )
    assert result.ok is False
    assert result.reason == "mutation is already stable"


def _scrap(scenario, quantity):
    return _inventory_entity(
        scenario,
        f"scrap ({quantity})",
        "resource",
        [ResourceStackComponent(resource_type="scrap", quantity=quantity)],
    )


async def test_identify_then_restore_old_world_tech_consumes_scrap():
    scenario = build_scenario()
    _install(scenario.actor)
    tech = _room_entity(
        scenario,
        "dusty crate",
        "item",
        [OldWorldTechComponent(tech_name="water purifier", restore_scrap=2)],
    )
    scrap = _scrap(scenario, 3)
    identified: list[OldWorldTechIdentifiedEvent] = []
    restored: list[OldWorldTechRestoredEvent] = []
    scenario.actor.bus.subscribe(OldWorldTechIdentifiedEvent, identified.append)
    scenario.actor.bus.subscribe(OldWorldTechRestoredEvent, restored.append)

    await scenario.actor.submit(_cmd(scenario, "identify-tech", tech_id=str(tech)))
    await scenario.actor.tick(HOUR)
    assert identified[0].tech_name == "water purifier"
    assert scenario.actor.world.get_entity(tech).get_component(OldWorldTechComponent).identified

    await scenario.actor.submit(_cmd(scenario, "restore-tech", tech_id=str(tech)))
    await scenario.actor.tick(HOUR)

    tech_state = scenario.actor.world.get_entity(tech).get_component(OldWorldTechComponent)
    assert tech_state.functional is True
    assert restored[0].scrap_spent == 2
    scrap_left = scenario.actor.world.get_entity(scrap).get_component(ResourceStackComponent)
    assert scrap_left.quantity == 1

    character = scenario.actor.world.get_entity(scenario.character)
    fragments = nukesim_fragments(scenario.actor.world, character)
    assert any("water purifier (functional)" in line for line in fragments)


def test_old_world_tech_handlers_reject_invalid_and_cover_edges_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    not_tech = _room_entity(scenario, "rock", "prop", [])
    tech = _room_entity(
        scenario,
        "sealed locker",
        "item",
        [OldWorldTechComponent(tech_name="laser rifle", restore_scrap=2)],
    )

    identify = IdentifyTechHandler()
    restore = RestoreTechHandler()

    # Invalid / wrong-kind / not-yet-identified paths.
    assert identify.execute(
        ctx, _handler_cmd(scenario, "identify-tech", character_id="x", tech_id="y")
    ).reason == "invalid character id"
    assert identify.execute(
        ctx, _handler_cmd(scenario, "identify-tech", tech_id=str(not_tech))
    ).reason == "target is the wrong kind"
    assert restore.execute(
        ctx, _handler_cmd(scenario, "restore-tech", tech_id=str(tech))
    ).reason == "identify the tech first"

    # Identify it; a second identify is rejected.
    assert identify.execute(ctx, _handler_cmd(scenario, "identify-tech", tech_id=str(tech))).ok
    assert identify.execute(
        ctx, _handler_cmd(scenario, "identify-tech", tech_id=str(tech))
    ).reason == "tech is already identified"

    # Restore needs enough scrap.
    assert restore.execute(
        ctx, _handler_cmd(scenario, "restore-tech", tech_id=str(tech))
    ).reason == "not enough scrap to restore"

    # Exactly enough scrap restores it and consumes the whole stack.
    _scrap(scenario, 2)
    assert restore.execute(ctx, _handler_cmd(scenario, "restore-tech", tech_id=str(tech))).ok
    character = scenario.actor.world.get_entity(scenario.character)
    remaining_scrap = [
        item_id
        for _edge, item_id in character.get_relationships(Contains)
        if scenario.actor.world.get_entity(item_id).has_component(ResourceStackComponent)
    ]
    assert remaining_scrap == []
    assert restore.execute(
        ctx, _handler_cmd(scenario, "restore-tech", tech_id=str(tech))
    ).reason == "tech is already functional"


def test_nukesim_fragments_show_unidentified_tech_and_leads():
    scenario = build_scenario()
    _room_entity(
        scenario,
        "scorched case",
        "item",
        [OldWorldTechComponent(tech_name="targeting computer")],
    )
    _room_entity(
        scenario,
        "scrawled note",
        "item",
        [TechLeadComponent(target_tech="fusion core", location_hint="the old reactor")],
    )

    character = scenario.actor.world.get_entity(scenario.character)
    fragments = nukesim_fragments(scenario.actor.world, character)
    assert any("unknown device (unidentified)" in line for line in fragments)
    assert any("Tech lead: fusion core near the old reactor" in line for line in fragments)


async def test_take_chem_relieves_sickness_and_builds_addiction():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.world.get_entity(scenario.character).add_component(
        RadiationSicknessComponent(severity=5.0)
    )
    chem = _inventory_entity(
        scenario,
        "stimpak",
        "chem",
        [ChemComponent(chem_type="stimulant", sickness_relief=2.0, addiction_per_dose=0.3)],
    )
    taken: list[ChemTakenEvent] = []
    scenario.actor.bus.subscribe(ChemTakenEvent, taken.append)

    await scenario.actor.submit(_cmd(scenario, "take-chem", chem_id=str(chem)))
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    assert character.get_component(RadiationSicknessComponent).severity == 3.0
    assert character.get_component(AddictionComponent).levels["stimulant"] == 0.3
    assert container_of(world.get_entity(chem)) is None  # consumed from inventory
    assert taken and taken[0].chem_type == "stimulant"


async def test_addiction_decays_with_withdrawal_over_time():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.world.get_entity(scenario.character).add_component(
        AddictionComponent(levels={"stimulant": 0.5}, last_updated_epoch=0)
    )
    withdrawals: list[WithdrawalProgressedEvent] = []
    scenario.actor.bus.subscribe(WithdrawalProgressedEvent, withdrawals.append)

    await scenario.actor.tick(HOUR)

    level = scenario.actor.world.get_entity(scenario.character).get_component(
        AddictionComponent
    ).levels["stimulant"]
    assert level == 0.4
    assert withdrawals and withdrawals[0].level == 0.4


async def test_addiction_clears_after_enough_withdrawal():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.world.get_entity(scenario.character).add_component(
        AddictionComponent(levels={"stimulant": 0.05}, last_updated_epoch=0)
    )

    await scenario.actor.tick(HOUR)

    assert not scenario.actor.world.get_entity(scenario.character).has_component(
        AddictionComponent
    )


async def test_drinking_contaminated_water_adds_rads_until_purified():
    scenario = build_scenario()
    _install(scenario.actor)
    water = _room_entity(
        scenario, "rad puddle", "water", [WaterPurityComponent(rads_per_drink=4.0)]
    )
    drunk: list[ContaminatedWaterDrunkEvent] = []
    purified: list[WaterPurifiedEvent] = []
    scenario.actor.bus.subscribe(ContaminatedWaterDrunkEvent, drunk.append)
    scenario.actor.bus.subscribe(WaterPurifiedEvent, purified.append)

    await scenario.actor.submit(_cmd(scenario, "drink-water", water_id=str(water)))
    await scenario.actor.tick(HOUR)
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(RadiationDoseComponent).amount == 4.0
    assert drunk and drunk[0].rads == 4.0

    await scenario.actor.submit(_cmd(scenario, "purify-water", water_id=str(water)))
    await scenario.actor.tick(HOUR)
    assert purified
    dose_before = character.get_component(RadiationDoseComponent).amount
    await scenario.actor.submit(_cmd(scenario, "drink-water", water_id=str(water)))
    await scenario.actor.tick(HOUR)
    assert character.get_component(RadiationDoseComponent).amount == dose_before


def test_chem_and_water_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    junk = _room_entity(scenario, "scrap", "junk", [JunkComponent(outputs={"scrap": 1})])
    clean = _room_entity(scenario, "clean spring", "water", [WaterPurityComponent(purified=True)])

    cases = [
        (
            TakeChemHandler(),
            _handler_cmd(scenario, "take-chem", character_id="x"),
            "invalid character",
        ),
        (TakeChemHandler(), _handler_cmd(scenario, "take-chem", chem_id=str(junk)), "wrong kind"),
        (
            PurifyWaterHandler(),
            _handler_cmd(scenario, "purify-water", character_id="x"),
            "invalid character",
        ),
        (
            PurifyWaterHandler(),
            _handler_cmd(scenario, "purify-water", water_id=str(clean)),
            "already purified",
        ),
        (
            DrinkContaminatedWaterHandler(),
            _handler_cmd(scenario, "drink-water", character_id="x"),
            "invalid character",
        ),
        (
            DrinkContaminatedWaterHandler(),
            _handler_cmd(scenario, "drink-water", water_id=str(junk)),
            "wrong kind",
        ),
    ]
    for handler, command, expected in cases:
        result = handler.execute(ctx, command)
        assert not result.ok, expected
        assert expected in result.reason, (expected, result.reason)


def test_nukesim_fragments_show_chems_water_and_addiction():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.world.get_entity(scenario.character).add_component(
        AddictionComponent(levels={"stimulant": 0.6})
    )
    _room_entity(scenario, "stimpak", "chem", [ChemComponent(chem_type="stimulant")])
    _room_entity(scenario, "rad puddle", "water", [WaterPurityComponent(rads_per_drink=4.0)])

    lines = nukesim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )
    assert any("Addiction to stimulant" in line for line in lines)
    assert any("Chem available: stimulant" in line for line in lines)
    assert any("Water source" in line and "contaminated" in line for line in lines)
