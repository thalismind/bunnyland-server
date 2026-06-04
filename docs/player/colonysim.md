# Colony-sim work and ownership

Colony-sim adds shared labor systems: reserving targets, gathering resources, crafting at
workstations, assigning jobs, completing jobs, and marking ownership. These mechanics are
useful when several characters are working in the same room and need the world to remember
who is using what.

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

## Craft items

Craft from a known recipe:

```text
!craft recipe_id=club
```

Crafting consumes the required resource stacks and creates the recipe output in your
inventory. Some recipes require a workstation in the room, such as a workbench.

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
!craft recipe_id=club
!assign-job job_id="haul job"
!complete-job job_id="haul job"
!release-reservation target_id="wood patch"
!claim-ownership target_id="wood patch"
```
