# Colony-sim work and ownership

Colony-sim adds shared labor systems: reserving targets, gathering resources, crafting and
baking at workstations, assigning jobs, completing jobs, marking ownership, work
priorities, allowed areas, room quality, colony wealth, and medical recovery. These
mechanics are useful when several characters are working in the same settlement and need
the world to remember who is using what. See
[Colony health and work](colony-health-and-work.md) for the medical, room-quality, wealth,
priority, and mental-state loops.

In Discord, prefix these commands with `!`.

## Reserve work

Reserve a reachable object before working on it:

```text
!reserve target_id="wood patch"
```

The target must be visible or otherwise reachable from your current room or inventory. A
reservation tells other characters that you intend to use that target. When you are done,
release it:

```text
!release-reservation target_id="wood patch"
```

Use reservations for short-term work claims. Use ownership for durable property claims.

## Gather resources

Gather from a reachable resource node:

```text
!gather-resource node_id="wood patch" quantity=2
```

The node must have enough available resources. A successful gather reduces the node's
current amount and creates a resource stack in your inventory, such as `wood x2`.

## Stockpiles and hauling

Create a stockpile in your current room:

```text
!create-stockpile name="wood stockpile" capacity=20 allowed_types="wood,plank"
```

Change its filter later:

```text
!set-storage-filter stockpile_id="wood stockpile" allowed_types="wood,plank,stone"
```

Forbid a reachable item to keep it out of hauling, then allow it again:

```text
!forbid-item item_id="wood x6"
!allow-item item_id="wood x6"
```

Haul a reachable item or resource stack into a reachable container or stockpile:

```text
!haul-item item_id="wood x6" target_container_id="wood stockpile"
```

Filtered stockpiles accept only matching resource stacks. Empty filters accept anything.
Capacity counts resource stack quantity.

Split and merge resource stacks:

```text
!split-stack item_id="wood x6" quantity=2
!merge-stack source_id="wood x2" target_id="wood x4"
```

## Craft items

Craft from a known recipe:

```text
!craft recipe_id=club
```

Crafting consumes the required resource stacks and creates the recipe output in your
inventory. Some recipes require a workstation in the room, such as a workbench.

Baking uses the same recipe engine:

```text
!bake recipe_id=cookies
```

Recipes may create plain resource stacks or item entities with food/drink data and
consumable uses. Existing resource-stack recipes continue to work.

## Jobs

Assign yourself to a reachable job:

```text
!assign-job job_id="haul job"
```

Complete it when the work is done:

```text
!complete-job job_id="haul job"
```

Jobs are durable world state. They are meant for colony-style task boards, hauling,
construction, maintenance, and other shared work.

## Ownership

Claim durable ownership over reachable property:

```text
!claim-ownership target_id="wood patch"
```

Release that ownership when it should become shared again:

```text
!release-ownership target_id="wood patch"
```

Ownership is bookkeeping. It does not automatically stop another player from touching an
object unless the world, policy, or server rules enforce that separately.

## Core loop

A simple colony loop:

```text
!reserve target_id="wood patch"
!gather-resource node_id="wood patch" quantity=2
!create-stockpile name="wood stockpile" capacity=20 allowed_types="wood"
!haul-item item_id="wood x2" target_container_id="wood stockpile"
!craft recipe_id=club
!set-work-priority work_type=haul priority=2
!assign-job job_id="haul job"
!complete-job job_id="haul job"
!release-reservation target_id="wood patch"
!claim-ownership target_id="wood patch"
```
