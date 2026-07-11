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

ALIASES = {
    "airlock": "bunnyland.voidsim.airlock",
    "alien-artifact": "bunnyland.voidsim.alien-artifact",
    "alien-species": "bunnyland.voidsim.alien-species",
    "astrogation": "bunnyland.voidsim.astrogation",
    "away-team": "bunnyland.voidsim.away-team",
    "blueprint": "bunnyland.voidsim.blueprint",
    "boarding-threat": "bunnyland.voidsim.boarding-threat",
    "cargo": "bunnyland.voidsim.cargo",
    "contract": "bunnyland.voidsim.contract",
    "customs-hold": "bunnyland.voidsim.customs-hold",
    "data-salvage": "bunnyland.voidsim.data-salvage",
    "diplomatic-mission": "bunnyland.voidsim.diplomatic-mission",
    "distress-signal": "bunnyland.voidsim.distress-signal",
    "drone": "bunnyland.voidsim.drone",
    "emergency": "bunnyland.voidsim.emergency",
    "fabricator": "bunnyland.voidsim.fabricator",
    "first-contact": "bunnyland.voidsim.first-contact",
    "gravity": "bunnyland.voidsim.gravity",
    "habitat-module": "bunnyland.voidsim.habitat-module",
    "insurance-policy": "bunnyland.voidsim.insurance-policy",
    "jump-drive": "bunnyland.voidsim.jump-drive",
    "mining-site": "bunnyland.voidsim.mining-site",
    "morale": "bunnyland.voidsim.morale",
    "mortgage": "bunnyland.voidsim.mortgage",
    "mutiny": "bunnyland.voidsim.mutiny",
    "navigation-route": "bunnyland.voidsim.navigation-route",
    "orbit": "bunnyland.voidsim.orbit",
    "orbital-body": "bunnyland.voidsim.orbital-body",
    "passenger": "bunnyland.voidsim.passenger",
    "quarantine": "bunnyland.voidsim.quarantine",
    "reactor": "bunnyland.voidsim.reactor",
    "salvage-claim": "bunnyland.voidsim.salvage-claim",
    "sensor": "bunnyland.voidsim.sensor",
    "ship": "bunnyland.voidsim.ship",
    "ship-ai": "bunnyland.voidsim.ship-ai",
    "ship-system": "bunnyland.voidsim.ship-system",
    "ship-upgrade": "bunnyland.voidsim.ship-upgrade",
    "smuggling-compartment": "bunnyland.voidsim.smuggling-compartment",
    "star-system": "bunnyland.voidsim.star-system",
    "station": "bunnyland.voidsim.station",
    "survey-site": "bunnyland.voidsim.survey-site",
    "trade-protocol": "bunnyland.voidsim.trade-protocol",
    "translation-matrix": "bunnyland.voidsim.translation-matrix",
    "xenobiology-sample": "bunnyland.voidsim.xenobiology-sample",
}


class VoidGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_room:
            name = ctx.name
            if generation_wants(ctx, "ship") or generation_mentions(ctx, "ship", "starship"):
                add(ShipComponent(name=name))
                add(PowerGridComponent())
            if generation_wants(ctx, "station") or generation_mentions(ctx, "station"):
                add(StationComponent(name=name))
            if generation_wants(ctx, "habitat-module", "ship") or generation_mentions(
                ctx, "module", "airlock", "ship"
            ):
                add(HabitatModuleComponent(module_type=ctx.biome))
                add(PressurizedComponent())
                add(LifeSupportComponent())
                add(OxygenComponent(last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "airlock") or generation_mentions(ctx, "airlock"):
                add(AirlockComponent())
            if generation_wants(ctx, "star-system"):
                add(StarSystemComponent(name=name))
            if generation_wants(ctx, "orbital-body") or generation_mentions(
                ctx, "planet", "moon", "asteroid"
            ):
                add(OrbitalBodyComponent(body_type=generation_orbital_body_type(ctx)))
            if generation_wants(ctx, "survey-site") or generation_mentions(ctx, "survey site"):
                add(SurveySiteComponent(resource=generation_resource_type(ctx)))
            if generation_wants(ctx, "mining-site") or generation_mentions(
                ctx, "mining site", "asteroid mine"
            ):
                add(MiningSiteComponent(resource_type=generation_resource_type(ctx)))
            if generation_wants(ctx, "salvage-claim") or generation_mentions(
                ctx, "salvage site", "derelict"
            ):
                add(SalvageClaimComponent(site_id=ctx.entity_id))
            if generation_wants(ctx, "contract"):
                add(ContractComponent(contract_type=generation_resource_type(ctx)))
            if generation_wants(ctx, "emergency") or generation_mentions(ctx, "emergency"):
                add(EmergencyComponent(emergency_type=generation_resource_type(ctx)))
            if generation_wants(ctx, "reactor") or generation_mentions(ctx, "reactor"):
                add(ReactorComponent())
            if generation_wants(ctx, "gravity"):
                add(GravityComponent())
        elif ctx.is_character:
            pass
        else:
            name = ctx.name
            resource_type = generation_resource_type(ctx)
            if generation_wants(ctx, "ship-system"):
                add(ShipSystemComponent(system_type=ctx.entity_kind))
            if generation_wants(ctx, "jump-drive") or generation_mentions(ctx, "jump drive"):
                add(JumpDriveComponent())
            if generation_wants(ctx, "fuel") or generation_mentions(ctx, "fuel"):
                add(FuelComponent())
            if generation_wants(ctx, "sensor") or generation_mentions(ctx, "sensor"):
                add(SensorComponent())
            if generation_wants(ctx, "distress-signal") or generation_mentions(
                ctx, "distress signal"
            ):
                add(DistressSignalComponent(text=ctx.intent or "distress signal"))
            if generation_wants(ctx, "fabricator") or generation_mentions(ctx, "fabricator"):
                add(FabricatorComponent())
            if generation_wants(ctx, "blueprint") or generation_mentions(ctx, "blueprint"):
                add(BlueprintComponent(name=name, system_type=resource_type))
            if generation_wants(ctx, "ship-upgrade"):
                add(ShipUpgradeComponent(system_type=resource_type))
            if generation_wants(ctx, "contract") or generation_mentions(ctx, "contract"):
                add(ContractComponent(contract_type=resource_type))
            if generation_wants(ctx, "cargo"):
                add(CargoComponent(cargo_type=resource_type))
            if generation_wants(ctx, "salvage-claim") or generation_mentions(ctx, "salvage claim"):
                add(SalvageClaimComponent(site_id=ctx.entity_id))
            if generation_wants(ctx, "alien-species") or generation_mentions(ctx, "alien species"):
                add(AlienSpeciesComponent(name=name))
            if generation_wants(ctx, "first-contact"):
                add(FirstContactComponent(species_id=ctx.entity_id))
            if generation_wants(ctx, "translation-matrix"):
                add(TranslationMatrixComponent(species_id=ctx.entity_id))
            if generation_wants(ctx, "quarantine") or generation_mentions(ctx, "quarantine"):
                add(QuarantineComponent(reason=ctx.intent or name))
            if generation_wants(ctx, "diplomatic-mission"):
                add(DiplomaticMissionComponent(species_id=ctx.entity_id))
            if generation_wants(ctx, "alien-artifact") or generation_mentions(
                ctx, "alien artifact"
            ):
                add(AlienArtifactComponent(species_id=ctx.entity_id))
            if generation_wants(ctx, "xenobiology-sample"):
                add(XenobiologySampleComponent(species_id=ctx.entity_id))
            if generation_wants(ctx, "trade-protocol"):
                add(TradeProtocolComponent(species_id=ctx.entity_id))
            if generation_wants(ctx, "drone"):
                add(DroneComponent(drone_type=resource_type))
            if generation_wants(ctx, "ship-ai") or generation_mentions(ctx, "ship ai"):
                add(ShipAIComponent(name=name))
            if generation_wants(ctx, "data-salvage") or generation_mentions(ctx, "data salvage"):
                add(DataSalvageComponent(data_type=resource_type))
            if generation_wants(ctx, "away-team"):
                add(AwayTeamComponent(mission=resource_type))
            if generation_wants(ctx, "morale"):
                add(MoraleComponent())
            if generation_wants(ctx, "mutiny"):
                add(MutinyComponent())
            if generation_wants(ctx, "emergency"):
                add(EmergencyComponent(emergency_type=resource_type))
            if generation_wants(ctx, "reactor") or generation_mentions(ctx, "reactor"):
                add(ReactorComponent())
            if generation_wants(ctx, "gravity"):
                add(GravityComponent())
            if generation_wants(ctx, "boarding-threat") or generation_mentions(
                ctx, "boarding threat"
            ):
                add(BoardingThreatComponent())
            if generation_wants(ctx, "passenger"):
                add(PassengerComponent())
            if generation_wants(ctx, "survey-site"):
                add(SurveySiteComponent(resource=resource_type))
            if generation_wants(ctx, "mining-site"):
                add(MiningSiteComponent(resource_type=resource_type))
            if generation_wants(ctx, "customs-hold"):
                add(CustomsHoldComponent())
            if generation_wants(ctx, "smuggling-compartment"):
                add(SmugglingCompartmentComponent())
            if generation_wants(ctx, "insurance-policy"):
                add(InsurancePolicyComponent(insured_entity_id=ctx.entity_id))
            if generation_wants(ctx, "mortgage"):
                add(MortgageComponent())
            if generation_wants(ctx, "orbital-body"):
                add(OrbitalBodyComponent(body_type=generation_orbital_body_type(ctx)))
            if generation_wants(ctx, "orbit"):
                add(OrbitComponent(body_id=ctx.entity_id))
            if generation_wants(ctx, "navigation-route"):
                add(NavigationRouteComponent(destination_id=ctx.entity_id))
            if generation_wants(ctx, "astrogation"):
                add(AstrogationComponent())
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = VoidGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "VoidGenerationEnricher"]
