# Dino-sim fossils, eggs, and kaiju incidents

Dino-sim adds prehistoric creature lifecycle mechanics. It is not a park-building package:
there are no guest, ticket, exhibit-rating, or shop loops. The main loops are finding and
identifying fossils, preparing clone eggs, handling reptile eggs and hatching, and dealing
with kaiju attacks when storyteller and colony-sim are active.

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
!resolve-incident incident_id="kaiju attack"
```
