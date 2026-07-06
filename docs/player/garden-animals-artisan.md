# Garden-sim animals and artisan machines

Garden-sim animals can be fed, petted, bred, and harvested for products. Machines process
resources over time, can be canceled, can break down, and can be repaired.

In Discord, prefix these commands with `!`.

## Animals

Feed and pet a reachable animal:

```text
!feed-animal animal_id="Daisy" feed_type=hay
!pet-animal animal_id="Daisy"
```

Fed animals have better mood. Petting improves friendship and is reset by the daily farm
reset.

Collect a ready product:

```text
!collect-animal-product animal_id="Daisy"
```

Breed two animals of the same species:

```text
!breed-animal animal_id="Daisy" mate_id="Clover" gestation_seconds=86400
```

When gestation is due, the animal birth consequence creates an offspring entity in the
same room.

## Machines

Start a machine recipe:

```text
!start-machine machine_id="preserves jar" recipe_id=berry-jam
```

Cancel a task:

```text
!cancel-machine machine_id="preserves jar"
```

Repair a broken machine:

```text
!repair-machine machine_id="old loom"
```

Broken machines reject new processing until repaired.
