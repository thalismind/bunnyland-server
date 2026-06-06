"""Tests for nuke-sim radiation, mutations, scavenging, and scrapping."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    PortableComponent,
    build_submitted_command,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.mechanics.colonysim import ResourceStackComponent
from bunnyland.mechanics.nukesim import (
    DecontaminateHandler,
    DecontaminationAppliedEvent,
    DecontaminationComponent,
    ItemScrappedEvent,
    JunkComponent,
    LootFoundEvent,
    LootTableComponent,
    MutationComponent,
    MutationManifestedEvent,
    RadiationDoseComponent,
    RadiationExposureEvent,
    RadiationScannedEvent,
    RadiationSicknessComponent,
    RadiationSourceComponent,
    RadiationSourceSealedEvent,
    RadMedicineComponent,
    RadProtectionComponent,
    ScanRadiationHandler,
    ScavengeHandler,
    ScavengeSiteComponent,
    ScrapItemHandler,
    SealRadiationSourceHandler,
    StabilizeMutationHandler,
    UseRadMedicineHandler,
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
