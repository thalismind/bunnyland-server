"""Colony-sim social crafting mechanics (spec 11.17, 21.4).

This v1 focuses on explicit reservations, resource gathering, and recipe crafting. It
intentionally does not include base building or hidden job automation.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic.dataclasses import dataclass
from relics import Component, Edge, Entity, EntityId, Frequency, System, World

from ..core.commands import SubmittedCommand
from ..core.components import (
    IdentityComponent,
    PortableComponent,
)
from ..core.ecs import (
    container_of,
    contents,
    parse_entity_id,
    reachable_ids,
    replace_component,
    spawn_entity,
)
from ..core.edges import ContainmentMode, Contains
from ..core.events import (
    EventVisibility,
    ItemCraftedEvent,
    JobAssignedEvent,
    JobCompletedEvent,
    OwnershipClaimedEvent,
    OwnershipReleasedEvent,
    ReservationCreatedEvent,
    ReservationReleasedEvent,
    ResourceGatheredEvent,
)
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected

SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class ResourceNodeComponent(Component):
    resource_type: str
    current: int
    maximum: int
    regen_per_day: float = 0.0


@dataclass(frozen=True)
class ResourceStackComponent(Component):
    resource_type: str
    quantity: int


@dataclass(frozen=True)
class WorkstationComponent(Component):
    station_type: str
    quality: float = 1.0


@dataclass(frozen=True)
class RecipeComponent(Component):
    recipe_id: str
    inputs: dict[str, int]
    outputs: dict[str, int]
    required_station: str | None = None
    action_cost: int = 1


@dataclass(frozen=True)
class JobComponent(Component):
    job_type: str
    priority: int
    assigned: bool = False
    completed: bool = False


@dataclass(frozen=True)
class ReservedBy(Edge):
    since_epoch: int


@dataclass(frozen=True)
class AssignedTo(Edge):
    since_epoch: int


@dataclass(frozen=True)
class Owns(Edge):
    since_epoch: int


class ResourceRegenSystem(System):
    """Regenerate resource nodes up to their maximum from ``regen_per_day``."""

    def query(self):
        return self.q.with_all([ResourceNodeComponent])

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        days = delta / SECONDS_PER_DAY
        if days <= 0:
            return
        for entity in entities:
            node = entity.get_component(ResourceNodeComponent)
            if node.regen_per_day <= 0 or node.current >= node.maximum:
                continue
            recovered = int(node.regen_per_day * days)
            if recovered <= 0:
                continue
            replace_component(
                entity,
                replace(node, current=min(node.maximum, node.current + recovered)),
            )


def _reservation_holder(entity: Entity) -> EntityId | None:
    reservations = entity.get_relationships(ReservedBy)
    return reservations[0][1] if reservations else None


def _assignment_holder(entity: Entity) -> EntityId | None:
    assignments = entity.get_relationships(AssignedTo)
    return assignments[0][1] if assignments else None


def _reserved_by_other(entity: Entity, character_id: EntityId) -> bool:
    holder = _reservation_holder(entity)
    return holder is not None and holder != character_id


def _assigned_by_other(entity: Entity, character_id: EntityId) -> bool:
    holder = _assignment_holder(entity)
    return holder is not None and holder != character_id


def _owner(entity: Entity) -> EntityId | None:
    owners = entity.get_incoming_relationships(Owns)
    return owners[0][0] if owners else None


def _room_id(world: World, character_id: EntityId) -> str | None:
    raw = container_of(world.get_entity(character_id))
    return str(raw) if raw is not None else None


def _resource_name(resource_type: str, quantity: int) -> str:
    return f"{resource_type} x{quantity}"


def _stack_in_inventory(character: Entity, world: World, resource_type: str) -> Entity | None:
    for item_id in contents(character):
        item = world.get_entity(item_id)
        if (
            item.has_component(ResourceStackComponent)
            and item.get_component(ResourceStackComponent).resource_type == resource_type
        ):
            return item
    return None


def _add_resource_stack(character: Entity, world: World, resource_type: str, quantity: int) -> str:
    existing = _stack_in_inventory(character, world, resource_type)
    if existing is not None:
        stack = existing.get_component(ResourceStackComponent)
        updated = replace(stack, quantity=stack.quantity + quantity)
        replace_component(existing, updated)
        replace_component(
            existing,
            IdentityComponent(
                name=_resource_name(resource_type, updated.quantity),
                kind="resource",
            ),
        )
        return str(existing.id)

    item = spawn_entity(
        world,
        [
            IdentityComponent(name=_resource_name(resource_type, quantity), kind="resource"),
            ResourceStackComponent(resource_type=resource_type, quantity=quantity),
            PortableComponent(can_pick_up=True),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    return str(item.id)


def _consume_resource_stack(
    character: Entity, world: World, resource_type: str, quantity: int
) -> bool:
    item = _stack_in_inventory(character, world, resource_type)
    if item is None:
        return False
    stack = item.get_component(ResourceStackComponent)
    if stack.quantity < quantity:
        return False
    remaining = stack.quantity - quantity
    if remaining == 0:
        character.remove_relationship(Contains, item.id)
    else:
        replace_component(item, replace(stack, quantity=remaining))
        replace_component(
            item,
            IdentityComponent(name=_resource_name(resource_type, remaining), kind="resource"),
        )
    return True


def _find_recipe(world: World, recipe_id: str) -> tuple[EntityId, RecipeComponent] | None:
    for entity in world.query().with_all([RecipeComponent]).execute_entities():
        recipe = entity.get_component(RecipeComponent)
        if recipe.recipe_id == recipe_id:
            return entity.id, recipe
    return None


def _has_station(world: World, character: Entity, station_type: str) -> bool:
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if (
            entity.has_component(WorkstationComponent)
            and entity.get_component(WorkstationComponent).station_type == station_type
        ):
            return True
    return False


class ReserveHandler:
    command_type = "reserve"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if character_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")

        character = ctx.entity(character_id)
        if target_id not in reachable_ids(ctx.world, character):
            return rejected("target is not reachable")
        target = ctx.entity(target_id)
        if _reserved_by_other(target, character_id):
            return rejected("target is reserved")
        if target.has_relationship(ReservedBy, character_id):
            return rejected("already reserved")

        target.add_relationship(ReservedBy(since_epoch=ctx.epoch), character_id)
        return ok(
            ReservationCreatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                )
            )
        )


class ReleaseReservationHandler:
    command_type = "release-reservation"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if character_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")

        target = ctx.entity(target_id)
        if not target.has_relationship(ReservedBy, character_id):
            return rejected("not reserved by you")
        target.remove_relationship(ReservedBy, character_id)
        return ok(
            ReservationReleasedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                )
            )
        )


class GatherResourceHandler:
    command_type = "gather-resource"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        node_id = parse_entity_id(command.payload.get("node_id"))
        quantity = int(command.payload.get("quantity", 1))
        if character_id is None or node_id is None:
            return rejected("invalid character or resource node id")
        if quantity <= 0:
            return rejected("quantity must be positive")
        if not ctx.world.has_entity(node_id):
            return rejected("resource node does not exist")

        character = ctx.entity(character_id)
        if node_id not in reachable_ids(ctx.world, character):
            return rejected("resource node is not reachable")
        node = ctx.entity(node_id)
        if not node.has_component(ResourceNodeComponent):
            return rejected("target is not a resource node")
        if _reserved_by_other(node, character_id):
            return rejected("resource node is reserved")

        resource = node.get_component(ResourceNodeComponent)
        if resource.current < quantity:
            return rejected("not enough resource")
        replace_component(node, replace(resource, current=resource.current - quantity))
        stack_id = _add_resource_stack(character, ctx.world, resource.resource_type, quantity)
        return ok(
            ResourceGatheredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(node_id), stack_id),
                    node_id=str(node_id),
                    resource_type=resource.resource_type,
                    quantity=quantity,
                    stack_id=stack_id,
                )
            )
        )


class CraftHandler:
    command_type = "craft"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        recipe_id = str(command.payload.get("recipe_id", "")).strip()
        if character_id is None:
            return rejected("invalid character id")
        if not recipe_id:
            return rejected("missing recipe id")

        recipe_result = _find_recipe(ctx.world, recipe_id)
        if recipe_result is None:
            return rejected("recipe does not exist")
        _recipe_entity_id, recipe = recipe_result
        character = ctx.entity(character_id)
        if recipe.required_station and not _has_station(
            ctx.world, character, recipe.required_station
        ):
            return rejected("required workstation is not reachable")
        for resource_type, quantity in recipe.inputs.items():
            stack = _stack_in_inventory(character, ctx.world, resource_type)
            if stack is None or stack.get_component(ResourceStackComponent).quantity < quantity:
                return rejected("missing recipe inputs")

        for resource_type, quantity in recipe.inputs.items():
            _consume_resource_stack(character, ctx.world, resource_type, quantity)
        output_ids = tuple(
            _add_resource_stack(character, ctx.world, resource_type, quantity)
            for resource_type, quantity in recipe.outputs.items()
        )
        return ok(
            ItemCraftedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=output_ids,
                    recipe_id=recipe.recipe_id,
                    output_ids=output_ids,
                )
            )
        )


class AssignJobHandler:
    command_type = "assign-job"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        job_id = parse_entity_id(command.payload.get("job_id"))
        if character_id is None or job_id is None:
            return rejected("invalid character or job id")
        if not ctx.world.has_entity(job_id):
            return rejected("job does not exist")

        character = ctx.entity(character_id)
        job_entity = ctx.entity(job_id)
        if job_id not in reachable_ids(ctx.world, character):
            return rejected("job is not reachable")
        if not job_entity.has_component(JobComponent):
            return rejected("target is not a job")
        job = job_entity.get_component(JobComponent)
        if job.completed:
            return rejected("job is already complete")
        if _assigned_by_other(job_entity, character_id):
            return rejected("job is assigned")
        if job_entity.has_relationship(AssignedTo, character_id):
            return rejected("job already assigned to you")

        replace_component(job_entity, replace(job, assigned=True))
        job_entity.add_relationship(AssignedTo(since_epoch=ctx.epoch), character_id)
        return ok(
            JobAssignedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(job_id),),
                    job_id=str(job_id),
                )
            )
        )


class CompleteJobHandler:
    command_type = "complete-job"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        job_id = parse_entity_id(command.payload.get("job_id"))
        if character_id is None or job_id is None:
            return rejected("invalid character or job id")
        if not ctx.world.has_entity(job_id):
            return rejected("job does not exist")

        job_entity = ctx.entity(job_id)
        if not job_entity.has_component(JobComponent):
            return rejected("target is not a job")
        if not job_entity.has_relationship(AssignedTo, character_id):
            return rejected("job is not assigned to you")

        job = job_entity.get_component(JobComponent)
        replace_component(job_entity, replace(job, assigned=False, completed=True))
        job_entity.remove_relationship(AssignedTo, character_id)
        return ok(
            JobCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(job_id),),
                    job_id=str(job_id),
                )
            )
        )


class ClaimOwnershipHandler:
    command_type = "claim-ownership"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if character_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")

        character = ctx.entity(character_id)
        if target_id not in reachable_ids(ctx.world, character):
            return rejected("target is not reachable")
        target = ctx.entity(target_id)
        owner_id = _owner(target)
        if owner_id == character_id:
            return rejected("already owned by you")
        if owner_id is not None:
            return rejected("target is already owned")

        character.add_relationship(Owns(since_epoch=ctx.epoch), target_id)
        return ok(
            OwnershipClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                )
            )
        )


class ReleaseOwnershipHandler:
    command_type = "release-ownership"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if character_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")

        character = ctx.entity(character_id)
        if not character.has_relationship(Owns, target_id):
            return rejected("not owned by you")

        character.remove_relationship(Owns, target_id)
        return ok(
            OwnershipReleasedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                )
            )
        )


def colonysim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    inventory = []
    for item_id in contents(character):
        item = world.get_entity(item_id)
        if item.has_component(ResourceStackComponent):
            stack = item.get_component(ResourceStackComponent)
            inventory.append(f"{stack.quantity} {stack.resource_type}")
    if inventory:
        lines.append("You have resources: " + ", ".join(sorted(inventory)) + ".")
    for entity in world.query().with_all([RecipeComponent]).execute_entities():
        recipe = entity.get_component(RecipeComponent)
        lines.append(f"You know the {recipe.recipe_id} recipe.")
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(ResourceNodeComponent):
            resource = entity.get_component(ResourceNodeComponent)
            lines.append(
                f"Nearby resource: {resource.resource_type} ({resource.current} available)."
            )
        if entity.has_component(WorkstationComponent):
            station = entity.get_component(WorkstationComponent)
            lines.append(f"Nearby workstation: {station.station_type}.")
        if entity.has_component(JobComponent):
            job = entity.get_component(JobComponent)
            if not job.completed:
                status = "assigned" if job.assigned else "available"
                lines.append(
                    f"Nearby job: {job.job_type} priority {job.priority} ({status})."
                )
        if character.has_relationship(Owns, entity_id) and entity_id != character.id:
            name = (
                entity.get_component(IdentityComponent).name
                if entity.has_component(IdentityComponent)
                else "something"
            )
            lines.append(f"You own {name}.")
    return sorted(lines)


__all__ = [
    "AssignedTo",
    "AssignJobHandler",
    "ClaimOwnershipHandler",
    "CompleteJobHandler",
    "CraftHandler",
    "GatherResourceHandler",
    "JobComponent",
    "Owns",
    "RecipeComponent",
    "ReleaseOwnershipHandler",
    "ReleaseReservationHandler",
    "ReserveHandler",
    "ReservedBy",
    "ResourceNodeComponent",
    "ResourceRegenSystem",
    "ResourceStackComponent",
    "WorkstationComponent",
    "colonysim_fragments",
]
