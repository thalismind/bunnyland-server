"""Tests for nuke-sim radiation, mutations, scavenging, and scrapping."""

from __future__ import annotations

from conftest import build_scenario, execute_handler

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
from bunnyland.core.components import CharacterComponent
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.foundation.mutation.mechanics import (
    RadiationMutationPressureComponent,
    RadiationShieldComponent,
)
from bunnyland.prompts import ComponentPromptContext
from bunnyland.prompts.context import PromptPerspective
from bunnyland.simpacks.barbariansim.mechanics import DurabilityComponent
from bunnyland.simpacks.colonysim.mechanics import ResourceStackComponent
from bunnyland.simpacks.nukesim.mechanics import (
    ActivateBeaconHandler,
    AddictionComponent,
    BeaconActivatedEvent,
    BeaconComponent,
    BootTerminalHandler,
    BrewChemHandler,
    BuildPurifierHandler,
    ChemBrewedEvent,
    ChemComponent,
    ChemRecipeComponent,
    ChemTakenEvent,
    ClaimFactionSalvageHandler,
    ClaimSettlementHandler,
    ContaminatedWaterDrunkEvent,
    CrateUnlockedEvent,
    DecontaminateHandler,
    DecontaminationAppliedEvent,
    DecontaminationComponent,
    DrinkContaminatedWaterHandler,
    FactionSalvageClaimedEvent,
    FactionSalvageComponent,
    FieldRepairAppliedEvent,
    FieldRepairComponent,
    FieldRepairHandler,
    GeneratorComponent,
    GeneratorPoweredEvent,
    HarvestSampleHandler,
    HotspotMarkedEvent,
    IdentifyTechHandler,
    IncreaseRaiderPressureHandler,
    InstallModHandler,
    ItemModComponent,
    ItemScrappedEvent,
    JunkComponent,
    LockedCrateComponent,
    LootFoundEvent,
    LootTableComponent,
    MarkHotspotHandler,
    ModInstalledEvent,
    MutationComponent,
    MutationManifestedEvent,
    OldWorldTechComponent,
    OldWorldTechIdentifiedEvent,
    OldWorldTechRestoredEvent,
    OpenTraderRouteHandler,
    PowerGeneratorHandler,
    PurifierBuiltEvent,
    PurifyWaterHandler,
    RadiationDoseComponent,
    RadiationExposureEvent,
    RadiationScannedEvent,
    RadiationSicknessComponent,
    RadiationSourceComponent,
    RadiationSourceSealedEvent,
    RadMedicineComponent,
    RadMedicineUsedEvent,
    RadProtectionComponent,
    RaiderPressureChangedEvent,
    RaiderPressureComponent,
    RestoreTechHandler,
    SalvageSettlementHandler,
    SampleComponent,
    SampleHarvestedEvent,
    SampleStudiedEvent,
    ScanRadiationHandler,
    ScavengeHandler,
    ScavengeSiteComponent,
    SchematicComponent,
    ScrapItemHandler,
    SealRadiationSourceHandler,
    SettlementClaimedEvent,
    SettlementComponent,
    SettlementSalvageComponent,
    SettlementSalvagedEvent,
    StabilizeMutationHandler,
    StudySampleHandler,
    StudyWastelandArtifactHandler,
    SuppressantComponent,
    SuppressantUsedEvent,
    TakeChemHandler,
    TechLeadComponent,
    TerminalBootedEvent,
    TerminalComponent,
    TraderRouteComponent,
    TraderRouteOpenedEvent,
    UnlockCrateHandler,
    UseRadMedicineHandler,
    UseSuppressantHandler,
    WastelandArtifactComponent,
    WastelandArtifactStudiedEvent,
    WaterPurifiedEvent,
    WaterPurifierComponent,
    WaterPurityComponent,
    WithdrawalProgressedEvent,
    install_nukesim,
    nukesim_fragments,
)

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
    actor.register_handler(ClaimSettlementHandler())
    actor.register_handler(SalvageSettlementHandler())
    actor.register_handler(BuildPurifierHandler())
    actor.register_handler(PowerGeneratorHandler())
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


def test_nukesim_reachable_component_rejects_missing_character():
    scenario = build_scenario()
    result = execute_handler(
        ScanRadiationHandler(),
        HandlerContext(scenario.actor.world, scenario.actor.epoch),
        _handler_cmd(
            scenario,
            "scan-radiation",
            character_id="entity_999999",
            target_id=str(scenario.room_a),
        ),
    )

    assert not result.ok
    assert result.reason == "character does not exist"


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


def test_nukesim_parity_handlers_mutate_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)

    def entity(entity_id):
        return scenario.actor.world.get_entity(entity_id)

    source_id = _room_entity(
        scenario,
        "cracked isotope case",
        "radiation-source",
        [RadiationSourceComponent(source_type="isotope", rads_per_hour=3)],
    )
    suppressant_id = _inventory_entity(
        scenario,
        "rad foam",
        "suppressant",
        [SuppressantComponent(pressure_reduction=2, uses=2)],
    )
    sample_id = _inventory_entity(
        scenario,
        "glowing moss sample",
        "sample",
        [SampleComponent(sample_type="glowing moss")],
    )
    crate_id = _room_entity(
        scenario,
        "sealed ammo crate",
        "crate",
        [LockedCrateComponent()],
    )
    artifact_id = _room_entity(
        scenario,
        "vault relic",
        "artifact",
        [WastelandArtifactComponent(artifact_type="vault")],
    )
    salvage_id = _room_entity(
        scenario,
        "faction cache",
        "salvage",
        [FactionSalvageComponent(faction_id="minutemen")],
    )
    item_id = _room_entity(
        scenario,
        "pipe rifle",
        "weapon",
        [DurabilityComponent(current=1, maximum=5)],
    )
    schematic_id = _room_entity(
        scenario,
        "scope schematic",
        "schematic",
        [SchematicComponent(mod_name="scope")],
    )
    kit_id = _room_entity(
        scenario,
        "sewing kit",
        "repair-kit",
        [FieldRepairComponent(repair_amount=2)],
    )
    recipe_id = _room_entity(
        scenario,
        "rad tonic recipe",
        "recipe",
        [ChemRecipeComponent(chem_type="rad tonic")],
    )
    beacon_id = _room_entity(
        scenario,
        "settlement beacon",
        "beacon",
        [BeaconComponent(message="safe")],
    )
    route_id = _room_entity(
        scenario,
        "south road caravan",
        "route",
        [TraderRouteComponent(destination="south road")],
    )
    terminal_id = _room_entity(
        scenario,
        "vault terminal",
        "terminal",
        [TerminalComponent()],
    )

    calls = [
        (
            MarkHotspotHandler(),
            "mark-hotspot",
            {"source_id": str(source_id), "label": "hot"},
            HotspotMarkedEvent,
        ),
        (
            UseSuppressantHandler(),
            "use-suppressant",
            {"item_id": str(suppressant_id)},
            SuppressantUsedEvent,
        ),
        (
            HarvestSampleHandler(),
            "harvest",
            {"sample_type": "glowing moss"},
            SampleHarvestedEvent,
        ),
        (
            StudySampleHandler(),
            "study-sample",
            {"sample_id": str(sample_id)},
            SampleStudiedEvent,
        ),
        (UnlockCrateHandler(), "unlock", {"crate_id": str(crate_id)}, CrateUnlockedEvent),
        (
            StudyWastelandArtifactHandler(),
            "study-wasteland-artifact",
            {"artifact_id": str(artifact_id)},
            WastelandArtifactStudiedEvent,
        ),
        (
            ClaimFactionSalvageHandler(),
            "claim-faction-salvage",
            {"salvage_id": str(salvage_id)},
            FactionSalvageClaimedEvent,
        ),
        (
            InstallModHandler(),
            "install-mod",
            {"item_id": str(item_id), "schematic_id": str(schematic_id)},
            ModInstalledEvent,
        ),
        (
            FieldRepairHandler(),
            "field-repair",
            {"item_id": str(item_id), "kit_id": str(kit_id)},
            FieldRepairAppliedEvent,
        ),
        (BrewChemHandler(), "brew-chem", {"recipe_id": str(recipe_id)}, ChemBrewedEvent),
        (
            ActivateBeaconHandler(),
            "activate-beacon",
            {"beacon_id": str(beacon_id)},
            BeaconActivatedEvent,
        ),
        (
            OpenTraderRouteHandler(),
            "open-trader-route",
            {"route_id": str(route_id)},
            TraderRouteOpenedEvent,
        ),
        (
            IncreaseRaiderPressureHandler(),
            "increase-raider-pressure",
            {"target_id": str(source_id), "amount": 2},
            RaiderPressureChangedEvent,
        ),
        (
            BootTerminalHandler(),
            "boot-terminal",
            {"terminal_id": str(terminal_id), "access_level": 2},
            TerminalBootedEvent,
        ),
    ]

    for handler, command_type, payload, event_type in calls:
        result = execute_handler(handler, ctx, _handler_cmd(scenario, command_type, **payload))
        assert result.ok, (command_type, result.reason)
        assert any(isinstance(event, event_type) for event in result.events)

    assert entity(suppressant_id).get_component(SuppressantComponent).uses == 1
    assert str(scenario.character) in entity(sample_id).get_component(SampleComponent).studied_by
    assert entity(crate_id).get_component(LockedCrateComponent).locked is False
    assert entity(artifact_id).get_component(WastelandArtifactComponent).studied is True
    assert entity(salvage_id).get_component(FactionSalvageComponent).claimed_by == str(
        scenario.character
    )
    assert entity(item_id).get_component(ItemModComponent).mod_name == "scope"
    assert entity(item_id).get_component(DurabilityComponent).current == 3
    assert entity(beacon_id).get_component(BeaconComponent).active is True
    assert entity(route_id).get_component(TraderRouteComponent).open is True
    assert entity(source_id).get_component(RaiderPressureComponent).pressure == 2
    assert entity(terminal_id).get_component(TerminalComponent).access_level == 2
    fragments = nukesim_fragments(scenario.actor.world, entity(scenario.character))
    assert "Radiation suppressant available: rad foam." in fragments
    assert "Sample glowing moss sample: glowing moss (studied)." in fragments
    assert "Locked crate sealed ammo crate: open." in fragments
    assert "Wasteland artifact vault relic: vault (studied)." in fragments
    assert "Faction salvage faction cache: minutemen, claimed." in fragments
    assert "Schematic scope schematic: scope." in fragments
    assert "Item mod pipe rifle: scope." in fragments
    assert "Beacon settlement beacon: active." in fragments
    assert "Trader route south road caravan: south road (open)." in fragments
    assert "Terminal vault terminal: booted, access 2." in fragments


def test_nukesim_parity_handlers_reject_invalid_targets_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    fake = "entity_999999"
    cases = [
        (
            MarkHotspotHandler(),
            "mark-hotspot",
            {"source_id": fake},
            "invalid character id",
            "target does not exist",
        ),
        (
            UseSuppressantHandler(),
            "use-suppressant",
            {"item_id": fake},
            "invalid character id",
            "target does not exist",
        ),
        (
            StudySampleHandler(),
            "study-sample",
            {"sample_id": fake},
            "invalid character id",
            "target does not exist",
        ),
        (
            UnlockCrateHandler(),
            "unlock",
            {"crate_id": fake},
            "invalid character id",
            "target does not exist",
        ),
        (
            StudyWastelandArtifactHandler(),
            "study-wasteland-artifact",
            {"artifact_id": fake},
            "invalid character id",
            "target does not exist",
        ),
        (
            ClaimFactionSalvageHandler(),
            "claim-faction-salvage",
            {"salvage_id": fake},
            "invalid character id",
            "target does not exist",
        ),
        (
            InstallModHandler(),
            "install-mod",
            {"item_id": fake, "schematic_id": fake},
            "invalid character or item id",
            "invalid character or item id",
        ),
        (
            FieldRepairHandler(),
            "field-repair",
            {"item_id": fake, "kit_id": fake},
            "invalid character or item id",
            "invalid character or item id",
        ),
        (
            BrewChemHandler(),
            "brew-chem",
            {"recipe_id": fake},
            "invalid character id",
            "target does not exist",
        ),
        (
            ActivateBeaconHandler(),
            "activate-beacon",
            {"beacon_id": fake},
            "invalid character id",
            "target does not exist",
        ),
        (
            OpenTraderRouteHandler(),
            "open-trader-route",
            {"route_id": fake},
            "invalid character id",
            "target does not exist",
        ),
        (
            IncreaseRaiderPressureHandler(),
            "increase-raider-pressure",
            {"target_id": fake},
            "invalid character or target id",
            "invalid character or target id",
        ),
        (
            BootTerminalHandler(),
            "boot-terminal",
            {"terminal_id": fake},
            "invalid character id",
            "target does not exist",
        ),
    ]

    for handler, command_type, payload, invalid_reason, missing_reason in cases:
        bad_character = execute_handler(
            handler,
            ctx,
            _handler_cmd(scenario, command_type, character_id="not-an-id", **payload),
        )
        assert bad_character.ok is False
        assert bad_character.reason == invalid_reason
        missing_target = execute_handler(
            handler, ctx, _handler_cmd(scenario, command_type, **payload)
        )
        assert missing_target.ok is False
        assert missing_target.reason == missing_reason

    result = execute_handler(
        HarvestSampleHandler(),
        ctx,
        _handler_cmd(scenario, "harvest", character_id="not-an-id"),
    )
    assert result.ok is False
    assert result.reason == "invalid character id"


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
    await scenario.actor.submit(_cmd(scenario, "seal-radiation-source", target_id=str(source)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "seal-radiation-source", target_id=str(source)))
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
    used: list[RadMedicineUsedEvent] = []
    scenario.actor.bus.subscribe(RadiationScannedEvent, scanned.append)
    scenario.actor.bus.subscribe(DecontaminationAppliedEvent, decon.append)
    scenario.actor.bus.subscribe(RadMedicineUsedEvent, used.append)
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
    await scenario.actor.submit(_cmd(scenario, "use", item_id=str(meds)))
    await scenario.actor.tick(HOUR)

    assert scanned[0].source_type == "fallout hotspot"
    assert decon[0].dose >= 0.0
    assert character.get_component(RadiationDoseComponent).amount == 1.0
    assert character.get_component(RadiationMutationPressureComponent).amount == 1.0
    assert used and used[0].item_id == str(meds)
    assert used[0].target_id == str(scenario.character)


async def test_use_rad_medicine_item_id_targets_reachable_patient():
    scenario = build_scenario()
    _install(scenario.actor)
    patient = _room_entity(
        scenario,
        "Clover",
        "character",
        [RadiationDoseComponent(amount=5.0), RadiationSicknessComponent(severity=2.0)],
    )
    meds = _inventory_entity(
        scenario,
        "rad-away",
        "medicine",
        [RadMedicineComponent(dose_reduction=3.0, sickness_reduction=1.0)],
    )
    used: list[RadMedicineUsedEvent] = []
    scenario.actor.bus.subscribe(RadMedicineUsedEvent, used.append)

    await scenario.actor.submit(_cmd(scenario, "use", item_id=str(meds), target_id=str(patient)))
    await scenario.actor.tick(HOUR)

    patient_entity = scenario.actor.world.get_entity(patient)
    assert patient_entity.get_component(RadiationDoseComponent).amount == 2.0
    assert patient_entity.get_component(RadiationSicknessComponent).severity == 1.0
    assert used and used[0].item_id == str(meds)
    assert used[0].target_id == str(patient)


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

    mutation = scenario.actor.world.get_entity(scenario.character).get_component(MutationComponent)
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


def test_nukesim_component_prompt_fragments_cover_self_target_and_named_state():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    sample = spawn_entity(
        world,
        [
            IdentityComponent(name="glowing sample", kind="sample"),
            SampleComponent(sample_type="fungus", studied_by=(str(character.id),)),
        ],
    )
    tech = spawn_entity(
        world,
        [
            IdentityComponent(name="scorched device", kind="item"),
            OldWorldTechComponent(tech_name="targeting computer", identified=True),
        ],
    )
    self_ctx = ComponentPromptContext.for_entity(world, character)
    sample_ctx = ComponentPromptContext.for_entity(world, sample, target=character)
    tech_ctx = ComponentPromptContext.for_entity(world, tech)

    assert RadiationDoseComponent(amount=3.0).prompt_fragments(self_ctx) == (
        "Radiation dose: 3 rads.",
    )
    assert sample.get_component(SampleComponent).prompt_fragments(sample_ctx) == (
        "Sample glowing sample: fungus (studied).",
    )
    assert tech.get_component(OldWorldTechComponent).prompt_fragments(tech_ctx) == (
        "Old-world tech scorched device: targeting computer "
        "(identified, needs 3 scrap to restore).",
    )


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
        (UseRadMedicineHandler(), "use", {"item_id": str(scenario.room_a)}),
        (ScavengeHandler(), "scavenge", {"site_id": str(scenario.room_a)}),
        (ScrapItemHandler(), "scrap-item", {"item_id": str(scenario.room_a)}),
        (StabilizeMutationHandler(), "stabilize-mutation", {}),
    ]

    for handler, command_type, payload in cases:
        result = execute_handler(
            handler,
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

    missing = execute_handler(
        StabilizeMutationHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "stabilize-mutation",
            character_id="entity_999999",
        ),
    )
    assert missing.ok is False
    assert missing.reason == "character does not exist"


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
            _handler_cmd(scenario, "use", item_id="entity_999"),
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
        result = execute_handler(handler, ctx, command)
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
                station_id=str(distant_station.id),
            ),
        ),
        (
            UseRadMedicineHandler(),
            _handler_cmd(
                scenario,
                "use",
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
        result = execute_handler(handler, ctx, command)
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
            _handler_cmd(scenario, "use", item_id=str(spent_meds)),
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
        result = execute_handler(handler, ctx, command)
        assert result.ok is False
        assert result.reason == reason

    character.add_component(
        MutationComponent(mutation_id="rad-adapted", label="Rad-Adapted", stable=False)
    )
    result = execute_handler(
        StabilizeMutationHandler(),
        ctx,
        _handler_cmd(scenario, "stabilize-mutation", mutation_id="wrong"),
    )
    assert result.ok is False
    assert result.reason == "mutation does not match"

    character.remove_component(MutationComponent)
    character.add_component(
        MutationComponent(mutation_id="rad-adapted", label="Rad-Adapted", stable=True)
    )
    result = execute_handler(
        StabilizeMutationHandler(),
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


def _fuel(scenario, quantity):
    return _inventory_entity(
        scenario,
        f"fuel ({quantity})",
        "resource",
        [ResourceStackComponent(resource_type="fuel", quantity=quantity)],
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

    await scenario.actor.submit(_cmd(scenario, "identify", tech_id=str(tech)))
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


async def test_claim_settlement_build_purifier_and_power_generator():
    scenario = build_scenario()
    _install(scenario.actor)
    settlement = _room_entity(
        scenario,
        "Red Rocket burrow",
        "settlement",
        [
            SettlementComponent(name="Red Rocket burrow"),
            WaterPurifierComponent(output_per_day=3, scrap_cost=2),
        ],
    )
    generator = _room_entity(
        scenario,
        "patched generator",
        "generator",
        [GeneratorComponent(power_output=6, fuel_cost=1)],
    )
    scrap = _scrap(scenario, 3)
    fuel = _fuel(scenario, 1)
    claimed: list[SettlementClaimedEvent] = []
    built: list[PurifierBuiltEvent] = []
    powered: list[GeneratorPoweredEvent] = []
    scenario.actor.bus.subscribe(SettlementClaimedEvent, claimed.append)
    scenario.actor.bus.subscribe(PurifierBuiltEvent, built.append)
    scenario.actor.bus.subscribe(GeneratorPoweredEvent, powered.append)

    await scenario.actor.submit(_cmd(scenario, "claim", target_id=str(settlement)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "build", target_id=str(settlement)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "power-generator", generator_id=str(generator)))
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    settlement_state = world.get_entity(settlement).get_component(SettlementComponent)
    purifier = world.get_entity(settlement).get_component(WaterPurifierComponent)
    generator_state = world.get_entity(generator).get_component(GeneratorComponent)
    scrap_left = world.get_entity(scrap).get_component(ResourceStackComponent)
    assert settlement_state.claimed_by == str(scenario.character)
    assert purifier.built is True
    assert generator_state.powered is True
    assert scrap_left.quantity == 1
    assert not world.has_entity(fuel) or container_of(world.get_entity(fuel)) is None
    assert claimed and claimed[0].name == "Red Rocket burrow"
    assert built and built[0].scrap_spent == 2
    assert powered and powered[0].fuel_spent == 1


async def test_salvage_settlement_outputs_resources_and_spends_durability():
    scenario = build_scenario()
    _install(scenario.actor)
    settlement = _room_entity(
        scenario,
        "Red Rocket burrow",
        "settlement",
        [
            SettlementComponent(name="Red Rocket burrow"),
            SettlementSalvageComponent(
                outputs={"scrap": 3, "fuel": 1},
                durability_cost=2.0,
            ),
            DurabilityComponent(current=5.0, maximum=5.0),
        ],
    )
    salvaged: list[SettlementSalvagedEvent] = []
    scenario.actor.bus.subscribe(SettlementSalvagedEvent, salvaged.append)

    await scenario.actor.submit(_cmd(scenario, "claim", target_id=str(settlement)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "salvage-settlement", settlement_id=str(settlement)))
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    settlement_entity = world.get_entity(settlement)
    salvage = settlement_entity.get_component(SettlementSalvageComponent)
    durability = settlement_entity.get_component(DurabilityComponent)
    character = world.get_entity(scenario.character)
    stacks = [
        world.get_entity(item_id).get_component(ResourceStackComponent)
        for _edge, item_id in character.get_relationships(Contains)
        if world.get_entity(item_id).has_component(ResourceStackComponent)
    ]
    assert salvage.depleted is True
    assert durability.current == 3.0
    assert salvaged[0].durability == 3.0
    assert {(stack.resource_type, stack.quantity) for stack in stacks} == {
        ("scrap", 3),
        ("fuel", 1),
    }


async def test_salvage_settlement_without_durability_skips_empty_outputs():
    scenario = build_scenario()
    _install(scenario.actor)
    settlement = _room_entity(
        scenario,
        "Picked Red Rocket",
        "settlement",
        [
            SettlementComponent(name="Picked Red Rocket"),
            SettlementSalvageComponent(outputs={"scrap": 2, "fuel": 0}),
        ],
    )
    salvaged: list[SettlementSalvagedEvent] = []
    scenario.actor.bus.subscribe(SettlementSalvagedEvent, salvaged.append)

    await scenario.actor.submit(_cmd(scenario, "claim", target_id=str(settlement)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "salvage-settlement", settlement_id=str(settlement)))
    await scenario.actor.tick(HOUR)

    output_ids = [parse_entity_id(raw) for raw in salvaged[0].output_ids]
    assert salvaged[0].durability is None
    assert len(output_ids) == 1
    assert output_ids[0] is not None
    stack = scenario.actor.world.get_entity(output_ids[0]).get_component(ResourceStackComponent)
    assert (stack.resource_type, stack.quantity) == ("scrap", 2)


def test_settlement_utility_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    settlement = _room_entity(
        scenario,
        "unclaimed outpost",
        "settlement",
        [SettlementComponent(name="unclaimed outpost"), WaterPurifierComponent(scrap_cost=2)],
    )
    claimed = _room_entity(
        scenario,
        "claimed outpost",
        "settlement",
        [
            SettlementComponent(name="claimed outpost", claimed_by=str(scenario.character)),
            WaterPurifierComponent(scrap_cost=2),
        ],
    )
    unclaimed_build = _room_entity(
        scenario,
        "unclaimed purifier site",
        "settlement",
        [SettlementComponent(name="unclaimed purifier site"), WaterPurifierComponent()],
    )
    built = _room_entity(
        scenario,
        "wet outpost",
        "settlement",
        [
            SettlementComponent(name="wet outpost", claimed_by=str(scenario.character)),
            WaterPurifierComponent(built=True),
        ],
    )
    bare_claimed = _room_entity(
        scenario,
        "bare outpost",
        "settlement",
        [SettlementComponent(name="bare outpost", claimed_by=str(scenario.character))],
    )
    unclaimed_salvage = _room_entity(
        scenario,
        "unclaimed salvage",
        "settlement",
        [
            SettlementComponent(name="unclaimed salvage"),
            SettlementSalvageComponent(outputs={"scrap": 1}),
        ],
    )
    depleted_salvage = _room_entity(
        scenario,
        "picked outpost",
        "settlement",
        [
            SettlementComponent(name="picked outpost", claimed_by=str(scenario.character)),
            SettlementSalvageComponent(outputs={"scrap": 1}, depleted=True),
        ],
    )
    broken_salvage = _room_entity(
        scenario,
        "broken outpost",
        "settlement",
        [
            SettlementComponent(name="broken outpost", claimed_by=str(scenario.character)),
            SettlementSalvageComponent(outputs={"scrap": 1}),
            DurabilityComponent(current=0.0, maximum=5.0, broken=True),
        ],
    )
    generator = _room_entity(
        scenario,
        "dry generator",
        "generator",
        [GeneratorComponent(fuel_cost=1)],
    )
    powered = _room_entity(
        scenario,
        "lit generator",
        "generator",
        [GeneratorComponent(powered=True)],
    )
    rock = _room_entity(scenario, "rock", "prop", [])

    claim = ClaimSettlementHandler()
    salvage = SalvageSettlementHandler()
    build = BuildPurifierHandler()
    power = PowerGeneratorHandler()
    assert (
        execute_handler(claim, ctx, _handler_cmd(scenario, "claim", character_id="x")).reason
        == "invalid character id"
    )
    assert (
        execute_handler(claim, ctx, _handler_cmd(scenario, "claim", target_id=str(rock))).reason
        == "target is the wrong kind"
    )
    assert (
        execute_handler(claim, ctx, _handler_cmd(scenario, "claim", target_id=str(claimed))).reason
        == "settlement is already claimed"
    )
    assert execute_handler(
        claim, ctx, _handler_cmd(scenario, "claim", target_id=str(settlement))
    ).ok

    assert (
        execute_handler(
            salvage, ctx, _handler_cmd(scenario, "salvage-settlement", character_id="x")
        ).reason
        == "invalid character id"
    )
    assert (
        execute_handler(
            salvage, ctx, _handler_cmd(scenario, "salvage-settlement", settlement_id=str(rock))
        ).reason
        == "target is the wrong kind"
    )
    assert (
        execute_handler(
            salvage,
            ctx,
            _handler_cmd(
                scenario,
                "salvage-settlement",
                settlement_id=str(unclaimed_salvage),
            ),
        ).reason
        == "claim the settlement first"
    )
    assert (
        execute_handler(
            salvage,
            ctx,
            _handler_cmd(scenario, "salvage-settlement", settlement_id=str(bare_claimed)),
        ).reason
        == "settlement has no salvage"
    )
    assert (
        execute_handler(
            salvage,
            ctx,
            _handler_cmd(scenario, "salvage-settlement", settlement_id=str(depleted_salvage)),
        ).reason
        == "settlement salvage is depleted"
    )
    assert (
        execute_handler(
            salvage,
            ctx,
            _handler_cmd(scenario, "salvage-settlement", settlement_id=str(broken_salvage)),
        ).reason
        == "settlement is too damaged to salvage"
    )

    assert (
        execute_handler(build, ctx, _handler_cmd(scenario, "build", character_id="x")).reason
        == "invalid character id"
    )
    assert (
        execute_handler(build, ctx, _handler_cmd(scenario, "build", target_id=str(rock))).reason
        == "target is the wrong kind"
    )
    assert (
        execute_handler(
            build, ctx, _handler_cmd(scenario, "build", target_id=str(unclaimed_build))
        ).reason
        == "claim the settlement first"
    )
    assert (
        execute_handler(build, ctx, _handler_cmd(scenario, "build", target_id=str(built))).reason
        == "purifier is already built"
    )
    assert (
        execute_handler(build, ctx, _handler_cmd(scenario, "build", target_id=str(claimed))).reason
        == "not enough scrap to build purifier"
    )
    _scrap(scenario, 2)
    assert execute_handler(build, ctx, _handler_cmd(scenario, "build", target_id=str(claimed))).ok
    _scrap(scenario, 2)
    assert execute_handler(
        build, ctx, _handler_cmd(scenario, "build", target_id=str(bare_claimed))
    ).ok
    assert scenario.actor.world.get_entity(bare_claimed).get_component(WaterPurifierComponent).built

    assert (
        execute_handler(
            power, ctx, _handler_cmd(scenario, "power-generator", character_id="x")
        ).reason
        == "invalid character id"
    )
    assert (
        execute_handler(
            power, ctx, _handler_cmd(scenario, "power-generator", generator_id=str(rock))
        ).reason
        == "target is the wrong kind"
    )
    assert (
        execute_handler(
            power, ctx, _handler_cmd(scenario, "power-generator", generator_id=str(powered))
        ).reason
        == "generator is already powered"
    )
    assert (
        execute_handler(
            power, ctx, _handler_cmd(scenario, "power-generator", generator_id=str(generator))
        ).reason
        == "not enough fuel to power generator"
    )
    _fuel(scenario, 1)
    assert execute_handler(
        power, ctx, _handler_cmd(scenario, "power-generator", generator_id=str(generator))
    ).ok


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
    assert (
        execute_handler(
            identify, ctx, _handler_cmd(scenario, "identify", character_id="x", tech_id="y")
        ).reason
        == "invalid character id"
    )
    assert (
        execute_handler(
            identify, ctx, _handler_cmd(scenario, "identify", tech_id=str(not_tech))
        ).reason
        == "target is the wrong kind"
    )
    assert (
        execute_handler(
            restore, ctx, _handler_cmd(scenario, "restore-tech", tech_id=str(tech))
        ).reason
        == "identify the tech first"
    )

    # Identify it; a second identify is rejected.
    assert execute_handler(identify, ctx, _handler_cmd(scenario, "identify", tech_id=str(tech))).ok
    assert (
        execute_handler(identify, ctx, _handler_cmd(scenario, "identify", tech_id=str(tech))).reason
        == "tech is already identified"
    )

    # Restore needs enough scrap.
    assert (
        execute_handler(
            restore, ctx, _handler_cmd(scenario, "restore-tech", tech_id=str(tech))
        ).reason
        == "not enough scrap to restore"
    )

    # Exactly enough scrap restores it and consumes the whole stack.
    _scrap(scenario, 2)
    assert execute_handler(
        restore, ctx, _handler_cmd(scenario, "restore-tech", tech_id=str(tech))
    ).ok
    character = scenario.actor.world.get_entity(scenario.character)
    remaining_scrap = [
        item_id
        for _edge, item_id in character.get_relationships(Contains)
        if scenario.actor.world.get_entity(item_id).has_component(ResourceStackComponent)
    ]
    assert remaining_scrap == []
    assert (
        execute_handler(
            restore, ctx, _handler_cmd(scenario, "restore-tech", tech_id=str(tech))
        ).reason
        == "tech is already functional"
    )


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
    _room_entity(
        scenario,
        "hilltop burrow",
        "settlement",
        [
            SettlementComponent(name="hilltop burrow"),
            SettlementSalvageComponent(outputs={"scrap": 1}),
            WaterPurifierComponent(scrap_cost=4),
            GeneratorComponent(fuel_cost=2),
        ],
    )
    _room_entity(
        scenario,
        "workshop burrow",
        "settlement",
        [
            SettlementComponent(name="workshop burrow", claimed_by=str(scenario.character)),
            SettlementSalvageComponent(outputs={"scrap": 1}, depleted=True),
            WaterPurifierComponent(built=True),
            GeneratorComponent(powered=True),
        ],
    )
    _room_entity(
        scenario,
        "clear spring",
        "water",
        [WaterPurityComponent()],
    )
    _room_entity(
        scenario,
        "filtered cistern",
        "water",
        [WaterPurityComponent(purified=True)],
    )
    _room_entity(
        scenario,
        "old recycler",
        "item",
        [
            OldWorldTechComponent(
                tech_name="recycler",
                identified=True,
                restore_scrap=5,
            )
        ],
    )

    character = scenario.actor.world.get_entity(scenario.character)
    fragments = nukesim_fragments(scenario.actor.world, character)
    assert any("unknown device (unidentified)" in line for line in fragments)
    assert any("recycler (identified, needs 5 scrap to restore)" in line for line in fragments)
    assert any("Tech lead: fusion core near the old reactor" in line for line in fragments)
    assert any("Settlement hilltop burrow: unclaimed" in line for line in fragments)
    assert any("Settlement workshop burrow: claimed" in line for line in fragments)
    assert any("Settlement salvage hilltop burrow: available" in line for line in fragments)
    assert any("Settlement salvage workshop burrow: depleted" in line for line in fragments)
    assert any("Water purifier hilltop burrow: needs 4 scrap" in line for line in fragments)
    assert any("Water purifier workshop burrow: built" in line for line in fragments)
    assert any("Generator hilltop burrow: needs 2 fuel" in line for line in fragments)
    assert any("Generator workshop burrow: powered" in line for line in fragments)
    assert any("Water source clear spring: clean" in line for line in fragments)
    assert any("Water source filtered cistern: purified" in line for line in fragments)


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

    level = (
        scenario.actor.world.get_entity(scenario.character)
        .get_component(AddictionComponent)
        .levels["stimulant"]
    )
    assert level == 0.4
    assert withdrawals and withdrawals[0].level == 0.4


async def test_addiction_clears_after_enough_withdrawal():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.world.get_entity(scenario.character).add_component(
        AddictionComponent(levels={"stimulant": 0.05}, last_updated_epoch=0)
    )

    await scenario.actor.tick(HOUR)

    assert not scenario.actor.world.get_entity(scenario.character).has_component(AddictionComponent)


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

    await scenario.actor.submit(_cmd(scenario, "drink", water_id=str(water)))
    await scenario.actor.tick(HOUR)
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(RadiationDoseComponent).amount == 4.0
    assert drunk and drunk[0].rads == 4.0

    await scenario.actor.submit(_cmd(scenario, "purify-water", water_id=str(water)))
    await scenario.actor.tick(HOUR)
    assert purified
    dose_before = character.get_component(RadiationDoseComponent).amount
    await scenario.actor.submit(_cmd(scenario, "drink", water_id=str(water)))
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
            _handler_cmd(scenario, "drink", character_id="x"),
            "invalid character",
        ),
        (
            DrinkContaminatedWaterHandler(),
            _handler_cmd(scenario, "drink", water_id=str(junk)),
            "wrong kind",
        ),
    ]
    for handler, command, expected in cases:
        result = execute_handler(handler, ctx, command)
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


def _third_person_ctx(world, entity):
    other = spawn_entity(world, [IdentityComponent(name="onlooker", kind="character")])
    return ComponentPromptContext.for_entity(
        world, entity, perspective=PromptPerspective(viewer=other)
    )


def test_mutation_and_addiction_fragments_hide_for_non_first_person():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    mutation = MutationComponent(mutation_id="glow", label="Glow", stable=False)
    addiction = AddictionComponent(levels={"stimulant": 0.6})
    ctx = _third_person_ctx(world, character)

    # Private state is suppressed when the viewer is not the entity itself.
    assert mutation.prompt_fragments(ctx) == ()
    assert addiction.prompt_fragments(ctx) == ()

    # And surfaces when viewing one's own state.
    self_ctx = ComponentPromptContext.for_entity(world, character)
    assert mutation.prompt_fragments(self_ctx) == ("Mutation: Glow (unstable).",)
    assert addiction.prompt_fragments(self_ctx) == ("Addiction to stimulant: 0.6.",)


def test_resource_stack_helpers_merge_and_skip_missing_inventory_entities():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    character = world.get_entity(scenario.character)

    # A non-inventory Contains edge on the character is skipped by the inventory scan.
    worn = spawn_entity(world, [IdentityComponent(name="worn rag", kind="cloth")])
    character.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), worn.id)

    # Scrapping twice merges onto the same stack instead of creating a new one.
    junk_a = _inventory_entity(scenario, "junk a", "junk", [JunkComponent(outputs={"scrap": 2})])
    junk_b = _inventory_entity(scenario, "junk b", "junk", [JunkComponent(outputs={"scrap": 3})])
    ctx = HandlerContext(world, scenario.actor.epoch)
    execute_handler(
        ScrapItemHandler(), ctx, _handler_cmd(scenario, "scrap-item", item_id=str(junk_a))
    )
    execute_handler(
        ScrapItemHandler(), ctx, _handler_cmd(scenario, "scrap-item", item_id=str(junk_b))
    )

    stacks = [
        world.get_entity(item_id).get_component(ResourceStackComponent)
        for _edge, item_id in character.get_relationships(Contains)
        if world.has_entity(item_id)
        and world.get_entity(item_id).has_component(ResourceStackComponent)
    ]
    assert [(s.resource_type, s.quantity) for s in stacks] == [("scrap", 5)]


async def test_radiation_shield_component_reduces_exposure():
    scenario = build_scenario()
    _install(scenario.actor)
    _room_entity(
        scenario,
        "hot cell",
        "radiation-source",
        [RadiationSourceComponent(rads_per_hour=4.0)],
    )
    scenario.actor.world.get_entity(scenario.character).add_component(
        RadiationShieldComponent(strength=50.0)
    )

    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(RadiationDoseComponent).amount == 2.0


async def test_radiation_only_affects_reachable_active_characters():
    scenario = build_scenario()
    _install(scenario.actor)
    source = _room_entity(
        scenario,
        "isotope case",
        "radiation-source",
        [RadiationSourceComponent(rads_per_hour=4.0)],
    )
    # A second character in a different room is not reachable from the source.
    world = scenario.actor.world
    bystander = spawn_entity(
        world,
        [IdentityComponent(name="bystander", kind="character"), CharacterComponent()],
    )
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), bystander.id
    )

    await scenario.actor.tick(HOUR)

    assert not world.get_entity(bystander.id).has_component(RadiationDoseComponent)
    assert world.get_entity(scenario.character).get_component(RadiationDoseComponent).amount == 4.0
    assert world.has_entity(source)


async def test_apply_radiation_no_op_when_source_sealed_keeps_dose_zero():
    scenario = build_scenario()
    _install(scenario.actor)
    _room_entity(
        scenario,
        "dead isotope",
        "radiation-source",
        [RadiationSourceComponent(rads_per_hour=0.0)],
    )

    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(RadiationDoseComponent)


async def test_radiation_without_sickness_per_rad_emits_no_sickness_change():
    scenario = build_scenario()
    _install(scenario.actor)
    _room_entity(
        scenario,
        "mild isotope",
        "radiation-source",
        [RadiationSourceComponent(rads_per_hour=3.0, sickness_per_rad=0.0)],
    )
    from bunnyland.simpacks.nukesim.mechanics import RadiationSicknessChangedEvent

    changes: list[RadiationSicknessChangedEvent] = []
    scenario.actor.bus.subscribe(RadiationSicknessChangedEvent, changes.append)

    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(RadiationDoseComponent).amount == 3.0
    # Sickness severity is unchanged (stays 0), so no sickness-change event fires.
    assert character.get_component(RadiationSicknessComponent).severity == 0.0
    assert changes == []


def test_reduce_radiation_state_skips_absent_sickness_component():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    # Dose present, but no sickness component -> sickness branch is skipped.
    character.add_component(RadiationDoseComponent(amount=5.0))
    station = _room_entity(
        scenario,
        "decon arch",
        "decontamination",
        [DecontaminationComponent(dose_reduction=2.0, sickness_reduction=1.0)],
    )

    result = execute_handler(
        DecontaminateHandler(),
        ctx,
        _handler_cmd(scenario, "decontaminate", station_id=str(station)),
    )

    assert result.ok
    assert character.get_component(RadiationDoseComponent).amount == 3.0
    assert not character.has_component(RadiationSicknessComponent)


def test_decontaminate_resolves_patient_and_item_target_keys():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    patient = _room_entity(
        scenario,
        "Clover",
        "character",
        [RadiationDoseComponent(amount=4.0)],
    )
    station = _room_entity(
        scenario,
        "decon arch",
        "decontamination",
        [DecontaminationComponent(dose_reduction=2.0)],
    )

    # patient_id is used when target_character_id is absent.
    result = execute_handler(
        DecontaminateHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "decontaminate",
            patient_id=str(patient),
            station_id=str(station),
        ),
    )
    assert result.ok
    assert (
        scenario.actor.world.get_entity(patient).get_component(RadiationDoseComponent).amount == 2.0
    )

    # item_id present routes the fallback to target_id.
    result = execute_handler(
        DecontaminateHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "decontaminate",
            item_id="ignored",
            target_id=str(patient),
            station_id=str(station),
        ),
    )
    assert result.ok
    assert (
        scenario.actor.world.get_entity(patient).get_component(RadiationDoseComponent).amount == 0.0
    )


def test_decontaminate_rejects_nonexistent_resolved_target():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    result = execute_handler(
        DecontaminateHandler(),
        ctx,
        _handler_cmd(scenario, "decontaminate", patient_id="entity_999999"),
    )
    assert result.ok is False
    assert result.reason == "target does not exist"


def test_decontaminate_rejects_unreachable_resolved_patient():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    distant = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far medic", kind="character")],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), distant.id
    )
    result = execute_handler(
        DecontaminateHandler(),
        ctx,
        _handler_cmd(scenario, "decontaminate", patient_id=str(distant.id)),
    )
    assert result.ok is False
    assert result.reason == "target is not reachable"


def test_use_rad_medicine_can_handle_and_multi_use_decrement():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    handler = UseRadMedicineHandler()

    # can_handle returns True purely on payload key when item is missing.
    cmd_missing = _handler_cmd(scenario, "use", item_id="entity_999999")
    assert handler.can_handle(ctx, cmd_missing) is True

    # A multi-use kit decrements rather than being consumed.
    meds = _inventory_entity(
        scenario,
        "rad-away pack",
        "medicine",
        [RadMedicineComponent(dose_reduction=1.0, uses=2)],
    )
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(RadiationDoseComponent(amount=3.0))
    result = execute_handler(handler, ctx, _handler_cmd(scenario, "use", item_id=str(meds)))
    assert result.ok
    assert scenario.actor.world.get_entity(meds).get_component(RadMedicineComponent).uses == 1


def test_take_chem_without_relief_and_with_existing_addiction():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(AddictionComponent(levels={"stimulant": 0.2}))
    chem = _inventory_entity(
        scenario,
        "pure stimpak",
        "chem",
        [ChemComponent(chem_type="stimulant", addiction_per_dose=0.3)],
    )

    result = execute_handler(
        TakeChemHandler(), ctx, _handler_cmd(scenario, "take-chem", chem_id=str(chem))
    )

    assert result.ok
    assert character.get_component(AddictionComponent).levels["stimulant"] == 0.5


def test_drink_water_can_handle_falls_through_to_component_check():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    water = _room_entity(
        scenario, "rad puddle", "water", [WaterPurityComponent(rads_per_drink=2.0)]
    )
    handler = DrinkContaminatedWaterHandler()

    # No water_id key -> falls through to source_id/target_id component check.
    assert handler.can_handle(ctx, _handler_cmd(scenario, "drink", source_id=str(water))) is True
    assert handler.can_handle(ctx, _handler_cmd(scenario, "drink", source_id="entity_999")) is False


async def test_scavenge_skips_empty_outputs_and_no_hazard_site():
    scenario = build_scenario()
    _install(scenario.actor)
    site = _room_entity(
        scenario,
        "dry cache",
        "scavenge-site",
        [
            ScavengeSiteComponent(site_type="ruin", charges=1, hazard_rads=0.0),
            LootTableComponent(outputs={"scrap": 2, "cloth": 0}),
        ],
    )
    found: list[LootFoundEvent] = []
    scenario.actor.bus.subscribe(LootFoundEvent, found.append)

    await scenario.actor.submit(_cmd(scenario, "scavenge", site_id=str(site)))
    await scenario.actor.tick(HOUR)

    # cloth (quantity 0) is skipped; only scrap is produced.
    assert {event.resource_type for event in found} == {"scrap"}
    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(RadiationDoseComponent)


async def test_scrap_item_without_contamination_emits_no_radiation():
    scenario = build_scenario()
    _install(scenario.actor)
    junk = _inventory_entity(
        scenario,
        "clean panel",
        "junk",
        [JunkComponent(outputs={"scrap": 1}, contaminated_rads=0.0)],
    )

    await scenario.actor.submit(_cmd(scenario, "scrap-item", item_id=str(junk)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(RadiationDoseComponent)


def test_consumable_and_scrap_handlers_allow_uncontained_self_targets():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)

    loose = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Wanderer", kind="character"),
            CharacterComponent(),
            RadMedicineComponent(uses=1),
        ],
    )
    result = execute_handler(
        UseRadMedicineHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "use",
            character_id=str(loose.id),
            item_id=str(loose.id),
        ),
    )
    assert result.ok
    loose.remove_component(RadMedicineComponent)

    carried_medicine = _inventory_entity(
        scenario,
        "rad-away",
        "medicine",
        [RadMedicineComponent(uses=1)],
    )
    result = execute_handler(
        UseRadMedicineHandler(),
        ctx,
        _handler_cmd(scenario, "use", item_id=str(carried_medicine)),
    )
    assert result.ok
    assert container_of(scenario.actor.world.get_entity(carried_medicine)) is None

    loose.add_component(ChemComponent(chem_type="stimulant"))
    result = execute_handler(
        TakeChemHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "take-chem",
            character_id=str(loose.id),
            chem_id=str(loose.id),
        ),
    )
    assert result.ok
    loose.remove_component(ChemComponent)

    loose.add_component(JunkComponent(outputs={"scrap": 0}))
    result = execute_handler(
        ScrapItemHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "scrap-item",
            character_id=str(loose.id),
            item_id=str(loose.id),
        ),
    )
    assert result.ok


def test_harvest_can_handle_branches():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    handler = HarvestSampleHandler()

    assert handler.can_handle(ctx, _handler_cmd(scenario, "harvest", sample_type="moss")) is True
    # A target-bearing harvest belongs to a different handler.
    assert handler.can_handle(ctx, _handler_cmd(scenario, "harvest", creature_id="x")) is False
    # product_type or an empty payload is accepted.
    assert handler.can_handle(ctx, _handler_cmd(scenario, "harvest", product_type="tissue")) is True
    assert handler.can_handle(ctx, _handler_cmd(scenario, "harvest")) is True


def test_unlock_crate_can_handle_and_already_unlocked():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    handler = UnlockCrateHandler()
    crate = _room_entity(
        scenario,
        "opened crate",
        "crate",
        [LockedCrateComponent(locked=False)],
    )

    # can_handle resolves via target_id when crate_id is absent.
    assert handler.can_handle(ctx, _handler_cmd(scenario, "unlock", target_id=str(crate))) is True
    assert (
        handler.can_handle(ctx, _handler_cmd(scenario, "unlock", target_id="entity_999")) is False
    )

    result = execute_handler(handler, ctx, _handler_cmd(scenario, "unlock", crate_id=str(crate)))
    assert result.ok is False
    assert result.reason == "crate is already unlocked"


def test_claim_faction_salvage_rejects_already_claimed():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    salvage = _room_entity(
        scenario,
        "claimed cache",
        "salvage",
        [FactionSalvageComponent(faction_id="minutemen", claimed_by="someone")],
    )
    result = execute_handler(
        ClaimFactionSalvageHandler(),
        ctx,
        _handler_cmd(scenario, "claim-faction-salvage", salvage_id=str(salvage)),
    )
    assert result.ok is False
    assert result.reason == "faction salvage already claimed"


def test_install_mod_rejects_unreachable_item_and_missing_schematic():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    distant_item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far rifle", kind="weapon"),
            DurabilityComponent(current=1, maximum=5),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), distant_item.id
    )
    unreachable = execute_handler(
        InstallModHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "install-mod",
            item_id=str(distant_item.id),
            schematic_id="entity_999",
        ),
    )
    assert unreachable.reason == "item is not reachable"

    item = _inventory_entity(
        scenario, "rifle", "weapon", [DurabilityComponent(current=1, maximum=5)]
    )
    bad_schematic = execute_handler(
        InstallModHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "install-mod",
            item_id=str(item),
            schematic_id="entity_999",
        ),
    )
    assert bad_schematic.reason == "target does not exist"


def test_field_repair_rejects_no_durability_and_missing_kit():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    no_durability = _inventory_entity(scenario, "rag", "cloth", [])
    no_dur_result = execute_handler(
        FieldRepairHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "field-repair",
            item_id=str(no_durability),
            kit_id="entity_999",
        ),
    )
    assert no_dur_result.reason == "target has no durability"

    item = _inventory_entity(
        scenario, "rifle", "weapon", [DurabilityComponent(current=1, maximum=5)]
    )
    bad_kit = execute_handler(
        FieldRepairHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "field-repair",
            item_id=str(item),
            kit_id="entity_999",
        ),
    )
    assert bad_kit.reason == "target does not exist"


def test_brew_chem_rejects_missing_ingredients():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    recipe = _room_entity(
        scenario,
        "rad tonic recipe",
        "recipe",
        [ChemRecipeComponent(chem_type="rad tonic", resource_inputs=(("scrap", 2),))],
    )
    result = execute_handler(
        BrewChemHandler(), ctx, _handler_cmd(scenario, "brew-chem", recipe_id=str(recipe))
    )
    assert result.ok is False
    assert result.reason == "missing chem ingredients"

    # With the ingredients on hand, the brew succeeds and consumes them.
    _scrap(scenario, 2)
    ok_result = execute_handler(
        BrewChemHandler(), ctx, _handler_cmd(scenario, "brew-chem", recipe_id=str(recipe))
    )
    assert ok_result.ok


def test_identify_and_restore_tech_can_handle_and_invalid_paths():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    tech = _room_entity(
        scenario,
        "scorched device",
        "item",
        [OldWorldTechComponent(tech_name="laser rifle")],
    )
    identify = IdentifyTechHandler()

    # can_handle resolves via target_id when tech_id is absent.
    assert identify.can_handle(ctx, _handler_cmd(scenario, "identify", target_id=str(tech))) is True
    assert (
        identify.can_handle(ctx, _handler_cmd(scenario, "identify", target_id="entity_9")) is False
    )

    restore = RestoreTechHandler()
    assert (
        execute_handler(
            restore,
            ctx,
            _handler_cmd(scenario, "restore-tech", character_id="not-an-id", tech_id=str(tech)),
        ).reason
        == "invalid character id"
    )
    assert (
        execute_handler(
            restore, ctx, _handler_cmd(scenario, "restore-tech", tech_id="entity_999")
        ).reason
        == "target does not exist"
    )


async def test_addiction_withdrawal_no_change_when_level_already_zero():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.world.get_entity(scenario.character).add_component(
        AddictionComponent(levels={"stimulant": 0.0}, last_updated_epoch=0)
    )
    withdrawals: list[WithdrawalProgressedEvent] = []
    scenario.actor.bus.subscribe(WithdrawalProgressedEvent, withdrawals.append)

    await scenario.actor.tick(HOUR)

    # A level already at zero does not change, so the component is retained (its
    # last_updated_epoch is bumped) without emitting a withdrawal event.
    addiction = scenario.actor.world.get_entity(scenario.character).get_component(
        AddictionComponent
    )
    assert addiction.levels == {"stimulant": 0.0}
    assert addiction.last_updated_epoch > 0
    assert withdrawals == []


def test_decontaminate_with_explicit_target_and_limited_uses():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(RadiationDoseComponent(amount=4.0))
    station = _room_entity(
        scenario,
        "metered decon arch",
        "decontamination",
        [DecontaminationComponent(dose_reduction=2.0, uses=2)],
    )

    # target_character_id is honored directly (skips the patient_id fallback) and a
    # finite-use station decrements its charges.
    result = execute_handler(
        DecontaminateHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "decontaminate",
            target_character_id=str(scenario.character),
            station_id=str(station),
        ),
    )
    assert result.ok
    assert character.get_component(RadiationDoseComponent).amount == 2.0
    assert (
        scenario.actor.world.get_entity(station).get_component(DecontaminationComponent).uses == 1
    )


def test_purify_water_rejects_wrong_kind_target():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    rock = _room_entity(scenario, "rock", "prop", [])
    result = execute_handler(
        PurifyWaterHandler(), ctx, _handler_cmd(scenario, "purify-water", water_id=str(rock))
    )
    assert result.ok is False
    assert result.reason == "target is the wrong kind"


def test_can_handle_short_circuits_on_primary_payload_key():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)

    # Each can_handle takes its early "key present" return True path.
    assert (
        UnlockCrateHandler().can_handle(ctx, _handler_cmd(scenario, "unlock", crate_id="anything"))
        is True
    )
    assert (
        IdentifyTechHandler().can_handle(
            ctx, _handler_cmd(scenario, "identify", tech_id="anything")
        )
        is True
    )
    assert (
        UseRadMedicineHandler().can_handle(ctx, _handler_cmd(scenario, "use", item_id="anything"))
        is True
    )

    # And a payload carrying none of the candidate keys yields a None id, which all
    # the can_handle guards reject.
    assert UnlockCrateHandler().can_handle(ctx, _handler_cmd(scenario, "unlock")) is False
    assert IdentifyTechHandler().can_handle(ctx, _handler_cmd(scenario, "identify")) is False
    assert DrinkContaminatedWaterHandler().can_handle(ctx, _handler_cmd(scenario, "drink")) is False
