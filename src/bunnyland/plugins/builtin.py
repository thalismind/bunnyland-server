"""Builtin bunnyland plugins (spec 21.4): core verbs, lifesim, memory.

This module is a plugin source: ``bunnyland_plugins()`` returns the plugins it declares,
exactly as a third-party module would. The world actor still provides the always-on
spine (clock, Action/Focus regen, downed/death); these plugins add the optional verb
surface and mechanics so disabling one removes its components/systems/verbs.
"""

from __future__ import annotations

from ..core.handlers import (
    MoveHandler,
    PutHandler,
    SayHandler,
    SleepHandler,
    TakeHandler,
    TellHandler,
    UseHandler,
    WaitHandler,
    WakeHandler,
    WriteHandler,
)
from ..mechanics.affect import AffectAggregation, AffectReactor
from ..mechanics.barbariansim import (
    ArmorComponent,
    AttackHandler,
    ChallengeHandler,
    CharacterPoisonedEvent,
    CleanseCorruptionHandler,
    CorruptionCleansedEvent,
    CorruptionComponent,
    CorruptionGainedEvent,
    DefendHandler,
    DefendingComponent,
    DurabilityComponent,
    ExposureChangedEvent,
    ExposureDamageEvent,
    FortificationComponent,
    FortifyHandler,
    FrostbiteStartedEvent,
    GainCorruptionHandler,
    HeatstrokeStartedEvent,
    ItemBrokenEvent,
    ItemDamagedEvent,
    ItemRepairedEvent,
    PickpocketHandler,
    PoisonCharacterHandler,
    PoisonComponent,
    PoisonProgressedEvent,
    PoisonTreatedEvent,
    RaidHandler,
    RepairItemHandler,
    ShelterComponent,
    SparHandler,
    StaminaChangedEvent,
    StaminaComponent,
    TemperatureExposureComponent,
    TemperatureResistanceComponent,
    TreatPoisonHandler,
    WeaponComponent,
    barbariansim_fragments,
    install_barbariansim,
)
from ..mechanics.colonysim import (
    AssignedTo,
    AssignJobHandler,
    ClaimOwnershipHandler,
    CompleteJobHandler,
    CraftHandler,
    GatherResourceHandler,
    JobComponent,
    Owns,
    RecipeComponent,
    ReleaseOwnershipHandler,
    ReleaseReservationHandler,
    ReservedBy,
    ReserveHandler,
    ResourceNodeComponent,
    ResourceRegenSystem,
    ResourceStackComponent,
    WorkstationComponent,
    colonysim_fragments,
)
from ..mechanics.consumables import ConsumableComponent, DrinkableComponent, FoodComponent
from ..mechanics.daggersim import (
    AcceptGeneratedQuestHandler,
    AccountOpenedEvent,
    AfflictionContractedEvent,
    AskForWorkHandler,
    AskRumorHandler,
    AttemptPacifyHandler,
    AutomapComponent,
    BankAccountComponent,
    BankComponent,
    BountyComponent,
    BountyPostedEvent,
    CastSpellHandler,
    ClassTemplateComponent,
    CommitCrimeHandler,
    CompleteGeneratedQuestHandler,
    ContractAfflictionHandler,
    ConversationToneComponent,
    CreateCustomClassHandler,
    CreateSpellHandler,
    CreatureLanguageComponent,
    CreaturePacifiedEvent,
    CrimeCommittedEvent,
    CrimeRecordComponent,
    CustomClassComponent,
    CustomClassCreatedEvent,
    CustomSpellComponent,
    DaggerQuestRewardComponent,
    DebtComponent,
    DepositHandler,
    DepositMadeEvent,
    DialogueApproachComponent,
    DungeonComponent,
    DungeonEnteredEvent,
    DungeonExitedEvent,
    DungeonGeneratedEvent,
    DungeonObjectiveComponent,
    DungeonObjectiveFoundEvent,
    DungeonRequestedEvent,
    DungeonRoomComponent,
    DungeonRoomDiscoveredEvent,
    EnterDungeonHandler,
    EtiquetteSkillComponent,
    ExpandSiteHandler,
    ExpansionHookComponent,
    ExpansionRequestedEvent,
    FeedingNeedChangedEvent,
    FeedingNeedComponent,
    FinePaidEvent,
    GeneratedQuestComponent,
    GeneratedSiteInstantiatedEvent,
    HostilityComponent,
    InstitutionComponent,
    InstitutionJoinedEvent,
    InstitutionServiceComponent,
    InstitutionServiceUsedEvent,
    InvestigateRumorHandler,
    JoinInstitutionHandler,
    LanguageSkillComponent,
    LawRegionComponent,
    LeaveDungeonHandler,
    LoanComponent,
    LoanDefaultedEvent,
    LoanIssuedEvent,
    LoanRepaidEvent,
    MarkPathHandler,
    MemberOfInstitution,
    OpenBankAccountHandler,
    OpenSecretDoorHandler,
    PacificationAttemptedEvent,
    PacifiedComponent,
    PayFineHandler,
    PlanTravelHandler,
    ProceduralSiteComponent,
    QuestDeadlineComponent,
    QuestFailedEvent,
    QuestGeneratedEvent,
    QuestTemplateComponent,
    RecallAnchorComponent,
    RecallAnchorSetEvent,
    RecallUsedEvent,
    RepayLoanHandler,
    RequestDungeonHandler,
    RestHandler,
    RestRiskComponent,
    RumorBecameExpansionEvent,
    RumorComponent,
    RumorDisprovenEvent,
    RumorHeardEvent,
    RumorReliabilityComponent,
    RumorSourceComponent,
    RumorTargetComponent,
    RumorVerifiedEvent,
    SearchRoomHandler,
    SecretDoorComponent,
    SecretDoorFoundEvent,
    SetRecallHandler,
    SocialRegisterComponent,
    SpellCastEvent,
    SpellCreatedEvent,
    SpellTemplateComponent,
    StreetwiseSkillComponent,
    SupernaturalAfflictionComponent,
    TakeLoanHandler,
    TransformationStartedEvent,
    TransformHandler,
    TravelCompletedEvent,
    TravelHubComponent,
    TravelModeComponent,
    TravelPlanComponent,
    TravelRoute,
    TravelStartedEvent,
    UnrealizedLocationComponent,
    UseInstitutionServiceHandler,
    UseRecallHandler,
    ViewMapHandler,
    WereformComponent,
    WithdrawalMadeEvent,
    WithdrawHandler,
    daggersim_fragments,
    install_daggersim,
)
from ..mechanics.daggersim import (
    QuestAcceptedEvent as DaggerQuestAcceptedEvent,
)
from ..mechanics.daggersim import (
    QuestCompletedEvent as DaggerQuestCompletedEvent,
)
from ..mechanics.dragonsim import (
    AcceptQuestHandler,
    CompleteObjectiveHandler,
    DiscoverLocationHandler,
    DiscoveryComponent,
    FactionComponent,
    FactionJoinedEvent,
    FactionLeftEvent,
    FactionReputationComponent,
    JoinFactionHandler,
    LeaveFactionHandler,
    LocationDiscoveredEvent,
    MemberOf,
    PointOfInterestComponent,
    QuestAcceptedEvent,
    QuestCompletedEvent,
    QuestComponent,
    QuestObjectiveCompletedEvent,
    QuestObjectiveComponent,
    QuestRewardComponent,
    QuestStageComponent,
    dragonsim_fragments,
)
from ..mechanics.eat_drink import DrinkHandler, EatHandler
from ..mechanics.environment import (
    CalendarComponent,
    ExtinguishHandler,
    FireComponent,
    FireDamageEvent,
    FireExtinguishedEvent,
    FireSpreadEvent,
    FireStartedEvent,
    FlammableComponent,
    IgniteHandler,
    TimeOfDayComponent,
    WeatherComponent,
    environment_fragments,
    install_environment,
)
from ..mechanics.gardensim import (
    CropComponent,
    CropGrewEvent,
    CropGrowthComponent,
    CropHarvestedEvent,
    CropReadyEvent,
    CropWateredEvent,
    CropWitheredEvent,
    FertilizeHandler,
    FertilizerAppliedEvent,
    FertilizerComponent,
    HarvestableComponent,
    HarvestCropHandler,
    PlantHandler,
    SeedComponent,
    SeedPlantedEvent,
    SoilComponent,
    SoilTilledEvent,
    TilledComponent,
    TillHandler,
    WaterCropHandler,
    WateredComponent,
    gardensim_fragments,
    install_gardensim,
)
from ..mechanics.lifesim import (
    AdoptChildHandler,
    AspirationChosenEvent,
    AspirationComponent,
    AssessTaxHandler,
    BillComponent,
    BillCreatedEvent,
    BillPaidEvent,
    BirthDueComponent,
    BusinessOpenedEvent,
    BusinessOwnerComponent,
    BusinessPromotedEvent,
    BusinessSaleEvent,
    CareerComponent,
    CareerStartedEvent,
    ChargeRentHandler,
    ChooseAspirationHandler,
    ClaimHomeHandler,
    ClaimRoomHandler,
    CompleteMilestoneHandler,
    CustomerComponent,
    EndPartnershipHandler,
    FindJobHandler,
    GossipSpreadEvent,
    GoToWorkHandler,
    HasBill,
    HasRoutine,
    HomeClaimedEvent,
    HomeComponent,
    HouseholdComponent,
    HouseholdFundsComponent,
    HouseholdJoinedEvent,
    JealousOf,
    JealousyTriggeredEvent,
    JobScheduleComponent,
    JoinHouseholdHandler,
    LifeStageComponent,
    MentorshipCompletedEvent,
    MentorSkillHandler,
    MilestoneCompletedEvent,
    MilestoneComponent,
    OpenBusinessHandler,
    OwnsBusiness,
    ParentOf,
    PartnerOf,
    PayBillHandler,
    PayWageHandler,
    PracticeSkillHandler,
    PregnancyComponent,
    PromoteBusinessHandler,
    PromotionEarnedEvent,
    QuitJobHandler,
    RelationshipStatus,
    RelationshipStatusChangedEvent,
    RentChargedEvent,
    ReproductiveComponent,
    ReputationComponent,
    ResolveBirthHandler,
    RoomClaimComponent,
    RoomClaimedEvent,
    RoutineComponent,
    RoutineDueEvent,
    RoutineSetEvent,
    SellItemHandler,
    SetRelationshipStatusHandler,
    SetRoutineHandler,
    SkillLeveledEvent,
    SkillSetComponent,
    SkillXPChangedEvent,
    SpreadGossipHandler,
    StartPartnershipHandler,
    StartPregnancyHandler,
    StudySkillHandler,
    TaxAssessedEvent,
    WagePaidEvent,
    WitnessRomanceHandler,
    WorkShiftCompletedEvent,
    install_lifesim,
    lifesim_fragments,
)
from ..mechanics.mechanisms import install_mechanisms
from ..mechanics.needs import (
    HungerComponent,
    HungerSystem,
    ThirstComponent,
    ThirstSystem,
    need_fragments,
)
from ..mechanics.persona import (
    GoalComponent,
    PreferenceComponent,
    TraitSetComponent,
    persona_fragments,
)
from ..mechanics.policy import (
    CharacterBoundaryComponent,
    WorldPolicyComponent,
    install_policy,
)
from ..mechanics.social import SocialBond, install_social, relationship_fragments
from ..mechanics.storyteller import (
    IncidentBudgetComponent,
    IncidentComponent,
    IncidentHistoryComponent,
    IncidentProposedEvent,
    IncidentResolvedEvent,
    IncidentStartedEvent,
    ResolveIncidentHandler,
    StorytellerComponent,
    ThreatPointsComponent,
    install_storyteller,
    storyteller_fragments,
)
from ..mechanics.voidsim import (
    AirlockComponent,
    AirlockCycledEvent,
    AnswerDistressSignalHandler,
    AstrogationComponent,
    BulkheadComponent,
    CoursePlottedEvent,
    CycleAirlockHandler,
    DistressSignalComponent,
    DockedTo,
    DockHandler,
    DockingCompletedEvent,
    EnterOrbitHandler,
    EvacuateModuleHandler,
    FuelChangedEvent,
    FuelComponent,
    HabitatModuleComponent,
    InspectShipSystemHandler,
    JumpCompletedEvent,
    JumpDriveComponent,
    JumpHandler,
    JumpRoute,
    JumpStartedEvent,
    LandHandler,
    LandingCompletedEvent,
    LaunchHandler,
    LeaveOrbitHandler,
    LifeSupportComponent,
    LifeSupportFailedEvent,
    ModuleEvacuatedEvent,
    NavigationHazardEncounteredEvent,
    NavigationRouteComponent,
    OpenAirlockHandler,
    OrbitalBodyComponent,
    OrbitComponent,
    OrbitEnteredEvent,
    OxygenComponent,
    PlotCourseHandler,
    PowerGridComponent,
    PowerReroutedEvent,
    PressureChangedEvent,
    PressurizedComponent,
    RadiationShieldComponent,
    RefuelHandler,
    RepairSystemHandler,
    ReroutePowerHandler,
    ScanHandler,
    SealBulkheadHandler,
    SensorComponent,
    ShipComponent,
    ShipSystemComponent,
    ShipSystemDamagedEvent,
    ShipSystemRepairedEvent,
    SignalDetectedEvent,
    StarSystemComponent,
    StationComponent,
    UndockHandler,
    install_voidsim,
    voidsim_fragments,
)
from ..memory import install_memory
from ..worldgen.generators import WorldGenerator, oneshot_generator, recursive_generator
from .model import (
    CommandContribution,
    ContentContribution,
    DependencyContribution,
    EcsContribution,
    Plugin,
    RuntimeContribution,
)

CORE_VERBS = "bunnyland.core_verbs"
LIFESIM = "bunnyland.lifesim"
MEMORY = "bunnyland.memory"
WORLDGEN = "bunnyland.worldgen"
ENVIRONMENT = "bunnyland.environment"
MECHANISMS = "bunnyland.mechanisms"
SOCIAL = "bunnyland.social"
POLICY = "bunnyland.policy"
PERSONA = "bunnyland.persona"
COLONYSIM = "bunnyland.colonysim"
BARBARIANSIM = "bunnyland.barbariansim"
GARDENSIM = "bunnyland.gardensim"
DRAGONSIM = "bunnyland.dragonsim"
DAGGERSIM = "bunnyland.daggersim"
VOIDSIM = "bunnyland.voidsim"
STORYTELLER = "bunnyland.storyteller"


def _install_affect(actor) -> None:
    reactor = AffectReactor(actor.world)
    reactor.subscribe(actor.bus)
    actor.register_consequence(AffectAggregation())


def core_verbs_plugin() -> Plugin:
    return Plugin(
        id=CORE_VERBS,
        name="Core Verbs",
        commands=CommandContribution(
            action_handlers=(
                MoveHandler,
                TakeHandler,
                PutHandler,
                UseHandler,
                WriteHandler,
                SleepHandler,
                WakeHandler,
                WaitHandler,
                SayHandler,
                TellHandler,
            )
        ),
    )


def lifesim_plugin() -> Plugin:
    return Plugin(
        id=LIFESIM,
        name="Life Sim",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(
            components=(
                HungerComponent,
                ThirstComponent,
                FoodComponent,
                DrinkableComponent,
                ConsumableComponent,
                AspirationComponent,
                MilestoneComponent,
                HouseholdFundsComponent,
                BillComponent,
                CareerComponent,
                JobScheduleComponent,
                BusinessOwnerComponent,
                CustomerComponent,
                HouseholdComponent,
                HomeComponent,
                RoomClaimComponent,
                RoutineComponent,
                ReputationComponent,
                SkillSetComponent,
                LifeStageComponent,
                ReproductiveComponent,
                PregnancyComponent,
                BirthDueComponent,
            ),
            edges=(
                ParentOf,
                HasRoutine,
                HasBill,
                OwnsBusiness,
                PartnerOf,
                RelationshipStatus,
                JealousOf,
            ),
            systems=(HungerSystem, ThirstSystem),
        ),
        commands=CommandContribution(
            action_handlers=(
                EatHandler,
                DrinkHandler,
                ChooseAspirationHandler,
                CompleteMilestoneHandler,
                PracticeSkillHandler,
                StudySkillHandler,
                MentorSkillHandler,
                FindJobHandler,
                GoToWorkHandler,
                QuitJobHandler,
                PayWageHandler,
                AssessTaxHandler,
                ChargeRentHandler,
                PayBillHandler,
                OpenBusinessHandler,
                SellItemHandler,
                PromoteBusinessHandler,
                JoinHouseholdHandler,
                ClaimHomeHandler,
                ClaimRoomHandler,
                SetRoutineHandler,
                SetRelationshipStatusHandler,
                SpreadGossipHandler,
                WitnessRomanceHandler,
                StartPartnershipHandler,
                EndPartnershipHandler,
                StartPregnancyHandler,
                ResolveBirthHandler,
                AdoptChildHandler,
            ),
            typed_events=(
                AspirationChosenEvent,
                MilestoneCompletedEvent,
                SkillXPChangedEvent,
                SkillLeveledEvent,
                MentorshipCompletedEvent,
                CareerStartedEvent,
                WorkShiftCompletedEvent,
                WagePaidEvent,
                BillCreatedEvent,
                TaxAssessedEvent,
                RentChargedEvent,
                BillPaidEvent,
                PromotionEarnedEvent,
                BusinessOpenedEvent,
                BusinessSaleEvent,
                BusinessPromotedEvent,
                HouseholdJoinedEvent,
                HomeClaimedEvent,
                RoomClaimedEvent,
                RoutineSetEvent,
                RoutineDueEvent,
                RelationshipStatusChangedEvent,
                GossipSpreadEvent,
                JealousyTriggeredEvent,
            )
        ),
        runtime=RuntimeContribution(service_factories=(_install_affect, install_lifesim)),
        content=ContentContribution(prompt_fragments=(need_fragments, lifesim_fragments)),
    )


def memory_plugin() -> Plugin:
    return Plugin(
        id=MEMORY,
        name="Memory",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        runtime=RuntimeContribution(service_factories=(_memory_factory,)),
    )


def _memory_factory(actor) -> None:
    install_memory(actor)


def _environment_factory(actor) -> None:
    install_environment(actor)


def environment_plugin() -> Plugin:
    return Plugin(
        id=ENVIRONMENT,
        name="Environment",
        ecs=EcsContribution(
            components=(
                CalendarComponent,
                TimeOfDayComponent,
                WeatherComponent,
                FlammableComponent,
                FireComponent,
            )
        ),
        commands=CommandContribution(
            action_handlers=(IgniteHandler, ExtinguishHandler),
            typed_events=(
                FireStartedEvent,
                FireSpreadEvent,
                FireDamageEvent,
                FireExtinguishedEvent,
            ),
        ),
        runtime=RuntimeContribution(service_factories=(_environment_factory,)),
        content=ContentContribution(prompt_fragments=(environment_fragments,)),
    )


def _mechanisms_factory(actor) -> None:
    install_mechanisms(actor)


def mechanisms_plugin() -> Plugin:
    return Plugin(
        id=MECHANISMS,
        name="Mechanisms",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        runtime=RuntimeContribution(service_factories=(_mechanisms_factory,)),
    )


def _social_factory(actor) -> None:
    install_social(actor)


def social_plugin() -> Plugin:
    return Plugin(
        id=SOCIAL,
        name="Social Bonds",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(edges=(SocialBond,)),
        runtime=RuntimeContribution(service_factories=(_social_factory,)),
        content=ContentContribution(prompt_fragments=(relationship_fragments,)),
    )


def _policy_factory(actor) -> None:
    install_policy(actor)


def policy_plugin() -> Plugin:
    return Plugin(
        id=POLICY,
        name="Policy & Boundaries",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(components=(WorldPolicyComponent, CharacterBoundaryComponent)),
        runtime=RuntimeContribution(service_factories=(_policy_factory,)),
    )


def persona_plugin() -> Plugin:
    return Plugin(
        id=PERSONA,
        name="Persona",
        ecs=EcsContribution(
            components=(TraitSetComponent, PreferenceComponent, GoalComponent)
        ),
        content=ContentContribution(prompt_fragments=(persona_fragments,)),
    )


def worldgen_plugin() -> Plugin:
    return Plugin(
        id=WORLDGEN,
        name="World Generators",
        content=ContentContribution(
            world_generators=(
                WorldGenerator(
                    "oneshot", oneshot_generator, "single LLM proposal, instantiated at once"
                ),
                WorldGenerator(
                    "recursive", recursive_generator, "breadth-first graph, grown room-by-room"
                ),
            )
        ),
    )


def colonysim_plugin() -> Plugin:
    return Plugin(
        id=COLONYSIM,
        name="Colony Sim",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(
            components=(
                ResourceNodeComponent,
                ResourceStackComponent,
                WorkstationComponent,
                RecipeComponent,
                JobComponent,
            ),
            edges=(ReservedBy, AssignedTo, Owns),
            systems=(ResourceRegenSystem,),
        ),
        commands=CommandContribution(
            action_handlers=(
                ReserveHandler,
                ReleaseReservationHandler,
                GatherResourceHandler,
                CraftHandler,
                AssignJobHandler,
                CompleteJobHandler,
                ClaimOwnershipHandler,
                ReleaseOwnershipHandler,
            )
        ),
        content=ContentContribution(prompt_fragments=(colonysim_fragments,)),
    )


def barbariansim_plugin() -> Plugin:
    return Plugin(
        id=BARBARIANSIM,
        name="Barbarian Sim",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(
            components=(
                WeaponComponent,
                ArmorComponent,
                PoisonComponent,
                CorruptionComponent,
                DefendingComponent,
                DurabilityComponent,
                FortificationComponent,
                StaminaComponent,
                TemperatureResistanceComponent,
                ShelterComponent,
                TemperatureExposureComponent,
            )
        ),
        commands=CommandContribution(
            action_handlers=(
                AttackHandler,
                SparHandler,
                DefendHandler,
                ChallengeHandler,
                FortifyHandler,
                RaidHandler,
                RepairItemHandler,
                PoisonCharacterHandler,
                TreatPoisonHandler,
                GainCorruptionHandler,
                CleanseCorruptionHandler,
                PickpocketHandler,
            ),
            typed_events=(
                StaminaChangedEvent,
                ExposureChangedEvent,
                HeatstrokeStartedEvent,
                FrostbiteStartedEvent,
                ExposureDamageEvent,
                ItemDamagedEvent,
                ItemBrokenEvent,
                ItemRepairedEvent,
                CharacterPoisonedEvent,
                PoisonProgressedEvent,
                PoisonTreatedEvent,
                CorruptionGainedEvent,
                CorruptionCleansedEvent,
            )
        ),
        runtime=RuntimeContribution(service_factories=(install_barbariansim,)),
        content=ContentContribution(prompt_fragments=(barbariansim_fragments,)),
    )


def gardensim_plugin() -> Plugin:
    return Plugin(
        id=GARDENSIM,
        name="Garden Sim",
        dependencies=DependencyContribution(
            requires=(CORE_VERBS,),
            recommends=(ENVIRONMENT, COLONYSIM),
        ),
        ecs=EcsContribution(
            components=(
                SoilComponent,
                TilledComponent,
                WateredComponent,
                FertilizerComponent,
                SeedComponent,
                CropComponent,
                CropGrowthComponent,
                HarvestableComponent,
            )
        ),
        commands=CommandContribution(
            action_handlers=(
                TillHandler,
                PlantHandler,
                WaterCropHandler,
                FertilizeHandler,
                HarvestCropHandler,
            ),
            typed_events=(
                SoilTilledEvent,
                SeedPlantedEvent,
                CropWateredEvent,
                FertilizerAppliedEvent,
                CropGrewEvent,
                CropReadyEvent,
                CropWitheredEvent,
                CropHarvestedEvent,
            ),
        ),
        runtime=RuntimeContribution(service_factories=(install_gardensim,)),
        content=ContentContribution(prompt_fragments=(gardensim_fragments,)),
    )


def dragonsim_plugin() -> Plugin:
    return Plugin(
        id=DRAGONSIM,
        name="Dragon Sim",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(
            components=(
                PointOfInterestComponent,
                DiscoveryComponent,
                QuestComponent,
                QuestStageComponent,
                QuestObjectiveComponent,
                QuestRewardComponent,
                FactionComponent,
                FactionReputationComponent,
            ),
            edges=(MemberOf,),
        ),
        commands=CommandContribution(
            action_handlers=(
                DiscoverLocationHandler,
                AcceptQuestHandler,
                CompleteObjectiveHandler,
                JoinFactionHandler,
                LeaveFactionHandler,
            ),
            typed_events=(
                LocationDiscoveredEvent,
                QuestAcceptedEvent,
                QuestObjectiveCompletedEvent,
                QuestCompletedEvent,
                FactionJoinedEvent,
                FactionLeftEvent,
            ),
        ),
        content=ContentContribution(prompt_fragments=(dragonsim_fragments,)),
    )


def daggersim_plugin() -> Plugin:
    return Plugin(
        id=DAGGERSIM,
        name="Dagger Sim",
        dependencies=DependencyContribution(
            requires=(CORE_VERBS,),
            recommends=(WORLDGEN,),
        ),
        ecs=EcsContribution(
            components=(
                ProceduralSiteComponent,
                UnrealizedLocationComponent,
                ExpansionHookComponent,
                RumorComponent,
                RumorSourceComponent,
                RumorReliabilityComponent,
                RumorTargetComponent,
                TravelHubComponent,
                TravelModeComponent,
                TravelPlanComponent,
                InstitutionComponent,
                InstitutionServiceComponent,
                QuestTemplateComponent,
                GeneratedQuestComponent,
                QuestDeadlineComponent,
                DaggerQuestRewardComponent,
                BankComponent,
                BankAccountComponent,
                LoanComponent,
                DebtComponent,
                LawRegionComponent,
                CrimeRecordComponent,
                BountyComponent,
                ClassTemplateComponent,
                CustomClassComponent,
                SpellTemplateComponent,
                CustomSpellComponent,
                LanguageSkillComponent,
                CreatureLanguageComponent,
                HostilityComponent,
                PacifiedComponent,
                SupernaturalAfflictionComponent,
                FeedingNeedComponent,
                WereformComponent,
                DungeonComponent,
                DungeonRoomComponent,
                DungeonObjectiveComponent,
                SecretDoorComponent,
                AutomapComponent,
                RecallAnchorComponent,
                RestRiskComponent,
                DialogueApproachComponent,
                EtiquetteSkillComponent,
                StreetwiseSkillComponent,
                SocialRegisterComponent,
                ConversationToneComponent,
            ),
            edges=(TravelRoute, MemberOfInstitution),
        ),
        commands=CommandContribution(
            action_handlers=(
                ExpandSiteHandler,
                AskRumorHandler,
                InvestigateRumorHandler,
                PlanTravelHandler,
                JoinInstitutionHandler,
                UseInstitutionServiceHandler,
                AskForWorkHandler,
                AcceptGeneratedQuestHandler,
                CompleteGeneratedQuestHandler,
                OpenBankAccountHandler,
                DepositHandler,
                WithdrawHandler,
                TakeLoanHandler,
                RepayLoanHandler,
                CommitCrimeHandler,
                PayFineHandler,
                CreateCustomClassHandler,
                CreateSpellHandler,
                CastSpellHandler,
                AttemptPacifyHandler,
                ContractAfflictionHandler,
                TransformHandler,
                RequestDungeonHandler,
                EnterDungeonHandler,
                SearchRoomHandler,
                OpenSecretDoorHandler,
                MarkPathHandler,
                ViewMapHandler,
                SetRecallHandler,
                UseRecallHandler,
                RestHandler,
                LeaveDungeonHandler,
            ),
            typed_events=(
                ExpansionRequestedEvent,
                GeneratedSiteInstantiatedEvent,
                RumorHeardEvent,
                RumorVerifiedEvent,
                RumorDisprovenEvent,
                RumorBecameExpansionEvent,
                TravelStartedEvent,
                TravelCompletedEvent,
                InstitutionJoinedEvent,
                InstitutionServiceUsedEvent,
                QuestGeneratedEvent,
                DaggerQuestAcceptedEvent,
                DaggerQuestCompletedEvent,
                QuestFailedEvent,
                AccountOpenedEvent,
                DepositMadeEvent,
                WithdrawalMadeEvent,
                LoanIssuedEvent,
                LoanRepaidEvent,
                LoanDefaultedEvent,
                CrimeCommittedEvent,
                BountyPostedEvent,
                FinePaidEvent,
                CustomClassCreatedEvent,
                SpellCreatedEvent,
                SpellCastEvent,
                PacificationAttemptedEvent,
                CreaturePacifiedEvent,
                AfflictionContractedEvent,
                FeedingNeedChangedEvent,
                TransformationStartedEvent,
                DungeonRequestedEvent,
                DungeonGeneratedEvent,
                DungeonEnteredEvent,
                DungeonRoomDiscoveredEvent,
                SecretDoorFoundEvent,
                RecallAnchorSetEvent,
                RecallUsedEvent,
                DungeonObjectiveFoundEvent,
                DungeonExitedEvent,
            ),
        ),
        runtime=RuntimeContribution(service_factories=(install_daggersim,)),
        content=ContentContribution(prompt_fragments=(daggersim_fragments,)),
    )


def voidsim_plugin() -> Plugin:
    return Plugin(
        id=VOIDSIM,
        name="Void Sim",
        dependencies=DependencyContribution(
            requires=(CORE_VERBS,),
            recommends=(WORLDGEN, ENVIRONMENT),
        ),
        ecs=EcsContribution(
            components=(
                ShipComponent,
                StationComponent,
                HabitatModuleComponent,
                AirlockComponent,
                BulkheadComponent,
                PressurizedComponent,
                LifeSupportComponent,
                ShipSystemComponent,
                PowerGridComponent,
                OxygenComponent,
                RadiationShieldComponent,
                StarSystemComponent,
                OrbitalBodyComponent,
                OrbitComponent,
                NavigationRouteComponent,
                JumpDriveComponent,
                FuelComponent,
                SensorComponent,
                DistressSignalComponent,
                AstrogationComponent,
            ),
            edges=(DockedTo, JumpRoute),
        ),
        commands=CommandContribution(
            action_handlers=(
                OpenAirlockHandler,
                CycleAirlockHandler,
                SealBulkheadHandler,
                RepairSystemHandler,
                ReroutePowerHandler,
                InspectShipSystemHandler,
                DockHandler,
                UndockHandler,
                EvacuateModuleHandler,
                PlotCourseHandler,
                JumpHandler,
                ScanHandler,
                AnswerDistressSignalHandler,
                RefuelHandler,
                EnterOrbitHandler,
                LeaveOrbitHandler,
                LandHandler,
                LaunchHandler,
            ),
            typed_events=(
                AirlockCycledEvent,
                PressureChangedEvent,
                LifeSupportFailedEvent,
                PowerReroutedEvent,
                ShipSystemDamagedEvent,
                ShipSystemRepairedEvent,
                DockingCompletedEvent,
                ModuleEvacuatedEvent,
                CoursePlottedEvent,
                JumpStartedEvent,
                JumpCompletedEvent,
                FuelChangedEvent,
                SignalDetectedEvent,
                NavigationHazardEncounteredEvent,
                OrbitEnteredEvent,
                LandingCompletedEvent,
            ),
        ),
        runtime=RuntimeContribution(service_factories=(install_voidsim,)),
        content=ContentContribution(prompt_fragments=(voidsim_fragments,)),
    )


def storyteller_plugin() -> Plugin:
    return Plugin(
        id=STORYTELLER,
        name="Storyteller",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(
            components=(
                StorytellerComponent,
                IncidentBudgetComponent,
                ThreatPointsComponent,
                IncidentHistoryComponent,
                IncidentComponent,
            )
        ),
        commands=CommandContribution(
            action_handlers=(ResolveIncidentHandler,),
            typed_events=(
                IncidentProposedEvent,
                IncidentStartedEvent,
                IncidentResolvedEvent,
            ),
        ),
        runtime=RuntimeContribution(service_factories=(install_storyteller,)),
        content=ContentContribution(prompt_fragments=(storyteller_fragments,)),
    )


def bunnyland_plugins() -> list[Plugin]:
    return [
        core_verbs_plugin(),
        lifesim_plugin(),
        memory_plugin(),
        worldgen_plugin(),
        environment_plugin(),
        mechanisms_plugin(),
        social_plugin(),
        policy_plugin(),
        persona_plugin(),
        colonysim_plugin(),
        barbariansim_plugin(),
        gardensim_plugin(),
        dragonsim_plugin(),
        daggersim_plugin(),
        voidsim_plugin(),
        storyteller_plugin(),
    ]


__all__ = [
    "BARBARIANSIM",
    "CORE_VERBS",
    "COLONYSIM",
    "DAGGERSIM",
    "DRAGONSIM",
    "ENVIRONMENT",
    "GARDENSIM",
    "LIFESIM",
    "MECHANISMS",
    "MEMORY",
    "PERSONA",
    "POLICY",
    "SOCIAL",
    "STORYTELLER",
    "VOIDSIM",
    "WORLDGEN",
    "barbariansim_plugin",
    "bunnyland_plugins",
    "colonysim_plugin",
    "core_verbs_plugin",
    "daggersim_plugin",
    "dragonsim_plugin",
    "environment_plugin",
    "gardensim_plugin",
    "storyteller_plugin",
    "lifesim_plugin",
    "mechanisms_plugin",
    "memory_plugin",
    "persona_plugin",
    "policy_plugin",
    "social_plugin",
    "voidsim_plugin",
    "worldgen_plugin",
]
