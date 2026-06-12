"""Tests for world generation: validation, instantiation, and the MVP checklist."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainerComponent,
    ControlledBy,
    EditorDisplayComponent,
    ExitTo,
    GenerationIntentComponent,
    IdentityComponent,
    Lane,
    LightComponent,
    MemoryProfileComponent,
    PortableComponent,
    RoomComponent,
    SuspendedComponent,
    TemperatureComponent,
    WorldActor,
    build_submitted_command,
    container_of,
    parse_entity_id,
)
from bunnyland.core.components import ReadableComponent, WritableComponent
from bunnyland.core.events import (
    CharacterGeneratedEvent,
    ObjectGeneratedEvent,
    RoomGeneratedEvent,
    WorldGeneratedEvent,
)
from bunnyland.mechanics.consumables import DrinkableComponent, FoodComponent
from bunnyland.plugins import ContentContribution, Plugin, apply_plugins, bunnyland_plugins
from bunnyland.worldgen import (
    CharacterProposal,
    CharacterSpec,
    ExitSpec,
    GenOptions,
    ItemProposal,
    ObjectSpec,
    RoomSpec,
    StoryEventProposal,
    StubWorldBuilder,
    WorldProposal,
    halloween_generator,
    holiday_generator,
    instantiate,
    tower_debate_generator,
    validate_proposal,
    waiting_room_generator,
)
from bunnyland.worldgen.ollama_builder import OllamaWorldBuilder, repair_world_proposal

HOUR = 3600.0


def test_validate_rejects_dangling_references():
    proposal = WorldProposal(
        seed="x",
        rooms=[RoomSpec(key="a", title="A")],
        exits=[ExitSpec(from_key="a", direction="north", to_key="ghost")],
    )
    errors = validate_proposal(proposal)
    assert any("unknown room" in e for e in errors)


def test_validate_accepts_stub_proposal():
    proposal = StubWorldBuilder().propose("a quiet marsh")
    assert validate_proposal(proposal) == []


def test_character_proposal_defaults_null_llm_fields():
    proposal = CharacterProposal.model_validate(
        {"name": "Moss", "controller": "llm", "llm_profile": None, "llm_model": None}
    )

    assert proposal.llm_profile == "default"
    assert proposal.llm_model == "deepseek-v4-flash"


def test_character_proposal_coerces_object_llm_profile_to_string():
    proposal = CharacterProposal.model_validate(
        {
            "name": "Elara",
            "controller": "llm",
            "llm_profile": {"name": "meadow-shepherd", "role": "guide"},
        }
    )

    assert proposal.llm_profile == "meadow-shepherd"


def test_character_spec_defaults_to_flash_controller_model():
    spec = CharacterSpec.model_validate(
        {
            "key": "moss",
            "name": "Moss",
            "room_key": "burrow",
            "controller": "llm",
            "llm_model": None,
        }
    )

    assert spec.llm_model == "deepseek-v4-flash"


def test_ollama_world_builder_initializes_client_with_host_and_auth(monkeypatch):
    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "ollama", SimpleNamespace(Client=Client))

    builder = OllamaWorldBuilder(model="world-model", host="https://ollama.example", api_key="k")

    assert builder._model == "world-model"
    assert captured == {
        "host": "https://ollama.example",
        "headers": {"Authorization": "Bearer k"},
    }


def test_story_event_proposal_accepts_common_severity_labels():
    event = StoryEventProposal.model_validate(
        {
            "title": "A harmless clue",
            "severity": "minor",
            "budget_spent": "low",
            "stimulus_intensity": "high",
        }
    )

    assert event.severity == 1.0
    assert event.budget_spent == 1.0
    assert event.stimulus_intensity == 3.0


def test_item_and_object_proposals_default_explicit_null_scalars():
    item = ItemProposal.model_validate(
        {
            "name": "a live-test tool",
            "nutrition": None,
            "satiety": None,
            "hydration": None,
            "open": None,
            "locked": None,
        }
    )
    obj = ObjectSpec.model_validate(
        {
            "key": "tool",
            "room_key": "room",
            "name": "a live-test tool",
            "nutrition": None,
            "satiety": None,
            "hydration": None,
            "open": None,
            "locked": None,
        }
    )

    assert item.nutrition == 0.0
    assert item.satiety == 0.0
    assert item.hydration == 0.0
    assert item.open is True
    assert item.locked is False
    assert obj.nutrition == 0.0
    assert obj.satiety == 0.0
    assert obj.hydration == 0.0
    assert obj.open is True
    assert obj.locked is False


def test_repair_world_proposal_moves_nested_objects_to_first_room_and_drops_bad_exits():
    proposal = WorldProposal.model_validate(
        {
            "seed": "repair",
            "rooms": [{"key": "meadow", "title": "Meadow"}],
            "exits": [{"from_key": "meadow", "direction": "east", "to_key": "ghost"}],
            "objects": [
                {
                    "key": "apple",
                    "room_key": "box",
                    "name": "an apple",
                    "kind": "food",
                }
            ],
            "characters": [{"key": "helper", "name": "Helper", "room_key": "box"}],
        }
    )

    repaired = repair_world_proposal(proposal)

    assert repaired.objects[0].room_key == "meadow"
    assert repaired.characters[0].room_key == "meadow"
    assert repaired.exits == []


def test_generation_options_default_to_pro_worldgen_model():
    assert GenOptions(llm=True).model == "deepseek-v4-pro"
    assert GenOptions(llm=True).provider == "ollama"


async def test_waiting_room_generator_builds_single_white_room_with_red_chair():
    actor = WorldActor()

    result = await waiting_room_generator(actor, "ignored seed", GenOptions())

    assert set(result.rooms) == {"waiting_room"}
    assert set(result.objects) == {"red_chair"}
    assert result.characters == {}

    room = actor.world.get_entity(result.rooms["waiting_room"])
    room_component = room.get_component(RoomComponent)
    assert room_component.title == "Waiting Room"
    assert room_component.biome == "white-room"
    assert room_component.indoor is True
    assert room.get_component(LightComponent).level == 1.0
    assert room.get_component(TemperatureComponent).celsius == 20.0

    chair = actor.world.get_entity(result.objects["red_chair"])
    identity = chair.get_component(IdentityComponent)
    assert identity.name == "a red chair"
    assert identity.kind == "chair"
    assert not chair.has_component(PortableComponent)
    assert container_of(chair) == result.rooms["waiting_room"]


@pytest.mark.parametrize(
    ("generate", "expected"),
    [
        (
            halloween_generator,
            {
                "rooms": {"porch", "foyer", "cellar"},
                "objects": {"candy_bowl", "lantern", "spell_note", "rain_barrel"},
                "characters": {"caretaker", "host"},
                "start": "porch",
                "direction": "in",
                "destination": "foyer",
                "claimable": "caretaker",
                "portable": "lantern",
                "food": "candy_bowl",
                "water": "rain_barrel",
            },
        ),
        (
            holiday_generator,
            {
                "rooms": {"snowfield", "workshop", "stable"},
                "objects": {"cocoa", "gingerbread", "gift_box", "silver_bell"},
                "characters": {"helper", "foreman"},
                "start": "snowfield",
                "direction": "in",
                "destination": "workshop",
                "claimable": "helper",
                "portable": "silver_bell",
                "food": "gingerbread",
                "water": "cocoa",
            },
        ),
    ],
)
async def test_seasonal_generators_build_playable_demo_worlds(generate, expected):
    actor = WorldActor()

    result = await generate(actor, "ignored seed", GenOptions())

    assert set(result.rooms) == expected["rooms"]
    assert set(result.objects) == expected["objects"]
    assert set(result.characters) == expected["characters"]

    start = actor.world.get_entity(result.rooms[expected["start"]])
    exits = {edge.direction: target for edge, target in start.get_relationships(ExitTo)}
    assert exits[expected["direction"]] == result.rooms[expected["destination"]]

    claimable = actor.world.get_entity(result.characters[expected["claimable"]])
    assert claimable.has_component(CharacterComponent)
    assert claimable.has_component(SuspendedComponent)

    portable = actor.world.get_entity(result.objects[expected["portable"]])
    assert portable.has_component(PortableComponent)

    food = actor.world.get_entity(result.objects[expected["food"]])
    assert food.has_component(FoodComponent)

    water = actor.world.get_entity(result.objects[expected["water"]])
    assert water.has_component(DrinkableComponent)


async def test_tower_debate_generator_builds_locked_philosophy_room():
    actor = WorldActor()

    result = await tower_debate_generator(actor, "ignored seed", GenOptions())

    assert set(result.rooms) == {"tower_room", "stair_landing"}
    assert set(result.objects) == {
        "arched_window",
        "debate_table",
        "angel_chair",
        "devil_chair",
        "narrow_bed",
        "cool_prisoners_print",
        "great_day_print",
        "higher_force_plaque",
    }
    assert set(result.characters) == {"angel", "devil"}

    tower_room = actor.world.get_entity(result.rooms["tower_room"])
    room_component = tower_room.get_component(RoomComponent)
    assert room_component.title == "Locked Tower Room"
    assert room_component.indoor is True
    exits = {
        edge.direction: (edge, target)
        for edge, target in tower_room.get_relationships(ExitTo)
    }
    down_edge, down_target = exits["down"]
    assert down_edge.locked is True
    assert down_target == result.rooms["stair_landing"]

    angel = actor.world.get_entity(result.characters["angel"])
    devil = actor.world.get_entity(result.characters["devil"])
    assert angel.get_component(CharacterComponent).species == "angel"
    assert devil.get_component(CharacterComponent).species == "devil"
    assert not angel.has_component(SuspendedComponent)
    assert not devil.has_component(SuspendedComponent)
    assert angel.get_relationships(ControlledBy)
    assert devil.get_relationships(ControlledBy)
    assert container_of(angel) == result.rooms["tower_room"]
    assert container_of(devil) == result.rooms["tower_room"]

    window = actor.world.get_entity(result.objects["arched_window"])
    assert window.get_component(IdentityComponent).kind == "window"
    assert not window.has_component(PortableComponent)

    art = actor.world.get_entity(result.objects["great_day_print"])
    readable = art.get_component(ReadableComponent)
    assert readable.title == "Make Every Day The Same Argument"
    assert "same debate about meaning" in readable.text
    assert "unseen above the tower" in readable.text


async def test_instantiate_builds_the_mvp_checklist():
    actor = WorldActor()
    events = []
    actor.bus.subscribe(WorldGeneratedEvent, events.append)

    proposal = StubWorldBuilder().propose("a quiet marsh")
    result = await instantiate(actor, proposal)
    world = actor.world

    # at least a few connected rooms
    assert len(result.rooms) == 2
    burrow = world.get_entity(result.rooms["burrow"])
    assert burrow.has_component(RoomComponent)

    # food + water + container + writable paper
    assert world.get_entity(result.objects["berries"]).has_component(FoodComponent)
    assert world.get_entity(result.objects["basin"]).has_component(DrinkableComponent)
    assert world.get_entity(result.objects["chest"]).has_component(ContainerComponent)
    assert world.get_entity(result.objects["paper"]).has_component(WritableComponent)

    # a controllable (suspended/claimable) character and an LLM character
    juniper = world.get_entity(result.characters["juniper"])
    hazel = world.get_entity(result.characters["hazel"])
    assert juniper.has_component(SuspendedComponent)
    assert juniper.has_component(CharacterComponent)
    assert not hazel.has_component(SuspendedComponent)
    assert hazel.get_relationships(ControlledBy)  # has an (LLM) controller
    assert hazel.get_component(MemoryProfileComponent).vector_collection == "mem-hazel"

    # both characters are in the burrow (so speech has an audience)
    assert container_of(juniper) == result.rooms["burrow"]
    assert container_of(hazel) == result.rooms["burrow"]

    assert events and events[0].room_count == 2 and events[0].character_count == 2


async def test_instantiate_emits_typed_generation_events_with_intent_tags_and_wants():
    actor = WorldActor()
    rooms: list[RoomGeneratedEvent] = []
    objects: list[ObjectGeneratedEvent] = []
    characters: list[CharacterGeneratedEvent] = []
    actor.bus.subscribe(RoomGeneratedEvent, rooms.append)
    actor.bus.subscribe(ObjectGeneratedEvent, objects.append)
    actor.bus.subscribe(CharacterGeneratedEvent, characters.append)

    proposal = WorldProposal(
        seed="storm cellar",
        rooms=[
            RoomSpec(
                key="cellar",
                title="Flooded Cellar",
                biome="cellar",
                indoor=True,
                description="a flooded cellar, signs of recent struggle",
                tags=("wet",),
                wants=("humidity",),
            )
        ],
        objects=[
            ObjectSpec(
                key="crate",
                room_key="cellar",
                name="a swollen crate",
                kind="container",
                description="waterlogged supplies",
                tags=("salvage",),
                wants=("loot-table",),
            )
        ],
        characters=[
            CharacterSpec(
                key="scout",
                name="Scout",
                room_key="cellar",
                species="hare",
                description="a worried scout checking the flood",
                traits=("watchful",),
                tags=("local",),
                wants=("faction-allegiance",),
            )
        ],
    )

    result = await instantiate(actor, proposal)

    assert [event.room_key for event in rooms] == ["cellar"]
    assert rooms[0].entity_id == str(result.rooms["cellar"])
    assert rooms[0].generation.description == "a flooded cellar, signs of recent struggle"
    assert rooms[0].generation.tags == ("cellar", "indoor", "wet")
    assert rooms[0].generation.wants == ("humidity",)
    assert (
        actor.world.get_entity(result.rooms["cellar"]).get_component(GenerationIntentComponent)
        == rooms[0].generation
    )

    assert [event.object_key for event in objects] == ["crate"]
    assert objects[0].entity_id == str(result.objects["crate"])
    assert objects[0].room_id == str(result.rooms["cellar"])
    assert objects[0].container_id == str(result.rooms["cellar"])
    assert objects[0].generation.description == "waterlogged supplies"
    assert objects[0].generation.tags == ("container", "salvage")
    assert objects[0].generation.wants == ("loot-table",)

    assert [event.character_key for event in characters] == ["scout"]
    assert characters[0].entity_id == str(result.characters["scout"])
    assert characters[0].room_id == str(result.rooms["cellar"])
    assert characters[0].generation.description == "a worried scout checking the flood"
    assert characters[0].generation.tags == ("hare", "watchful", "local")
    assert characters[0].generation.wants == ("faction-allegiance",)


async def test_plugin_worldgen_hook_can_enrich_generated_entities():
    class RoomEmojiHook:
        def subscribe(self, actor: WorldActor) -> None:
            self.actor = actor
            actor.bus.subscribe(RoomGeneratedEvent, self.on_room)

        def on_room(self, event: RoomGeneratedEvent) -> None:
            if "humidity" not in event.wants:
                return
            entity_id = parse_entity_id(event.entity_id)
            assert entity_id is not None
            self.actor.world.get_entity(entity_id).add_component(
                EditorDisplayComponent(emoji="~")
            )

    actor = WorldActor()
    apply_plugins(
        [
            Plugin(
                id="humidity",
                name="Humidity",
                content=ContentContribution(worldgen_hooks=(RoomEmojiHook,)),
            )
        ],
        actor,
    )
    proposal = WorldProposal(
        seed="rain",
        rooms=[
            RoomSpec(
                key="room",
                title="Rain Room",
                description="rain pools on the floor",
                wants=("humidity",),
            )
        ],
    )

    result = await instantiate(actor, proposal)

    room = actor.world.get_entity(result.rooms["room"])
    assert room.get_component(EditorDisplayComponent).emoji == "~"


async def test_builtin_worldgen_hooks_enrich_from_generation_intent():
    from bunnyland.mechanics.barbariansim import StaminaComponent, WeaponComponent
    from bunnyland.mechanics.colonysim import (
        BodyPartHealthComponent,
        ColonyIncidentComponent,
        JobBillComponent,
        PawnProfileComponent,
        PrisonerComponent,
        ResearchProjectComponent,
        ResourceNodeComponent,
        StockpileComponent,
        SurgeryBillComponent,
        TradeOfferComponent,
    )
    from bunnyland.mechanics.daggersim import DungeonComponent
    from bunnyland.mechanics.dinosim import DinosaurComponent, EnclosureComponent
    from bunnyland.mechanics.dragonsim import FactionReputationComponent, PointOfInterestComponent
    from bunnyland.mechanics.environment import FlammableComponent
    from bunnyland.mechanics.gardensim import (
        CropQualityComponent,
        FarmQuestComponent,
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
        WeedComponent,
    )
    from bunnyland.mechanics.lifesim import (
        CharacterProfileComponent,
        HomeObjectComponent,
        WhimComponent,
    )
    from bunnyland.mechanics.nukesim import MutationThresholdComponent, RadiationSourceComponent
    from bunnyland.mechanics.voidsim import (
        HabitatModuleComponent,
        ShipComponent,
        ShipSystemComponent,
    )

    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    proposal = WorldProposal(
        seed="enriched",
        rooms=[
            RoomSpec(
                key="garden_ship",
                title="Greenhouse Ship",
                biome="greenhouse",
                indoor=True,
                generation=GenerationIntentComponent(
                    description="a greenhouse ship with a small dinosaur pen",
                    tags=("ship",),
                    wants=(
                        "soil",
                        "greenhouse",
                        "stockpile",
                        "ship",
                        "point-of-interest",
                        "dungeon",
                        "enclosure",
                        "mine-level",
                        "radiation-source",
                    ),
                    needs=("flammable",),
                ),
            )
        ],
        objects=[
            ObjectSpec(
                key="ore",
                room_key="garden_ship",
                name="a metal ore vein",
                kind="resource",
                wants=("resource-node",),
            ),
            ObjectSpec(
                key="seeds",
                room_key="garden_ship",
                name="turnip seeds",
                kind="seed",
                wants=("seed",),
            ),
            ObjectSpec(
                key="blade",
                room_key="garden_ship",
                name="a survival sword",
                kind="weapon",
                wants=("weapon",),
            ),
            ObjectSpec(
                key="drive",
                room_key="garden_ship",
                name="a damaged drive core",
                kind="drive",
                wants=("ship-system",),
            ),
            ObjectSpec(
                key="chair",
                room_key="garden_ship",
                name="a cozy home chair",
                kind="furniture",
                wants=("home-object", "whim"),
            ),
            ObjectSpec(
                key="work_order",
                room_key="garden_ship",
                name="a work order bill",
                kind="job",
                wants=("job-bill",),
            ),
            ObjectSpec(
                key="research",
                room_key="garden_ship",
                name="hydroponic research notes",
                kind="research",
                wants=("research",),
            ),
            ObjectSpec(
                key="incident",
                room_key="garden_ship",
                name="minor blight incident",
                kind="incident",
                wants=("incident",),
            ),
            ObjectSpec(
                key="trade",
                room_key="garden_ship",
                name="a trader's offer",
                kind="trade",
                wants=("trade-offer",),
            ),
            ObjectSpec(
                key="surgery",
                room_key="garden_ship",
                name="a limb surgery order",
                kind="surgery",
                wants=("surgery", "body-part"),
            ),
            ObjectSpec(
                key="crop",
                room_key="garden_ship",
                name="a perennial crop",
                kind="crop",
                wants=("crop-quality", "regrowable", "pest", "weed"),
            ),
            ObjectSpec(
                key="machine",
                room_key="garden_ship",
                name="a preserves machine",
                kind="machine",
                wants=("machine",),
            ),
            ObjectSpec(
                key="shipping",
                room_key="garden_ship",
                name="a shipping crate",
                kind="shipping-bin",
                wants=("shipping-bin",),
            ),
            ObjectSpec(
                key="geode",
                room_key="garden_ship",
                name="a metal geode",
                kind="geode",
                wants=("geode",),
            ),
            ObjectSpec(
                key="ladder",
                room_key="garden_ship",
                name="a ladder down",
                kind="ladder",
                wants=("ladder",),
            ),
            ObjectSpec(
                key="mail",
                room_key="garden_ship",
                name="a welcome letter",
                kind="mail",
                wants=("mail",),
            ),
            ObjectSpec(
                key="quest",
                room_key="garden_ship",
                name="an order board quest",
                kind="quest",
                wants=("farm-quest",),
            ),
        ],
        characters=[
            CharacterSpec(
                key="raptor",
                name="Clever",
                room_key="garden_ship",
                species="raptor",
                wants=(
                    "profile",
                    "pawn-profile",
                    "prisoner",
                    "dinosaur",
                    "stamina",
                    "mutation-threshold",
                    "faction-reputation",
                ),
            )
        ],
    )

    result = await instantiate(actor, proposal)

    room = actor.world.get_entity(result.rooms["garden_ship"])
    assert room.has_component(SoilComponent)
    assert room.has_component(GreenhouseComponent)
    assert room.has_component(MineLevelComponent)
    assert room.has_component(StockpileComponent)
    assert room.has_component(ShipComponent)
    assert room.has_component(HabitatModuleComponent)
    assert room.has_component(PointOfInterestComponent)
    assert room.has_component(DungeonComponent)
    assert room.has_component(EnclosureComponent)
    assert room.has_component(RadiationSourceComponent)
    assert room.has_component(FlammableComponent)

    assert actor.world.get_entity(result.objects["ore"]).has_component(ResourceNodeComponent)
    assert actor.world.get_entity(result.objects["seeds"]).has_component(SeedComponent)
    assert actor.world.get_entity(result.objects["blade"]).has_component(WeaponComponent)
    assert actor.world.get_entity(result.objects["drive"]).has_component(ShipSystemComponent)
    assert actor.world.get_entity(result.objects["chair"]).has_component(HomeObjectComponent)
    assert actor.world.get_entity(result.objects["chair"]).has_component(WhimComponent)
    assert actor.world.get_entity(result.objects["work_order"]).has_component(JobBillComponent)
    assert actor.world.get_entity(result.objects["research"]).has_component(
        ResearchProjectComponent
    )
    assert actor.world.get_entity(result.objects["incident"]).has_component(ColonyIncidentComponent)
    assert actor.world.get_entity(result.objects["trade"]).has_component(TradeOfferComponent)
    assert actor.world.get_entity(result.objects["surgery"]).has_component(SurgeryBillComponent)
    assert actor.world.get_entity(result.objects["surgery"]).has_component(BodyPartHealthComponent)
    assert actor.world.get_entity(result.objects["crop"]).has_component(CropQualityComponent)
    assert actor.world.get_entity(result.objects["crop"]).has_component(RegrowableComponent)
    assert actor.world.get_entity(result.objects["crop"]).has_component(PestComponent)
    assert actor.world.get_entity(result.objects["crop"]).has_component(WeedComponent)
    assert actor.world.get_entity(result.objects["machine"]).has_component(MachineComponent)
    assert actor.world.get_entity(result.objects["shipping"]).has_component(ShippingBinComponent)
    assert actor.world.get_entity(result.objects["geode"]).has_component(GeodeComponent)
    assert actor.world.get_entity(result.objects["ladder"]).has_component(LadderComponent)
    assert actor.world.get_entity(result.objects["mail"]).has_component(MailComponent)
    assert actor.world.get_entity(result.objects["quest"]).has_component(FarmQuestComponent)

    raptor = actor.world.get_entity(result.characters["raptor"])
    assert raptor.has_component(CharacterProfileComponent)
    assert raptor.has_component(PawnProfileComponent)
    assert raptor.has_component(PrisonerComponent)
    assert raptor.has_component(DinosaurComponent)
    assert raptor.has_component(StaminaComponent)
    assert raptor.has_component(MutationThresholdComponent)
    assert raptor.has_component(FactionReputationComponent)


async def test_builtin_worldgen_hooks_enrich_from_descriptive_mentions():
    from bunnyland.mechanics.colonysim import (
        ColonyIncidentComponent,
        JobBillComponent,
        PawnProfileComponent,
        PrisonerComponent,
        ResearchProjectComponent,
        ResourceStackComponent,
        StockpileComponent,
        SurgeryBillComponent,
        TradeOfferComponent,
        WorkstationComponent,
    )
    from bunnyland.mechanics.gardensim import (
        CropQualityComponent,
        FarmQuestComponent,
        FertilizerComponent,
        GeodeComponent,
        LadderComponent,
        MachineComponent,
        MailComponent,
        MineLevelComponent,
        PestComponent,
        RegrowableComponent,
        ShippingBinComponent,
        TreeComponent,
        WeedComponent,
    )
    from bunnyland.mechanics.lifesim import (
        CharacterProfileComponent,
        HomeObjectComponent,
        WhimComponent,
    )

    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    proposal = WorldProposal(
        seed="mentions",
        rooms=[
            RoomSpec(
                key="room",
                title="Farm Warehouse Cavern",
                description="a greenhouse farm warehouse cavern",
            )
        ],
        objects=[
            ObjectSpec(
                key="wish_chair",
                room_key="room",
                name="a wish chair for the home",
                kind="furniture",
            ),
            ObjectSpec(
                key="stack",
                room_key="room",
                name="a pile of wood",
                kind="resource",
            ),
            ObjectSpec(key="forge", room_key="room", name="a metal forge", kind="bench"),
            ObjectSpec(
                key="research",
                room_key="room",
                name="technology research notes",
                kind="paper",
            ),
            ObjectSpec(key="raid", room_key="room", name="a raid incident", kind="incident"),
            ObjectSpec(key="trade", room_key="room", name="a trader offer", kind="trade"),
            ObjectSpec(
                key="surgery",
                room_key="room",
                name="a limb operation work order",
                kind="surgery",
            ),
            ObjectSpec(key="compost", room_key="room", name="a bag of compost", kind="item"),
            ObjectSpec(key="tree", room_key="room", name="a young tree", kind="tree"),
            ObjectSpec(
                key="crop",
                room_key="room",
                name="a perennial crop with pest bugs and weeds",
                kind="crop",
            ),
            ObjectSpec(key="keg", room_key="room", name="a keg machine", kind="machine"),
            ObjectSpec(
                key="shipping",
                room_key="room",
                name="a shipping bin",
                kind="shipping",
            ),
            ObjectSpec(key="geode", room_key="room", name="a stone geode", kind="geode"),
            ObjectSpec(key="ladder", room_key="room", name="a mine ladder", kind="ladder"),
            ObjectSpec(key="mail", room_key="room", name="a letter in the mail", kind="mail"),
            ObjectSpec(
                key="quest",
                room_key="room",
                name="an order board quest",
                kind="quest",
            ),
        ],
        characters=[
            CharacterSpec(
                key="pawn",
                name="Morgan",
                room_key="room",
                description="a captive worker with a backstory and routine",
                traits=("crafting",),
            )
        ],
    )

    result = await instantiate(actor, proposal)

    room = actor.world.get_entity(result.rooms["room"])
    assert room.has_component(StockpileComponent)
    assert room.has_component(MineLevelComponent)
    pawn = actor.world.get_entity(result.characters["pawn"])
    assert pawn.has_component(CharacterProfileComponent)
    assert pawn.has_component(PawnProfileComponent)
    assert pawn.has_component(PrisonerComponent)
    assert actor.world.get_entity(result.objects["wish_chair"]).has_component(HomeObjectComponent)
    assert actor.world.get_entity(result.objects["wish_chair"]).has_component(WhimComponent)
    assert actor.world.get_entity(result.objects["stack"]).has_component(ResourceStackComponent)
    assert actor.world.get_entity(result.objects["forge"]).has_component(WorkstationComponent)
    assert actor.world.get_entity(result.objects["research"]).has_component(
        ResearchProjectComponent
    )
    assert actor.world.get_entity(result.objects["raid"]).has_component(ColonyIncidentComponent)
    assert actor.world.get_entity(result.objects["trade"]).has_component(TradeOfferComponent)
    assert actor.world.get_entity(result.objects["surgery"]).has_component(SurgeryBillComponent)
    assert actor.world.get_entity(result.objects["surgery"]).has_component(JobBillComponent)
    assert actor.world.get_entity(result.objects["compost"]).has_component(FertilizerComponent)
    assert actor.world.get_entity(result.objects["tree"]).has_component(TreeComponent)
    crop = actor.world.get_entity(result.objects["crop"])
    assert crop.has_component(CropQualityComponent)
    assert crop.has_component(RegrowableComponent)
    assert crop.has_component(PestComponent)
    assert crop.has_component(WeedComponent)
    assert actor.world.get_entity(result.objects["keg"]).has_component(MachineComponent)
    assert actor.world.get_entity(result.objects["shipping"]).has_component(ShippingBinComponent)
    assert actor.world.get_entity(result.objects["geode"]).has_component(GeodeComponent)
    assert actor.world.get_entity(result.objects["ladder"]).has_component(LadderComponent)
    assert actor.world.get_entity(result.objects["mail"]).has_component(MailComponent)
    assert actor.world.get_entity(result.objects["quest"]).has_component(FarmQuestComponent)


async def test_builtin_worldgen_hooks_cover_cross_package_mention_branches():
    from bunnyland.mechanics.barbariansim import (
        ArmorComponent,
        FortificationComponent,
        ShelterComponent,
        StaminaComponent,
    )
    from bunnyland.mechanics.daggersim import (
        DungeonComponent,
        DungeonRoomComponent,
        InstitutionComponent,
        ProceduralSiteComponent,
        QuestTemplateComponent,
        RumorComponent,
        TravelHubComponent,
    )
    from bunnyland.mechanics.dinosim import (
        DinosaurComponent,
        EggComponent,
        FertilityComponent,
        FossilFragmentComponent,
        SpeciesComponent,
    )
    from bunnyland.mechanics.dragonsim import (
        FactionComponent,
        FactionReputationComponent,
        PointOfInterestComponent,
        QuestComponent,
    )
    from bunnyland.mechanics.environment import FireComponent, FlammableComponent
    from bunnyland.mechanics.nukesim import (
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
    from bunnyland.mechanics.voidsim import (
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
        StarSystemComponent,
        StationComponent,
    )

    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    proposal = WorldProposal(
        seed="cross-package",
        rooms=[
            RoomSpec(
                key="hub",
                title="Shelter Camp Guild Vault Station",
                biome="vault",
                description=(
                    "a shelter camp guild dungeon crossroads bank ship station airlock "
                    "reactor ruin cache"
                ),
                wants=("procedural-site", "quest", "star-system"),
            )
        ],
        objects=[
            ObjectSpec(
                key="firewood",
                room_key="hub",
                name="burning wood fuel",
                kind="fuel",
                wants=("fire",),
            ),
            ObjectSpec(
                key="barricade",
                room_key="hub",
                name="armor shield barricade wall",
                kind="fortification",
            ),
            ObjectSpec(
                key="shrine",
                room_key="hub",
                name="quest shrine landmark faction guild",
                kind="shrine",
                wants=("quest",),
            ),
            ObjectSpec(
                key="rumor",
                room_key="hub",
                name="a rumor parchment",
                kind="paper",
                description="rumor of a hidden vault",
            ),
            ObjectSpec(
                key="template",
                room_key="hub",
                name="quest template notice",
                kind="paper",
                wants=("quest-template",),
            ),
            ObjectSpec(
                key="fossil_egg",
                room_key="hub",
                name="amber fossil egg",
                kind="relic",
            ),
            ObjectSpec(
                key="ship_parts",
                room_key="hub",
                name="jump drive fuel sensor distress signal",
                kind="ship-system",
            ),
            ObjectSpec(
                key="rad_kit",
                room_key="hub",
                name="junk reactor cache",
                kind="rad-kit",
                wants=("rad-protection", "decontamination", "rad-medicine", "junk"),
            ),
        ],
        characters=[
            CharacterSpec(
                key="fighter",
                name="Clever Fighter",
                room_key="hub",
                species="raptor",
                description="a warrior fighter raptor",
                wants=("radiation-dose", "mutation-threshold", "faction-reputation"),
            )
        ],
    )

    result = await instantiate(actor, proposal)

    room = actor.world.get_entity(result.rooms["hub"])
    assert room.has_component(ShelterComponent)
    assert room.has_component(ProceduralSiteComponent)
    assert room.has_component(DungeonComponent)
    assert room.has_component(DungeonRoomComponent)
    assert room.has_component(TravelHubComponent)
    assert room.has_component(InstitutionComponent)
    assert room.has_component(QuestComponent)
    assert room.has_component(ShipComponent)
    assert room.has_component(PowerGridComponent)
    assert room.has_component(StationComponent)
    assert room.has_component(HabitatModuleComponent)
    assert room.has_component(PressurizedComponent)
    assert room.has_component(LifeSupportComponent)
    assert room.has_component(OxygenComponent)
    assert room.has_component(AirlockComponent)
    assert room.has_component(StarSystemComponent)
    assert room.has_component(RadiationSourceComponent)
    assert room.has_component(ScavengeSiteComponent)
    assert room.has_component(LootTableComponent)

    assert actor.world.get_entity(result.objects["firewood"]).has_component(FlammableComponent)
    assert actor.world.get_entity(result.objects["firewood"]).has_component(FireComponent)
    assert actor.world.get_entity(result.objects["barricade"]).has_component(ArmorComponent)
    assert actor.world.get_entity(result.objects["barricade"]).has_component(FortificationComponent)
    shrine = actor.world.get_entity(result.objects["shrine"])
    assert shrine.has_component(PointOfInterestComponent)
    assert shrine.has_component(FactionComponent)
    assert shrine.has_component(QuestComponent)
    assert actor.world.get_entity(result.objects["rumor"]).has_component(RumorComponent)
    assert actor.world.get_entity(result.objects["template"]).has_component(QuestTemplateComponent)
    fossil = actor.world.get_entity(result.objects["fossil_egg"])
    assert fossil.has_component(FossilFragmentComponent)
    assert fossil.has_component(EggComponent)
    ship_parts = actor.world.get_entity(result.objects["ship_parts"])
    assert ship_parts.has_component(JumpDriveComponent)
    assert ship_parts.has_component(FuelComponent)
    assert ship_parts.has_component(SensorComponent)
    assert ship_parts.has_component(DistressSignalComponent)
    rad_kit = actor.world.get_entity(result.objects["rad_kit"])
    assert rad_kit.has_component(RadProtectionComponent)
    assert rad_kit.has_component(DecontaminationComponent)
    assert rad_kit.has_component(RadMedicineComponent)
    assert rad_kit.has_component(JunkComponent)
    assert rad_kit.has_component(RadiationSourceComponent)
    assert rad_kit.has_component(ScavengeSiteComponent)

    fighter = actor.world.get_entity(result.characters["fighter"])
    assert fighter.has_component(StaminaComponent)
    assert fighter.has_component(DinosaurComponent)
    assert fighter.has_component(SpeciesComponent)
    assert fighter.has_component(FertilityComponent)
    assert fighter.has_component(RadiationDoseComponent)
    assert fighter.has_component(MutationThresholdComponent)
    assert fighter.has_component(FactionReputationComponent)


async def test_generated_world_is_playable_via_plugins():
    # Apply the core verbs, then drive a generated character through a move.
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    result = await instantiate(actor, StubWorldBuilder().propose("seed"))

    # Resume Juniper under a fresh controller so it can act.
    from bunnyland.core import spawn_entity

    controller = spawn_entity(actor.world)
    gen = actor.assign_controller(result.characters["juniper"], controller.id)
    actor.world.get_entity(result.characters["juniper"]).remove_component(SuspendedComponent)

    move = build_submitted_command(
        character_id=str(result.characters["juniper"]),
        controller_id=str(controller.id),
        controller_generation=gen,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "north"},
    )
    await actor.submit(move)
    await actor.tick(HOUR)

    juniper = actor.world.get_entity(result.characters["juniper"])
    assert container_of(juniper) == result.rooms["tunnel"]


async def test_instantiate_raises_on_invalid_proposal():
    actor = WorldActor()
    bad = WorldProposal(seed="x", rooms=[])
    with pytest.raises(ValueError):
        await instantiate(actor, bad)
