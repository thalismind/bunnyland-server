# Garden-sim farm production

Garden-sim covers more than crop beds. V1 farm production includes edible harvests,
processing machines, farm animals, fishing, mining, foraging, gifts, festivals, bundles,
season checks, greenhouse exceptions, and daily farm reset state.

## Edible produce

Harvested crops become portable resource stacks. Seeds can also mark their produce as
edible. Edible produce carries food data, so the same strawberry stack can be used in a
recipe, gifted, contributed to a bundle, or eaten with `!eat`.

## Processing machines

Machines use processing recipes. Start a machine with a reachable machine and a known
recipe:

```text
!start-machine machine_id="mill" recipe_id=flour
```

Starting a machine consumes the required resource stacks from your inventory and creates a
timed processing task on the machine. When enough world time has passed, collect output:

```text
!collect-machine-output machine_id="mill"
```

Recipes can create plain resource stacks or consumable food/drink outputs. This is the
farm production bridge into colony-sim crafting and baking.

## Baking through recipes

Baking uses the same recipe engine as crafting:

```text
!bake recipe_id=cookies
```

A cookie recipe can require an oven workstation, consume resources such as flour and
sugar, and create edible cookie entities with multiple uses. There is no separate cooking
subsystem to learn.

## Farm animals

Farm animals track age, mood, friendship, sickness, feeding, petting, and products.

Feed an animal with a resource stack such as hay:

```text
!feed-animal animal_id=Henrietta feed_type=hay
```

Pet an animal once per day:

```text
!pet-animal animal_id=Henrietta
```

Adult, healthy animals can produce items such as eggs, milk, or wool on their production
interval. Collect ready products with:

```text
!collect-animal-product animal_id=Henrietta
```

Friendship and mood improve product quality.

## Fishing, mining, and foraging

Gather field resources with explicit handlers:

```text
!fish spot_id="pond"
!mine node_id="copper node"
!forage forage_id="wild leek"
```

Fishing spots can be seasonal and can require bait. Mining nodes and forage objects are
removed after collection and place resource stacks in your inventory.

## Gifts and friendship

Give an inventory item to a reachable character:

```text
!give-gift target_id=Marnie item_id="wild leek"
```

Gift preferences can mark resources as loved, liked, or disliked. The recipient's farm
friendship points update and the item moves into their inventory.

## Festivals

Festival entities are reachable world objects with a season. Join an active festival with:

```text
!join-festival festival_id="Egg Festival"
```

Joining records the character on the festival component and emits a visible event. If the
environment calendar is present, the festival must match the current season.

## Bundles

Bundles track required resource types and contributed quantities:

```text
!contribute-bundle bundle_id="Spring Bundle" resource_type=trout quantity=1
```

Contributing consumes matching resource stacks from your inventory. The bundle is marked
complete when every requirement is filled.

## Daily reset

Worlds can include a daily farm reset component. Once a full in-game day passes, reset
events clear per-day animal interaction flags such as petting so the next day's farm loop
can begin.
