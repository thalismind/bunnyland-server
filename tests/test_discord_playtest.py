from __future__ import annotations

import json
from pathlib import Path

from bunnyland.core import (
    ButtonComponent,
    CharacterComponent,
    ContainerComponent,
    ContainmentMode,
    Contains,
    DoorComponent,
    ExitTo,
    HealthComponent,
    IdentityComponent,
    KeyComponent,
    LockableComponent,
    MemoryProfileComponent,
    PortableComponent,
    PutHandler,
    ReadableComponent,
    RoomComponent,
    SayHandler,
    SleepHandler,
    SleepingComponent,
    TakeHandler,
    TellHandler,
    UseHandler,
    WaitHandler,
    WakeHandler,
    WritableComponent,
    WriteHandler,
    container_of,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.events import (
    CharacterAttackedEvent,
    CharacterPickpocketedEvent,
    CommandRejectedEvent,
    ItemCraftedEvent,
    ItemDroppedEvent,
    ItemPutEvent,
    ItemTakenEvent,
    JobAssignedEvent,
    JobCompletedEvent,
    OwnershipClaimedEvent,
    OwnershipReleasedEvent,
    ResourceGatheredEvent,
)
from bunnyland.discord.playtest import (
    DiscordPlaytest,
    PlaytestInput,
    load_discord_playtest,
    run_discord_playtest,
)
from bunnyland.engine import GameLoop
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent
from bunnyland.mechanics import barbariansim as barb
from bunnyland.mechanics import colonysim as colony
from bunnyland.mechanics import daggersim as dagger
from bunnyland.mechanics import dinosim as dino
from bunnyland.mechanics import dragonsim as dragon
from bunnyland.mechanics import lifesim as life
from bunnyland.mechanics import nukesim as nuke
from bunnyland.mechanics import voidsim as void
from bunnyland.mechanics.colonysim import ClaimOwnershipHandler, Owns
from bunnyland.mechanics.consumables import ConsumableComponent, DrinkableComponent, FoodComponent
from bunnyland.mechanics.eat_drink import DrinkHandler, EatHandler
from bunnyland.mechanics.environment import (
    ExtinguishHandler,
    FireComponent,
    FireExtinguishedEvent,
    FireStartedEvent,
    FlammableComponent,
    IgniteHandler,
    install_environment,
)
from bunnyland.mechanics.gardensim import (
    CropComponent,
    CropGrowthConsequence,
    CropHarvestedEvent,
    CropReadyEvent,
    FertilizeHandler,
    FertilizerAppliedEvent,
    FertilizerComponent,
    HarvestableComponent,
    HarvestCropHandler,
    PlantHandler,
    SeedComponent,
    SoilComponent,
    TillHandler,
    WaterCropHandler,
)
from bunnyland.mechanics.lifesim import (
    BusinessSaleEvent,
    ClaimRoomHandler,
    CustomerComponent,
    HouseholdFundsComponent,
    OpenBusinessHandler,
    RoomClaimComponent,
    SellItemHandler,
)
from bunnyland.mechanics.mechanisms import (
    ButtonResetEvent,
    DoorAutoClosedEvent,
    install_mechanisms,
)
from bunnyland.mechanics.meter import Meter
from bunnyland.mechanics.needs import HungerComponent, HungerSystem, ThirstComponent, ThirstSystem
from bunnyland.mechanics.policy import BoundaryTag, install_policy
from bunnyland.mechanics.social import bond_between, install_social
from bunnyland.mechanics.storyteller import (
    IncidentBudgetComponent,
    IncidentComponent,
    IncidentResolvedEvent,
    IncidentStartedEvent,
    ResolveIncidentHandler,
    StorytellerComponent,
    install_storyteller,
)
from bunnyland.memory import InMemoryStore, install_memory
from bunnyland.memory.store import MemoryEntry
from bunnyland.prompts.builder import PromptBuilder

PLAYTEST_DIR = Path(__file__).resolve().parents[1] / "examples" / "playtests"


def _loop(actor) -> GameLoop:
    return GameLoop(
        actor,
        ControllerDispatch(actor, PromptBuilder(actor.world), ScriptedAgent([])),
        tick_seconds=1.0,
        time_scale=3600.0,
    )


def _install_gardening_playtest(actor) -> None:
    actor.register_handler(ClaimOwnershipHandler())
    actor.register_handler(TillHandler())
    actor.register_handler(FertilizeHandler())
    actor.register_handler(PlantHandler())
    actor.register_handler(WaterCropHandler())
    actor.register_handler(HarvestCropHandler())
    actor.register_handler(OpenBusinessHandler())
    actor.register_handler(SellItemHandler())
    actor.register_consequence(CropGrowthConsequence())


def _add_garden_market(scenario):
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HouseholdFundsComponent(balance=10))

    merchant = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Marigold", kind="character"),
            CharacterComponent(species="bunny"),
            CustomerComponent(budget=20),
            HouseholdFundsComponent(balance=0),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), merchant.id
    )

    soil = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="garden bed", kind="soil"), SoilComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), soil.id
    )
    seeds = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="radish seeds", kind="seed"),
            PortableComponent(can_pick_up=True),
            SeedComponent(
                crop_type="radish",
                growth_days=0.25,
                yield_item="radish",
                yield_quantity=2,
            ),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), seeds.id)
    fertilizer = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="speed compost", kind="fertilizer"),
            PortableComponent(can_pick_up=True),
            FertilizerComponent(kind="speed", growth_multiplier=2.0, quality_bonus=0.1),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), fertilizer.id)
    return soil.id, merchant.id, fertilizer.id


def _run_path(name: str) -> Path:
    return PLAYTEST_DIR / name


def _add_inventory_item(scenario, name: str, *, kind: str = "item", components=()):
    item = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind=kind), PortableComponent(can_pick_up=True), *components],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), item.id
    )
    return item.id


def _room_content(scenario, name: str, kind: str, components=()):
    entity = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind=kind), *components],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity.id


def _collect_rejections(actor) -> list[CommandRejectedEvent]:
    rejected: list[CommandRejectedEvent] = []
    actor.bus.subscribe(CommandRejectedEvent, rejected.append)
    return rejected


class _DeterministicMemoryStore(InMemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self._next = 1

    def add(
        self,
        collection: str,
        *,
        text: str,
        tags: tuple[str, ...] = (),
        created_at_epoch: int = 0,
        source: str = "manual",
    ) -> MemoryEntry:
        entry = MemoryEntry(
            id=f"note-{self._next}",
            text=text,
            tags=tuple(tags),
            created_at_epoch=created_at_epoch,
            source=source,
        )
        self._next += 1
        self._collections[collection].append(entry)
        return entry


def _install_core_actions_playtest(actor) -> None:
    for handler in (
        TakeHandler(),
        PutHandler(),
        UseHandler(),
        SayHandler(),
        TellHandler(),
        SleepHandler(),
        WakeHandler(),
        WaitHandler(),
        WriteHandler(),
    ):
        actor.register_handler(handler)
    install_social(actor)


def _add_core_actions_world(scenario):
    basket_id = _room_content(
        scenario,
        "woven basket",
        "container",
        [ContainerComponent(open=True, transparent=True)],
    )
    key_id = _room_content(
        scenario,
        "brass key",
        "key",
        [PortableComponent(can_pick_up=True), KeyComponent(key_name="burrow")],
    )
    pebble_id = _room_content(
        scenario,
        "smooth pebble",
        "item",
        [PortableComponent(can_pick_up=True)],
    )
    sign_id = _room_content(
        scenario,
        "blank sign",
        "sign",
        [ReadableComponent(title="blank sign"), WritableComponent(remaining_space=100)],
    )
    door_id = _room_content(
        scenario,
        "burrow door",
        "door",
        [DoorComponent(open=False), LockableComponent(locked=True, key_name="burrow")],
    )
    hazel_id = _room_content(
        scenario,
        "Hazel",
        "character",
        [CharacterComponent(species="bunny")],
    )
    return basket_id, key_id, pebble_id, sign_id, door_id, hazel_id


def _install_needs_memory_playtest(actor):
    actor.register_handler(EatHandler())
    actor.register_handler(DrinkHandler())
    actor.register_handler(WaitHandler())
    actor.world.register_system(HungerSystem())
    actor.world.register_system(ThirstSystem())
    return install_memory(actor, _DeterministicMemoryStore())


def _add_needs_memory_world(scenario):
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HungerComponent(meter=Meter(value=60.0), metabolism=6.0))
    character.add_component(ThirstComponent(meter=Meter(value=55.0), hydration_loss_rate=6.0))
    character.add_component(MemoryProfileComponent(vector_collection="juniper-memory"))
    food_id = _add_inventory_item(
        scenario,
        "berry tart",
        kind="food",
        components=[
            FoodComponent(nutrition=12.0, satiety=25.0),
            ConsumableComponent(current_uses=1, max_uses=1),
        ],
    )
    water_id = _room_content(
        scenario,
        "stone basin",
        "water",
        [DrinkableComponent(hydration=20.0, purity=1.0)],
    )
    return food_id, water_id


def _install_environment_mechanisms_playtest(actor) -> None:
    actor.register_handler(UseHandler())
    actor.register_handler(IgniteHandler())
    actor.register_handler(ExtinguishHandler())
    install_environment(actor)
    install_mechanisms(actor)


def _add_environment_mechanisms_world(scenario):
    door_id = _room_content(
        scenario,
        "green door",
        "door",
        [DoorComponent(open=False, auto_close_after_ticks=1)],
    )
    button_id = _room_content(
        scenario,
        "round button",
        "button",
        [ButtonComponent(active=True, toggle=False, reset_after_ticks=1)],
    )
    kindling_id = _room_content(
        scenario,
        "dry kindling",
        "item",
        [FlammableComponent(fuel=3.0)],
    )
    return door_id, button_id, kindling_id


def _install_storyteller_playtest(actor) -> None:
    actor.register_handler(ResolveIncidentHandler())
    install_storyteller(actor)


def _add_storyteller_world(scenario):
    storyteller = spawn_entity(
        scenario.actor.world,
        [
            StorytellerComponent(
                enabled=True, interval_seconds=24 * 3600, next_incident_epoch=3600
            ),
            IncidentBudgetComponent(points=2.0, points_per_day=0.0, last_updated_epoch=0),
        ],
    )
    return storyteller.id


def _install_colonysim_playtest(actor) -> None:
    actor.register_handler(colony.ReserveHandler())
    actor.register_handler(colony.ReleaseReservationHandler())
    actor.register_handler(colony.GatherResourceHandler())
    actor.register_handler(colony.CraftHandler())
    actor.register_handler(colony.AssignJobHandler())
    actor.register_handler(colony.CompleteJobHandler())
    actor.register_handler(colony.ClaimOwnershipHandler())
    actor.register_handler(colony.ReleaseOwnershipHandler())
    actor.world.register_system(colony.ResourceRegenSystem())


def _add_colonysim_loop_world(scenario):
    node_id = _room_content(
        scenario,
        "wood patch",
        "resource_node",
        [colony.ResourceNodeComponent(resource_type="wood", current=4, maximum=4)],
    )
    job_id = _room_content(
        scenario,
        "haul job",
        "job",
        [colony.JobComponent(job_type="haul", priority=5)],
    )
    _room_content(
        scenario,
        "Workbench",
        "workstation",
        [colony.WorkstationComponent(station_type="bench")],
    )
    recipe = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="club recipe", kind="recipe"),
            colony.RecipeComponent(
                recipe_id="club",
                inputs={"wood": 2},
                outputs={"club": 1},
                required_station="bench",
            ),
        ],
    )
    return node_id, job_id, recipe.id


def _install_dinosim_playtest(actor) -> None:
    dino.install_dinosim(actor)
    actor.register_handler(dino.IdentifyFossilHandler())
    actor.register_handler(dino.ExtractAncientSampleHandler())
    actor.register_handler(dino.PrepareCloneHandler())
    actor.register_handler(dino.LayEggHandler())
    actor.register_handler(dino.FertilizeEggHandler())
    actor.register_handler(dino.IncubateEggHandler())
    actor.register_handler(dino.HatchEggHandler())


def _add_dinosim_loop_world(scenario):
    fossil_id = _room_content(
        scenario,
        "amber bone shard",
        "fossil",
        [dino.FossilFragmentComponent(sample_quality=0.8)],
    )
    parent_id = _room_content(
        scenario,
        "clever raptor",
        "character",
        [
            CharacterComponent(species="velociraptor"),
            dino.DinosaurComponent(species_name="velociraptor"),
            dino.FertilityComponent(),
            dino.ReptileProcreationComponent(egg_species_name="velociraptor"),
        ],
    )
    return fossil_id, parent_id


def _add_dinosim_kaiju_world(scenario):
    install_storyteller(scenario.actor)
    colony.install_colonysim(scenario.actor)
    dino.install_dinosim(scenario.actor)
    storyteller = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="kaiju storyteller", kind="controller"),
            StorytellerComponent(interval_seconds=24 * 3600, next_incident_epoch=3600),
            IncidentBudgetComponent(points=20.0, points_per_day=0.0),
        ],
    )
    return storyteller.id


def _install_nukesim_playtest(actor) -> None:
    nuke.install_nukesim(actor)
    actor.register_handler(nuke.ScanRadiationHandler())
    actor.register_handler(nuke.SealRadiationSourceHandler())
    actor.register_handler(nuke.DecontaminateHandler())
    actor.register_handler(nuke.UseRadMedicineHandler())
    actor.register_handler(nuke.ScavengeHandler())
    actor.register_handler(nuke.ScrapItemHandler())
    actor.register_handler(nuke.StabilizeMutationHandler())


def _add_nukesim_loop_world(scenario):
    source_id = _room_content(
        scenario,
        "isotope case",
        "radiation-source",
        [nuke.RadiationSourceComponent(rads_per_hour=1.0)],
    )
    site_id = _room_content(
        scenario,
        "pharmacy cache",
        "scavenge-site",
        [
            nuke.ScavengeSiteComponent(site_type="pharmacy", charges=1, hazard_rads=2.0),
            nuke.LootTableComponent(outputs={"scrap": 2, "cloth": 1}),
        ],
    )
    station_id = _room_content(
        scenario,
        "decon arch",
        "decontamination",
        [
            nuke.DecontaminationComponent(
                dose_reduction=3.0,
                sickness_reduction=2.0,
                mutation_pressure_reduction=3.0,
            )
        ],
    )
    med_id = _add_inventory_item(
        scenario,
        "rad-away",
        kind="medicine",
        components=[nuke.RadMedicineComponent(dose_reduction=2.0)],
    )
    junk_id = _add_inventory_item(
        scenario,
        "bent pressure cooker",
        kind="junk",
        components=[nuke.JunkComponent(outputs={"scrap": 2}, contaminated_rads=1.0)],
    )
    return source_id, site_id, station_id, med_id, junk_id


def _install_barbariansim_playtest(actor) -> None:
    install_policy(actor, enabled=frozenset({BoundaryTag.PVP, BoundaryTag.PICKPOCKETING}))
    barb.install_barbariansim(actor)
    actor.register_handler(barb.AttackHandler())
    actor.register_handler(barb.SparHandler())
    actor.register_handler(barb.DefendHandler())
    actor.register_handler(barb.ChallengeHandler())
    actor.register_handler(barb.FortifyHandler())
    actor.register_handler(barb.RaidHandler())
    actor.register_handler(barb.RepairItemHandler())
    actor.register_handler(barb.PoisonCharacterHandler())
    actor.register_handler(barb.TreatPoisonHandler())
    actor.register_handler(barb.GainCorruptionHandler())
    actor.register_handler(barb.CleanseCorruptionHandler())
    actor.register_handler(barb.PickpocketHandler())


def _add_barbariansim_loop_world(scenario):
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HealthComponent(current=20.0, maximum=20.0))
    character.add_component(barb.StaminaComponent(current=20.0, maximum=20.0, regen_per_hour=5.0))
    target_id = _room_content(
        scenario,
        "Ash",
        "character",
        [
            CharacterComponent(species="bunny"),
            HealthComponent(current=20.0, maximum=20.0),
        ],
    )
    weapon_id = _add_inventory_item(
        scenario,
        "Axe",
        kind="weapon",
        components=[
            barb.WeaponComponent(damage=6.0, damage_type="slash", lethal_capable=True),
            barb.DurabilityComponent(current=1.0, maximum=2.0),
        ],
    )
    coin_id = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Coin", kind="item"), PortableComponent(can_pick_up=True)],
    )
    scenario.actor.world.get_entity(target_id).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), coin_id.id
    )
    palisade_id = _room_content(scenario, "wooden palisade", "fortification")
    return target_id, weapon_id, coin_id.id, palisade_id


def _install_dragonsim_playtest(actor) -> None:
    actor.register_handler(dragon.DiscoverLocationHandler())
    actor.register_handler(dragon.AcceptQuestHandler())
    actor.register_handler(dragon.CompleteObjectiveHandler())
    actor.register_handler(dragon.JoinFactionHandler())
    actor.register_handler(dragon.LeaveFactionHandler())


def _add_dragonsim_loop_world(scenario):
    poi_id = _room_content(
        scenario,
        "old watchtower",
        "location",
        [dragon.PointOfInterestComponent(location_type="ruin", region="north meadow")],
    )
    quest = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Find the Lost Ring", kind="quest"),
            dragon.QuestComponent(quest_id="lost-ring", title="Find the Lost Ring"),
        ],
    )
    objective = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="lost ring objective", kind="objective"),
            dragon.QuestObjectiveComponent(
                quest_id="lost-ring",
                description="Recover the ring from the watchtower",
            ),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), quest.id
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), objective.id
    )
    reward_item = _room_content(scenario, "silver carrot", "item", [PortableComponent()])
    reward = spawn_entity(
        scenario.actor.world,
        [
            dragon.QuestRewardComponent(
                quest_id="lost-ring",
                description="A silver carrot",
                item_ids=(str(reward_item),),
            )
        ],
    )
    faction_id = _room_content(
        scenario,
        "Moss Wardens",
        "faction",
        [dragon.FactionComponent(name="Moss Wardens", ideology="protect the burrow")],
    )
    return poi_id, quest.id, objective.id, reward.id, reward_item, faction_id


def _install_lifesim_playtest(actor) -> None:
    install_policy(
        actor,
        enabled=frozenset({BoundaryTag.ROMANCE, BoundaryTag.ADULT, BoundaryTag.PREGNANCY}),
    )
    life.install_lifesim(actor)
    for handler in (
        life.ChooseAspirationHandler(),
        life.CompleteMilestoneHandler(),
        life.PracticeSkillHandler(),
        life.StudySkillHandler(),
        life.FindJobHandler(),
        life.GoToWorkHandler(),
        life.AssessTaxHandler(),
        life.PayBillHandler(),
        life.OpenBusinessHandler(),
        life.SellItemHandler(),
        life.PromoteBusinessHandler(),
        life.JoinHouseholdHandler(),
        life.ClaimHomeHandler(),
        life.ClaimRoomHandler(),
        life.SetRoutineHandler(),
        life.SetRelationshipStatusHandler(),
        life.SpreadGossipHandler(),
        life.StartPartnershipHandler(),
        life.StartPregnancyHandler(),
        life.ResolveBirthHandler(),
        life.AdoptChildHandler(),
    ):
        actor.register_handler(handler)


def _add_lifesim_loop_world(scenario):
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(life.ReproductiveComponent(can_be_pregnant=True))
    partner_id = _room_content(
        scenario,
        "Hazel",
        "character",
        [
            CharacterComponent(species="bunny"),
            life.ReproductiveComponent(can_cause_pregnancy=True),
        ],
    )
    child_id = _room_content(
        scenario,
        "Clover",
        "character",
        [CharacterComponent(species="bunny"), life.LifeStageComponent(stage="child")],
    )
    item_id = _add_inventory_item(scenario, "berry tart")
    customer_id = _room_content(
        scenario,
        "Marigold",
        "character",
        [CharacterComponent(species="bunny"), life.CustomerComponent(budget=30)],
    )
    return partner_id, child_id, item_id, customer_id


def _install_daggersim_playtest(actor) -> None:
    for handler in (
        dagger.ExpandSiteHandler(),
        dagger.AskRumorHandler(),
        dagger.InvestigateRumorHandler(),
        dagger.PlanTravelHandler(),
        dagger.JoinInstitutionHandler(),
        dagger.UseInstitutionServiceHandler(),
        dagger.AskForWorkHandler(),
        dagger.AcceptGeneratedQuestHandler(),
        dagger.CompleteGeneratedQuestHandler(),
        dagger.OpenBankAccountHandler(),
        dagger.DepositHandler(),
        dagger.WithdrawHandler(),
        dagger.TakeLoanHandler(),
        dagger.RepayLoanHandler(),
        dagger.CommitCrimeHandler(),
        dagger.PayFineHandler(),
        dagger.CreateCustomClassHandler(),
        dagger.CreateSpellHandler(),
        dagger.EnchantItemHandler(),
        dagger.CastSpellHandler(),
        dagger.AttemptPacifyHandler(),
        dagger.ContractAfflictionHandler(),
        dagger.TransformHandler(),
        dagger.RequestDungeonHandler(),
        dagger.EnterDungeonHandler(),
        dagger.SearchRoomHandler(),
        dagger.OpenSecretDoorHandler(),
        dagger.MarkPathHandler(),
        dagger.ViewMapHandler(),
        dagger.SetRecallHandler(),
        dagger.UseRecallHandler(),
        dagger.RestHandler(),
        dagger.LeaveDungeonHandler(),
    ):
        actor.register_handler(handler)
    actor.register_consequence(dagger.TravelCompletionConsequence())
    actor.register_consequence(dagger.QuestDeadlineConsequence())
    actor.register_consequence(dagger.LoanDueConsequence())
    actor.register_consequence(dagger.FeedingNeedConsequence())


def _add_daggersim_rumor_world(scenario):
    site_id = _room_content(
        scenario,
        "Rain Garden Hamlet",
        "settlement",
        [
            dagger.ProceduralSiteComponent(site_type="hamlet", seed="rain-garden"),
            dagger.UnrealizedLocationComponent(
                summary="a damp trading stop at the edge of the moss road",
                region_id="moss-road",
            ),
            dagger.ExpansionHookComponent(
                trigger="rumor", generator_plugin_id="worldgen.recursive"
            ),
        ],
    )
    rumor_id = _room_content(
        scenario,
        "carrot vault rumor",
        "rumor",
        [
            dagger.RumorComponent(text="The old carrot vault beneath Rain Garden still exists."),
            dagger.RumorReliabilityComponent(score=1.0),
            dagger.RumorTargetComponent(target_id=str(site_id)),
        ],
    )
    origin = scenario.actor.world.get_entity(scenario.room_a)
    destination = scenario.actor.world.get_entity(scenario.room_b)
    origin.add_component(dagger.TravelHubComponent(name="Mosslit Burrow", region_id="moss-road"))
    destination.add_component(dagger.TravelHubComponent(name="North Tunnel", region_id="moss-road"))
    origin.add_relationship(
        dagger.TravelRoute(travel_seconds=2 * 3600, label="moss road"),
        scenario.room_b,
    )
    return site_id, rumor_id


def _add_daggersim_economy_world(scenario):
    institution = _room_content(
        scenario,
        "Burrow Cartographers",
        "institution",
        [dagger.InstitutionComponent(name="Burrow Cartographers", institution_type="guild")],
    )
    service = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="local map service", kind="service"),
            dagger.InstitutionServiceComponent(
                service_name="local map",
                required_rank="member",
                output_item_name="moss road map",
            ),
        ],
    )
    scenario.actor.world.get_entity(institution).add_relationship(
        Contains(mode=ContainmentMode.CONTAINER), service.id
    )
    template = _room_content(
        scenario,
        "ratcatcher errand",
        "quest-template",
        [
            dagger.QuestTemplateComponent(
                title="Clear the North Tunnel",
                objective="Drive the rats away from the old milestone.",
                reward_item_name="guild writ",
                duration_seconds=10 * 3600,
            )
        ],
    )
    bank = _room_content(
        scenario,
        "Carrot Factors Bank",
        "bank",
        [dagger.BankComponent(name="Carrot Factors Bank", region_id="moss-road")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_component(
        dagger.LawRegionComponent(region_id="moss-road", fines={"trespass": 15, "default": 10})
    )
    return institution, service.id, template, bank


def _add_daggersim_magic_world(scenario):
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HealthComponent(current=3.0, maximum=10.0))
    class_template = _room_content(
        scenario,
        "Moonlit Forager template",
        "class-template",
        [
            dagger.ClassTemplateComponent(
                class_name="Moonlit Forager",
                primary_skills=("foraging", "stealth", "gardening"),
                major_skills=("cooking", "animal speech", "memory"),
                minor_skills=("etiquette", "knife", "weather lore"),
                advantages=("night vision",),
                disadvantages=("heat weakness",),
            )
        ],
    )
    spell_template = _room_content(
        scenario,
        "mend sprout formula",
        "spell-template",
        [dagger.SpellTemplateComponent(spell_name="Mend Sprout", effect_type="heal", magnitude=4)],
    )
    charm = _add_inventory_item(scenario, "moss charm")
    creature = _room_content(
        scenario,
        "moon moth",
        "creature",
        [
            dagger.CreatureLanguageComponent(language="Mothwing", pacification_difficulty=2),
            dagger.HostilityComponent(hostile=True),
        ],
    )
    character.add_component(dagger.LanguageSkillComponent(languages={"Mothwing": 2}))
    return class_template, spell_template, charm, creature


def _add_daggersim_dungeon_world(scenario):
    entry = spawn_entity(
        scenario.actor.world,
        [RoomComponent(title="Vault Antechamber"), dagger.DungeonRoomComponent("carrot-vault", 0)],
    )
    deeper = spawn_entity(
        scenario.actor.world,
        [RoomComponent(title="Inner Vault"), dagger.DungeonRoomComponent("carrot-vault", 1)],
    )
    dungeon = _room_content(
        scenario,
        "Carrot Vault",
        "dungeon",
        [
            dagger.DungeonComponent(
                dungeon_id="carrot-vault",
                theme="ruin",
                seed="cv-1",
                entry_room_id=str(entry.id),
                generated=False,
            ),
            dagger.ExpansionHookComponent(
                trigger="quest", generator_plugin_id="worldgen.recursive"
            ),
        ],
    )
    door = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="cracked tiles", kind="secret-door"),
            dagger.SecretDoorComponent(
                target_room_id=str(deeper.id),
                direction="down",
                hint="a draft behind the tiles",
            ),
        ],
    )
    objective = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="the carrot reliquary", kind="objective"),
            dagger.DungeonObjectiveComponent(
                objective_kind="relic",
                description="the lost reliquary",
            ),
        ],
    )
    scenario.actor.world.get_entity(entry.id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), door.id
    )
    scenario.actor.world.get_entity(entry.id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), objective.id
    )
    scenario.actor.world.get_entity(entry.id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), dungeon
    )
    return dungeon, entry.id, deeper.id, door.id, objective.id


def _install_voidsim_playtest(actor) -> None:
    for handler in (
        void.OpenAirlockHandler(),
        void.CycleAirlockHandler(),
        void.SealBulkheadHandler(),
        void.RepairSystemHandler(),
        void.ReroutePowerHandler(),
        void.InspectShipSystemHandler(),
        void.DockHandler(),
        void.UndockHandler(),
        void.EvacuateModuleHandler(),
        void.PlotCourseHandler(),
        void.JumpHandler(),
        void.ScanHandler(),
        void.AnswerDistressSignalHandler(),
        void.RefuelHandler(),
        void.EnterOrbitHandler(),
        void.LeaveOrbitHandler(),
        void.LandHandler(),
        void.LaunchHandler(),
    ):
        actor.register_handler(handler)
    actor.register_consequence(void.LifeSupportConsequence())
    actor.register_consequence(void.JumpTravelConsequence())
    actor.register_consequence(void.ChaosInfluenceConsequence())


def _add_voidsim_systems_world(scenario):
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(void.HabitatModuleComponent(module_type="bridge"))
    room.add_component(void.PressurizedComponent(pressure=1.0))
    room.add_component(void.OxygenComponent(level=10.0, maximum=100.0))
    room.add_component(void.LifeSupportComponent(online=False, oxygen_per_hour=100.0))
    airlock = _room_content(
        scenario,
        "port airlock",
        "airlock",
        [void.AirlockComponent(module_id=str(scenario.room_a), exposes_vacuum=True)],
    )
    bulkhead = _room_content(scenario, "aft bulkhead", "bulkhead", [void.BulkheadComponent()])
    grid = _room_content(
        scenario,
        "main bus",
        "power-grid",
        [void.PowerGridComponent(available=100.0)],
    )
    system = _room_content(
        scenario,
        "life support unit",
        "ship-system",
        [void.ShipSystemComponent(system_type="life-support", integrity=40.0, online=False)],
    )
    other = _room_content(
        scenario,
        "Ensign Clover",
        "character",
        [CharacterComponent(species="bunny")],
    )
    return airlock, bulkhead, grid, system, other


def _add_voidsim_navigation_world(scenario):
    scenario.actor.world.get_entity(scenario.room_a).add_component(void.StarSystemComponent("Sol"))
    scenario.actor.world.get_entity(scenario.room_b).add_component(
        void.StarSystemComponent("Proxima")
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        void.JumpRoute(fuel_cost=10.0, hazard="none", jump_seconds=1, label="moss lane"),
        scenario.room_b,
    )
    ship = _room_content(
        scenario,
        "Burrow Runner",
        "ship",
        [
            void.ShipComponent(name="Burrow Runner"),
            void.FuelComponent(level=20.0, maximum=100.0),
            void.JumpDriveComponent(),
            void.SensorComponent(),
        ],
    )
    station = _room_content(
        scenario,
        "Moss Station",
        "station",
        [void.StationComponent(name="Moss Station")],
    )
    signal = _room_content(
        scenario,
        "mayday beacon",
        "signal",
        [void.DistressSignalComponent(text="Hull breach, send aid.")],
    )
    body = _room_content(
        scenario,
        "Moss Moon",
        "orbital-body",
        [void.OrbitalBodyComponent(body_type="moon", landable=True)],
    )
    return ship, station, signal, body


def _add_voidsim_chaos_world(scenario):
    scenario.actor.world.get_entity(scenario.room_a).add_component(
        void.HabitatModuleComponent(module_type="chapel")
    )
    source = _room_content(
        scenario,
        "warp breach",
        "chaos-source",
        [
            void.ChaosInfluenceComponent(
                source_type="warp breach",
                corruption_per_hour=2.0,
                mutation_pressure_per_corruption=0.5,
            )
        ],
    )
    ward = _room_content(
        scenario,
        "gellar charm",
        "ward",
        [void.ChaosWardComponent(protection_per_hour=1.0)],
    )
    return source, ward


async def test_discord_playtest_schedules_inputs_by_tick(scenario):
    spec = DiscordPlaytest(
        ticks=2,
        inputs=(
            PlaytestInput(
                tick=0,
                user_id=123,
                channel_id=456,
                content="!claim Juniper",
                expect=("You are now controlling Juniper.",),
            ),
            PlaytestInput(
                tick=1,
                user_id=123,
                channel_id=456,
                content="!move north",
                expect=("You are now in North Tunnel",),
            ),
        ),
    )

    result = await run_discord_playtest(_loop(scenario.actor), spec)

    assert result.ticks == 2
    assert scenario.character_room() == scenario.room_b
    assert result.inputs[1].reactions
    assert "You are now in North Tunnel" in result.inputs[1].messages[0]


async def test_discord_playtest_writes_trace_artifacts(scenario, tmp_path, monkeypatch):
    monkeypatch.setenv("BUNNYLAND_PLAYTEST_TRACE_DIR", str(tmp_path))
    spec = DiscordPlaytest(
        name="trace-smoke",
        ticks=2,
        inputs=(
            PlaytestInput(
                tick=0,
                user_id=123,
                channel_id=456,
                content="!claim Juniper",
                expect=("You are now controlling Juniper.",),
            ),
            PlaytestInput(
                tick=1,
                user_id=123,
                channel_id=456,
                content="!move north",
                expect=("You are now in North Tunnel",),
            ),
        ),
    )

    await run_discord_playtest(_loop(scenario.actor), spec)

    trace_path = next(tmp_path.glob("*.trace.json"))
    world_path = next(tmp_path.glob("*.world.json"))
    trace = json.loads(trace_path.read_text())
    assert trace["status"] == "passed"
    assert trace["received_messages"][0]["content"] == "!claim Juniper"
    assert trace["sent_messages"][0]["content"] == "<@123> You are now controlling Juniper."
    assert trace["inputs"][1]["content"] == "!move north"
    assert trace["inputs"][1]["messages"] == [
        "<@123> You are now in North Tunnel\nHere: Juniper.\nExits: south."
    ]
    assert any(item["command"]["command_type"] == "move" for item in trace["commands"])
    assert any(
        item["event_type"] == "CommandExecutedEvent" and item["command_type"] == "move"
        for item in trace["events"]
    )
    assert trace["final_world_path"] == world_path.name
    assert trace["final_epoch"] == scenario.actor.epoch
    assert trace["final_world"]["bunnyland"]["saved_at_epoch"] == scenario.actor.epoch
    assert trace["final_world"] == json.loads(world_path.read_text())


async def test_discord_playtest_schedules_inputs_by_starting_epoch(scenario):
    spec = DiscordPlaytest(
        ticks=2,
        inputs=(
            PlaytestInput(
                tick=0,
                user_id=123,
                channel_id=456,
                content="!claim Juniper",
                expect=("You are now controlling Juniper.",),
            ),
            PlaytestInput(
                epoch=3600,
                user_id=123,
                channel_id=456,
                content="!move north",
                expect=("You are now in North Tunnel",),
            ),
        ),
    )

    result = await run_discord_playtest(_loop(scenario.actor), spec)

    assert scenario.character_room() == scenario.room_b
    assert result.inputs[1].tick == 1
    assert result.inputs[1].epoch == 3600


async def test_discord_playtest_character_claims_current_room(scenario):
    scenario.actor.register_handler(ClaimRoomHandler())
    spec = load_discord_playtest(PLAYTEST_DIR / "discord-claim-room.json")

    result = await run_discord_playtest(_loop(scenario.actor), spec)

    room = scenario.actor.world.get_entity(scenario.room_a)
    claim = room.get_component(RoomClaimComponent)
    assert result.ticks == 2
    assert result.inputs[1].reactions
    assert "Room claimed: Mosslit Burrow" in result.inputs[1].messages[0]
    assert claim.claimed_by_id == str(scenario.character)
    assert claim.claimed_at_epoch == scenario.actor.epoch


async def test_discord_playtest_core_actions_loop(scenario):
    _install_core_actions_playtest(scenario.actor)
    basket_id, _key_id, pebble_id, sign_id, door_id, hazel_id = _add_core_actions_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    taken: list[ItemTakenEvent] = []
    put: list[ItemPutEvent] = []
    dropped: list[ItemDroppedEvent] = []
    scenario.actor.bus.subscribe(ItemTakenEvent, taken.append)
    scenario.actor.bus.subscribe(ItemPutEvent, put.append)
    scenario.actor.bus.subscribe(ItemDroppedEvent, dropped.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-core-actions.json")),
    )

    sign = scenario.actor.world.get_entity(sign_id)
    door = scenario.actor.world.get_entity(door_id)
    hazel_bond = bond_between(scenario.actor.world, scenario.character, hazel_id)
    pebble = scenario.actor.world.get_entity(pebble_id)
    assert rejected == []
    assert result.ticks == 15
    assert len(result.inputs) == 15
    assert taken and put and dropped
    assert container_of(pebble) == scenario.room_a
    assert put[0].to_container_id == str(basket_id)
    assert sign.get_component(ReadableComponent).text == "Meet at dawn"
    assert door.get_component(DoorComponent).open is True
    assert not scenario.actor.world.get_entity(scenario.character).has_component(SleepingComponent)
    assert hazel_bond is not None
    assert hazel_bond.affinity > 0
    assert hazel_bond.familiarity > 0


async def test_discord_playtest_needs_and_memory_loop(scenario):
    _install_needs_memory_playtest(scenario.actor)
    food_id, water_id = _add_needs_memory_world(scenario)
    rejected = _collect_rejections(scenario.actor)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-needs-memory.json")),
    )

    character = scenario.actor.world.get_entity(scenario.character)
    assert rejected == []
    assert result.ticks == 8
    assert len(result.inputs) == 8
    assert not scenario.actor.world.has_entity(food_id)
    assert scenario.actor.world.has_entity(water_id)
    assert character.get_component(HungerComponent).meter.value > 35.0
    assert character.get_component(ThirstComponent).meter.value > 35.0
    assert character.get_component(MemoryProfileComponent).last_reflection_epoch > 0


async def test_discord_playtest_environment_and_mechanisms_loop(scenario):
    _install_environment_mechanisms_playtest(scenario.actor)
    door_id, button_id, kindling_id = _add_environment_mechanisms_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    closed: list[DoorAutoClosedEvent] = []
    reset: list[ButtonResetEvent] = []
    started: list[FireStartedEvent] = []
    extinguished: list[FireExtinguishedEvent] = []
    scenario.actor.bus.subscribe(DoorAutoClosedEvent, closed.append)
    scenario.actor.bus.subscribe(ButtonResetEvent, reset.append)
    scenario.actor.bus.subscribe(FireStartedEvent, started.append)
    scenario.actor.bus.subscribe(FireExtinguishedEvent, extinguished.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-environment-mechanisms.json")),
    )

    door = scenario.actor.world.get_entity(door_id)
    button = scenario.actor.world.get_entity(button_id)
    kindling = scenario.actor.world.get_entity(kindling_id)
    assert rejected == []
    assert result.ticks == 7
    assert len(result.inputs) == 5
    assert door.get_component(DoorComponent).open is False
    assert button.get_component(ButtonComponent).pressed is False
    assert not kindling.has_component(FireComponent)
    assert closed and closed[0].door_id == str(door_id)
    assert reset and reset[0].button_id == str(button_id)
    assert started and extinguished


async def test_discord_playtest_storyteller_incident_loop(scenario):
    _install_storyteller_playtest(scenario.actor)
    _add_storyteller_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    started: list[IncidentStartedEvent] = []
    resolved: list[IncidentResolvedEvent] = []
    scenario.actor.bus.subscribe(IncidentStartedEvent, started.append)
    scenario.actor.bus.subscribe(IncidentResolvedEvent, resolved.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-storyteller-incidents.json")),
    )

    incidents = list(
        scenario.actor.world.query().with_all([IncidentComponent]).execute_entities()
    )
    assert rejected == []
    assert result.ticks == 3
    assert len(result.inputs) == 3
    assert len(incidents) == 1
    assert incidents[0].get_component(IncidentComponent).resolved_at_epoch is not None
    assert started and started[0].kind == "resource_drop"
    assert resolved and resolved[0].kind == "resource_drop"


async def test_discord_playtest_character_gardens_claimed_land_end_to_end(scenario):
    _install_gardening_playtest(scenario.actor)
    soil_id, merchant_id, fertilizer_id = _add_garden_market(scenario)
    rejected: list[CommandRejectedEvent] = []
    ready: list[CropReadyEvent] = []
    harvested: list[CropHarvestedEvent] = []
    fertilized: list[FertilizerAppliedEvent] = []
    sold: list[BusinessSaleEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejected.append)
    scenario.actor.bus.subscribe(CropReadyEvent, ready.append)
    scenario.actor.bus.subscribe(CropHarvestedEvent, harvested.append)
    scenario.actor.bus.subscribe(FertilizerAppliedEvent, fertilized.append)
    scenario.actor.bus.subscribe(BusinessSaleEvent, sold.append)
    spec = load_discord_playtest(PLAYTEST_DIR / "discord-gardening.json")

    result = await run_discord_playtest(_loop(scenario.actor), spec)

    character = scenario.actor.world.get_entity(scenario.character)
    merchant = scenario.actor.world.get_entity(merchant_id)
    soil = scenario.actor.world.get_entity(soil_id)
    harvested_item = scenario.actor.world.get_entity(parse_entity_id(harvested[0].item_id))
    assert rejected == []
    assert result.ticks == 34
    assert len(result.inputs) == 9
    assert character.has_relationship(Owns, soil_id)
    assert len(fertilized) == 1
    assert fertilized[0].fertilizer_id == str(fertilizer_id)
    assert container_of(scenario.actor.world.get_entity(fertilizer_id)) is None
    assert len(ready) == 1
    assert ready[0].soil_id == str(soil_id)
    assert len(harvested) == 1
    assert harvested_item.get_component(IdentityComponent).name == "radish x2"
    assert container_of(harvested_item) is None
    assert not soil.has_component(CropComponent)
    assert not soil.has_component(HarvestableComponent)
    assert len(sold) == 1
    assert sold[0].price == 8
    assert character.get_component(HouseholdFundsComponent).balance == 18
    assert merchant.get_component(HouseholdFundsComponent).balance == 0
    assert merchant.get_component(CustomerComponent).budget == 12


async def test_discord_playtest_colonysim_core_loop(scenario):
    _install_colonysim_playtest(scenario.actor)
    node_id, job_id, _recipe_id = _add_colonysim_loop_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    gathered: list[ResourceGatheredEvent] = []
    crafted: list = []
    assigned: list = []
    completed: list = []
    claimed: list = []
    released: list = []
    scenario.actor.bus.subscribe(ResourceGatheredEvent, gathered.append)
    scenario.actor.bus.subscribe(ItemCraftedEvent, crafted.append)
    scenario.actor.bus.subscribe(JobAssignedEvent, assigned.append)
    scenario.actor.bus.subscribe(JobCompletedEvent, completed.append)
    scenario.actor.bus.subscribe(OwnershipClaimedEvent, claimed.append)
    scenario.actor.bus.subscribe(OwnershipReleasedEvent, released.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-colonysim-core.json")),
    )

    character = scenario.actor.world.get_entity(scenario.character)
    node = scenario.actor.world.get_entity(node_id)
    job = scenario.actor.world.get_entity(job_id)
    assert rejected == []
    assert result.ticks == 9
    assert len(result.inputs) == 9
    assert node.get_component(colony.ResourceNodeComponent).current == 2
    assert len(gathered) == 1
    assert len(crafted) == 1
    crafted_item = scenario.actor.world.get_entity(parse_entity_id(crafted[0].output_ids[0]))
    assert crafted_item.get_component(colony.ResourceStackComponent).resource_type == "club"
    assert container_of(crafted_item) == scenario.character
    assert job.get_component(colony.JobComponent).completed is True
    assert assigned and completed
    assert claimed and released
    assert not node.has_relationship(colony.ReservedBy, scenario.character)
    assert not character.has_relationship(Owns, node_id)


async def test_discord_playtest_dinosim_lifecycle_loop(scenario):
    _install_dinosim_playtest(scenario.actor)
    fossil_id, _parent_id = _add_dinosim_loop_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    identified: list[dino.FossilIdentifiedEvent] = []
    extracted: list[dino.AncientSampleExtractedEvent] = []
    clones: list[dino.ClonePreparedEvent] = []
    hatched: list[dino.EggHatchedEvent] = []
    scenario.actor.bus.subscribe(dino.FossilIdentifiedEvent, identified.append)
    scenario.actor.bus.subscribe(dino.AncientSampleExtractedEvent, extracted.append)
    scenario.actor.bus.subscribe(dino.ClonePreparedEvent, clones.append)
    scenario.actor.bus.subscribe(dino.EggHatchedEvent, hatched.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-dinosim-lifecycle.json")),
    )

    fossil = scenario.actor.world.get_entity(fossil_id)
    hatchlings = [
        entity
        for entity in scenario.actor.world.query()
        .with_all([dino.DinosaurComponent, dino.HatchlingComponent])
        .execute_entities()
    ]
    assert rejected == []
    assert result.ticks == 12
    assert len(result.inputs) == 12
    assert fossil.get_component(dino.SpeciesIdentificationComponent).species_name == "velociraptor"
    assert identified and extracted and clones
    assert len(hatched) == 2
    assert len(hatchlings) == 2
    assert all(
        entity.get_component(CharacterComponent).species == "velociraptor"
        for entity in hatchlings
    )


async def test_discord_playtest_dinosim_kaiju_incident_loop(scenario):
    scenario.actor.register_handler(ResolveIncidentHandler())
    _add_dinosim_kaiju_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    started: list[IncidentStartedEvent] = []
    resolved: list[IncidentResolvedEvent] = []
    scenario.actor.bus.subscribe(IncidentStartedEvent, started.append)
    scenario.actor.bus.subscribe(IncidentResolvedEvent, resolved.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-dinosim-kaiju.json")),
    )

    incidents = list(
        scenario.actor.world.query().with_all([IncidentComponent]).execute_entities()
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    room_entities = [
        scenario.actor.world.get_entity(entity_id)
        for _edge, entity_id in room.get_relationships(Contains)
    ]
    assert rejected == []
    assert result.ticks == 3
    assert len(result.inputs) == 2
    assert len(incidents) == 1
    assert incidents[0].get_component(IncidentComponent).kind == "kaiju_attack"
    assert incidents[0].has_component(dino.SettlementDamageComponent)
    assert incidents[0].get_component(IncidentComponent).resolved_at_epoch is not None
    assert any(entity.has_component(dino.KaijuComponent) for entity in room_entities)
    assert started and started[0].kind == "kaiju_attack"
    assert resolved and resolved[0].kind == "kaiju_attack"


async def test_discord_playtest_nukesim_wasteland_loop(scenario):
    _install_nukesim_playtest(scenario.actor)
    _source_id, site_id, _station_id, _med_id, _junk_id = _add_nukesim_loop_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    scanned: list = []
    scavenged: list = []
    scrapped: list = []
    sealed: list = []
    decontaminated: list = []
    medicated: list = []
    scenario.actor.bus.subscribe(nuke.RadiationScannedEvent, scanned.append)
    scenario.actor.bus.subscribe(nuke.SiteScavengedEvent, scavenged.append)
    scenario.actor.bus.subscribe(nuke.ItemScrappedEvent, scrapped.append)
    scenario.actor.bus.subscribe(nuke.RadiationSourceSealedEvent, sealed.append)
    scenario.actor.bus.subscribe(nuke.DecontaminationAppliedEvent, decontaminated.append)
    scenario.actor.bus.subscribe(nuke.RadMedicineUsedEvent, medicated.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-nukesim-wasteland.json")),
    )

    character = scenario.actor.world.get_entity(scenario.character)
    site = scenario.actor.world.get_entity(site_id)
    assert rejected == []
    assert result.ticks == 7
    assert len(result.inputs) == 7
    assert scanned and scavenged and scrapped and sealed and decontaminated and medicated
    assert site.get_component(nuke.ScavengeSiteComponent).depleted is True
    assert character.has_component(nuke.RadiationDoseComponent)
    assert character.get_component(nuke.RadiationDoseComponent).amount >= 0.0
    assert scrapped[0].output_ids


async def test_discord_playtest_barbariansim_core_loop(scenario):
    _install_barbariansim_playtest(scenario.actor)
    target_id, weapon_id, coin_id, palisade_id = _add_barbariansim_loop_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    attacked: list = []
    repaired: list = []
    poisoned: list = []
    treated: list = []
    pickpocketed: list = []
    scenario.actor.bus.subscribe(CharacterAttackedEvent, attacked.append)
    scenario.actor.bus.subscribe(barb.ItemRepairedEvent, repaired.append)
    scenario.actor.bus.subscribe(barb.CharacterPoisonedEvent, poisoned.append)
    scenario.actor.bus.subscribe(barb.PoisonTreatedEvent, treated.append)
    scenario.actor.bus.subscribe(CharacterPickpocketedEvent, pickpocketed.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-barbariansim-core.json")),
    )

    character = scenario.actor.world.get_entity(scenario.character)
    target = scenario.actor.world.get_entity(target_id)
    weapon = scenario.actor.world.get_entity(weapon_id)
    palisade = scenario.actor.world.get_entity(palisade_id)
    assert rejected == []
    assert result.ticks == 13
    assert len(result.inputs) == 13
    assert target.get_component(HealthComponent).current < 20.0
    assert not target.has_component(barb.PoisonComponent)
    assert not character.has_component(barb.CorruptionComponent)
    assert weapon.get_component(barb.DurabilityComponent).current > 0
    assert palisade.get_component(barb.FortificationComponent).durability < 10.0
    assert container_of(scenario.actor.world.get_entity(coin_id)) == scenario.character
    assert len(attacked) >= 2
    assert repaired and poisoned and treated and pickpocketed


async def test_discord_playtest_dragonsim_core_loop(scenario):
    _install_dragonsim_playtest(scenario.actor)
    poi_id, quest_id, objective_id, reward_id, reward_item_id, faction_id = (
        _add_dragonsim_loop_world(scenario)
    )
    rejected = _collect_rejections(scenario.actor)
    completed_quests: list = []
    scenario.actor.bus.subscribe(dragon.QuestCompletedEvent, completed_quests.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-dragonsim-core.json")),
    )

    character = scenario.actor.world.get_entity(scenario.character)
    poi = scenario.actor.world.get_entity(poi_id)
    quest = scenario.actor.world.get_entity(quest_id)
    objective = scenario.actor.world.get_entity(objective_id)
    reward = scenario.actor.world.get_entity(reward_id)
    assert rejected == []
    assert result.ticks == 6
    assert len(result.inputs) == 6
    assert poi.get_component(dragon.PointOfInterestComponent).discovered is True
    assert quest.get_component(dragon.QuestComponent).status == "completed"
    assert objective.get_component(dragon.QuestObjectiveComponent).completed is True
    assert reward.get_component(dragon.QuestRewardComponent).claimed is True
    assert container_of(scenario.actor.world.get_entity(reward_item_id)) == scenario.character
    assert not character.has_relationship(dragon.MemberOf, faction_id)
    assert completed_quests


async def test_discord_playtest_lifesim_core_loop(scenario):
    _install_lifesim_playtest(scenario.actor)
    partner_id, child_id, item_id, customer_id = _add_lifesim_loop_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    births: list = []
    sales: list = []
    scenario.actor.bus.subscribe(life.BirthResolvedEvent, births.append)
    scenario.actor.bus.subscribe(life.BusinessSaleEvent, sales.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-lifesim-core.json")),
    )

    character = scenario.actor.world.get_entity(scenario.character)
    partner = scenario.actor.world.get_entity(partner_id)
    assert rejected == []
    assert result.ticks == 17
    assert len(result.inputs) == 16
    assert character.get_component(life.AspirationComponent).completed == ("meet a friend",)
    assert character.get_component(life.SkillSetComponent).levels["cooking"] == 1
    assert character.get_component(life.CareerComponent).level == 2
    assert scenario.actor.world.get_entity(scenario.room_a).has_component(life.HomeComponent)
    assert scenario.actor.world.get_entity(scenario.room_b).has_component(life.RoomClaimComponent)
    assert character.has_relationship(life.PartnerOf, partner_id)
    assert partner.has_relationship(life.PartnerOf, scenario.character)
    assert character.has_relationship(life.ParentOf, child_id)
    assert births and sales
    assert not character.has_component(life.PregnancyComponent)
    assert container_of(scenario.actor.world.get_entity(item_id)) is None
    assert (
        scenario.actor.world.get_entity(customer_id).get_component(life.CustomerComponent).budget
        == 15
    )
    assert character.get_component(life.HouseholdFundsComponent).balance == 39


async def test_discord_playtest_lifesim_billing_business_routine_social_loop(scenario):
    _install_lifesim_playtest(scenario.actor)
    partner_id, _child_id, _item_id, _customer_id = _add_lifesim_loop_world(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(life.HouseholdFundsComponent(balance=50))
    rejected = _collect_rejections(scenario.actor)
    paid: list = []
    promoted: list = []
    routines: list = []
    due: list = []
    statuses: list = []
    gossip: list = []
    scenario.actor.bus.subscribe(life.BillPaidEvent, paid.append)
    scenario.actor.bus.subscribe(life.BusinessPromotedEvent, promoted.append)
    scenario.actor.bus.subscribe(life.RoutineSetEvent, routines.append)
    scenario.actor.bus.subscribe(life.RoutineDueEvent, due.append)
    scenario.actor.bus.subscribe(life.RelationshipStatusChangedEvent, statuses.append)
    scenario.actor.bus.subscribe(life.GossipSpreadEvent, gossip.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-lifesim-economy-routine-social.json")),
    )

    businesses = [
        scenario.actor.world.get_entity(target_id)
        for _edge, target_id in character.get_relationships(life.OwnsBusiness)
    ]
    bills = [
        scenario.actor.world.get_entity(target_id)
        for _edge, target_id in character.get_relationships(life.HasBill)
    ]
    assert rejected == []
    assert result.ticks == 9
    assert len(result.inputs) == 8
    assert paid and paid[0].amount == 7
    assert character.get_component(life.HouseholdFundsComponent).balance == 43
    assert businesses[0].get_component(life.BusinessOwnerComponent).promoted is True
    assert bills[0].get_component(life.BillComponent).paid_at_epoch is not None
    assert routines and routines[0].activity == "water crops"
    assert due and due[0].activity == "water crops"
    assert statuses and statuses[0].status == "friend"
    assert gossip and gossip[0].target_id == str(partner_id)
    assert scenario.actor.world.get_entity(partner_id).get_component(
        life.ReputationComponent
    ).known_for == ("keeps the rent ledger tidy",)


async def test_discord_playtest_daggersim_rumor_travel_loop(scenario):
    _install_daggersim_playtest(scenario.actor)
    site_id, rumor_id = _add_daggersim_rumor_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    completed: list = []
    scenario.actor.bus.subscribe(dagger.TravelCompletedEvent, completed.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-daggersim-rumor-travel.json")),
    )

    site = scenario.actor.world.get_entity(site_id)
    rumor = scenario.actor.world.get_entity(rumor_id)
    assert rejected == []
    assert result.ticks == 7
    assert len(result.inputs) == 5
    assert rumor.get_component(dagger.RumorComponent).state == "verified"
    assert site.get_component(dagger.ProceduralSiteComponent).generated is True
    assert site.get_component(dagger.UnrealizedLocationComponent).detail_level == "instantiated"
    assert scenario.character_room() == scenario.room_b
    assert completed


async def test_discord_playtest_daggersim_economy_loop(scenario):
    _install_daggersim_playtest(scenario.actor)
    institution_id, _service_id, _template_id, bank_id = _add_daggersim_economy_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    generated: list = []
    completed: list = []
    repaid: list = []
    withdrawn: list = []
    paid: list = []
    scenario.actor.bus.subscribe(dagger.QuestGeneratedEvent, generated.append)
    scenario.actor.bus.subscribe(dagger.QuestCompletedEvent, completed.append)
    scenario.actor.bus.subscribe(dagger.WithdrawalMadeEvent, withdrawn.append)
    scenario.actor.bus.subscribe(dagger.LoanRepaidEvent, repaid.append)
    scenario.actor.bus.subscribe(dagger.FinePaidEvent, paid.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-daggersim-economy.json")),
    )

    character = scenario.actor.world.get_entity(scenario.character)
    account = next(
        entity
        for entity in scenario.actor.world.query()
        .with_all([dagger.BankAccountComponent])
        .execute_entities()
        if entity.get_component(dagger.BankAccountComponent).bank_id == str(bank_id)
    )
    assert rejected == []
    assert result.ticks == 13
    assert len(result.inputs) == 13
    assert character.has_relationship(dagger.MemberOfInstitution, institution_id)
    assert any(
        entity.get_component(IdentityComponent).name == "moss road map"
        for _edge, target_id in character.get_relationships(Contains)
        if (entity := scenario.actor.world.get_entity(target_id)).has_component(IdentityComponent)
    )
    assert generated and completed and withdrawn and repaid and paid
    assert account.get_component(dagger.BankAccountComponent).balance == 0
    assert all(
        not entity.has_component(dagger.BountyComponent)
        for entity in scenario.actor.world.query()
        .with_all([dagger.CrimeRecordComponent])
        .execute_entities()
    )


async def test_discord_playtest_daggersim_magic_loop(scenario):
    _install_daggersim_playtest(scenario.actor)
    _class_template, _spell_template, _charm_id, creature_id = _add_daggersim_magic_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    pacified: list = []
    transformed: list = []
    scenario.actor.bus.subscribe(dagger.CreaturePacifiedEvent, pacified.append)
    scenario.actor.bus.subscribe(dagger.TransformationStartedEvent, transformed.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-daggersim-magic.json")),
    )

    character = scenario.actor.world.get_entity(scenario.character)
    creature = scenario.actor.world.get_entity(creature_id)
    assert rejected == []
    assert result.ticks == 7
    assert len(result.inputs) == 7
    assert character.get_component(dagger.CustomClassComponent).class_name == "Rainpath Scout"
    assert character.get_component(HealthComponent).current == 7.0
    assert creature.get_component(dagger.HostilityComponent).hostile is False
    assert creature.has_component(dagger.PacifiedComponent)
    assert character.has_component(dagger.SupernaturalAfflictionComponent)
    assert character.has_component(dagger.WereformComponent)
    assert pacified and transformed


async def test_discord_playtest_daggersim_enchant_item_loop(scenario):
    _install_daggersim_playtest(scenario.actor)
    _class_template, _spell_template, charm_id, _creature_id = _add_daggersim_magic_world(
        scenario
    )
    rejected = _collect_rejections(scenario.actor)
    enchanted: list = []
    cast: list = []
    scenario.actor.bus.subscribe(dagger.ItemEnchantedEvent, enchanted.append)
    scenario.actor.bus.subscribe(dagger.SpellCastEvent, cast.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-daggersim-enchant-item.json")),
    )

    character = scenario.actor.world.get_entity(scenario.character)
    charm = scenario.actor.world.get_entity(charm_id)
    assert rejected == []
    assert result.ticks == 5
    assert len(result.inputs) == 5
    assert charm.get_component(dagger.EnchantedItemComponent).spell_name == "Mend Moss"
    assert len(enchanted) == 1
    assert len(cast) == 1
    assert character.get_component(HealthComponent).current == 7.0


async def test_discord_playtest_daggersim_dungeon_loop(scenario):
    _install_daggersim_playtest(scenario.actor)
    dungeon_id, entry_id, deeper_id, door_id, objective_id = _add_daggersim_dungeon_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    exited: list = []
    scenario.actor.bus.subscribe(dagger.DungeonExitedEvent, exited.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-daggersim-dungeon.json")),
    )

    character = scenario.actor.world.get_entity(scenario.character)
    dungeon = scenario.actor.world.get_entity(dungeon_id)
    door = scenario.actor.world.get_entity(door_id)
    objective = scenario.actor.world.get_entity(objective_id)
    assert rejected == []
    assert result.ticks == 10
    assert len(result.inputs) == 10
    assert dungeon.get_component(dagger.DungeonComponent).entered is False
    assert door.get_component(dagger.SecretDoorComponent).opened is True
    assert objective.get_component(dagger.DungeonObjectiveComponent).found is True
    discovered_exits = [
        target_id
        for _edge, target_id in scenario.actor.world.get_entity(entry_id).get_relationships(
            ExitTo
        )
    ]
    assert deeper_id in discovered_exits
    assert container_of(character) == entry_id
    assert str(entry_id) in character.get_component(dagger.AutomapComponent).marked_rooms
    assert exited


async def test_discord_playtest_voidsim_ship_systems_loop(scenario):
    _install_voidsim_playtest(scenario.actor)
    airlock_id, bulkhead_id, grid_id, system_id, other_id = _add_voidsim_systems_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    failures: list = []
    scenario.actor.bus.subscribe(void.LifeSupportFailedEvent, failures.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-voidsim-ship-systems.json")),
    )

    room = scenario.actor.world.get_entity(scenario.room_a)
    airlock = scenario.actor.world.get_entity(airlock_id)
    bulkhead = scenario.actor.world.get_entity(bulkhead_id)
    grid = scenario.actor.world.get_entity(grid_id)
    system = scenario.actor.world.get_entity(system_id)
    assert rejected == []
    assert result.ticks == 9
    assert len(result.inputs) == 8
    assert airlock.get_component(void.AirlockComponent).state == "sealed"
    assert bulkhead.get_component(void.BulkheadComponent).sealed is True
    assert system.get_component(void.ShipSystemComponent).integrity == 100.0
    assert system.get_component(void.ShipSystemComponent).online is True
    assert grid.get_component(void.PowerGridComponent).available == 70.0
    assert container_of(scenario.actor.world.get_entity(other_id)) == scenario.room_b
    assert room.get_component(void.OxygenComponent).failed is True
    assert failures


async def test_discord_playtest_voidsim_navigation_loop(scenario):
    _install_voidsim_playtest(scenario.actor)
    ship_id, station_id, signal_id, body_id = _add_voidsim_navigation_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    completed: list = []
    scenario.actor.bus.subscribe(void.JumpCompletedEvent, completed.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-voidsim-navigation.json")),
    )

    ship = scenario.actor.world.get_entity(ship_id)
    signal = scenario.actor.world.get_entity(signal_id)
    assert rejected == []
    assert result.ticks == 13
    assert len(result.inputs) == 12
    assert not list(ship.get_relationships(void.DockedTo))
    assert container_of(ship) == scenario.room_b
    assert ship.get_component(void.FuelComponent).level == 90.0
    assert signal.get_component(void.DistressSignalComponent).answered is True
    assert not ship.has_component(void.OrbitComponent)
    assert completed


async def test_discord_playtest_voidsim_chaos_influence_loop(scenario):
    _install_voidsim_playtest(scenario.actor)
    source_id, ward_id = _add_voidsim_chaos_world(scenario)
    rejected = _collect_rejections(scenario.actor)
    influence: list = []
    scenario.actor.bus.subscribe(void.ChaosInfluenceAppliedEvent, influence.append)

    result = await run_discord_playtest(
        _loop(scenario.actor),
        load_discord_playtest(_run_path("discord-voidsim-chaos-influence.json")),
    )

    character = scenario.actor.world.get_entity(scenario.character)
    assert rejected == []
    assert result.ticks == 3
    assert len(result.inputs) == 2
    assert character.get_component(barb.CorruptionComponent).amount == 3.0
    assert character.get_component(void.ChaosMutationPressureComponent).amount == 1.5
    assert influence
    assert {event.source_id for event in influence} == {str(source_id)}
    assert scenario.actor.world.has_entity(ward_id)
