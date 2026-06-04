# How to use environment and mechanisms

Environment mechanics track time, weather, light, and fire. Mechanisms are objects such
as doors and buttons.

## Doors and buttons

Use a reachable door:

```text
!use green door
```

Some doors are lockable:

```text
!take brass key
!use burrow door with brass key
!use burrow door
```

Buttons are also used through the same verb:

```text
!use round button
```

Some mechanisms reset automatically after world ticks. A momentary button can pop back
up, and an auto-close door can shut after it has been open long enough.

## Fire

Ignite a reachable flammable target:

```text
!ignite target_id="dry kindling"
```

Extinguish a burning target:

```text
!extinguish target_id="dry kindling"
```

Room fires can spread to flammable contents and damage active characters. If the prompt
or room context says there is a fire here, treat it as an immediate problem.

## Time and weather

Time and weather usually happen through ticks rather than direct player commands. They can
change room light, prompt context, and how urgent nearby hazards feel. Use `!look` after
waiting or moving to refresh what your character can see.
