# Dino-sim fossils, eggs, companions, and kaiju incidents

Dino-sim adds prehistoric creature lifecycle mechanics. It is not a park-building package:
there are no guest, ticket, exhibit-rating, or shop loops. The main loops are finding and
identifying fossils, preparing clone eggs, handling reptile eggs and hatching, taming
creatures as companions, and dealing with kaiju attacks when storyteller and colony-sim are
active.

In Discord, prefix these commands with `!`.

## Fossils and cloning

Identify a reachable fossil by species:

```text
!identify-fossil fossil_id="amber bone shard" species_name="velociraptor"
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
!command-companion creature_id="clever raptor" command_name="guard"
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
!build-enclosure room_id="Fern Paddock" name="Fern Pen" capacity=3 feeding_pen=true
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

## Kaiju storyteller incidents

Kaiju attacks are storyteller incidents when both `bunnyland.dinosim` and
`bunnyland.colonysim` are enabled. The storyteller budget can select a `kaiju_attack`,
place an active incident in a room, spawn a kaiju threat, and attach settlement damage.

Resolve the active incident with the normal storyteller command:

```text
!resolve-incident incident_id="kaiju attack"
```

Colony-sim provides the settlement side of the incident: evacuation, repair jobs, hauling,
resource pressure, and recovery. Without colony-sim, dino-sim can still use local creature
encounters, but it does not assume settlement damage or colony job queues exist.

## Example loop

```text
!identify-fossil fossil_id="amber bone shard" species_name="velociraptor"
!extract-ancient-sample fossil_id="amber bone shard"
!prepare-clone sample_id="velociraptor ancient sample"
!incubate-egg egg_id="velociraptor egg"
!hatch-egg egg_id="velociraptor egg"
!lay-egg parent_id="clever raptor"
!fertilize-egg egg_id="velociraptor egg" parent_id="clever raptor"
!track-creature creature_id="clever raptor"
!set-bait bait_id="scented bait" target_species="velociraptor"
!approach-creature creature_id="clever raptor"
!tame-creature creature_id="clever raptor"
!train-command creature_id="clever raptor" command_name="guard" progress=2
!command-companion creature_id="clever raptor" command_name="guard"
!build-enclosure room_id="Fern Paddock" name="Fern Pen"
!lock-pen enclosure_id="Fern Paddock"
!resolve-incident incident_id="kaiju attack"
```
