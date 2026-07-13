# Dino-sim fossils, eggs, companions, and kaiju incidents

Dino-sim adds prehistoric creature lifecycle mechanics. It is not a park-building package:
there are no guest, ticket, exhibit-rating, or shop loops. The main loops are finding and
identifying fossils, preparing clone eggs, handling reptile eggs and hatching, taming
creatures as companions, and dealing with kaiju attacks when storyteller and colony-sim are
active.

In Discord, prefix these commands with `!`.

For day-to-day ranching, feed stores, colony-sim resource-backed feed, creature needs,
eggs, products, ranch work, and guard duty, see
[Dino-sim ranching, feed, and creature products](dino-ranching-products.md).

## Fossils and cloning

Identify a reachable fossil by species:

```text
!identify target_id="amber bone shard" species_name="velociraptor"
```

Identified fossils record a `SpeciesIdentificationComponent` with the chosen species and
confidence based on sample quality.

Extract a viable ancient sample from an identified fossil:

```text
!extract-ancient-sample fossil_id="amber bone shard"
```

Prepare a clone from the sample:

```text
!prepare-clone sample_id="velociraptor ancient sample"
```

Clone preparation consumes the sample and creates a fertilized egg. From that point on the
egg uses the same incubation and hatching commands as naturally laid eggs.

## Egg handling and reptile procreation

Have a reachable reptile or dinosaur lay an egg:

```text
!lay-egg parent_id="clever raptor"
```

Fertilize a natural egg with a reachable fertile parent:

```text
!fertilize-egg egg_id="velociraptor egg" parent_id="clever raptor"
```

Start incubation:

```text
!incubate-egg egg_id="velociraptor egg"
```

When incubation has finished, hatch the egg:

```text
!hatch-egg egg_id="velociraptor egg"
```

Hatching creates a normal character/critter entity with dino and lifesim-compatible age
state. Lifesim can then handle ageing, care, relationships, injury, and death without a
separate dinosaur-only timeline.

## Tracking, taming, training, and companions

Track a reachable creature:

```text
!track-creature creature_id="clever raptor"
```

Set reachable bait for a species:

```text
!set-bait bait_id="scented bait" target_species="velociraptor" potency=1
```

Use a reachable tranquilizer item on a creature:

```text
!tranquilize-creature creature_id="clever raptor" tranquilizer_id="sleep dart"
```

Approach and tame the creature:

```text
!approach-creature creature_id="clever raptor"
!tame-creature creature_id="clever raptor" role="guard"
```

Bait and sedation make taming progress faster. When progress reaches the creature's
threshold, the creature becomes your companion.

Train and issue a companion command:

```text
!train-command creature_id="clever raptor" command_name="guard" progress=2
!command target_id="clever raptor" instruction="guard"
```

You can mount your own companion and recall it back to your current room:

```text
!mount-creature creature_id="clever raptor"
!recall-creature creature_id="clever raptor"
```

Companions are still normal creature entities with normal controllers. These commands add
durable ECS state for trust, training, current orders, mounting, and recall; they do not add
park-management systems.

## Enclosures, containment, and escapes

Build a pen around a room:

```text
!build target_id="Fern Paddock" name="Fern Pen" capacity=3 feeding_pen=true
```

Repair and reinforce containment:

```text
!repair-fence enclosure_id="Fern Paddock" amount=4
!reinforce-gate enclosure_id="Fern Paddock" amount=2
```

Lock or open the pen gate:

```text
!lock-pen enclosure_id="Fern Paddock"
!open-pen enclosure_id="Fern Paddock"
```

Open gates, breaches, and ruined fences raise escape risk. When risk crosses the threshold,
creatures can escape through a room exit. Trigger containment to close and lock the gate
again:

```text
!trigger-containment enclosure_id="Fern Paddock"
```

If a creature escapes, reach it and recapture it into an enclosure:

```text
!hide-from-creature creature_id="clever raptor"
!recapture-creature creature_id="clever raptor" enclosure_id="Fern Paddock"
```

Evacuate non-creature characters from a room during an incident:

```text
!evacuate-room room_id="Fern Paddock" destination_id="Amber Hatchery Lab"
```

## Dangerous encounters and damage response

Some creatures can carry attack, armor, weak point, pack hunt, apex predator, or kaiju
state. Respond directly when one threatens the room:

```text
!dodge-creature creature_id="clever raptor"
!fight-creature creature_id="clever raptor" damage=2
!target-weak-point creature_id="clever raptor" damage=2
!drive-off-predator creature_id="clever raptor"
```

Call for help or signal an army response during a large incident:

```text
!call-for-help room_id="Fern Paddock" strength=2
!signal-army room_id="Fern Paddock" creature_id="kaiju threat" strength=8
```

Repair settlement damage after a kaiju or predator incident:

```text
!repair-damage damage_id="damaged gatehouse" amount=2
```

## Creature needs

Living creatures grow hungry over time, and a hungry creature slowly becomes stressed.
Observe a reachable creature to read its current hunger and stress:

```text
!observe-creature creature_id="clever raptor"
```

Feed it from a reachable feed store to bring hunger back down:

```text
!feed-creature creature_id="clever raptor" feed_store_id="Fern Paddock"
```

Calm a stressed creature down:

```text
!calm-creature creature_id="clever raptor"
```

Each nearby creature's hunger and stress show in your character context, so you can keep
your ranch fed and settled before stress turns into trouble. The dedicated ranching guide
covers the feed and product loops in more detail.

## Creature products and ranch work

Feed stores can be stocked on an enclosure, pen, or nearby room:

```text
!stock-feed feed_store_id="Fern Paddock" amount=5
```

In worlds with colony-sim resources, stock feed from a carried resource stack:

```text
!stock-feed feed_store_id="Fern Paddock" amount=3 resource_type=hay
```

When `resource_type` is present, the command spends that many units from your inventory
before adding feed to the store. If you do not have enough of the resource, the feed store
is unchanged.

Collect eggs into inventory or harvest products from a reachable creature:

```text
!collect-egg egg_id="velociraptor egg"
!harvest target_id="clever raptor" product_type="milk"
!harvest target_id="clever raptor" product_type="toxin"
!harvest target_id="clever raptor" product_type="hide"
```

Assign ranch labor or guard duty to a creature:

```text
!assign-ranch-work creature_id="clever raptor" work_type="haul" target_id="Fern Paddock"
!assign-guard creature_id="clever raptor" location_id="Fern Paddock"
```

See the ranching guide for how feed stores, products, colony-sim feed resources, ranch
labor, and guard duty fit together.

## Fossil prep, incubation, and juvenile care

Survey, excavate, clean, and stabilize a reachable fossil:

```text
!survey-fossil fossil_id="amber bone shard"
!excavate-fossil fossil_id="amber bone shard" progress=0.5
!clean-fossil fossil_id="amber bone shard"
!stabilize-fossil fossil_id="amber bone shard"
```

Inspect and incubate eggs, including lab and brooding support:

```text
!inspect target_id="velociraptor egg" viability=0.9
!lab-incubate-egg egg_id="velociraptor egg" lab_id="Amber Hatchery Lab"
!brood-egg egg_id="velociraptor egg" warmth=1
!set-incubation-temperature egg_id="velociraptor egg" temperature=31
```

Imprint and care for young creatures:

```text
!imprint-creature creature_id="clever raptor" bond=1
!care-for-juvenile creature_id="clever raptor" care=1
```

Study aquatic creatures and mark containment panic:

```text
!study-water-creature creature_id="lagoon swimmer"
!trigger-containment-panic enclosure_id="Fern Paddock" severity=2
```

## Kaiju storyteller incidents

Kaiju attacks are storyteller incidents when both `bunnyland.dinosim` and
`bunnyland.colonysim` are enabled. The storyteller budget can select a `kaiju_attack`,
place an active incident in a room, split the attack budget across one to three epic
kaiju, choose target rooms from the incident room's region, and attach settlement damage.

Resolve the active incident with the normal storyteller command:

```text
!resolve-incident incident_id="kaiju attack"
```

Colony-sim provides the settlement side of the incident: evacuation, repair jobs, hauling,
resource pressure, and recovery. Without colony-sim, dino-sim can still use local creature
encounters, but it does not assume settlement damage or colony job queues exist.

## Example loop

```text
!identify target_id="amber bone shard" species_name="velociraptor"
!survey-fossil fossil_id="amber bone shard"
!excavate-fossil fossil_id="amber bone shard" progress=0.5
!clean-fossil fossil_id="amber bone shard"
!stabilize-fossil fossil_id="amber bone shard"
!extract-ancient-sample fossil_id="amber bone shard"
!prepare-clone sample_id="velociraptor ancient sample"
!inspect target_id="velociraptor egg" viability=0.9
!incubate-egg egg_id="velociraptor egg"
!set-incubation-temperature egg_id="velociraptor egg" temperature=31
!hatch-egg egg_id="velociraptor egg"
!lay-egg parent_id="clever raptor"
!fertilize-egg egg_id="velociraptor egg" parent_id="clever raptor"
!imprint-creature creature_id="clever raptor" bond=1
!care-for-juvenile creature_id="clever raptor" care=1
!track-creature creature_id="clever raptor"
!set-bait bait_id="scented bait" target_species="velociraptor"
!approach-creature creature_id="clever raptor"
!tame-creature creature_id="clever raptor"
!train-command creature_id="clever raptor" command_name="guard" progress=2
!command target_id="clever raptor" instruction="guard"
!build target_id="Fern Paddock" name="Fern Pen"
!fight-creature creature_id="clever raptor" damage=2
!target-weak-point creature_id="clever raptor" damage=2
!repair-damage damage_id="damaged gatehouse" amount=2
!stock-feed feed_store_id="Fern Paddock" amount=5
!harvest target_id="clever raptor" product_type="milk"
!assign-guard creature_id="clever raptor" location_id="Fern Paddock"
!lock-pen enclosure_id="Fern Paddock"
!resolve-incident incident_id="kaiju attack"
```
