# Hunger and thirst

Hunger and thirst are character needs. They rise as world time passes and can affect
prompts, context, and some scenario decisions when they become pressing.

## Eat

Food lowers hunger:

```text
!eat berry tart
```

Consumable food is removed when its uses run out. Some worlds also let you use or prepare
food through package-specific actions, but eating is the basic way to reduce hunger when
you already have edible food.

## Drink

Water sources lower thirst:

```text
!drink stone basin
```

Renewable drink sources, such as a basin, stay in the world. Consumable drinks can run
out like food.

## Time and need decay

Needs rise as world time passes. Waiting, moving, acting, or letting controllers run can
make hunger or thirst come back:

```text
!wait
!eat berry tart
!drink stone basin
```

Only pressing needs appear in some character context. If a client does not show hunger or
thirst all the time, use the room or character view, inspect your character where
available, or check the prompt/context surface that client exposes.

For fatigue, hygiene, comfort, fun, social contact, privacy, safety, and self-care, see
[Daily needs](daily-needs.md).
