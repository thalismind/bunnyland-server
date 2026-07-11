"""Declarative voidsim generation contributions."""

from ...core.generation import GenerationDelta, GenerationRequest
from ...worldgen.enrichment import (
    GenerationContext,
    generation_mentions,
    generation_orbital_body_type,
    generation_resource_type,
    generation_wants,
)
from .mechanics import (
    AirlockComponent,
    AlienArtifactComponent,
    AlienSpeciesComponent,
    AstrogationComponent,
    AwayTeamComponent,
    BlueprintComponent,
    BoardingThreatComponent,
    CargoComponent,
    ContractComponent,
    CustomsHoldComponent,
    DataSalvageComponent,
    DiplomaticMissionComponent,
    DistressSignalComponent,
    DroneComponent,
    EmergencyComponent,
    FabricatorComponent,
    FirstContactComponent,
    FuelComponent,
    GravityComponent,
    HabitatModuleComponent,
    InsurancePolicyComponent,
    JumpDriveComponent,
    LifeSupportComponent,
    MiningSiteComponent,
    MoraleComponent,
    MortgageComponent,
    MutinyComponent,
    NavigationRouteComponent,
    OrbitalBodyComponent,
    OrbitComponent,
    OxygenComponent,
    PassengerComponent,
    PowerGridComponent,
    PressurizedComponent,
    QuarantineComponent,
    ReactorComponent,
    SalvageClaimComponent,
    SensorComponent,
    ShipAIComponent,
    ShipComponent,
    ShipSystemComponent,
    ShipUpgradeComponent,
    SmugglingCompartmentComponent,
    StarSystemComponent,
    StationComponent,
    SurveySiteComponent,
    TradeProtocolComponent,
    TranslationMatrixComponent,
    XenobiologySampleComponent,
)

CAPABILITIES = (
    "bunnyland.voidsim.airlock",
    "bunnyland.voidsim.alien-artifact",
    "bunnyland.voidsim.alien-species",
    "bunnyland.voidsim.astrogation",
    "bunnyland.voidsim.away-team",
    "bunnyland.voidsim.blueprint",
    "bunnyland.voidsim.boarding-threat",
    "bunnyland.voidsim.cargo",
    "bunnyland.voidsim.contract",
    "bunnyland.voidsim.customs-hold",
    "bunnyland.voidsim.data-salvage",
    "bunnyland.voidsim.diplomatic-mission",
    "bunnyland.voidsim.distress-signal",
    "bunnyland.voidsim.drone",
    "bunnyland.voidsim.emergency",
    "bunnyland.voidsim.fabricator",
    "bunnyland.voidsim.first-contact",
    "bunnyland.voidsim.fuel",
    "bunnyland.voidsim.gravity",
    "bunnyland.voidsim.habitat-module",
    "bunnyland.voidsim.insurance-policy",
    "bunnyland.voidsim.jump-drive",
    "bunnyland.voidsim.mining-site",
    "bunnyland.voidsim.morale",
    "bunnyland.voidsim.mortgage",
    "bunnyland.voidsim.mutiny",
    "bunnyland.voidsim.navigation-route",
    "bunnyland.voidsim.orbit",
    "bunnyland.voidsim.orbital-body",
    "bunnyland.voidsim.passenger",
    "bunnyland.voidsim.quarantine",
    "bunnyland.voidsim.reactor",
    "bunnyland.voidsim.salvage-claim",
    "bunnyland.voidsim.sensor",
    "bunnyland.voidsim.ship",
    "bunnyland.voidsim.ship-ai",
    "bunnyland.voidsim.ship-system",
    "bunnyland.voidsim.ship-upgrade",
    "bunnyland.voidsim.smuggling-compartment",
    "bunnyland.voidsim.star-system",
    "bunnyland.voidsim.station",
    "bunnyland.voidsim.survey-site",
    "bunnyland.voidsim.trade-protocol",
    "bunnyland.voidsim.translation-matrix",
    "bunnyland.voidsim.xenobiology-sample",
)


class VoidGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_room:
            name = ctx.name
            if generation_wants(ctx, "bunnyland.voidsim.ship") or generation_mentions(
                ctx, "ship", "starship"
            ):
                add(ShipComponent(name=name))
                add(PowerGridComponent())
            if generation_wants(ctx, "bunnyland.voidsim.station") or generation_mentions(
                ctx, "station"
            ):
                add(StationComponent(name=name))
            if generation_wants(
                ctx, "bunnyland.voidsim.habitat-module", "bunnyland.voidsim.ship"
            ) or generation_mentions(ctx, "module", "airlock", "ship"):
                add(HabitatModuleComponent(module_type=ctx.biome))
                add(PressurizedComponent())
                add(LifeSupportComponent())
                add(OxygenComponent(last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.voidsim.airlock") or generation_mentions(
                ctx, "airlock"
            ):
                add(AirlockComponent())
            if generation_wants(ctx, "bunnyland.voidsim.star-system"):
                add(StarSystemComponent(name=name))
            if generation_wants(ctx, "bunnyland.voidsim.orbital-body") or generation_mentions(
                ctx, "planet", "moon", "asteroid"
            ):
                add(OrbitalBodyComponent(body_type=generation_orbital_body_type(ctx)))
            if generation_wants(ctx, "bunnyland.voidsim.survey-site") or generation_mentions(
                ctx, "survey site"
            ):
                add(SurveySiteComponent(resource=generation_resource_type(ctx)))
            if generation_wants(ctx, "bunnyland.voidsim.mining-site") or generation_mentions(
                ctx, "mining site", "asteroid mine"
            ):
                add(MiningSiteComponent(resource_type=generation_resource_type(ctx)))
            if generation_wants(ctx, "bunnyland.voidsim.salvage-claim") or generation_mentions(
                ctx, "salvage site", "derelict"
            ):
                add(SalvageClaimComponent(site_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.voidsim.contract"):
                add(ContractComponent(contract_type=generation_resource_type(ctx)))
            if generation_wants(ctx, "bunnyland.voidsim.emergency") or generation_mentions(
                ctx, "emergency"
            ):
                add(EmergencyComponent(emergency_type=generation_resource_type(ctx)))
            if generation_wants(ctx, "bunnyland.voidsim.reactor") or generation_mentions(
                ctx, "reactor"
            ):
                add(ReactorComponent())
            if generation_wants(ctx, "bunnyland.voidsim.gravity"):
                add(GravityComponent())
        elif ctx.is_character:
            pass
        else:
            name = ctx.name
            resource_type = generation_resource_type(ctx)
            if generation_wants(ctx, "bunnyland.voidsim.ship-system"):
                add(ShipSystemComponent(system_type=ctx.entity_kind))
            if generation_wants(ctx, "bunnyland.voidsim.jump-drive") or generation_mentions(
                ctx, "jump drive"
            ):
                add(JumpDriveComponent())
            if generation_wants(ctx, "bunnyland.voidsim.fuel") or generation_mentions(ctx, "fuel"):
                add(FuelComponent())
            if generation_wants(ctx, "bunnyland.voidsim.sensor") or generation_mentions(
                ctx, "sensor"
            ):
                add(SensorComponent())
            if generation_wants(ctx, "bunnyland.voidsim.distress-signal") or generation_mentions(
                ctx, "distress signal"
            ):
                add(DistressSignalComponent(text=ctx.intent or "distress signal"))
            if generation_wants(ctx, "bunnyland.voidsim.fabricator") or generation_mentions(
                ctx, "fabricator"
            ):
                add(FabricatorComponent())
            if generation_wants(ctx, "bunnyland.voidsim.blueprint") or generation_mentions(
                ctx, "blueprint"
            ):
                add(BlueprintComponent(name=name, system_type=resource_type))
            if generation_wants(ctx, "bunnyland.voidsim.ship-upgrade"):
                add(ShipUpgradeComponent(system_type=resource_type))
            if generation_wants(ctx, "bunnyland.voidsim.contract") or generation_mentions(
                ctx, "contract"
            ):
                add(ContractComponent(contract_type=resource_type))
            if generation_wants(ctx, "bunnyland.voidsim.cargo"):
                add(CargoComponent(cargo_type=resource_type))
            if generation_wants(ctx, "bunnyland.voidsim.salvage-claim") or generation_mentions(
                ctx, "salvage claim"
            ):
                add(SalvageClaimComponent(site_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.voidsim.alien-species") or generation_mentions(
                ctx, "alien species"
            ):
                add(AlienSpeciesComponent(name=name))
            if generation_wants(ctx, "bunnyland.voidsim.first-contact"):
                add(FirstContactComponent(species_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.voidsim.translation-matrix"):
                add(TranslationMatrixComponent(species_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.voidsim.quarantine") or generation_mentions(
                ctx, "quarantine"
            ):
                add(QuarantineComponent(reason=ctx.intent or name))
            if generation_wants(ctx, "bunnyland.voidsim.diplomatic-mission"):
                add(DiplomaticMissionComponent(species_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.voidsim.alien-artifact") or generation_mentions(
                ctx, "alien artifact"
            ):
                add(AlienArtifactComponent(species_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.voidsim.xenobiology-sample"):
                add(XenobiologySampleComponent(species_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.voidsim.trade-protocol"):
                add(TradeProtocolComponent(species_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.voidsim.drone"):
                add(DroneComponent(drone_type=resource_type))
            if generation_wants(ctx, "bunnyland.voidsim.ship-ai") or generation_mentions(
                ctx, "ship ai"
            ):
                add(ShipAIComponent(name=name))
            if generation_wants(ctx, "bunnyland.voidsim.data-salvage") or generation_mentions(
                ctx, "data salvage"
            ):
                add(DataSalvageComponent(data_type=resource_type))
            if generation_wants(ctx, "bunnyland.voidsim.away-team"):
                add(AwayTeamComponent(mission=resource_type))
            if generation_wants(ctx, "bunnyland.voidsim.morale"):
                add(MoraleComponent())
            if generation_wants(ctx, "bunnyland.voidsim.mutiny"):
                add(MutinyComponent())
            if generation_wants(ctx, "bunnyland.voidsim.emergency"):
                add(EmergencyComponent(emergency_type=resource_type))
            if generation_wants(ctx, "bunnyland.voidsim.reactor") or generation_mentions(
                ctx, "reactor"
            ):
                add(ReactorComponent())
            if generation_wants(ctx, "bunnyland.voidsim.gravity"):
                add(GravityComponent())
            if generation_wants(ctx, "bunnyland.voidsim.boarding-threat") or generation_mentions(
                ctx, "boarding threat"
            ):
                add(BoardingThreatComponent())
            if generation_wants(ctx, "bunnyland.voidsim.passenger"):
                add(PassengerComponent())
            if generation_wants(ctx, "bunnyland.voidsim.survey-site"):
                add(SurveySiteComponent(resource=resource_type))
            if generation_wants(ctx, "bunnyland.voidsim.mining-site"):
                add(MiningSiteComponent(resource_type=resource_type))
            if generation_wants(ctx, "bunnyland.voidsim.customs-hold"):
                add(CustomsHoldComponent())
            if generation_wants(ctx, "bunnyland.voidsim.smuggling-compartment"):
                add(SmugglingCompartmentComponent())
            if generation_wants(ctx, "bunnyland.voidsim.insurance-policy"):
                add(InsurancePolicyComponent(insured_entity_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.voidsim.mortgage"):
                add(MortgageComponent())
            if generation_wants(ctx, "bunnyland.voidsim.orbital-body"):
                add(OrbitalBodyComponent(body_type=generation_orbital_body_type(ctx)))
            if generation_wants(ctx, "bunnyland.voidsim.orbit"):
                add(OrbitComponent(body_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.voidsim.navigation-route"):
                add(NavigationRouteComponent(destination_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.voidsim.astrogation"):
                add(AstrogationComponent())
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = VoidGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "VoidGenerationEnricher"]
