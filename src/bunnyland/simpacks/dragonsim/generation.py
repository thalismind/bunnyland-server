"""Declarative dragonsim generation contributions."""

from ...core.generation import GenerationDelta, GenerationRequest
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
    FactionReputationComponent,
    GreatSoulComponent,
    GuardComponent,
    JailComponent,
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
    WantedComponent,
    WordOfPowerComponent,
)
from .quests import CureQuestHookComponent, QuestTemplateComponent

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
    "bunnyland.dragonsim.quest-objective",
    "bunnyland.dragonsim.quest-reward",
    "bunnyland.dragonsim.quest-stage",
    "bunnyland.dragonsim.spell",
    "bunnyland.dragonsim.spell-cooldown",
    "bunnyland.dragonsim.stealth",
    "bunnyland.dragonsim.surrender",
    "bunnyland.dragonsim.voice-inscription",
    "bunnyland.dragonsim.wanted",
    "bunnyland.dragonsim.word-of-power",
)

ALIASES = {
    "ancient-beast": "bunnyland.dragonsim.ancient-beast",
    "artifact": "bunnyland.dragonsim.artifact",
    "bounty": "bunnyland.dragonsim.bounty",
    "carvable": "bunnyland.dragonsim.carvable",
    "discovery": "bunnyland.dragonsim.discovery",
    "encounter-zone": "bunnyland.dragonsim.encounter-zone",
    "faction": "bunnyland.dragonsim.faction",
    "faction-reputation": "bunnyland.dragonsim.faction-reputation",
    "great-soul": "bunnyland.dragonsim.great-soul",
    "guard": "bunnyland.dragonsim.guard",
    "jail": "bunnyland.dragonsim.jail",
    "lock-difficulty": "bunnyland.dragonsim.lock-difficulty",
    "locked": "bunnyland.dragonsim.locked",
    "lore-book": "bunnyland.dragonsim.lore-book",
    "magic": "bunnyland.dragonsim.magic",
    "map-marker": "bunnyland.dragonsim.map-marker",
    "perk": "bunnyland.dragonsim.perk",
    "persuasion": "bunnyland.dragonsim.persuasion",
    "point-of-interest": "bunnyland.dragonsim.point-of-interest",
    "potion": "bunnyland.dragonsim.potion",
    "potion-recipe": "bunnyland.dragonsim.potion-recipe",
    "quest": "bunnyland.dragonsim.quest",
    "quest-objective": "bunnyland.dragonsim.quest-objective",
    "quest-reward": "bunnyland.dragonsim.quest-reward",
    "quest-stage": "bunnyland.dragonsim.quest-stage",
    "spell": "bunnyland.dragonsim.spell",
    "spell-cooldown": "bunnyland.dragonsim.spell-cooldown",
    "stealth": "bunnyland.dragonsim.stealth",
    "surrender": "bunnyland.dragonsim.surrender",
    "voice-inscription": "bunnyland.dragonsim.voice-inscription",
    "wanted": "bunnyland.dragonsim.wanted",
    "word-of-power": "bunnyland.dragonsim.word-of-power",
}


class DragonGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_character:
            name = ctx.name
            if generation_wants(ctx, "faction-reputation"):
                add(FactionReputationComponent(scores={}))
            if generation_wants(ctx, "guard") or generation_mentions(ctx, "guard"):
                add(GuardComponent(faction_id=generation_generated_id(ctx, "faction")))
            if generation_wants(ctx, "jail"):
                add(
                    JailComponent(
                        faction_id=generation_generated_id(ctx, "faction"),
                        release_epoch=ctx.world_epoch,
                    )
                )
            if generation_wants(ctx, "great-soul"):
                add(GreatSoulComponent(souls=1))
            if generation_wants(ctx, "stealth") or generation_mentions(ctx, "sneak", "stealthy"):
                add(SneakingComponent(sneaking=True, since_epoch=ctx.world_epoch))
            if generation_wants(ctx, "wanted", "bounty"):
                add(WantedComponent(amounts={generation_generated_id(ctx, "faction"): 10}))
            if generation_wants(ctx, "magic"):
                add(MagicComponent(last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "spell-cooldown"):
                add(SpellCooldownComponent(ready_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "persuasion"):
                add(PersuasionComponent(disposition=1))
            if generation_wants(ctx, "surrender"):
                add(SurrenderComponent(reason=ctx.intent or name, at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "ancient-beast") or generation_mentions(ctx, "ancient beast"):
                add(AncientBeastComponent(name=name))
        else:
            name = ctx.name
            if generation_wants(ctx, "point-of-interest") or generation_mentions(
                ctx, "landmark", "shrine", "ruin"
            ):
                add(PointOfInterestComponent(location_type=ctx.entity_kind))
            if generation_wants(ctx, "discovery"):
                add(DiscoveryComponent(first_discovered_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "map-marker") or generation_mentions(ctx, "map marker"):
                add(MapMarkerComponent(label=name, marker_type=ctx.entity_kind))
            if generation_wants(ctx, "encounter-zone") or generation_mentions(
                ctx, "encounter zone"
            ):
                add(EncounterZoneComponent(zone_type=ctx.entity_kind))
            if generation_wants(ctx, "faction") or generation_mentions(
                ctx, "faction", "guild", "clan"
            ):
                add(FactionComponent(name=name))
            if generation_wants(ctx, "quest"):
                add(
                    QuestComponent(
                        quest_id=ctx.entity_key, title=name, description=ctx.intent or name
                    )
                )
                add(QuestStateComponent())
            if generation_wants(ctx, "quest-stage"):
                add(QuestStateComponent())
            if generation_wants(ctx, "quest-objective"):
                add(QuestObjectiveComponent(description=ctx.intent or name))
            if generation_wants(ctx, "quest-reward"):
                add(QuestRewardComponent(description=ctx.intent or name))
            if generation_wants(ctx, "guard") or generation_mentions(ctx, "guard"):
                add(GuardComponent(faction_id=generation_generated_id(ctx, "faction")))
            if generation_wants(ctx, "jail") or generation_mentions(ctx, "jail"):
                add(
                    JailComponent(
                        faction_id=generation_generated_id(ctx, "faction"),
                        release_epoch=ctx.world_epoch,
                    )
                )
            if generation_wants(ctx, "perk"):
                add(PerkComponent(name=name, skill_name=generation_resource_type(ctx)))
            if generation_wants(ctx, "ancient-beast") or generation_mentions(ctx, "ancient beast"):
                add(AncientBeastComponent(name=name))
            if generation_wants(ctx, "word-of-power") or generation_mentions(ctx, "word of power"):
                add(WordOfPowerComponent(name=name))
            if generation_wants(ctx, "lock-difficulty", "locked"):
                add(LockDifficultyComponent(difficulty=2))
            if generation_wants(ctx, "lore-book") or generation_mentions(
                ctx, "lore book", "manual"
            ):
                add(LoreBookComponent(title=name, lore=ctx.intent or name))
            if generation_wants(ctx, "spell"):
                add(SpellComponent(name=name, effect=ctx.intent or name))
            if generation_wants(ctx, "potion-recipe"):
                add(PotionRecipeComponent(name=name, potion_name=f"{name} potion"))
            if generation_wants(ctx, "potion"):
                add(PotionComponent(name=name, effect=ctx.intent or name))
            if generation_wants(ctx, "artifact") or generation_mentions(ctx, "artifact"):
                add(ArtifactComponent(name=name, effect=ctx.intent or name))
            if generation_wants(ctx, "carvable"):
                add(CarvableComponent(remaining_space=24))
            if generation_wants(ctx, "voice-inscription"):
                add(
                    VoiceInscriptionComponent(
                        word_id=generation_generated_id(ctx, "word"), phrase=ctx.intent or name
                    )
                )
        return GenerationDelta(
            components=tuple(components.values()),
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
            if generation_wants(ctx, "cure-quest-hook"):
                add(CureQuestHookComponent(affliction_type=ctx.intent or "worldgen"))
        else:
            name = ctx.name
            if generation_wants(ctx, "quest-template"):
                add(
                    QuestTemplateComponent(
                        title=name, objective=ctx.intent or name, reward_item_name="coin"
                    )
                )
            if generation_wants(ctx, "generated-quest"):
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
            if generation_wants(ctx, "quest-deadline"):
                add(QuestStateComponent(due_at_epoch=ctx.world_epoch + 86400))
            if generation_wants(ctx, "dagger-quest-reward"):
                add(QuestRewardComponent(description=name))
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
