"""Declarative gardensim generation contributions."""

from ...core.generation import GenerationDelta, GenerationRequest
from ...worldgen.enrichment import (
    GenerationContext,
    generation_animal_species,
    generation_crop_type,
    generation_fish_type,
    generation_mentions,
    generation_resource_type,
    generation_season,
    generation_wants,
)
from .mechanics import (
    AnimalBreedingComponent,
    AnimalHomeComponent,
    AnimalProductComponent,
    BundleComponent,
    CollectionComponent,
    CropComponent,
    CropGrowthComponent,
    CropInspectionComponent,
    CropQualityComponent,
    DailyFarmResetComponent,
    FarmAnimalComponent,
    FarmQuestComponent,
    FertilizerComponent,
    FestivalComponent,
    FishingSpotComponent,
    ForageComponent,
    FriendshipComponent,
    GeodeComponent,
    GiftPreferenceComponent,
    GreenhouseComponent,
    HarvestableComponent,
    LadderComponent,
    MachineBreakdownComponent,
    MachineComponent,
    MailComponent,
    MineLevelComponent,
    MiningNodeComponent,
    MuseumCollectionComponent,
    PestComponent,
    ProcessingRecipeComponent,
    RegrowableComponent,
    RewardComponent,
    SeedComponent,
    ShippingBinComponent,
    SoilComponent,
    TilledComponent,
    TreeComponent,
    TreeTapComponent,
    WateredComponent,
    WeedComponent,
)

CAPABILITIES = (
    "bunnyland.gardensim.animal-breeding",
    "bunnyland.gardensim.animal-home",
    "bunnyland.gardensim.animal-product",
    "bunnyland.gardensim.bundle",
    "bunnyland.gardensim.collection",
    "bunnyland.gardensim.crop",
    "bunnyland.gardensim.crop-growth",
    "bunnyland.gardensim.crop-inspection",
    "bunnyland.gardensim.crop-quality",
    "bunnyland.gardensim.daily-farm-reset",
    "bunnyland.gardensim.farm-animal",
    "bunnyland.gardensim.farm-quest",
    "bunnyland.gardensim.fertilizer",
    "bunnyland.gardensim.festival",
    "bunnyland.gardensim.fishing-spot",
    "bunnyland.gardensim.forage",
    "bunnyland.gardensim.friendship",
    "bunnyland.gardensim.garden-soil",
    "bunnyland.gardensim.geode",
    "bunnyland.gardensim.gift-preference",
    "bunnyland.gardensim.greenhouse",
    "bunnyland.gardensim.harvestable",
    "bunnyland.gardensim.ladder",
    "bunnyland.gardensim.machine",
    "bunnyland.gardensim.machine-breakdown",
    "bunnyland.gardensim.mail",
    "bunnyland.gardensim.mine-level",
    "bunnyland.gardensim.mining-node",
    "bunnyland.gardensim.museum-collection",
    "bunnyland.gardensim.pest",
    "bunnyland.gardensim.processing-recipe",
    "bunnyland.gardensim.regrowable",
    "bunnyland.gardensim.reward",
    "bunnyland.gardensim.seed",
    "bunnyland.gardensim.shipping-bin",
    "bunnyland.gardensim.soil",
    "bunnyland.gardensim.tilled",
    "bunnyland.gardensim.tree",
    "bunnyland.gardensim.tree-tap",
    "bunnyland.gardensim.watered",
    "bunnyland.gardensim.weed",
)

ALIASES = {
    "animal-breeding": "bunnyland.gardensim.animal-breeding",
    "animal-home": "bunnyland.gardensim.animal-home",
    "animal-product": "bunnyland.gardensim.animal-product",
    "bundle": "bunnyland.gardensim.bundle",
    "collection": "bunnyland.gardensim.collection",
    "crop": "bunnyland.gardensim.crop",
    "crop-growth": "bunnyland.gardensim.crop-growth",
    "crop-inspection": "bunnyland.gardensim.crop-inspection",
    "crop-quality": "bunnyland.gardensim.crop-quality",
    "daily-farm-reset": "bunnyland.gardensim.daily-farm-reset",
    "farm-animal": "bunnyland.gardensim.farm-animal",
    "farm-quest": "bunnyland.gardensim.farm-quest",
    "fertilizer": "bunnyland.gardensim.fertilizer",
    "festival": "bunnyland.gardensim.festival",
    "fishing-spot": "bunnyland.gardensim.fishing-spot",
    "forage": "bunnyland.gardensim.forage",
    "friendship": "bunnyland.gardensim.friendship",
    "garden-soil": "bunnyland.gardensim.garden-soil",
    "geode": "bunnyland.gardensim.geode",
    "gift-preference": "bunnyland.gardensim.gift-preference",
    "greenhouse": "bunnyland.gardensim.greenhouse",
    "harvestable": "bunnyland.gardensim.harvestable",
    "ladder": "bunnyland.gardensim.ladder",
    "machine": "bunnyland.gardensim.machine",
    "machine-breakdown": "bunnyland.gardensim.machine-breakdown",
    "mail": "bunnyland.gardensim.mail",
    "mine-level": "bunnyland.gardensim.mine-level",
    "mining-node": "bunnyland.gardensim.mining-node",
    "museum-collection": "bunnyland.gardensim.museum-collection",
    "pest": "bunnyland.gardensim.pest",
    "processing-recipe": "bunnyland.gardensim.processing-recipe",
    "regrowable": "bunnyland.gardensim.regrowable",
    "reward": "bunnyland.gardensim.reward",
    "seed": "bunnyland.gardensim.seed",
    "shipping-bin": "bunnyland.gardensim.shipping-bin",
    "soil": "bunnyland.gardensim.soil",
    "tilled": "bunnyland.gardensim.tilled",
    "tree": "bunnyland.gardensim.tree",
    "tree-tap": "bunnyland.gardensim.tree-tap",
    "watered": "bunnyland.gardensim.watered",
    "weed": "bunnyland.gardensim.weed",
}


class GardenGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_room:
            if generation_wants(ctx, "soil", "garden-soil") or generation_mentions(
                ctx, "garden", "farm", "field"
            ):
                add(SoilComponent(quality=1.2))
            if generation_wants(ctx, "greenhouse") or generation_mentions(ctx, "greenhouse"):
                add(GreenhouseComponent())
            if generation_wants(ctx, "mine-level") or generation_mentions(ctx, "mine", "cavern"):
                add(MineLevelComponent(level=1))
            if generation_wants(ctx, "daily-farm-reset"):
                add(DailyFarmResetComponent(last_reset_epoch=ctx.world_epoch))
        elif ctx.is_character:
            resource_type = generation_resource_type(ctx)
            if generation_wants(ctx, "gift-preference") or generation_mentions(
                ctx, "likes", "loves gifts"
            ):
                add(GiftPreferenceComponent(likes=(resource_type,)))
            if generation_wants(ctx, "friendship") or generation_mentions(ctx, "friend"):
                add(FriendshipComponent())
            if generation_wants(ctx, "collection") or generation_mentions(ctx, "collection"):
                add(CollectionComponent(entries=(resource_type,)))
        else:
            name = ctx.name
            crop_type = generation_crop_type(ctx)
            resource_type = generation_resource_type(ctx)
            if generation_wants(ctx, "seed") or generation_mentions(ctx, "seed", "seeds"):
                add(SeedComponent(crop_type=crop_type, growth_days=2.0, yield_item=crop_type))
            if generation_wants(ctx, "tilled") or generation_mentions(ctx, "tilled soil"):
                add(TilledComponent(tilled_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "watered") or generation_mentions(ctx, "watered"):
                add(
                    WateredComponent(
                        watered_at_epoch=ctx.world_epoch,
                        expires_at_epoch=ctx.world_epoch + 24 * 60 * 60,
                    )
                )
            if generation_wants(ctx, "crop") or generation_mentions(ctx, "planted crop"):
                add(CropComponent(crop_type=crop_type, planted_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "crop-growth"):
                add(
                    CropGrowthComponent(
                        progress_days=0.0, required_days=2.0, last_updated_epoch=ctx.world_epoch
                    )
                )
            if generation_wants(ctx, "harvestable") or generation_mentions(ctx, "harvestable"):
                add(HarvestableComponent(yield_item=resource_type, ready=True))
            if generation_wants(ctx, "fertilizer") or generation_mentions(
                ctx, "fertilizer", "compost"
            ):
                add(FertilizerComponent(kind="compost", growth_multiplier=1.2))
            if generation_wants(ctx, "tree") or generation_mentions(ctx, "sapling", "tree"):
                add(
                    TreeComponent(
                        tree_type=resource_type, planted_at_epoch=ctx.world_epoch, maturity_days=7.0
                    )
                )
            if generation_wants(ctx, "tree-tap") or generation_mentions(
                ctx, "tree tap", "tapped tree"
            ):
                add(
                    TreeTapComponent(
                        tapped_at_epoch=ctx.world_epoch, last_collected_epoch=ctx.world_epoch
                    )
                )
            if generation_wants(ctx, "crop-quality") or generation_mentions(ctx, "crop", "sprout"):
                add(CropQualityComponent(quality=1.1))
            if generation_wants(ctx, "regrowable") or generation_mentions(
                ctx, "regrow", "perennial"
            ):
                add(RegrowableComponent(regrow_days=2.0))
            if generation_wants(ctx, "pest") or generation_mentions(ctx, "pest", "bugs"):
                add(PestComponent(severity=0.5))
            if generation_wants(ctx, "weed") or generation_mentions(ctx, "weed", "weeds"):
                add(WeedComponent(density=0.5))
            if generation_wants(ctx, "crop-inspection"):
                add(CropInspectionComponent(inspected_at_epoch=ctx.world_epoch, notes=ctx.intent))
            if generation_wants(ctx, "machine") or generation_mentions(
                ctx, "machine", "preserves", "keg"
            ):
                add(MachineComponent(machine_type=resource_type))
            if generation_wants(ctx, "machine-breakdown") or generation_mentions(
                ctx, "broken machine"
            ):
                add(MachineBreakdownComponent(reason=ctx.intent or "worldgen"))
            if generation_wants(ctx, "processing-recipe") or generation_mentions(
                ctx, "processing recipe"
            ):
                add(
                    ProcessingRecipeComponent(
                        recipe_id=resource_type,
                        machine_type=resource_type,
                        inputs={resource_type: 1},
                        outputs={resource_type: 1},
                        duration_seconds=60,
                    )
                )
            if generation_wants(ctx, "animal-home") or generation_mentions(ctx, "coop", "barn"):
                add(AnimalHomeComponent())
            if generation_wants(ctx, "farm-animal") or generation_mentions(
                ctx, "farm animal", "cow", "chicken"
            ):
                species = generation_animal_species(ctx)
                add(FarmAnimalComponent(species=species))
            if generation_wants(ctx, "animal-product"):
                add(AnimalProductComponent(product_type=resource_type))
            if generation_wants(ctx, "animal-breeding"):
                add(AnimalBreedingComponent(offspring_species=generation_animal_species(ctx)))
            if generation_wants(ctx, "fishing-spot") or generation_mentions(
                ctx, "fishing spot", "pond"
            ):
                add(
                    FishingSpotComponent(
                        fish_type=generation_fish_type(ctx), season=generation_season(ctx)
                    )
                )
            if generation_wants(ctx, "mining-node") or generation_mentions(
                ctx, "mining node", "ore node"
            ):
                add(MiningNodeComponent(resource_type=resource_type))
            if generation_wants(ctx, "shipping-bin") or generation_mentions(
                ctx, "shipping bin", "shipping crate"
            ):
                add(ShippingBinComponent())
            if generation_wants(ctx, "geode") or generation_mentions(ctx, "geode"):
                add(GeodeComponent(resource_type=resource_type))
            if generation_wants(ctx, "ladder") or generation_mentions(ctx, "ladder"):
                add(LadderComponent(target_room_id=ctx.entity_id))
            if generation_wants(ctx, "forage") or generation_mentions(ctx, "forage"):
                add(ForageComponent(resource_type=resource_type, seasons=(generation_season(ctx),)))
            if generation_wants(ctx, "festival") or generation_mentions(ctx, "festival"):
                add(FestivalComponent(name=name, season=generation_season(ctx)))
            if generation_wants(ctx, "bundle") or generation_mentions(ctx, "bundle"):
                add(BundleComponent(bundle_id=ctx.object_key, requirements={resource_type: 1}))
            if generation_wants(ctx, "collection") or generation_mentions(ctx, "collection"):
                add(CollectionComponent(entries=(resource_type,)))
            if generation_wants(ctx, "museum-collection") or generation_mentions(ctx, "museum"):
                add(MuseumCollectionComponent())
            if generation_wants(ctx, "reward") or generation_mentions(ctx, "reward"):
                add(RewardComponent(resource_type=resource_type))
            if generation_wants(ctx, "mail") or generation_mentions(ctx, "mail", "letter"):
                add(MailComponent(subject=name))
            if generation_wants(ctx, "farm-quest") or generation_mentions(
                ctx, "quest", "order board"
            ):
                add(FarmQuestComponent(quest_id=resource_type, requested={resource_type: 1}))
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = GardenGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "GardenGenerationEnricher"]
