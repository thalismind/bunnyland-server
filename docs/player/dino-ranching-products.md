# Dino-sim ranching, feed, and creature products

Dino-sim ranching covers day-to-day creature care after you have eggs, companions, or
contained animals. It reuses lifesim age state, colony-sim resources, garden-style animal
feed loops, colony repair/work concepts, and barbarian-style combat where those packs are
enabled.

In Discord, prefix these commands with `!`.

## Feed stores

Feed stores can live on an enclosure, pen, or nearby room. Stock one directly:

```text
!stock-feed feed_store_id="Fern Paddock" amount=5
```

If the world uses colony-sim resources, stock feed by spending a carried resource stack:

```text
!stock-feed feed_store_id="Fern Paddock" amount=3 resource_type=hay
```

When `resource_type` is present, the command spends that many units from your inventory
before increasing the feed store. If you do not carry enough of that resource, the command
is refused and the feed store does not change.

## Hunger and stress

Observe a reachable creature:

```text
!observe-creature creature_id="clever raptor"
```

Feed it from a reachable feed store:

```text
!feed-creature creature_id="clever raptor" feed_store_id="Fern Paddock"
```

Calm stress:

```text
!calm-creature creature_id="clever raptor"
```

Living creatures grow hungry over time. Hunger can raise stress, and stressed animals are
more likely to become incident pressure in worlds that use storyteller or containment
systems. Nearby creature hunger and stress show in your character context.

## Eggs and products

Collect a reachable egg:

```text
!collect-egg egg_id="velociraptor egg"
```

Harvest a reachable creature product:

```text
!harvest target_id="clever raptor" product_type="milk"
!harvest target_id="clever raptor" product_type="toxin"
!harvest target_id="clever raptor" product_type="hide"
!harvest target_id="clever raptor" product_type="bone"
```

Renewable products can be depleted until the world restocks them. Hide and bone harvests
are usually one-time carcass or creature-product actions. Harvested products appear in your
inventory as items or resource-like outputs depending on the world setup.

## Ranch labor and guard duty

Assign ranch work to a reachable creature:

```text
!assign-ranch-work creature_id="clever raptor" work_type="haul" target_id="Fern Paddock"
```

Assign guard duty:

```text
!assign-guard creature_id="clever raptor" location_id="Fern Paddock"
```

Ranch labor records the work type and target. Guard duty records where the animal is
watching. These are durable behavior hints for prompt context, storyteller incidents, and
future work systems.

## Containment support

Ranching depends on containment. Keep pens maintained:

```text
!repair-fence enclosure_id="Fern Paddock" amount=4
!reinforce-gate enclosure_id="Fern Paddock" amount=2
!lock-pen enclosure_id="Fern Paddock"
```

If a creature escapes, recapture it into an enclosure:

```text
!recapture-creature creature_id="clever raptor" enclosure_id="Fern Paddock"
```

## Ranch loop

```text
!stock-feed feed_store_id="Fern Paddock" amount=3 resource_type=hay
!observe-creature creature_id="clever raptor"
!feed-creature creature_id="clever raptor" feed_store_id="Fern Paddock"
!calm-creature creature_id="clever raptor"
!collect-egg egg_id="velociraptor egg"
!harvest target_id="clever raptor" product_type="milk"
!assign-ranch-work creature_id="clever raptor" work_type="haul" target_id="Fern Paddock"
!assign-guard creature_id="clever raptor" location_id="Fern Paddock"
```
