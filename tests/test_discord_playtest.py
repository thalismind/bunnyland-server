from __future__ import annotations

from pathlib import Path

from bunnyland.core import (
    CharacterComponent,
    ContainmentMode,
    Contains,
    IdentityComponent,
    PortableComponent,
    container_of,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.discord.playtest import (
    DiscordPlaytest,
    PlaytestInput,
    load_discord_playtest,
    run_discord_playtest,
)
from bunnyland.engine import GameLoop
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent
from bunnyland.mechanics.colonysim import ClaimOwnershipHandler, Owns
from bunnyland.mechanics.gardensim import (
    CropComponent,
    CropGrowthConsequence,
    CropHarvestedEvent,
    CropReadyEvent,
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
    return soil.id, merchant.id


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
    assert "Done: claim room." in result.inputs[1].messages[0]
    assert claim.claimed_by_id == str(scenario.character)
    assert claim.claimed_at_epoch == scenario.actor.epoch


async def test_discord_playtest_character_gardens_claimed_land_end_to_end(scenario):
    _install_gardening_playtest(scenario.actor)
    soil_id, merchant_id = _add_garden_market(scenario)
    rejected: list[CommandRejectedEvent] = []
    ready: list[CropReadyEvent] = []
    harvested: list[CropHarvestedEvent] = []
    sold: list[BusinessSaleEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejected.append)
    scenario.actor.bus.subscribe(CropReadyEvent, ready.append)
    scenario.actor.bus.subscribe(CropHarvestedEvent, harvested.append)
    scenario.actor.bus.subscribe(BusinessSaleEvent, sold.append)
    spec = load_discord_playtest(PLAYTEST_DIR / "discord-gardening.json")

    result = await run_discord_playtest(_loop(scenario.actor), spec)

    character = scenario.actor.world.get_entity(scenario.character)
    merchant = scenario.actor.world.get_entity(merchant_id)
    soil = scenario.actor.world.get_entity(soil_id)
    harvested_item = scenario.actor.world.get_entity(parse_entity_id(harvested[0].item_id))
    assert rejected == []
    assert result.ticks == 33
    assert len(result.inputs) == 8
    assert character.has_relationship(Owns, soil_id)
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
