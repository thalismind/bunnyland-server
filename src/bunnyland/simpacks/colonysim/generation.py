"""Declarative colonysim generation contributions."""

from ...core.generation import GenerationDelta, GenerationRequest
from ...worldgen.enrichment import (
    GenerationContext,
    generation_mentions,
    generation_resource_type,
    generation_trade_faction,
    generation_wants,
)
from .mechanics import (
    AllowedAreaComponent,
    BedRestComponent,
    BodyPartHealthComponent,
    CaravanComponent,
    ColonyIncidentComponent,
    ColonyWealthComponent,
    FactionRelationComponent,
    ForbiddenComponent,
    HaulableComponent,
    InfectionComponent,
    JobBillComponent,
    JobComponent,
    MedicalBedComponent,
    MedicineComponent,
    MentalStateComponent,
    PawnProfileComponent,
    PrisonerComponent,
    ProstheticComponent,
    RecipeComponent,
    ResearchProjectComponent,
    ResourceNodeComponent,
    ResourceStackComponent,
    RoomQualityComponent,
    RoomRoleComponent,
    RoomStatComponent,
    StockpileComponent,
    StorageFilterComponent,
    SurgeryBillComponent,
    TechUnlockComponent,
    TradeOfferComponent,
    WorkCapabilityComponent,
    WorkPriorityComponent,
    WorkstationComponent,
)

CAPABILITIES = (
    "bunnyland.colonysim.allowed-area",
    "bunnyland.colonysim.bed-rest",
    "bunnyland.colonysim.body-part",
    "bunnyland.colonysim.captive",
    "bunnyland.colonysim.caravan",
    "bunnyland.colonysim.colony-wealth",
    "bunnyland.colonysim.faction-relation",
    "bunnyland.colonysim.forbidden",
    "bunnyland.colonysim.haulable",
    "bunnyland.colonysim.incident",
    "bunnyland.colonysim.infection",
    "bunnyland.colonysim.job",
    "bunnyland.colonysim.job-bill",
    "bunnyland.colonysim.medical-bed",
    "bunnyland.colonysim.medicine",
    "bunnyland.colonysim.mental-state",
    "bunnyland.colonysim.pawn-profile",
    "bunnyland.colonysim.prisoner",
    "bunnyland.colonysim.prosthetic",
    "bunnyland.colonysim.recipe",
    "bunnyland.colonysim.research",
    "bunnyland.colonysim.resource-node",
    "bunnyland.colonysim.resource-stack",
    "bunnyland.colonysim.room-quality",
    "bunnyland.colonysim.room-role",
    "bunnyland.colonysim.room-stat",
    "bunnyland.colonysim.stockpile",
    "bunnyland.colonysim.storage-filter",
    "bunnyland.colonysim.surgery",
    "bunnyland.colonysim.tech-unlock",
    "bunnyland.colonysim.trade-offer",
    "bunnyland.colonysim.work-capability",
    "bunnyland.colonysim.work-priority",
    "bunnyland.colonysim.workstation",
)

ALIASES = {
    "allowed-area": "bunnyland.colonysim.allowed-area",
    "bed-rest": "bunnyland.colonysim.bed-rest",
    "body-part": "bunnyland.colonysim.body-part",
    "captive": "bunnyland.colonysim.captive",
    "caravan": "bunnyland.colonysim.caravan",
    "colony-wealth": "bunnyland.colonysim.colony-wealth",
    "faction-relation": "bunnyland.colonysim.faction-relation",
    "forbidden": "bunnyland.colonysim.forbidden",
    "haulable": "bunnyland.colonysim.haulable",
    "incident": "bunnyland.colonysim.incident",
    "infection": "bunnyland.colonysim.infection",
    "job": "bunnyland.colonysim.job",
    "job-bill": "bunnyland.colonysim.job-bill",
    "medical-bed": "bunnyland.colonysim.medical-bed",
    "medicine": "bunnyland.colonysim.medicine",
    "mental-state": "bunnyland.colonysim.mental-state",
    "pawn-profile": "bunnyland.colonysim.pawn-profile",
    "prisoner": "bunnyland.colonysim.prisoner",
    "prosthetic": "bunnyland.colonysim.prosthetic",
    "recipe": "bunnyland.colonysim.recipe",
    "research": "bunnyland.colonysim.research",
    "resource-node": "bunnyland.colonysim.resource-node",
    "resource-stack": "bunnyland.colonysim.resource-stack",
    "room-quality": "bunnyland.colonysim.room-quality",
    "room-role": "bunnyland.colonysim.room-role",
    "room-stat": "bunnyland.colonysim.room-stat",
    "stockpile": "bunnyland.colonysim.stockpile",
    "storage-filter": "bunnyland.colonysim.storage-filter",
    "surgery": "bunnyland.colonysim.surgery",
    "tech-unlock": "bunnyland.colonysim.tech-unlock",
    "trade-offer": "bunnyland.colonysim.trade-offer",
    "work-capability": "bunnyland.colonysim.work-capability",
    "work-priority": "bunnyland.colonysim.work-priority",
    "workstation": "bunnyland.colonysim.workstation",
}


class ColonyGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_room:
            if generation_wants(ctx, "stockpile") or generation_mentions(
                ctx, "stockpile", "warehouse"
            ):
                add(StockpileComponent(capacity=40))
            if generation_wants(ctx, "room-role") or generation_mentions(
                ctx, "barracks", "clinic", "dining room"
            ):
                add(RoomRoleComponent(role=ctx.biome or "room"))
            if generation_wants(ctx, "room-stat") or generation_mentions(
                ctx, "beautiful", "clean", "comfortable"
            ):
                add(RoomStatComponent(beauty=1.0, cleanliness=1.0, comfort=1.0, wealth=25.0))
            if generation_wants(ctx, "room-quality") or generation_mentions(
                ctx, "impressive", "quality room"
            ):
                add(
                    RoomQualityComponent(
                        role=ctx.biome or "room",
                        beauty=1.0,
                        cleanliness=1.0,
                        comfort=1.0,
                        impressiveness=3.0,
                        updated_at_epoch=ctx.world_epoch,
                    )
                )
            if generation_wants(ctx, "colony-wealth") or generation_mentions(
                ctx, "colony wealth", "wealth"
            ):
                add(
                    ColonyWealthComponent(
                        wealth=100.0, expectations="low", updated_at_epoch=ctx.world_epoch
                    )
                )
        elif ctx.is_character:
            if generation_wants(ctx, "pawn-profile") or generation_mentions(
                ctx, "backstory", "passion"
            ):
                add(
                    PawnProfileComponent(
                        backstory=ctx.generation.description,
                        passions={tag: 1 for tag in ctx.generation.tags},
                    )
                )
            if generation_wants(ctx, "prisoner", "captive") or generation_mentions(
                ctx, "prisoner", "captive"
            ):
                add(PrisonerComponent(policy="hold"))
            if generation_wants(ctx, "work-priority") or generation_mentions(ctx, "work priority"):
                add(WorkPriorityComponent(priorities={generation_resource_type(ctx): 1}))
            if generation_wants(ctx, "work-capability") or generation_mentions(
                ctx, "capable", "disabled work"
            ):
                add(WorkCapabilityComponent(skill_levels={generation_resource_type(ctx): 1}))
            if generation_wants(ctx, "allowed-area") or generation_mentions(ctx, "allowed area"):
                add(AllowedAreaComponent(room_ids=()))
            if generation_wants(ctx, "bed-rest") or generation_mentions(ctx, "bed rest"):
                add(BedRestComponent(started_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "infection") or generation_mentions(
                ctx, "infection", "infected"
            ):
                add(InfectionComponent(severity=0.1, last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "mental-state") or generation_mentions(
                ctx, "mental state", "inspired"
            ):
                add(MentalStateComponent(state="inspired", reason=ctx.intent or "worldgen"))
        else:
            name = ctx.name
            resource_type = generation_resource_type(ctx)
            if generation_wants(ctx, "resource-node") or generation_mentions(
                ctx, "vein", "deposit", "patch"
            ):
                add(ResourceNodeComponent(resource_type=resource_type, current=5, maximum=5))
            if generation_wants(ctx, "resource-stack") or generation_mentions(
                ctx, "stack", "pile of"
            ):
                add(ResourceStackComponent(resource_type=resource_type, quantity=5))
            if generation_wants(ctx, "stockpile"):
                add(StockpileComponent(capacity=20))
            if generation_wants(ctx, "storage-filter") or generation_mentions(
                ctx, "storage filter"
            ):
                add(StorageFilterComponent(allowed_types=(resource_type,)))
            if generation_wants(ctx, "haulable") or generation_mentions(ctx, "haulable"):
                add(HaulableComponent(priority=1))
            if generation_wants(ctx, "forbidden") or generation_mentions(ctx, "forbidden"):
                add(ForbiddenComponent())
            if generation_wants(ctx, "workstation") or generation_mentions(
                ctx, "workbench", "forge", "bench"
            ):
                add(WorkstationComponent(station_type=resource_type))
            if generation_wants(ctx, "recipe") or generation_mentions(ctx, "recipe"):
                add(
                    RecipeComponent(
                        recipe_id=resource_type,
                        inputs={resource_type: 1},
                        outputs={resource_type: 1},
                    )
                )
            if generation_wants(ctx, "job"):
                add(JobComponent(job_type=resource_type, priority=1))
            if generation_wants(ctx, "job-bill") or generation_mentions(ctx, "bill", "work order"):
                add(JobBillComponent(recipe_id=resource_type, work_required=5.0))
            if generation_wants(ctx, "research") or generation_mentions(
                ctx, "research", "technology"
            ):
                add(ResearchProjectComponent(project_id=resource_type, work_required=10.0))
            if generation_wants(ctx, "incident") or generation_mentions(
                ctx, "incident", "raid", "blight"
            ):
                add(ColonyIncidentComponent(incident_type=resource_type))
            if generation_wants(ctx, "trade-offer") or generation_mentions(ctx, "trade", "trader"):
                add(TradeOfferComponent(faction_id="generated-faction", gives={resource_type: 1}))
            if generation_wants(ctx, "surgery") or generation_mentions(ctx, "surgery", "operation"):
                add(SurgeryBillComponent(part="torso", operation=resource_type))
            if generation_wants(ctx, "body-part") or generation_mentions(ctx, "body part", "limb"):
                add(BodyPartHealthComponent(part=resource_type))
            if generation_wants(ctx, "tech-unlock") or generation_mentions(ctx, "unlocked tech"):
                add(TechUnlockComponent(tech_id=resource_type, unlocked_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "faction-relation") or generation_mentions(
                ctx, "faction relation"
            ):
                add(
                    FactionRelationComponent(faction_id=generation_trade_faction(ctx), goodwill=1.0)
                )
            if generation_wants(ctx, "caravan") or generation_mentions(ctx, "caravan"):
                add(
                    CaravanComponent(
                        destination=ctx.intent or name, departed_at_epoch=ctx.world_epoch
                    )
                )
            if generation_wants(ctx, "medicine") or generation_mentions(ctx, "medicine", "medkit"):
                add(MedicineComponent(quality=1.0, uses=1))
            if generation_wants(ctx, "medical-bed") or generation_mentions(
                ctx, "clinic bed", "medical bed"
            ):
                add(MedicalBedComponent())
            if generation_wants(ctx, "prosthetic") or generation_mentions(ctx, "prosthetic"):
                add(ProstheticComponent(part=resource_type))
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = ColonyGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "ColonyGenerationEnricher"]
