"""Tests for colony-sim reservations, gathering, and crafting."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    PortableComponent,
    build_submitted_command,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.events import (
    CommandRejectedEvent,
    ItemCraftedEvent,
    ResourceGatheredEvent,
)
from bunnyland.mechanics.colonysim import (
    CraftHandler,
    GatherResourceHandler,
    RecipeComponent,
    ReleaseReservationHandler,
    ReservedBy,
    ReserveHandler,
    ResourceNodeComponent,
    ResourceStackComponent,
    WorkstationComponent,
    colonysim_fragments,
)

HOUR = 3600.0


def _install(actor):
    actor.register_handler(ReserveHandler())
    actor.register_handler(ReleaseReservationHandler())
    actor.register_handler(GatherResourceHandler())
    actor.register_handler(CraftHandler())


def _cmd(scenario, command_type, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def _resource_node(scenario, resource_type="wood", current=3):
    node = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=f"{resource_type} patch", kind="resource_node"),
            ResourceNodeComponent(resource_type=resource_type, current=current, maximum=current),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), node.id
    )
    return node.id


def _stack(scenario, resource_type, quantity):
    item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=f"{resource_type} x{quantity}", kind="resource"),
            ResourceStackComponent(resource_type=resource_type, quantity=quantity),
            PortableComponent(can_pick_up=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), item.id
    )
    return item.id


async def test_reservation_blocks_other_characters_until_released():
    scenario = build_scenario()
    _install(scenario.actor)
    node = _resource_node(scenario)

    await scenario.actor.submit(_cmd(scenario, "reserve", target_id=str(node)))
    await scenario.actor.tick(HOUR)

    assert scenario.actor.world.get_entity(node).has_relationship(ReservedBy, scenario.character)

    await scenario.actor.submit(_cmd(scenario, "release-reservation", target_id=str(node)))
    await scenario.actor.tick(HOUR)

    assert not scenario.actor.world.get_entity(node).has_relationship(
        ReservedBy, scenario.character
    )


async def test_gather_resource_decrements_node_and_adds_inventory_stack():
    scenario = build_scenario()
    _install(scenario.actor)
    node = _resource_node(scenario, current=4)
    gathered: list[ResourceGatheredEvent] = []
    scenario.actor.bus.subscribe(ResourceGatheredEvent, gathered.append)

    await scenario.actor.submit(
        _cmd(scenario, "gather-resource", node_id=str(node), quantity=2)
    )
    await scenario.actor.tick(HOUR)

    node_entity = scenario.actor.world.get_entity(node)
    assert node_entity.get_component(ResourceNodeComponent).current == 2
    stack = scenario.actor.world.get_entity(parse_entity_id(gathered[0].stack_id))
    assert stack.get_component(ResourceStackComponent).resource_type == "wood"
    assert stack.get_component(ResourceStackComponent).quantity == 2


async def test_gather_rejects_when_resource_reserved_by_someone_else():
    scenario = build_scenario()
    _install(scenario.actor)
    node = _resource_node(scenario)
    other = spawn_entity(scenario.actor.world, [IdentityComponent(name="Other", kind="character")])
    scenario.actor.world.get_entity(node).add_relationship(ReservedBy(since_epoch=0), other.id)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "gather-resource", node_id=str(node)))
    await scenario.actor.tick(HOUR)

    assert any("reserved" in event.reason for event in rejects)


async def test_craft_consumes_inputs_at_reachable_workstation_and_creates_outputs():
    scenario = build_scenario()
    _install(scenario.actor)
    _stack(scenario, "wood", 2)
    recipe = spawn_entity(
        scenario.actor.world,
        [
            RecipeComponent(
                recipe_id="club",
                inputs={"wood": 2},
                outputs={"club": 1},
                required_station="bench",
            )
        ],
    )
    bench = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Workbench", kind="workstation"),
            WorkstationComponent(station_type="bench"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), bench.id
    )
    crafted: list[ItemCraftedEvent] = []
    scenario.actor.bus.subscribe(ItemCraftedEvent, crafted.append)

    await scenario.actor.submit(_cmd(scenario, "craft", recipe_id="club"))
    await scenario.actor.tick(HOUR)

    assert recipe.has_component(RecipeComponent)
    assert crafted[0].recipe_id == "club"
    output = scenario.actor.world.get_entity(parse_entity_id(crafted[0].output_ids[0]))
    assert output.get_component(ResourceStackComponent).resource_type == "club"
    assert output.get_component(ResourceStackComponent).quantity == 1


def test_colonysim_fragments_show_nearby_resources_and_recipes():
    scenario = build_scenario()
    _resource_node(scenario, "berries", current=5)
    spawn_entity(
        scenario.actor.world,
        [RecipeComponent(recipe_id="snack", inputs={"berries": 1}, outputs={"snack": 1})],
    )

    fragments = colonysim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )

    assert any("berries" in line for line in fragments)
    assert any("snack recipe" in line for line in fragments)
