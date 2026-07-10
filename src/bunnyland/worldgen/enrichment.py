"""World-generation enrichment hooks contributed by built-in plugins.

These hooks keep the core generator mostly ignorant of sim-pack schemas. Generated
entities expose semantic ``wants``, tags, and intent text; each enabled plugin decides
which of its own components to attach.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.components import IdentityComponent
from ..core.ecs import parse_entity_id, replace_component
from ..core.events import CharacterGeneratedEvent, ObjectGeneratedEvent, RoomGeneratedEvent
from ..mechanics.barbariansim import (
    ArmorComponent,
    BaseClaimComponent,
    BlessingComponent,
    BossComponent,
    BuildingComponent,
    ClimbingGateComponent,
    ClimbingSkillComponent,
    CorruptionComponent,
    CurseComponent,
    DangerZoneComponent,
    DurabilityComponent,
    FortificationComponent,
    KeyComponent,
    PoisonComponent,
    PurgeWaveComponent,
    RitualComponent,
    ShelterComponent,
    ShrineComponent,
    SiegeReadinessComponent,
    StaminaComponent,
    SurvivalGapComponent,
    TemperatureExposureComponent,
    TemperatureResistanceComponent,
    TrapComponent,
    TreasureComponent,
    WeaponComponent,
)
from ..mechanics.colonysim import (
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
from ..mechanics.daggersim import (
    AfflictionStigmaComponent,
    AutomapComponent,
    BankComponent,
    BountyComponent,
    CampingComponent,
    ClassTemplateComponent,
    ConversationToneComponent,
    CreatureLanguageComponent,
    CureQuestHookComponent,
    CustomClassComponent,
    CustomSpellComponent,
    DaggerQuestRewardComponent,
    DialogueApproachComponent,
    DungeonComponent,
    DungeonObjectiveComponent,
    DungeonRoomComponent,
    EnchantedItemComponent,
    EtiquetteSkillComponent,
    ExpansionHookComponent,
    FeedingNeedComponent,
    GeneratedQuestComponent,
    HostilityComponent,
    IngredientComponent,
    InstitutionComponent,
    InstitutionDuesComponent,
    InstitutionReputationComponent,
    InstitutionServiceComponent,
    LanguageSkillComponent,
    LawRegionComponent,
    LegalReputationComponent,
    LodgingComponent,
    PotionMakerComponent,
    ProceduralSiteComponent,
    PropertyDeedComponent,
    QuestDeadlineComponent,
    QuestTemplateComponent,
    RecallAnchorComponent,
    RechargeServiceComponent,
    RegionalReputationComponent,
    RestRiskComponent,
    RumorComponent,
    RumorReliabilityComponent,
    RumorSourceComponent,
    RumorTargetComponent,
    SecretDoorComponent,
    ServiceAccessComponent,
    SocialRegisterComponent,
    SpellTemplateComponent,
    StreetwiseSkillComponent,
    SupernaturalAfflictionComponent,
    TravelHubComponent,
    TravelInterruptionComponent,
    TravelModeComponent,
    TravelSupplyComponent,
    UnrealizedLocationComponent,
)
from ..mechanics.dinosim import (
    AncientSampleComponent,
    ApexPredatorComponent,
    ArmorPlateComponent,
    BaitComponent,
    BoneComponent,
    ChargeComponent,
    CreatureAttackComponent,
    CreatureNeedComponent,
    CreatureProductComponent,
    DinosaurComponent,
    EggComponent,
    EnclosureComponent,
    EscapeRiskComponent,
    FertilityComponent,
    FossilFragmentComponent,
    FossilSurveyComponent,
    HerdComponent,
    HideComponent,
    KaijuComponent,
    NestComponent,
    RoarComponent,
    ScentComponent,
    SpeciesComponent,
    TerritoryComponent,
    ToxinComponent,
    TrackComponent,
    TrampleComponent,
    TranquilizerComponent,
    WaterCreatureComponent,
    WeakPointComponent,
)
from ..mechanics.dragonsim import (
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
    QuestRewardComponent,
    QuestStageComponent,
    SpellComponent,
    SpellCooldownComponent,
    StealthComponent,
    SurrenderComponent,
    VoiceInscriptionComponent,
    WantedComponent,
    WordOfPowerComponent,
)
from ..mechanics.environment import FireComponent, FlammableComponent
from ..mechanics.gardensim import (
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
from ..mechanics.lifesim import (
    AspirationComponent,
    BillComponent,
    BusinessOwnerComponent,
    CareerComponent,
    CharacterProfileComponent,
    CustomerComponent,
    HomeComponent,
    HomeObjectComponent,
    HouseholdComponent,
    JobScheduleComponent,
    ReproductiveComponent,
    ReputationComponent,
    RoomClaimComponent,
    RoutineComponent,
    SkillSetComponent,
    WhimComponent,
)
from ..mechanics.neonsim import (
    AccessLevelComponent,
    AugmentationSlotsComponent,
    BlackMarketComponent,
    CameraComponent,
    CheckpointComponent,
    ClinicComponent,
    CyberpunkSiteComponent,
    DataBrokerComponent,
    DeviceComponent,
    FixerComponent,
    HackableComponent,
    RestrictedAreaComponent,
    RunnerContractComponent,
    SafehouseComponent,
    SecurityZoneComponent,
    SurveillanceCoverageComponent,
)
from ..mechanics.nukesim import (
    BeaconComponent,
    ChemComponent,
    ChemRecipeComponent,
    DecontaminationComponent,
    FactionSalvageComponent,
    FieldRepairComponent,
    GeneratorComponent,
    HotspotMarkerComponent,
    ItemModComponent,
    JunkComponent,
    LockedCrateComponent,
    LootTableComponent,
    MutationComponent,
    MutationResistanceComponent,
    MutationThresholdComponent,
    OldWorldTechComponent,
    RadiationDoseComponent,
    RadiationSourceComponent,
    RadMedicineComponent,
    RadProtectionComponent,
    RaiderPressureComponent,
    SampleComponent,
    ScavengeSiteComponent,
    SchematicComponent,
    SettlementComponent,
    SettlementSalvageComponent,
    SuppressantComponent,
    TechLeadComponent,
    TerminalComponent,
    TraderRouteComponent,
    WastelandArtifactComponent,
    WaterPurifierComponent,
    WaterPurityComponent,
)
from ..mechanics.voidsim import (
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

if TYPE_CHECKING:
    from relics import Entity

    from ..core.events import GeneratedEntityEvent
    from ..core.world_actor import WorldActor

_RESOURCE_TYPES = (
    "wood",
    "stone",
    "metal",
    "ore",
    "food",
    "water",
    "fuel",
    "scrap",
    "medicine",
    "bone",
    "hide",
    "sap",
)

_DEFAULT_EXPANSION_GENERATOR = "worldgen.recursive"


def _entity(actor: WorldActor, event: GeneratedEntityEvent) -> Entity | None:
    entity_id = parse_entity_id(event.entity_id)
    if entity_id is None or not actor.world.has_entity(entity_id):
        return None
    return actor.world.get_entity(entity_id)


def _text(event: GeneratedEntityEvent) -> str:
    generation = event.generation
    return " ".join(
        (
            event.entity_kind,
            generation.description,
            *generation.tags,
            *generation.wants,
            *generation.needs,
        )
    ).casefold()


def _wants(event: GeneratedEntityEvent, *names: str) -> bool:
    wanted = {want.casefold() for want in (*event.generation.wants, *event.generation.needs)}
    return any(name.casefold() in wanted for name in names)


def _mentions(event: GeneratedEntityEvent, *terms: str) -> bool:
    text = _text(event)
    return any(term.casefold() in text for term in terms)


def _name(entity: Entity, fallback: str) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return fallback


def _resource_type(event: GeneratedEntityEvent) -> str:
    text = _text(event)
    for resource_type in _RESOURCE_TYPES:
        if resource_type in text:
            return resource_type
    return "scrap"


def _crop_type(event: GeneratedEntityEvent) -> str:
    text = _text(event)
    for suffix in (" seeds", " seed"):
        if suffix in text:
            return text.split(suffix, 1)[0].rsplit(" ", 1)[-1] or "turnip"
    return "turnip"


def _expansion_trigger(event: GeneratedEntityEvent) -> str:
    if _wants(event, "rumor"):
        return "rumor"
    if _wants(event, "quest"):
        return "quest"
    return "worldgen"


def _orbital_body_type(event: GeneratedEntityEvent) -> str:
    text = _text(event)
    if "moon" in text:
        return "moon"
    if "asteroid" in text:
        return "asteroid-belt"
    if "station" in text:
        return "station"
    return "planet"


def _generated_id(event: GeneratedEntityEvent, suffix: str) -> str:
    return f"generated-{event.entity_key}-{suffix}"


def _trade_faction(event: GeneratedEntityEvent) -> str:
    if _mentions(event, "trader"):
        return "generated-trader"
    if _mentions(event, "faction"):
        return "generated-faction"
    return "generated-colony"


def _animal_species(event: GeneratedEntityEvent) -> str:
    text = _text(event)
    for species in ("chicken", "cow", "goat", "sheep", "duck", "rabbit"):
        if species in text:
            return species
    return event.entity_kind if event.entity_kind != "object" else "animal"


def _fish_type(event: GeneratedEntityEvent) -> str:
    text = _text(event)
    for fish_type in ("trout", "bass", "catfish", "salmon", "carp"):
        if fish_type in text:
            return fish_type
    return "trout"


def _season(event: GeneratedEntityEvent) -> str:
    text = _text(event)
    for season in ("spring", "summer", "autumn", "winter"):
        if season in text:
            return season
    return "spring"


class EnvironmentWorldgenHook:
    def _on_entity(self, event: RoomGeneratedEvent | ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "flammable", "fuel") or _mentions(
            event, "wood", "paper", "cloth", "grass", "forest", "brush", "fuel"
        ):
            replace_component(entity, FlammableComponent(fuel=8.0))
        if _wants(event, "fire", "burning"):
            replace_component(entity, FireComponent(last_updated_epoch=event.world_epoch))


class LifeWorldgenHook:
    def _on_room(self, event: RoomGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "home"):
            replace_component(
                entity,
                HomeComponent(
                    owner_id=_generated_id(event, "owner"),
                    household_id=_generated_id(event, "household"),
                ),
            )
        if _wants(event, "room-claim"):
            replace_component(
                entity,
                RoomClaimComponent(
                    claimed_by_id=_generated_id(event, "claimant"),
                    claimed_at_epoch=event.world_epoch,
                ),
            )

    def _on_character(self, event: CharacterGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "profile", "character-profile") or _mentions(
            event, "routine", "interest", "hobby", "backstory"
        ):
            replace_component(
                entity,
                CharacterProfileComponent(
                    traits=tuple(event.generation.tags),
                    interests=tuple(event.generation.wants),
                    preferred_routine="generated routine" if _mentions(event, "routine") else "",
                ),
            )
        if _wants(event, "aspiration") or _mentions(event, "aspiration", "life goal"):
            replace_component(
                entity,
                AspirationComponent(
                    name=event.intent or "generated aspiration",
                    milestones=tuple(event.generation.tags),
                ),
            )
        if _wants(event, "career") or _mentions(event, "career", "job"):
            replace_component(entity, CareerComponent(title=event.intent or "Generated Career"))
        if _wants(event, "job-schedule") or _mentions(event, "shift", "schedule"):
            replace_component(entity, JobScheduleComponent(next_shift_epoch=event.world_epoch))
        if _wants(event, "customer") or _mentions(event, "customer", "shopper"):
            replace_component(entity, CustomerComponent())
        if _wants(event, "household") or _mentions(event, "household", "family"):
            replace_component(
                entity,
                HouseholdComponent(
                    household_id=_generated_id(event, "household"),
                    name=event.intent or _name(entity, event.entity_key),
                ),
            )
        if _wants(event, "routine") or _mentions(event, "daily routine"):
            replace_component(
                entity,
                RoutineComponent(
                    activity=event.intent or "generated routine",
                    next_due_epoch=event.world_epoch,
                ),
            )
        if _wants(event, "reputation") or _mentions(event, "known for", "famous"):
            replace_component(entity, ReputationComponent(known_for=tuple(event.generation.tags)))
        if _wants(event, "skill-set") or _mentions(event, "skill", "skilled"):
            resource_type = _resource_type(event)
            replace_component(
                entity,
                SkillSetComponent(levels={resource_type: 1}, xp={resource_type: 0.0}),
            )
        if _wants(event, "reproductive") or _mentions(event, "fertile"):
            replace_component(entity, ReproductiveComponent(species_group=event.species))

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.object_key)
        if _wants(event, "whim") or _mentions(event, "whim", "wish"):
            replace_component(entity, WhimComponent(want=name))
        if _wants(event, "home-object") or _mentions(
            event, "chair", "bed", "stove", "sofa", "decor", "home"
        ):
            replace_component(entity, HomeObjectComponent(affordance="comfort", decor_score=1.0))
        if _wants(event, "bill") or _mentions(event, "bill", "rent", "tax"):
            replace_component(entity, BillComponent(amount=10, reason=event.intent or name))
        if _wants(event, "business-owner") or _mentions(event, "business", "shop", "stall"):
            replace_component(entity, BusinessOwnerComponent(name=name))


class ColonyWorldgenHook:
    def _on_room(self, event: RoomGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "stockpile") or _mentions(event, "stockpile", "warehouse"):
            replace_component(entity, StockpileComponent(capacity=40))
        if _wants(event, "room-role") or _mentions(event, "barracks", "clinic", "dining room"):
            replace_component(entity, RoomRoleComponent(role=event.biome or "room"))
        if _wants(event, "room-stat") or _mentions(event, "beautiful", "clean", "comfortable"):
            replace_component(
                entity,
                RoomStatComponent(beauty=1.0, cleanliness=1.0, comfort=1.0, wealth=25.0),
            )
        if _wants(event, "room-quality") or _mentions(event, "impressive", "quality room"):
            replace_component(
                entity,
                RoomQualityComponent(
                    role=event.biome or "room",
                    beauty=1.0,
                    cleanliness=1.0,
                    comfort=1.0,
                    impressiveness=3.0,
                    updated_at_epoch=event.world_epoch,
                ),
            )
        if _wants(event, "colony-wealth") or _mentions(event, "colony wealth", "wealth"):
            replace_component(
                entity,
                ColonyWealthComponent(
                    wealth=100.0,
                    expectations="low",
                    updated_at_epoch=event.world_epoch,
                ),
            )

    def _on_character(self, event: CharacterGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "pawn-profile") or _mentions(event, "backstory", "passion"):
            replace_component(
                entity,
                PawnProfileComponent(
                    backstory=event.generation.description,
                    passions={tag: 1 for tag in event.generation.tags},
                ),
            )
        if _wants(event, "prisoner", "captive") or _mentions(event, "prisoner", "captive"):
            replace_component(entity, PrisonerComponent(policy="hold"))
        if _wants(event, "work-priority") or _mentions(event, "work priority"):
            replace_component(entity, WorkPriorityComponent(priorities={_resource_type(event): 1}))
        if _wants(event, "work-capability") or _mentions(event, "capable", "disabled work"):
            replace_component(
                entity,
                WorkCapabilityComponent(skill_levels={_resource_type(event): 1}),
            )
        if _wants(event, "allowed-area") or _mentions(event, "allowed area"):
            replace_component(entity, AllowedAreaComponent(room_ids=()))
        if _wants(event, "bed-rest") or _mentions(event, "bed rest"):
            replace_component(entity, BedRestComponent(started_at_epoch=event.world_epoch))
        if _wants(event, "infection") or _mentions(event, "infection", "infected"):
            replace_component(
                entity,
                InfectionComponent(severity=0.1, last_updated_epoch=event.world_epoch),
            )
        if _wants(event, "mental-state") or _mentions(event, "mental state", "inspired"):
            replace_component(
                entity,
                MentalStateComponent(state="inspired", reason=event.intent or "worldgen"),
            )

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.object_key)
        resource_type = _resource_type(event)
        if _wants(event, "resource-node") or _mentions(event, "vein", "deposit", "patch"):
            replace_component(
                entity,
                ResourceNodeComponent(resource_type=resource_type, current=5, maximum=5),
            )
        if _wants(event, "resource-stack") or _mentions(event, "stack", "pile of"):
            replace_component(
                entity,
                ResourceStackComponent(resource_type=resource_type, quantity=5),
            )
        if _wants(event, "stockpile"):
            replace_component(entity, StockpileComponent(capacity=20))
        if _wants(event, "storage-filter") or _mentions(event, "storage filter"):
            replace_component(entity, StorageFilterComponent(allowed_types=(resource_type,)))
        if _wants(event, "haulable") or _mentions(event, "haulable"):
            replace_component(entity, HaulableComponent(priority=1))
        if _wants(event, "forbidden") or _mentions(event, "forbidden"):
            replace_component(entity, ForbiddenComponent())
        if _wants(event, "workstation") or _mentions(event, "workbench", "forge", "bench"):
            replace_component(entity, WorkstationComponent(station_type=resource_type))
        if _wants(event, "recipe") or _mentions(event, "recipe"):
            replace_component(
                entity,
                RecipeComponent(
                    recipe_id=resource_type,
                    inputs={resource_type: 1},
                    outputs={resource_type: 1},
                ),
            )
        if _wants(event, "job"):
            replace_component(entity, JobComponent(job_type=resource_type, priority=1))
        if _wants(event, "job-bill") or _mentions(event, "bill", "work order"):
            replace_component(entity, JobBillComponent(recipe_id=resource_type, work_required=5.0))
        if _wants(event, "research") or _mentions(event, "research", "technology"):
            replace_component(
                entity,
                ResearchProjectComponent(project_id=resource_type, work_required=10.0),
            )
        if _wants(event, "incident") or _mentions(event, "incident", "raid", "blight"):
            replace_component(entity, ColonyIncidentComponent(incident_type=resource_type))
        if _wants(event, "trade-offer") or _mentions(event, "trade", "trader"):
            replace_component(
                entity,
                TradeOfferComponent(faction_id="generated-faction", gives={resource_type: 1}),
            )
        if _wants(event, "surgery") or _mentions(event, "surgery", "operation"):
            replace_component(entity, SurgeryBillComponent(part="torso", operation=resource_type))
        if _wants(event, "body-part") or _mentions(event, "body part", "limb"):
            replace_component(entity, BodyPartHealthComponent(part=resource_type))
        if _wants(event, "tech-unlock") or _mentions(event, "unlocked tech"):
            replace_component(
                entity,
                TechUnlockComponent(tech_id=resource_type, unlocked_at_epoch=event.world_epoch),
            )
        if _wants(event, "faction-relation") or _mentions(event, "faction relation"):
            replace_component(
                entity,
                FactionRelationComponent(faction_id=_trade_faction(event), goodwill=1.0),
            )
        if _wants(event, "caravan") or _mentions(event, "caravan"):
            replace_component(
                entity,
                CaravanComponent(
                    destination=event.intent or name,
                    departed_at_epoch=event.world_epoch,
                ),
            )
        if _wants(event, "medicine") or _mentions(event, "medicine", "medkit"):
            replace_component(entity, MedicineComponent(quality=1.0, uses=1))
        if _wants(event, "medical-bed") or _mentions(event, "clinic bed", "medical bed"):
            replace_component(entity, MedicalBedComponent())
        if _wants(event, "prosthetic") or _mentions(event, "prosthetic"):
            replace_component(entity, ProstheticComponent(part=resource_type))


class GardenWorldgenHook:
    def _on_room(self, event: RoomGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "soil", "garden-soil") or _mentions(event, "garden", "farm", "field"):
            replace_component(entity, SoilComponent(quality=1.2))
        if _wants(event, "greenhouse") or _mentions(event, "greenhouse"):
            replace_component(entity, GreenhouseComponent())
        if _wants(event, "mine-level") or _mentions(event, "mine", "cavern"):
            replace_component(entity, MineLevelComponent(level=1))
        if _wants(event, "daily-farm-reset"):
            replace_component(entity, DailyFarmResetComponent(last_reset_epoch=event.world_epoch))

    def _on_character(self, event: CharacterGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        resource_type = _resource_type(event)
        if _wants(event, "gift-preference") or _mentions(event, "likes", "loves gifts"):
            replace_component(entity, GiftPreferenceComponent(likes=(resource_type,)))
        if _wants(event, "friendship") or _mentions(event, "friend"):
            replace_component(entity, FriendshipComponent())
        if _wants(event, "collection") or _mentions(event, "collection"):
            replace_component(entity, CollectionComponent(entries=(resource_type,)))

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.object_key)
        crop_type = _crop_type(event)
        resource_type = _resource_type(event)
        if _wants(event, "seed") or _mentions(event, "seed", "seeds"):
            replace_component(
                entity,
                SeedComponent(crop_type=crop_type, growth_days=2.0, yield_item=crop_type),
            )
        if _wants(event, "tilled") or _mentions(event, "tilled soil"):
            replace_component(entity, TilledComponent(tilled_at_epoch=event.world_epoch))
        if _wants(event, "watered") or _mentions(event, "watered"):
            replace_component(
                entity,
                WateredComponent(
                    watered_at_epoch=event.world_epoch,
                    expires_at_epoch=event.world_epoch + 24 * 60 * 60,
                ),
            )
        if _wants(event, "crop") or _mentions(event, "planted crop"):
            replace_component(
                entity,
                CropComponent(crop_type=crop_type, planted_at_epoch=event.world_epoch),
            )
        if _wants(event, "crop-growth"):
            replace_component(
                entity,
                CropGrowthComponent(
                    progress_days=0.0,
                    required_days=2.0,
                    last_updated_epoch=event.world_epoch,
                ),
            )
        if _wants(event, "harvestable") or _mentions(event, "harvestable"):
            replace_component(entity, HarvestableComponent(yield_item=resource_type, ready=True))
        if _wants(event, "fertilizer") or _mentions(event, "fertilizer", "compost"):
            replace_component(entity, FertilizerComponent(kind="compost", growth_multiplier=1.2))
        if _wants(event, "tree") or _mentions(event, "sapling", "tree"):
            replace_component(
                entity,
                TreeComponent(
                    tree_type=resource_type,
                    planted_at_epoch=event.world_epoch,
                    maturity_days=7.0,
                ),
            )
        if _wants(event, "tree-tap") or _mentions(event, "tree tap", "tapped tree"):
            replace_component(
                entity,
                TreeTapComponent(
                    tapped_at_epoch=event.world_epoch,
                    last_collected_epoch=event.world_epoch,
                ),
            )
        if _wants(event, "crop-quality") or _mentions(event, "crop", "sprout"):
            replace_component(entity, CropQualityComponent(quality=1.1))
        if _wants(event, "regrowable") or _mentions(event, "regrow", "perennial"):
            replace_component(entity, RegrowableComponent(regrow_days=2.0))
        if _wants(event, "pest") or _mentions(event, "pest", "bugs"):
            replace_component(entity, PestComponent(severity=0.5))
        if _wants(event, "weed") or _mentions(event, "weed", "weeds"):
            replace_component(entity, WeedComponent(density=0.5))
        if _wants(event, "crop-inspection"):
            replace_component(
                entity,
                CropInspectionComponent(inspected_at_epoch=event.world_epoch, notes=event.intent),
            )
        if _wants(event, "machine") or _mentions(event, "machine", "preserves", "keg"):
            replace_component(entity, MachineComponent(machine_type=resource_type))
        if _wants(event, "machine-breakdown") or _mentions(event, "broken machine"):
            replace_component(entity, MachineBreakdownComponent(reason=event.intent or "worldgen"))
        if _wants(event, "processing-recipe") or _mentions(event, "processing recipe"):
            replace_component(
                entity,
                ProcessingRecipeComponent(
                    recipe_id=resource_type,
                    machine_type=resource_type,
                    inputs={resource_type: 1},
                    outputs={resource_type: 1},
                    duration_seconds=60,
                ),
            )
        if _wants(event, "animal-home") or _mentions(event, "coop", "barn"):
            replace_component(entity, AnimalHomeComponent())
        if _wants(event, "farm-animal") or _mentions(event, "farm animal", "cow", "chicken"):
            species = _animal_species(event)
            replace_component(entity, FarmAnimalComponent(species=species))
        if _wants(event, "animal-product"):
            replace_component(entity, AnimalProductComponent(product_type=resource_type))
        if _wants(event, "animal-breeding"):
            replace_component(
                entity,
                AnimalBreedingComponent(offspring_species=_animal_species(event)),
            )
        if _wants(event, "fishing-spot") or _mentions(event, "fishing spot", "pond"):
            replace_component(
                entity,
                FishingSpotComponent(fish_type=_fish_type(event), season=_season(event)),
            )
        if _wants(event, "mining-node") or _mentions(event, "mining node", "ore node"):
            replace_component(entity, MiningNodeComponent(resource_type=resource_type))
        if _wants(event, "shipping-bin") or _mentions(event, "shipping bin", "shipping crate"):
            replace_component(entity, ShippingBinComponent())
        if _wants(event, "geode") or _mentions(event, "geode"):
            replace_component(entity, GeodeComponent(resource_type=resource_type))
        if _wants(event, "ladder") or _mentions(event, "ladder"):
            replace_component(entity, LadderComponent(target_room_id=event.entity_id))
        if _wants(event, "forage") or _mentions(event, "forage"):
            replace_component(
                entity,
                ForageComponent(resource_type=resource_type, seasons=(_season(event),)),
            )
        if _wants(event, "festival") or _mentions(event, "festival"):
            replace_component(entity, FestivalComponent(name=name, season=_season(event)))
        if _wants(event, "bundle") or _mentions(event, "bundle"):
            replace_component(
                entity,
                BundleComponent(bundle_id=event.object_key, requirements={resource_type: 1}),
            )
        if _wants(event, "collection") or _mentions(event, "collection"):
            replace_component(entity, CollectionComponent(entries=(resource_type,)))
        if _wants(event, "museum-collection") or _mentions(event, "museum"):
            replace_component(entity, MuseumCollectionComponent())
        if _wants(event, "reward") or _mentions(event, "reward"):
            replace_component(entity, RewardComponent(resource_type=resource_type))
        if _wants(event, "mail") or _mentions(event, "mail", "letter"):
            replace_component(entity, MailComponent(subject=name))
        if _wants(event, "farm-quest") or _mentions(event, "quest", "order board"):
            replace_component(
                entity,
                FarmQuestComponent(quest_id=resource_type, requested={resource_type: 1}),
            )


class BarbarianWorldgenHook:
    def _on_character(self, event: CharacterGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.character_key)
        if _wants(event, "temperature-resistance"):
            replace_component(entity, TemperatureResistanceComponent(heat=5.0, cold=5.0))
        if _wants(event, "temperature-exposure"):
            replace_component(
                entity,
                TemperatureExposureComponent(last_updated_epoch=event.world_epoch),
            )
        if _wants(event, "poison") or _mentions(event, "poisoned"):
            replace_component(entity, PoisonComponent(severity=1.0))
        if _wants(event, "corruption") or _mentions(event, "corrupted"):
            replace_component(entity, CorruptionComponent(amount=1.0))
        if _wants(event, "stamina", "combatant") or _mentions(event, "warrior", "fighter"):
            replace_component(entity, StaminaComponent())
        if _wants(event, "blessing"):
            replace_component(entity, BlessingComponent(name=name, source_id=event.entity_id))
        if _wants(event, "curse"):
            replace_component(entity, CurseComponent(name=name, source_id=event.entity_id))
        if _wants(event, "climbing-skill") or _mentions(event, "climber"):
            replace_component(entity, ClimbingSkillComponent(level=1))

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.object_key)
        if _wants(event, "weapon") or _mentions(event, "sword", "axe", "spear", "club"):
            replace_component(entity, WeaponComponent(damage=8.0, lethal_capable=True))
        if _wants(event, "armor") or _mentions(event, "armor", "shield"):
            replace_component(entity, ArmorComponent(rating=2.0))
        if _wants(event, "durability") or _mentions(event, "durable"):
            replace_component(entity, DurabilityComponent(current=10.0, maximum=10.0))
        if _wants(event, "durable-fortification") or _mentions(event, "barricade", "wall"):
            replace_component(entity, FortificationComponent(rating=2.0, durability=20.0))
        if _wants(event, "trap") or _mentions(event, "trap"):
            replace_component(entity, TrapComponent(damage=6.0))
        if _wants(event, "shrine") or _mentions(event, "shrine", "altar"):
            replace_component(entity, ShrineComponent(deity=name))
        if _wants(event, "ritual") or _mentions(event, "ritual"):
            replace_component(entity, RitualComponent(ritual_type=event.intent or name))
        if _wants(event, "blessing"):
            replace_component(entity, BlessingComponent(name=name, source_id=event.entity_id))
        if _wants(event, "curse"):
            replace_component(entity, CurseComponent(name=name, source_id=event.entity_id))
        if _wants(event, "key") or _mentions(event, "key"):
            replace_component(entity, KeyComponent(key_name=name))
        if _wants(event, "treasure") or _mentions(event, "treasure", "cache"):
            replace_component(
                entity,
                TreasureComponent(treasure_type=event.entity_kind, key_name=name),
            )
        if _wants(event, "climbing-gate") or _mentions(event, "cliff", "climb"):
            replace_component(entity, ClimbingGateComponent(required_level=1))

    def _on_room(self, event: RoomGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.room_key)
        if _wants(event, "shelter") or _mentions(event, "shelter", "camp"):
            replace_component(entity, ShelterComponent(temperature_buffer=10.0))
        if _wants(event, "base-claim"):
            replace_component(
                entity,
                BaseClaimComponent(
                    claimed_by=_generated_id(event, "claimant"),
                    clan=name,
                    claimed_at_epoch=event.world_epoch,
                ),
            )
        if _wants(event, "survival-gap") or _mentions(event, "shortage", "survival gap"):
            replace_component(entity, SurvivalGapComponent(required_resource=_resource_type(event)))
        if _wants(event, "building") or _mentions(event, "building", "hall"):
            replace_component(entity, BuildingComponent(integrity=20.0, maximum_integrity=20.0))
        if _wants(event, "siege-readiness") or _mentions(event, "siege"):
            replace_component(entity, SiegeReadinessComponent(score=1.0))
        if _wants(event, "purge-wave") or _mentions(event, "purge wave"):
            replace_component(
                entity,
                PurgeWaveComponent(wave=1, started_at_epoch=event.world_epoch),
            )
        if _wants(event, "danger-zone") or _mentions(event, "danger zone", "ruin"):
            replace_component(entity, DangerZoneComponent(zone_type=event.biome))
        if _wants(event, "boss") or _mentions(event, "boss", "warlord"):
            replace_component(entity, BossComponent(name=name))


class DragonWorldgenHook:
    def _on_site(self, event: RoomGeneratedEvent | ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.entity_key)
        if _wants(event, "point-of-interest") or _mentions(event, "landmark", "shrine", "ruin"):
            replace_component(entity, PointOfInterestComponent(location_type=event.entity_kind))
        if _wants(event, "discovery"):
            replace_component(
                entity,
                DiscoveryComponent(first_discovered_at_epoch=event.world_epoch),
            )
        if _wants(event, "map-marker") or _mentions(event, "map marker"):
            replace_component(entity, MapMarkerComponent(label=name, marker_type=event.entity_kind))
        if _wants(event, "encounter-zone") or _mentions(event, "encounter zone"):
            replace_component(entity, EncounterZoneComponent(zone_type=event.entity_kind))
        if _wants(event, "faction") or _mentions(event, "faction", "guild", "clan"):
            replace_component(entity, FactionComponent(name=name))
        if _wants(event, "quest"):
            replace_component(entity, QuestComponent(quest_id=event.entity_key, title=name))
        if _wants(event, "quest-stage"):
            replace_component(entity, QuestStageComponent(quest_id=event.entity_key))
        if _wants(event, "quest-objective"):
            replace_component(
                entity,
                QuestObjectiveComponent(
                    quest_id=event.entity_key,
                    description=event.intent or name,
                ),
            )
        if _wants(event, "quest-reward"):
            replace_component(
                entity,
                QuestRewardComponent(quest_id=event.entity_key, description=event.intent or name),
            )
        if _wants(event, "guard") or _mentions(event, "guard"):
            replace_component(entity, GuardComponent(faction_id=_generated_id(event, "faction")))
        if _wants(event, "jail") or _mentions(event, "jail"):
            replace_component(
                entity,
                JailComponent(
                    faction_id=_generated_id(event, "faction"),
                    release_epoch=event.world_epoch,
                ),
            )
        if _wants(event, "perk"):
            replace_component(entity, PerkComponent(name=name, skill_name=_resource_type(event)))
        if _wants(event, "ancient-beast") or _mentions(event, "ancient beast"):
            replace_component(entity, AncientBeastComponent(name=name))
        if _wants(event, "word-of-power") or _mentions(event, "word of power"):
            replace_component(entity, WordOfPowerComponent(name=name))
        if _wants(event, "lock-difficulty", "locked"):
            replace_component(entity, LockDifficultyComponent(difficulty=2))
        if _wants(event, "lore-book") or _mentions(event, "lore book", "manual"):
            replace_component(entity, LoreBookComponent(title=name, lore=event.intent or name))
        if _wants(event, "spell"):
            replace_component(entity, SpellComponent(name=name, effect=event.intent or name))
        if _wants(event, "potion-recipe"):
            replace_component(
                entity,
                PotionRecipeComponent(name=name, potion_name=f"{name} potion"),
            )
        if _wants(event, "potion"):
            replace_component(entity, PotionComponent(name=name, effect=event.intent or name))
        if _wants(event, "artifact") or _mentions(event, "artifact"):
            replace_component(entity, ArtifactComponent(name=name, effect=event.intent or name))
        if _wants(event, "carvable"):
            replace_component(entity, CarvableComponent(remaining_space=24))
        if _wants(event, "voice-inscription"):
            replace_component(
                entity,
                VoiceInscriptionComponent(
                    word_id=_generated_id(event, "word"),
                    phrase=event.intent or name,
                ),
            )

    def _on_character(self, event: CharacterGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.character_key)
        if _wants(event, "faction-reputation"):
            replace_component(entity, FactionReputationComponent(scores={}))
        if _wants(event, "guard") or _mentions(event, "guard"):
            replace_component(entity, GuardComponent(faction_id=_generated_id(event, "faction")))
        if _wants(event, "jail"):
            replace_component(
                entity,
                JailComponent(
                    faction_id=_generated_id(event, "faction"),
                    release_epoch=event.world_epoch,
                ),
            )
        if _wants(event, "great-soul"):
            replace_component(entity, GreatSoulComponent(souls=1))
        if _wants(event, "stealth") or _mentions(event, "sneak", "stealthy"):
            replace_component(
                entity,
                StealthComponent(sneaking=True, since_epoch=event.world_epoch),
            )
        if _wants(event, "wanted", "bounty"):
            replace_component(
                entity,
                WantedComponent(amounts={_generated_id(event, "faction"): 10}),
            )
        if _wants(event, "magic"):
            replace_component(entity, MagicComponent(last_updated_epoch=event.world_epoch))
        if _wants(event, "spell-cooldown"):
            replace_component(entity, SpellCooldownComponent(ready_at_epoch=event.world_epoch))
        if _wants(event, "persuasion"):
            replace_component(entity, PersuasionComponent(disposition=1))
        if _wants(event, "surrender"):
            replace_component(
                entity,
                SurrenderComponent(reason=event.intent or name, at_epoch=event.world_epoch),
            )
        if _wants(event, "ancient-beast") or _mentions(event, "ancient beast"):
            replace_component(entity, AncientBeastComponent(name=name))


class DaggerWorldgenHook:
    def _on_room(self, event: RoomGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.room_key)
        if _wants(event, "procedural-site"):
            replace_component(
                entity,
                ProceduralSiteComponent(site_type=event.biome, seed=event.seed),
            )
        if _wants(event, "unrealized-location") or _mentions(event, "unrealized location"):
            replace_component(
                entity,
                UnrealizedLocationComponent(
                    summary=event.intent or name,
                    region_id=event.entity_id,
                ),
            )
        if _wants(event, "expansion-hook"):
            replace_component(
                entity,
                ExpansionHookComponent(
                    trigger=_expansion_trigger(event),
                    generator_plugin_id=_DEFAULT_EXPANSION_GENERATOR,
                ),
            )
        if _wants(event, "dungeon") or _mentions(event, "dungeon", "crypt", "vault"):
            replace_component(
                entity,
                DungeonComponent(
                    dungeon_id=event.room_key,
                    theme=event.biome,
                    seed=event.seed,
                    entry_room_id=event.entity_id,
                ),
            )
            replace_component(
                entity,
                DungeonRoomComponent(dungeon_id=event.room_key, discovered=True),
            )
        if _wants(event, "travel-hub") or _mentions(event, "crossroads", "station"):
            replace_component(entity, TravelHubComponent(name=name))
        if _wants(event, "travel-mode"):
            replace_component(entity, TravelModeComponent(mode=event.biome or "foot"))
        if _wants(event, "institution") or _mentions(event, "guild", "temple", "bank"):
            replace_component(entity, InstitutionComponent(name=name))
        if _wants(event, "institution-service"):
            replace_component(entity, InstitutionServiceComponent(service_name=name))
        if _wants(event, "institution-dues"):
            replace_component(entity, InstitutionDuesComponent(amount_due=10))
        if _wants(event, "bank") or _mentions(event, "bank"):
            replace_component(entity, BankComponent(name=name, region_id=event.entity_id))
        if _wants(event, "law-region"):
            replace_component(
                entity,
                LawRegionComponent(region_id=event.entity_id, fines={"trespass": 5}),
            )
        if _wants(event, "property-deed"):
            replace_component(
                entity,
                PropertyDeedComponent(property_id=event.entity_id, region_id=event.entity_id),
            )
        if _wants(event, "lodging") or _mentions(event, "inn", "lodging"):
            replace_component(entity, LodgingComponent(price=5))
        if _wants(event, "camping") or _mentions(event, "camp"):
            replace_component(
                entity,
                CampingComponent(risk="low", started_at_epoch=event.world_epoch),
            )
        if _wants(event, "travel-supply"):
            replace_component(entity, TravelSupplyComponent(quantity=3))
        if _wants(event, "travel-interruption"):
            replace_component(
                entity,
                TravelInterruptionComponent(reason=event.intent or "worldgen"),
            )
        if _wants(event, "rest-risk"):
            replace_component(entity, RestRiskComponent(band="uneasy", note=event.intent or name))

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.object_key)
        if _wants(event, "expansion-hook"):
            replace_component(
                entity,
                ExpansionHookComponent(
                    trigger=_expansion_trigger(event),
                    generator_plugin_id=_DEFAULT_EXPANSION_GENERATOR,
                ),
            )
        if _wants(event, "rumor") or _mentions(event, "rumor"):
            replace_component(entity, RumorComponent(text=event.intent or name))
        if _wants(event, "rumor-source"):
            replace_component(entity, RumorSourceComponent(source_id=event.room_id))
        if _wants(event, "rumor-reliability"):
            replace_component(entity, RumorReliabilityComponent(score=0.75))
        if _wants(event, "rumor-target"):
            replace_component(
                entity,
                RumorTargetComponent(target_id=event.room_id or event.entity_id),
            )
        if _wants(event, "quest-template"):
            replace_component(
                entity,
                QuestTemplateComponent(
                    title=name,
                    objective=event.intent or name,
                    reward_item_name="coin",
                ),
            )
        if _wants(event, "generated-quest"):
            replace_component(
                entity,
                GeneratedQuestComponent(title=name, objective=event.intent or name),
            )
        if _wants(event, "quest-deadline"):
            replace_component(
                entity,
                QuestDeadlineComponent(due_at_epoch=event.world_epoch + 86400),
            )
        if _wants(event, "dagger-quest-reward"):
            replace_component(entity, DaggerQuestRewardComponent(item_name=name))
        if _wants(event, "bank") or _mentions(event, "bank"):
            replace_component(entity, BankComponent(name=name, region_id=event.room_id or ""))
        if _wants(event, "spell-template"):
            replace_component(
                entity,
                SpellTemplateComponent(
                    spell_name=name,
                    effect_type="worldgen",
                    magnitude=1.0,
                ),
            )
        if _wants(event, "custom-spell"):
            replace_component(
                entity,
                CustomSpellComponent(spell_name=name, effect_type="worldgen", magnitude=1.0),
            )
        if _wants(event, "enchanted-item"):
            replace_component(
                entity,
                EnchantedItemComponent(
                    spell_name=name,
                    effect_type="worldgen",
                    magnitude=1.0,
                ),
            )
        if _wants(event, "potion-maker"):
            replace_component(
                entity,
                PotionMakerComponent(recipe_name=name, output_item_name=f"{name} potion"),
            )
        if _wants(event, "recharge-service"):
            replace_component(entity, RechargeServiceComponent(charge_amount=1))
        if _wants(event, "ingredient"):
            replace_component(
                entity,
                IngredientComponent(ingredient_name=name, effect=event.intent or "worldgen"),
            )
        if _wants(event, "creature-language"):
            replace_component(entity, CreatureLanguageComponent(language=event.entity_kind))
        if _wants(event, "hostility"):
            replace_component(entity, HostilityComponent(hostile=True))
        if _wants(event, "dungeon-objective"):
            replace_component(
                entity,
                DungeonObjectiveComponent(
                    objective_kind=event.entity_kind,
                    description=event.intent or name,
                ),
            )
        if _wants(event, "secret-door") or _mentions(event, "secret door"):
            replace_component(
                entity,
                SecretDoorComponent(target_room_id=event.room_id or event.entity_id, hint=name),
            )
        if _wants(event, "automap"):
            replace_component(
                entity,
                AutomapComponent(marked_rooms=(event.room_id,) if event.room_id else ()),
            )

    def _on_character(self, event: CharacterGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.character_key)
        if _wants(event, "bounty"):
            replace_component(entity, BountyComponent(amount=10, region_id=event.room_id))
        if _wants(event, "regional-reputation"):
            replace_component(entity, RegionalReputationComponent(scores={event.room_id: 1}))
        if _wants(event, "institution-reputation"):
            replace_component(
                entity,
                InstitutionReputationComponent(scores={_generated_id(event, "institution"): 1}),
            )
        if _wants(event, "legal-reputation"):
            replace_component(entity, LegalReputationComponent(scores={event.room_id: 0}))
        if _wants(event, "service-access"):
            replace_component(
                entity,
                ServiceAccessComponent(service_ids=(_generated_id(event, "service"),)),
            )
        if _wants(event, "class-template"):
            replace_component(
                entity,
                ClassTemplateComponent(class_name=name, primary_skills=tuple(event.tags)),
            )
        if _wants(event, "custom-class"):
            replace_component(
                entity,
                CustomClassComponent(class_name=name, primary_skills=tuple(event.tags)),
            )
        if _wants(event, "language-skill"):
            replace_component(entity, LanguageSkillComponent(languages={event.species: 1}))
        if _wants(event, "supernatural-affliction"):
            replace_component(
                entity,
                SupernaturalAfflictionComponent(
                    affliction_type=event.intent or "worldgen",
                    contracted_at_epoch=event.world_epoch,
                ),
            )
        if _wants(event, "affliction-stigma"):
            replace_component(entity, AfflictionStigmaComponent(region_id=event.room_id))
        if _wants(event, "cure-quest-hook"):
            replace_component(
                entity,
                CureQuestHookComponent(affliction_type=event.intent or "worldgen"),
            )
        if _wants(event, "feeding-need"):
            replace_component(
                entity,
                FeedingNeedComponent(current=1.0, last_updated_epoch=event.world_epoch),
            )
        if _wants(event, "recall-anchor"):
            replace_component(entity, RecallAnchorComponent(room_id=event.room_id))
        if _wants(event, "dialogue-approach"):
            replace_component(entity, DialogueApproachComponent(last_approach="worldgen"))
        if _wants(event, "etiquette-skill"):
            replace_component(entity, EtiquetteSkillComponent(level=1))
        if _wants(event, "streetwise-skill"):
            replace_component(entity, StreetwiseSkillComponent(level=1))
        if _wants(event, "social-register"):
            replace_component(entity, SocialRegisterComponent(register=event.species))
        if _wants(event, "conversation-tone"):
            replace_component(
                entity,
                ConversationToneComponent(tone="curious", last_reaction=event.intent or name),
            )


class DinoWorldgenHook:
    def _on_character(self, event: CharacterGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "dinosaur") or _mentions(event, "dinosaur", "raptor", "rex"):
            replace_component(entity, DinosaurComponent(species_name=event.species))
            replace_component(entity, SpeciesComponent(common_name=event.species))
            replace_component(entity, FertilityComponent())
        if _wants(event, "water-creature") or _mentions(event, "aquatic", "water creature"):
            replace_component(entity, WaterCreatureComponent(species_name=event.species))
        if _wants(event, "creature-need"):
            replace_component(entity, CreatureNeedComponent(last_updated_epoch=event.world_epoch))
        if _wants(event, "kaiju") or _mentions(event, "kaiju"):
            replace_component(entity, KaijuComponent())
        if _wants(event, "creature-attack"):
            replace_component(entity, CreatureAttackComponent())
        if _wants(event, "roar") or _mentions(event, "roar"):
            replace_component(entity, RoarComponent())
        if _wants(event, "charge"):
            replace_component(entity, ChargeComponent())
        if _wants(event, "trample"):
            replace_component(entity, TrampleComponent())
        if _wants(event, "armor-plate"):
            replace_component(entity, ArmorPlateComponent())
        if _wants(event, "weak-point"):
            replace_component(entity, WeakPointComponent())
        if _wants(event, "apex-predator"):
            replace_component(entity, ApexPredatorComponent())

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        species = _resource_type(event)
        if _wants(event, "fossil") or _mentions(event, "fossil", "amber"):
            replace_component(entity, FossilFragmentComponent(sample_quality=0.8))
        if _wants(event, "fossil-survey"):
            replace_component(entity, FossilSurveyComponent())
        if _wants(event, "ancient-sample"):
            replace_component(entity, AncientSampleComponent(species_name=species))
        if _wants(event, "bait"):
            replace_component(entity, BaitComponent(target_species=species))
        if _wants(event, "tranquilizer"):
            replace_component(entity, TranquilizerComponent())
        if _wants(event, "creature-product"):
            replace_component(entity, CreatureProductComponent(product_type=species))
        if _wants(event, "hide"):
            replace_component(entity, HideComponent())
        if _wants(event, "bone"):
            replace_component(entity, BoneComponent())
        if _wants(event, "toxin"):
            replace_component(entity, ToxinComponent())
        if _wants(event, "egg") or _mentions(event, "egg"):
            replace_component(
                entity,
                EggComponent(species_name=species, laid_at_epoch=event.world_epoch),
            )

    def _on_room(self, event: RoomGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        species = _resource_type(event)
        if _wants(event, "enclosure") or _mentions(event, "enclosure", "pen"):
            replace_component(entity, EnclosureComponent(name=_name(entity, event.room_key)))
            replace_component(entity, EscapeRiskComponent(last_updated_epoch=event.world_epoch))
        if _wants(event, "track") or _mentions(event, "tracks", "footprints"):
            replace_component(
                entity,
                TrackComponent(room_id=event.entity_id, last_tracked_epoch=event.world_epoch),
            )
        if _wants(event, "territory") or _mentions(event, "territory"):
            replace_component(
                entity,
                TerritoryComponent(species_name=species, marked_at_epoch=event.world_epoch),
            )
        if _wants(event, "herd") or _mentions(event, "herd"):
            replace_component(
                entity,
                HerdComponent(species_name=species, last_tracked_epoch=event.world_epoch),
            )
        if _wants(event, "nest") or _mentions(event, "nest"):
            replace_component(entity, NestComponent(species_name=species))
        if _wants(event, "scent"):
            replace_component(entity, ScentComponent(species_name=species))


class VoidWorldgenHook:
    def _on_room(self, event: RoomGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.room_key)
        if _wants(event, "ship") or _mentions(event, "ship", "starship"):
            replace_component(entity, ShipComponent(name=name))
            replace_component(entity, PowerGridComponent())
        if _wants(event, "station") or _mentions(event, "station"):
            replace_component(entity, StationComponent(name=name))
        if _wants(event, "habitat-module", "ship") or _mentions(event, "module", "airlock", "ship"):
            replace_component(entity, HabitatModuleComponent(module_type=event.biome))
            replace_component(entity, PressurizedComponent())
            replace_component(entity, LifeSupportComponent())
            replace_component(entity, OxygenComponent(last_updated_epoch=event.world_epoch))
        if _wants(event, "airlock") or _mentions(event, "airlock"):
            replace_component(entity, AirlockComponent())
        if _wants(event, "star-system"):
            replace_component(entity, StarSystemComponent(name=name))
        if _wants(event, "orbital-body") or _mentions(event, "planet", "moon", "asteroid"):
            replace_component(entity, OrbitalBodyComponent(body_type=_orbital_body_type(event)))
        if _wants(event, "survey-site") or _mentions(event, "survey site"):
            replace_component(entity, SurveySiteComponent(resource=_resource_type(event)))
        if _wants(event, "mining-site") or _mentions(event, "mining site", "asteroid mine"):
            replace_component(entity, MiningSiteComponent(resource_type=_resource_type(event)))
        if _wants(event, "salvage-claim") or _mentions(event, "salvage site", "derelict"):
            replace_component(entity, SalvageClaimComponent(site_id=event.entity_id))
        if _wants(event, "contract"):
            replace_component(entity, ContractComponent(contract_type=_resource_type(event)))
        if _wants(event, "emergency") or _mentions(event, "emergency"):
            replace_component(entity, EmergencyComponent(emergency_type=_resource_type(event)))
        if _wants(event, "reactor") or _mentions(event, "reactor"):
            replace_component(entity, ReactorComponent())
        if _wants(event, "gravity"):
            replace_component(entity, GravityComponent())

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.object_key)
        resource_type = _resource_type(event)
        if _wants(event, "ship-system"):
            replace_component(entity, ShipSystemComponent(system_type=event.entity_kind))
        if _wants(event, "jump-drive") or _mentions(event, "jump drive"):
            replace_component(entity, JumpDriveComponent())
        if _wants(event, "fuel") or _mentions(event, "fuel"):
            replace_component(entity, FuelComponent())
        if _wants(event, "sensor") or _mentions(event, "sensor"):
            replace_component(entity, SensorComponent())
        if _wants(event, "distress-signal") or _mentions(event, "distress signal"):
            replace_component(
                entity,
                DistressSignalComponent(text=event.intent or "distress signal"),
            )
        if _wants(event, "fabricator") or _mentions(event, "fabricator"):
            replace_component(entity, FabricatorComponent())
        if _wants(event, "blueprint") or _mentions(event, "blueprint"):
            replace_component(entity, BlueprintComponent(name=name, system_type=resource_type))
        if _wants(event, "ship-upgrade"):
            replace_component(entity, ShipUpgradeComponent(system_type=resource_type))
        if _wants(event, "contract") or _mentions(event, "contract"):
            replace_component(entity, ContractComponent(contract_type=resource_type))
        if _wants(event, "cargo"):
            replace_component(entity, CargoComponent(cargo_type=resource_type))
        if _wants(event, "salvage-claim") or _mentions(event, "salvage claim"):
            replace_component(entity, SalvageClaimComponent(site_id=event.entity_id))
        if _wants(event, "alien-species") or _mentions(event, "alien species"):
            replace_component(entity, AlienSpeciesComponent(name=name))
        if _wants(event, "first-contact"):
            replace_component(entity, FirstContactComponent(species_id=event.entity_id))
        if _wants(event, "translation-matrix"):
            replace_component(entity, TranslationMatrixComponent(species_id=event.entity_id))
        if _wants(event, "quarantine") or _mentions(event, "quarantine"):
            replace_component(entity, QuarantineComponent(reason=event.intent or name))
        if _wants(event, "diplomatic-mission"):
            replace_component(entity, DiplomaticMissionComponent(species_id=event.entity_id))
        if _wants(event, "alien-artifact") or _mentions(event, "alien artifact"):
            replace_component(entity, AlienArtifactComponent(species_id=event.entity_id))
        if _wants(event, "xenobiology-sample"):
            replace_component(entity, XenobiologySampleComponent(species_id=event.entity_id))
        if _wants(event, "trade-protocol"):
            replace_component(entity, TradeProtocolComponent(species_id=event.entity_id))
        if _wants(event, "drone"):
            replace_component(entity, DroneComponent(drone_type=resource_type))
        if _wants(event, "ship-ai") or _mentions(event, "ship ai"):
            replace_component(entity, ShipAIComponent(name=name))
        if _wants(event, "data-salvage") or _mentions(event, "data salvage"):
            replace_component(entity, DataSalvageComponent(data_type=resource_type))
        if _wants(event, "away-team"):
            replace_component(entity, AwayTeamComponent(mission=resource_type))
        if _wants(event, "morale"):
            replace_component(entity, MoraleComponent())
        if _wants(event, "mutiny"):
            replace_component(entity, MutinyComponent())
        if _wants(event, "emergency"):
            replace_component(entity, EmergencyComponent(emergency_type=resource_type))
        if _wants(event, "reactor") or _mentions(event, "reactor"):
            replace_component(entity, ReactorComponent())
        if _wants(event, "gravity"):
            replace_component(entity, GravityComponent())
        if _wants(event, "boarding-threat") or _mentions(event, "boarding threat"):
            replace_component(entity, BoardingThreatComponent())
        if _wants(event, "passenger"):
            replace_component(entity, PassengerComponent())
        if _wants(event, "survey-site"):
            replace_component(entity, SurveySiteComponent(resource=resource_type))
        if _wants(event, "mining-site"):
            replace_component(entity, MiningSiteComponent(resource_type=resource_type))
        if _wants(event, "customs-hold"):
            replace_component(entity, CustomsHoldComponent())
        if _wants(event, "smuggling-compartment"):
            replace_component(entity, SmugglingCompartmentComponent())
        if _wants(event, "insurance-policy"):
            replace_component(entity, InsurancePolicyComponent(insured_entity_id=event.entity_id))
        if _wants(event, "mortgage"):
            replace_component(entity, MortgageComponent())
        if _wants(event, "orbital-body"):
            replace_component(entity, OrbitalBodyComponent(body_type=_orbital_body_type(event)))
        if _wants(event, "orbit"):
            replace_component(entity, OrbitComponent(body_id=event.entity_id))
        if _wants(event, "navigation-route"):
            replace_component(entity, NavigationRouteComponent(destination_id=event.entity_id))
        if _wants(event, "astrogation"):
            replace_component(entity, AstrogationComponent())


class NukeWorldgenHook:
    def _on_entity(self, event: RoomGeneratedEvent | ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.entity_key)
        resource_type = _resource_type(event)
        if _wants(event, "radiation-source") or _mentions(
            event, "radiation", "fallout", "reactor"
        ):
            replace_component(
                entity,
                RadiationSourceComponent(last_updated_epoch=event.world_epoch),
            )
        if _wants(event, "scavenge-site") or _mentions(event, "ruin", "wasteland", "cache"):
            replace_component(entity, ScavengeSiteComponent(hazard_rads=1.0))
            replace_component(entity, LootTableComponent(outputs={"scrap": 2}))
        if _wants(event, "settlement") or _mentions(event, "settlement"):
            replace_component(entity, SettlementComponent(name=name))
        if _wants(event, "settlement-salvage") or _mentions(event, "settlement salvage"):
            replace_component(entity, SettlementSalvageComponent(outputs={"scrap": 2}))
        if _wants(event, "water-purifier") or _mentions(event, "water purifier"):
            replace_component(entity, WaterPurifierComponent())
        if _wants(event, "generator") or _mentions(event, "generator"):
            replace_component(entity, GeneratorComponent())
        if _wants(event, "beacon") or _mentions(event, "radio beacon"):
            replace_component(entity, BeaconComponent(message=event.intent or name))
        if _wants(event, "trader-route") or _mentions(event, "trader route"):
            replace_component(entity, TraderRouteComponent(destination=name))
        if _wants(event, "raider-pressure") or _mentions(event, "raider"):
            replace_component(entity, RaiderPressureComponent())
        if _wants(event, "terminal") or _mentions(event, "terminal"):
            replace_component(entity, TerminalComponent())
        if _wants(event, "old-world-tech") or _mentions(event, "old-world", "pre-war"):
            replace_component(entity, OldWorldTechComponent(tech_name=name))
        if _wants(event, "tech-lead"):
            replace_component(
                entity,
                TechLeadComponent(target_tech=resource_type, location_hint=event.intent),
            )
        if _wants(event, "water-purity") or _mentions(event, "dirty water", "purified water"):
            replace_component(
                entity,
                WaterPurityComponent(
                    rads_per_drink=1.0 if _mentions(event, "dirty", "contaminated") else 0.0,
                    purified=_mentions(event, "purified"),
                ),
            )
        if isinstance(event, ObjectGeneratedEvent):
            if _wants(event, "rad-protection"):
                replace_component(entity, RadProtectionComponent(rating=0.5))
            if _wants(event, "decontamination"):
                replace_component(entity, DecontaminationComponent())
            if _wants(event, "rad-medicine"):
                replace_component(entity, RadMedicineComponent())
            if _wants(event, "mutation"):
                replace_component(
                    entity,
                    MutationComponent(
                        mutation_id=event.entity_key,
                        label=name,
                        manifested_at_epoch=event.world_epoch,
                    ),
                )
            if _wants(event, "mutation-resistance"):
                replace_component(entity, MutationResistanceComponent(threshold_bonus=1.0))
            if _wants(event, "suppressant"):
                replace_component(entity, SuppressantComponent())
            if _wants(event, "sample") or _mentions(event, "sample"):
                replace_component(entity, SampleComponent(sample_type=resource_type))
            if _wants(event, "locked-crate") or _mentions(event, "locked crate"):
                replace_component(entity, LockedCrateComponent())
            if _wants(event, "wasteland-artifact") or _mentions(event, "wasteland artifact"):
                replace_component(entity, WastelandArtifactComponent(artifact_type=resource_type))
            if _wants(event, "faction-salvage"):
                replace_component(entity, FactionSalvageComponent(faction_id="generated-faction"))
            if _wants(event, "schematic"):
                replace_component(entity, SchematicComponent(mod_name=name))
            if _wants(event, "item-mod"):
                replace_component(entity, ItemModComponent(mod_name=name))
            if _wants(event, "field-repair"):
                replace_component(entity, FieldRepairComponent())
            if _wants(event, "chem") or _mentions(event, "chem"):
                replace_component(entity, ChemComponent(chem_type=resource_type))
            if _wants(event, "chem-recipe"):
                replace_component(entity, ChemRecipeComponent(chem_type=resource_type))
            if _wants(event, "hotspot-marker"):
                replace_component(
                    entity,
                    HotspotMarkerComponent(source_id=event.entity_id, marked_by="worldgen"),
                )
            if _wants(event, "junk") or _mentions(event, "junk"):
                replace_component(
                    entity,
                    JunkComponent(outputs={"scrap": 1}, contaminated_rads=0.5),
                )

    def _on_character(self, event: CharacterGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "radiation-dose"):
            replace_component(entity, RadiationDoseComponent(last_updated_epoch=event.world_epoch))
        if _wants(event, "mutation-threshold"):
            replace_component(entity, MutationThresholdComponent())
        if _wants(event, "mutation-resistance"):
            replace_component(entity, MutationResistanceComponent(threshold_bonus=1.0))


class NeonWorldgenHook:
    def _on_entity(self, event: RoomGeneratedEvent | ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "cyberpunk-site") or _mentions(
            event, "district", "arcology", "corp", "nightclub", "plaza", "market", "alley"
        ):
            replace_component(entity, CyberpunkSiteComponent(site_type=_name(entity, "site")))
        if _wants(event, "security-zone") or _mentions(event, "restricted", "secure", "vault"):
            replace_component(entity, SecurityZoneComponent(clearance_required=2))
            replace_component(entity, RestrictedAreaComponent())
        if _wants(event, "checkpoint") or _mentions(event, "checkpoint", "turnstile"):
            replace_component(entity, CheckpointComponent(clearance_required=2, bribe_cost=20))
        if _wants(event, "safehouse") or _mentions(event, "safehouse", "hideout", "flop"):
            replace_component(entity, SafehouseComponent())
        if _wants(event, "camera") or _mentions(event, "camera", "cctv"):
            replace_component(entity, DeviceComponent(device_type="camera"))
            replace_component(entity, CameraComponent())
            replace_component(entity, SurveillanceCoverageComponent())
        if _wants(event, "terminal") or _mentions(event, "terminal", "server", "console"):
            replace_component(entity, DeviceComponent(device_type="terminal"))
            replace_component(entity, HackableComponent(security=2))
        if _wants(event, "black-market") or _mentions(event, "vendor", "black market", "dealer"):
            replace_component(entity, BlackMarketComponent())
        if _wants(event, "data-broker") or _mentions(event, "fence", "broker"):
            replace_component(entity, DataBrokerComponent())
        if _wants(event, "clinic") or _mentions(event, "clinic", "ripperdoc", "surgeon"):
            licensed = not _mentions(event, "ripperdoc", "street", "back-alley")
            replace_component(entity, ClinicComponent(licensed=licensed))
        if _wants(event, "contract") or _mentions(event, "contract", "job posting", "gig"):
            replace_component(entity, RunnerContractComponent())

    def _on_character(self, event: CharacterGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "fixer") or _mentions(event, "fixer"):
            replace_component(entity, FixerComponent(name=_name(entity, "fixer")))
        if _wants(event, "netrunner") or _mentions(event, "netrunner", "runner", "hacker"):
            replace_component(entity, AccessLevelComponent(clearance=2))
            replace_component(entity, AugmentationSlotsComponent())


__all__ = [
    "BarbarianWorldgenHook",
    "ColonyWorldgenHook",
    "DaggerWorldgenHook",
    "DinoWorldgenHook",
    "DragonWorldgenHook",
    "EnvironmentWorldgenHook",
    "GardenWorldgenHook",
    "LifeWorldgenHook",
    "NeonWorldgenHook",
    "NukeWorldgenHook",
    "VoidWorldgenHook",
]
