"""Declarative dragonsim generation contributions."""

from ...core.generation import GenerationDelta, GenerationEdge, GenerationRequest, GenerationTarget
from ...worldgen.enrichment import (
    GenerationContext,
    generation_generated_id,
    generation_mentions,
    generation_resource_type,
    generation_wants,
)
from .mechanics import (
    AncientBeastComponent,
    ArtifactComponent,
    CarvableComponent,
    DiscoveryComponent,
    EncounterZoneComponent,
    FactionComponent,
    GreatSoulComponent,
    GuardsForFaction,
    HasStandingWithFaction,
    JailedByFaction,
    LockDifficultyComponent,
    LoreBookComponent,
    MagicComponent,
    MapMarkerComponent,
    PerkComponent,
    PersuasionComponent,
    PointOfInterestComponent,
    PotionComponent,
    PotionRecipeComponent,
    QuestComponent,
    QuestObjectiveComponent,
    QuestProvenanceComponent,
    QuestRewardComponent,
    QuestStateComponent,
    SneakingComponent,
    SpellComponent,
    SpellCooldownComponent,
    SurrenderComponent,
    VoiceInscriptionComponent,
    WantedByFaction,
    WordOfPowerComponent,
)
from .quests import QuestTemplateComponent

CAPABILITIES = (
    "bunnyland.dragonsim.ancient-beast",
    "bunnyland.dragonsim.artifact",
    "bunnyland.dragonsim.bounty",
    "bunnyland.dragonsim.carvable",
    "bunnyland.dragonsim.discovery",
    "bunnyland.dragonsim.encounter-zone",
    "bunnyland.dragonsim.faction",
    "bunnyland.dragonsim.faction-reputation",
    "bunnyland.dragonsim.great-soul",
    "bunnyland.dragonsim.generated-quest",
    "bunnyland.dragonsim.guard",
    "bunnyland.dragonsim.jail",
    "bunnyland.dragonsim.lock-difficulty",
    "bunnyland.dragonsim.locked",
    "bunnyland.dragonsim.lore-book",
    "bunnyland.dragonsim.magic",
    "bunnyland.dragonsim.map-marker",
    "bunnyland.dragonsim.perk",
    "bunnyland.dragonsim.persuasion",
    "bunnyland.dragonsim.point-of-interest",
    "bunnyland.dragonsim.potion",
    "bunnyland.dragonsim.potion-recipe",
    "bunnyland.dragonsim.quest",
    "bunnyland.dragonsim.quest-deadline",
    "bunnyland.dragonsim.quest-objective",
    "bunnyland.dragonsim.quest-reward",
    "bunnyland.dragonsim.quest-template",
    "bunnyland.dragonsim.quest-stage",
    "bunnyland.dragonsim.spell",
    "bunnyland.dragonsim.spell-cooldown",
    "bunnyland.dragonsim.stealth",
    "bunnyland.dragonsim.surrender",
    "bunnyland.dragonsim.voice-inscription",
    "bunnyland.dragonsim.wanted",
    "bunnyland.dragonsim.word-of-power",
)


class DragonGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}
        edges = []

        def add(component):
            components[type(component)] = component

        if ctx.is_character:
            name = ctx.name
            if generation_wants(ctx, "bunnyland.dragonsim.faction-reputation"):
                faction_id = request.context.get("faction_id")
                if faction_id:
                    edges.append(
                        GenerationEdge(HasStandingWithFaction(), GenerationTarget(str(faction_id)))
                    )
            if generation_wants(ctx, "bunnyland.dragonsim.guard") or generation_mentions(
                ctx, "guard"
            ):
                faction_id = request.context.get("faction_id")
                if faction_id:
                    edges.append(
                        GenerationEdge(GuardsForFaction(), GenerationTarget(str(faction_id)))
                    )
            if generation_wants(ctx, "bunnyland.dragonsim.jail"):
                faction_id = request.context.get("faction_id")
                if faction_id:
                    edges.append(
                        GenerationEdge(
                            JailedByFaction(release_epoch=ctx.world_epoch),
                            GenerationTarget(str(faction_id)),
                        )
                    )
            if generation_wants(ctx, "bunnyland.dragonsim.great-soul"):
                add(GreatSoulComponent(souls=1))
            if generation_wants(ctx, "bunnyland.dragonsim.stealth") or generation_mentions(
                ctx, "sneak", "stealthy"
            ):
                add(SneakingComponent(sneaking=True, since_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.dragonsim.wanted", "bunnyland.dragonsim.bounty"):
                faction_id = request.context.get("faction_id")
                if faction_id:
                    edges.append(
                        GenerationEdge(
                            WantedByFaction(amount=10), GenerationTarget(str(faction_id))
                        )
                    )
            if generation_wants(ctx, "bunnyland.dragonsim.magic"):
                add(MagicComponent(last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.dragonsim.spell-cooldown"):
                add(SpellCooldownComponent(ready_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.dragonsim.persuasion"):
                add(PersuasionComponent(disposition=1))
            if generation_wants(ctx, "bunnyland.dragonsim.surrender"):
                add(SurrenderComponent(reason=ctx.intent or name, at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.dragonsim.ancient-beast") or generation_mentions(
                ctx, "ancient beast"
            ):
                add(AncientBeastComponent(name=name))
        else:
            name = ctx.name
            if generation_wants(
                ctx, "bunnyland.dragonsim.point-of-interest"
            ) or generation_mentions(ctx, "landmark", "shrine", "ruin"):
                add(PointOfInterestComponent(location_type=ctx.entity_kind))
            if generation_wants(ctx, "bunnyland.dragonsim.discovery"):
                add(DiscoveryComponent(first_discovered_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.dragonsim.map-marker") or generation_mentions(
                ctx, "map marker"
            ):
                add(MapMarkerComponent(label=name, marker_type=ctx.entity_kind))
            if generation_wants(ctx, "bunnyland.dragonsim.encounter-zone") or generation_mentions(
                ctx, "encounter zone"
            ):
                add(EncounterZoneComponent(zone_type=ctx.entity_kind))
            if generation_wants(ctx, "bunnyland.dragonsim.faction") or generation_mentions(
                ctx, "faction", "guild", "clan"
            ):
                add(FactionComponent(name=name))
            if generation_wants(ctx, "bunnyland.dragonsim.quest"):
                add(
                    QuestComponent(
                        quest_id=ctx.entity_key, title=name, description=ctx.intent or name
                    )
                )
                add(QuestStateComponent())
            if generation_wants(ctx, "bunnyland.dragonsim.quest-stage"):
                add(QuestStateComponent())
            if generation_wants(ctx, "bunnyland.dragonsim.quest-objective"):
                add(QuestObjectiveComponent(description=ctx.intent or name))
            if generation_wants(ctx, "bunnyland.dragonsim.quest-reward"):
                add(QuestRewardComponent(description=ctx.intent or name))
            if generation_wants(ctx, "bunnyland.dragonsim.guard") or generation_mentions(
                ctx, "guard"
            ):
                faction_id = request.context.get("faction_id")
                if faction_id:
                    edges.append(
                        GenerationEdge(GuardsForFaction(), GenerationTarget(str(faction_id)))
                    )
            if generation_wants(ctx, "bunnyland.dragonsim.perk"):
                add(PerkComponent(name=name, skill_name=generation_resource_type(ctx)))
            if generation_wants(ctx, "bunnyland.dragonsim.ancient-beast") or generation_mentions(
                ctx, "ancient beast"
            ):
                add(AncientBeastComponent(name=name))
            if generation_wants(ctx, "bunnyland.dragonsim.word-of-power") or generation_mentions(
                ctx, "word of power"
            ):
                add(WordOfPowerComponent(name=name))
            if generation_wants(
                ctx, "bunnyland.dragonsim.lock-difficulty", "bunnyland.dragonsim.locked"
            ):
                add(LockDifficultyComponent(difficulty=2))
            if generation_wants(ctx, "bunnyland.dragonsim.lore-book") or generation_mentions(
                ctx, "lore book", "manual"
            ):
                add(LoreBookComponent(title=name, lore=ctx.intent or name))
            if generation_wants(ctx, "bunnyland.dragonsim.spell"):
                add(SpellComponent(name=name, effect=ctx.intent or name))
            if generation_wants(ctx, "bunnyland.dragonsim.potion-recipe"):
                add(PotionRecipeComponent(name=name, potion_name=f"{name} potion"))
            if generation_wants(ctx, "bunnyland.dragonsim.potion"):
                add(PotionComponent(name=name, effect=ctx.intent or name))
            if generation_wants(ctx, "bunnyland.dragonsim.artifact") or generation_mentions(
                ctx, "artifact"
            ):
                add(ArtifactComponent(name=name, effect=ctx.intent or name))
            if generation_wants(ctx, "bunnyland.dragonsim.carvable"):
                add(CarvableComponent(remaining_space=24))
            if generation_wants(ctx, "bunnyland.dragonsim.voice-inscription"):
                add(
                    VoiceInscriptionComponent(
                        word_id=generation_generated_id(ctx, "word"), phrase=ctx.intent or name
                    )
                )
        return GenerationDelta(
            components=tuple(components.values()),
            edges=tuple(edges),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


class GeneratedQuestGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_room:
            pass
        elif ctx.is_character:
            pass
        else:
            name = ctx.name
            if generation_wants(ctx, "bunnyland.dragonsim.quest-template"):
                add(
                    QuestTemplateComponent(
                        title=name, objective=ctx.intent or name, reward_item_name="coin"
                    )
                )
            if generation_wants(ctx, "bunnyland.dragonsim.generated-quest"):
                add(
                    QuestComponent(
                        quest_id=ctx.entity_key, title=name, description=ctx.intent or name
                    )
                )
                add(QuestStateComponent())
                add(
                    QuestProvenanceComponent(
                        generator="bunnyland.dragonsim", generated_at_epoch=ctx.world_epoch
                    )
                )
            if generation_wants(ctx, "bunnyland.dragonsim.quest-deadline"):
                add(QuestStateComponent(due_at_epoch=ctx.world_epoch + 86400))
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = DragonGenerationEnricher()
GENERATED_QUEST_ENRICHER = GeneratedQuestGenerationEnricher()

__all__ = [
    "GENERATION_ENRICHER",
    "DragonGenerationEnricher",
    "GENERATED_QUEST_ENRICHER",
    "GeneratedQuestGenerationEnricher",
]
