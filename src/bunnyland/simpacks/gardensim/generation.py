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


class GardenGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_room:
            if generation_wants(
                ctx, "bunnyland.gardensim.soil", "bunnyland.gardensim.garden-soil"
            ) or generation_mentions(ctx, "garden", "farm", "field"):
                add(SoilComponent(quality=1.2))
            if generation_wants(ctx, "bunnyland.gardensim.greenhouse") or generation_mentions(
                ctx, "greenhouse"
            ):
                add(GreenhouseComponent())
            if generation_wants(ctx, "bunnyland.gardensim.mine-level") or generation_mentions(
                ctx, "mine", "cavern"
            ):
                add(MineLevelComponent(level=1))
            if generation_wants(ctx, "bunnyland.gardensim.daily-farm-reset"):
                add(DailyFarmResetComponent(last_reset_epoch=ctx.world_epoch))
        elif ctx.is_character:
            resource_type = generation_resource_type(ctx)
            if generation_wants(ctx, "bunnyland.gardensim.gift-preference") or generation_mentions(
                ctx, "likes", "loves gifts"
            ):
                add(GiftPreferenceComponent(likes=(resource_type,)))
            if generation_wants(ctx, "bunnyland.gardensim.friendship") or generation_mentions(
                ctx, "friend"
            ):
                add(FriendshipComponent())
            if generation_wants(ctx, "bunnyland.gardensim.collection") or generation_mentions(
                ctx, "collection"
            ):
                add(CollectionComponent(entries=(resource_type,)))
        else:
            name = ctx.name
            crop_type = generation_crop_type(ctx)
            resource_type = generation_resource_type(ctx)
            if generation_wants(ctx, "bunnyland.gardensim.seed") or generation_mentions(
                ctx, "seed", "seeds"
            ):
                add(SeedComponent(crop_type=crop_type, growth_days=2.0, yield_item=crop_type))
            if generation_wants(ctx, "bunnyland.gardensim.tilled") or generation_mentions(
                ctx, "tilled soil"
            ):
                add(TilledComponent(tilled_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.gardensim.watered") or generation_mentions(
                ctx, "watered"
            ):
                add(
                    WateredComponent(
                        watered_at_epoch=ctx.world_epoch,
                        expires_at_epoch=ctx.world_epoch + 24 * 60 * 60,
                    )
                )
            if generation_wants(ctx, "bunnyland.gardensim.crop") or generation_mentions(
                ctx, "planted crop"
            ):
                add(CropComponent(crop_type=crop_type, planted_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.gardensim.crop-growth"):
                add(
                    CropGrowthComponent(
                        progress_days=0.0, required_days=2.0, last_updated_epoch=ctx.world_epoch
                    )
                )
            if generation_wants(ctx, "bunnyland.gardensim.harvestable") or generation_mentions(
                ctx, "harvestable"
            ):
                add(HarvestableComponent(yield_item=resource_type, ready=True))
            if generation_wants(ctx, "bunnyland.gardensim.fertilizer") or generation_mentions(
                ctx, "fertilizer", "compost"
            ):
                add(FertilizerComponent(kind="compost", growth_multiplier=1.2))
            if generation_wants(ctx, "bunnyland.gardensim.tree") or generation_mentions(
                ctx, "sapling", "tree"
            ):
                add(
                    TreeComponent(
                        tree_type=resource_type, planted_at_epoch=ctx.world_epoch, maturity_days=7.0
                    )
                )
            if generation_wants(ctx, "bunnyland.gardensim.tree-tap") or generation_mentions(
                ctx, "tree tap", "tapped tree"
            ):
                add(
                    TreeTapComponent(
                        tapped_at_epoch=ctx.world_epoch, last_collected_epoch=ctx.world_epoch
                    )
                )
            if generation_wants(ctx, "bunnyland.gardensim.crop-quality") or generation_mentions(
                ctx, "crop", "sprout"
            ):
                add(CropQualityComponent(quality=1.1))
            if generation_wants(ctx, "bunnyland.gardensim.regrowable") or generation_mentions(
                ctx, "regrow", "perennial"
            ):
                add(RegrowableComponent(regrow_days=2.0))
            if generation_wants(ctx, "bunnyland.gardensim.pest") or generation_mentions(
                ctx, "pest", "bugs"
            ):
                add(PestComponent(severity=0.5))
            if generation_wants(ctx, "bunnyland.gardensim.weed") or generation_mentions(
                ctx, "weed", "weeds"
            ):
                add(WeedComponent(density=0.5))
            if generation_wants(ctx, "bunnyland.gardensim.crop-inspection"):
                add(CropInspectionComponent(inspected_at_epoch=ctx.world_epoch, notes=ctx.intent))
            if generation_wants(ctx, "bunnyland.gardensim.machine") or generation_mentions(
                ctx, "machine", "preserves", "keg"
            ):
                add(MachineComponent(machine_type=resource_type))
            if generation_wants(
                ctx, "bunnyland.gardensim.machine-breakdown"
            ) or generation_mentions(ctx, "broken machine"):
                add(MachineBreakdownComponent(reason=ctx.intent or "worldgen"))
            if generation_wants(
                ctx, "bunnyland.gardensim.processing-recipe"
            ) or generation_mentions(ctx, "processing recipe"):
                add(
                    ProcessingRecipeComponent(
                        recipe_id=resource_type,
                        machine_type=resource_type,
                        inputs={resource_type: 1},
                        outputs={resource_type: 1},
                        duration_seconds=60,
                    )
                )
            if generation_wants(ctx, "bunnyland.gardensim.animal-home") or generation_mentions(
                ctx, "coop", "barn"
            ):
                add(AnimalHomeComponent())
            if generation_wants(ctx, "bunnyland.gardensim.farm-animal") or generation_mentions(
                ctx, "farm animal", "cow", "chicken"
            ):
                species = generation_animal_species(ctx)
                add(FarmAnimalComponent(species=species))
            if generation_wants(ctx, "bunnyland.gardensim.animal-product"):
                add(AnimalProductComponent(product_type=resource_type))
            if generation_wants(ctx, "bunnyland.gardensim.animal-breeding"):
                add(AnimalBreedingComponent(offspring_species=generation_animal_species(ctx)))
            if generation_wants(ctx, "bunnyland.gardensim.fishing-spot") or generation_mentions(
                ctx, "fishing spot", "pond"
            ):
                add(
                    FishingSpotComponent(
                        fish_type=generation_fish_type(ctx), season=generation_season(ctx)
                    )
                )
            if generation_wants(ctx, "bunnyland.gardensim.mining-node") or generation_mentions(
                ctx, "mining node", "ore node"
            ):
                add(MiningNodeComponent(resource_type=resource_type))
            if generation_wants(ctx, "bunnyland.gardensim.shipping-bin") or generation_mentions(
                ctx, "shipping bin", "shipping crate"
            ):
                add(ShippingBinComponent())
            if generation_wants(ctx, "bunnyland.gardensim.geode") or generation_mentions(
                ctx, "geode"
            ):
                add(GeodeComponent(resource_type=resource_type))
            if generation_wants(ctx, "bunnyland.gardensim.ladder") or generation_mentions(
                ctx, "ladder"
            ):
                add(LadderComponent(target_room_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.gardensim.forage") or generation_mentions(
                ctx, "forage"
            ):
                add(ForageComponent(resource_type=resource_type, seasons=(generation_season(ctx),)))
            if generation_wants(ctx, "bunnyland.gardensim.festival") or generation_mentions(
                ctx, "festival"
            ):
                add(FestivalComponent(name=name, season=generation_season(ctx)))
            if generation_wants(ctx, "bunnyland.gardensim.bundle") or generation_mentions(
                ctx, "bundle"
            ):
                add(BundleComponent(bundle_id=ctx.object_key, requirements={resource_type: 1}))
            if generation_wants(ctx, "bunnyland.gardensim.collection") or generation_mentions(
                ctx, "collection"
            ):
                add(CollectionComponent(entries=(resource_type,)))
            if generation_wants(
                ctx, "bunnyland.gardensim.museum-collection"
            ) or generation_mentions(ctx, "museum"):
                add(MuseumCollectionComponent())
            if generation_wants(ctx, "bunnyland.gardensim.reward") or generation_mentions(
                ctx, "reward"
            ):
                add(RewardComponent(resource_type=resource_type))
            if generation_wants(ctx, "bunnyland.gardensim.mail") or generation_mentions(
                ctx, "mail", "letter"
            ):
                add(MailComponent(subject=name))
            if generation_wants(ctx, "bunnyland.gardensim.farm-quest") or generation_mentions(
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
