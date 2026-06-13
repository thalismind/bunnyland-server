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
    FortificationComponent,
    ShelterComponent,
    StaminaComponent,
    WeaponComponent,
)
from ..mechanics.colonysim import (
    BodyPartHealthComponent,
    ColonyIncidentComponent,
    JobBillComponent,
    JobComponent,
    PawnProfileComponent,
    PrisonerComponent,
    ResearchProjectComponent,
    ResourceNodeComponent,
    ResourceStackComponent,
    StockpileComponent,
    SurgeryBillComponent,
    TradeOfferComponent,
    WorkstationComponent,
)
from ..mechanics.daggersim import (
    DungeonComponent,
    DungeonRoomComponent,
    InstitutionComponent,
    ProceduralSiteComponent,
    QuestTemplateComponent,
    RumorComponent,
    TravelHubComponent,
)
from ..mechanics.dinosim import (
    DinosaurComponent,
    EggComponent,
    EnclosureComponent,
    EscapeRiskComponent,
    FertilityComponent,
    FossilFragmentComponent,
    SpeciesComponent,
)
from ..mechanics.dragonsim import (
    FactionComponent,
    FactionReputationComponent,
    PointOfInterestComponent,
    QuestComponent,
)
from ..mechanics.environment import FireComponent, FlammableComponent
from ..mechanics.gardensim import (
    CropQualityComponent,
    FarmQuestComponent,
    FertilizerComponent,
    GeodeComponent,
    GreenhouseComponent,
    LadderComponent,
    MachineComponent,
    MailComponent,
    MineLevelComponent,
    PestComponent,
    RegrowableComponent,
    SeedComponent,
    ShippingBinComponent,
    SoilComponent,
    TreeComponent,
    WeedComponent,
)
from ..mechanics.lifesim import (
    CharacterProfileComponent,
    HomeObjectComponent,
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
    DecontaminationComponent,
    JunkComponent,
    LootTableComponent,
    MutationThresholdComponent,
    RadiationDoseComponent,
    RadiationSourceComponent,
    RadMedicineComponent,
    RadProtectionComponent,
    ScavengeSiteComponent,
)
from ..mechanics.voidsim import (
    AirlockComponent,
    DistressSignalComponent,
    FuelComponent,
    HabitatModuleComponent,
    JumpDriveComponent,
    LifeSupportComponent,
    OxygenComponent,
    PowerGridComponent,
    PressurizedComponent,
    SensorComponent,
    ShipComponent,
    ShipSystemComponent,
    StarSystemComponent,
    StationComponent,
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


class EnvironmentWorldgenHook:
    def subscribe(self, actor: WorldActor) -> None:
        self.actor = actor
        actor.bus.subscribe(RoomGeneratedEvent, self._on_entity)
        actor.bus.subscribe(ObjectGeneratedEvent, self._on_entity)

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
    def subscribe(self, actor: WorldActor) -> None:
        self.actor = actor
        actor.bus.subscribe(CharacterGeneratedEvent, self._on_character)
        actor.bus.subscribe(ObjectGeneratedEvent, self._on_object)

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

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "whim") or _mentions(event, "whim", "wish"):
            replace_component(entity, WhimComponent(want=_name(entity, "generated whim")))
        if _wants(event, "home-object") or _mentions(
            event, "chair", "bed", "stove", "sofa", "decor", "home"
        ):
            replace_component(entity, HomeObjectComponent(affordance="comfort", decor_score=1.0))


class ColonyWorldgenHook:
    def subscribe(self, actor: WorldActor) -> None:
        self.actor = actor
        actor.bus.subscribe(RoomGeneratedEvent, self._on_room)
        actor.bus.subscribe(CharacterGeneratedEvent, self._on_character)
        actor.bus.subscribe(ObjectGeneratedEvent, self._on_object)

    def _on_room(self, event: RoomGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "stockpile") or _mentions(event, "stockpile", "warehouse"):
            replace_component(entity, StockpileComponent(capacity=40))

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

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
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
        if _wants(event, "workstation") or _mentions(event, "workbench", "forge", "bench"):
            replace_component(entity, WorkstationComponent(station_type=resource_type))
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


class GardenWorldgenHook:
    def subscribe(self, actor: WorldActor) -> None:
        self.actor = actor
        actor.bus.subscribe(RoomGeneratedEvent, self._on_room)
        actor.bus.subscribe(ObjectGeneratedEvent, self._on_object)

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

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "seed") or _mentions(event, "seed", "seeds"):
            crop_type = _crop_type(event)
            replace_component(
                entity,
                SeedComponent(crop_type=crop_type, growth_days=2.0, yield_item=crop_type),
            )
        if _wants(event, "fertilizer") or _mentions(event, "fertilizer", "compost"):
            replace_component(entity, FertilizerComponent(kind="compost", growth_multiplier=1.2))
        if _wants(event, "tree") or _mentions(event, "sapling", "tree"):
            replace_component(
                entity,
                TreeComponent(
                    tree_type=_resource_type(event),
                    planted_at_epoch=event.world_epoch,
                    maturity_days=7.0,
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
        if _wants(event, "machine") or _mentions(event, "machine", "preserves", "keg"):
            replace_component(entity, MachineComponent(machine_type=_resource_type(event)))
        if _wants(event, "shipping-bin") or _mentions(event, "shipping bin", "shipping crate"):
            replace_component(entity, ShippingBinComponent())
        if _wants(event, "geode") or _mentions(event, "geode"):
            replace_component(entity, GeodeComponent(resource_type=_resource_type(event)))
        if _wants(event, "ladder") or _mentions(event, "ladder"):
            replace_component(entity, LadderComponent(target_room_id=event.entity_id))
        if _wants(event, "mail") or _mentions(event, "mail", "letter"):
            replace_component(entity, MailComponent(subject=_name(entity, "generated mail")))
        if _wants(event, "farm-quest") or _mentions(event, "quest", "order board"):
            resource_type = _resource_type(event)
            replace_component(
                entity,
                FarmQuestComponent(quest_id=resource_type, requested={resource_type: 1}),
            )


class BarbarianWorldgenHook:
    def subscribe(self, actor: WorldActor) -> None:
        self.actor = actor
        actor.bus.subscribe(CharacterGeneratedEvent, self._on_character)
        actor.bus.subscribe(ObjectGeneratedEvent, self._on_object)
        actor.bus.subscribe(RoomGeneratedEvent, self._on_room)

    def _on_character(self, event: CharacterGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is not None and (
            _wants(event, "stamina", "combatant")
            or _mentions(event, "warrior", "fighter")
        ):
            replace_component(entity, StaminaComponent())

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "weapon") or _mentions(event, "sword", "axe", "spear", "club"):
            replace_component(entity, WeaponComponent(damage=8.0, lethal_capable=True))
        if _wants(event, "armor") or _mentions(event, "armor", "shield"):
            replace_component(entity, ArmorComponent(rating=2.0))
        if _wants(event, "durable-fortification") or _mentions(event, "barricade", "wall"):
            replace_component(entity, FortificationComponent(rating=2.0, durability=20.0))

    def _on_room(self, event: RoomGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is not None and (_wants(event, "shelter") or _mentions(event, "shelter", "camp")):
            replace_component(entity, ShelterComponent(temperature_buffer=10.0))


class DragonWorldgenHook:
    def subscribe(self, actor: WorldActor) -> None:
        self.actor = actor
        actor.bus.subscribe(RoomGeneratedEvent, self._on_site)
        actor.bus.subscribe(ObjectGeneratedEvent, self._on_site)
        actor.bus.subscribe(CharacterGeneratedEvent, self._on_character)

    def _on_site(self, event: RoomGeneratedEvent | ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.entity_key)
        if _wants(event, "point-of-interest") or _mentions(event, "landmark", "shrine", "ruin"):
            replace_component(entity, PointOfInterestComponent(location_type=event.entity_kind))
        if _wants(event, "faction") or _mentions(event, "faction", "guild", "clan"):
            replace_component(entity, FactionComponent(name=name))
        if _wants(event, "quest"):
            replace_component(entity, QuestComponent(quest_id=event.entity_key, title=name))

    def _on_character(self, event: CharacterGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is not None and _wants(event, "faction-reputation"):
            replace_component(entity, FactionReputationComponent(scores={}))


class DaggerWorldgenHook:
    def subscribe(self, actor: WorldActor) -> None:
        self.actor = actor
        actor.bus.subscribe(RoomGeneratedEvent, self._on_room)
        actor.bus.subscribe(ObjectGeneratedEvent, self._on_object)

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
        if _wants(event, "institution") or _mentions(event, "guild", "temple", "bank"):
            replace_component(entity, InstitutionComponent(name=name))

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        name = _name(entity, event.object_key)
        if _wants(event, "rumor") or _mentions(event, "rumor"):
            replace_component(entity, RumorComponent(text=event.intent or name))
        if _wants(event, "quest-template"):
            replace_component(
                entity,
                QuestTemplateComponent(
                    title=name,
                    objective=event.intent or name,
                    reward_item_name="coin",
                ),
            )


class DinoWorldgenHook:
    def subscribe(self, actor: WorldActor) -> None:
        self.actor = actor
        actor.bus.subscribe(CharacterGeneratedEvent, self._on_character)
        actor.bus.subscribe(ObjectGeneratedEvent, self._on_object)
        actor.bus.subscribe(RoomGeneratedEvent, self._on_room)

    def _on_character(self, event: CharacterGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        if _wants(event, "dinosaur") or _mentions(event, "dinosaur", "raptor", "rex"):
            replace_component(entity, DinosaurComponent(species_name=event.species))
            replace_component(entity, SpeciesComponent(common_name=event.species))
            replace_component(entity, FertilityComponent())

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
        species = _resource_type(event)
        if _wants(event, "fossil") or _mentions(event, "fossil", "amber"):
            replace_component(entity, FossilFragmentComponent(sample_quality=0.8))
        if _wants(event, "egg") or _mentions(event, "egg"):
            replace_component(
                entity,
                EggComponent(species_name=species, laid_at_epoch=event.world_epoch),
            )

    def _on_room(self, event: RoomGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is not None and (
            _wants(event, "enclosure") or _mentions(event, "enclosure", "pen")
        ):
            replace_component(entity, EnclosureComponent(name=_name(entity, event.room_key)))
            replace_component(entity, EscapeRiskComponent(last_updated_epoch=event.world_epoch))


class VoidWorldgenHook:
    def subscribe(self, actor: WorldActor) -> None:
        self.actor = actor
        actor.bus.subscribe(RoomGeneratedEvent, self._on_room)
        actor.bus.subscribe(ObjectGeneratedEvent, self._on_object)

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

    def _on_object(self, event: ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
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


class NukeWorldgenHook:
    def subscribe(self, actor: WorldActor) -> None:
        self.actor = actor
        actor.bus.subscribe(RoomGeneratedEvent, self._on_entity)
        actor.bus.subscribe(ObjectGeneratedEvent, self._on_entity)
        actor.bus.subscribe(CharacterGeneratedEvent, self._on_character)

    def _on_entity(self, event: RoomGeneratedEvent | ObjectGeneratedEvent) -> None:
        entity = _entity(self.actor, event)
        if entity is None:
            return
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
        if isinstance(event, ObjectGeneratedEvent):
            if _wants(event, "rad-protection"):
                replace_component(entity, RadProtectionComponent(rating=0.5))
            if _wants(event, "decontamination"):
                replace_component(entity, DecontaminationComponent())
            if _wants(event, "rad-medicine"):
                replace_component(entity, RadMedicineComponent())
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


class NeonWorldgenHook:
    def subscribe(self, actor: WorldActor) -> None:
        self.actor = actor
        actor.bus.subscribe(RoomGeneratedEvent, self._on_entity)
        actor.bus.subscribe(ObjectGeneratedEvent, self._on_entity)
        actor.bus.subscribe(CharacterGeneratedEvent, self._on_character)

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
