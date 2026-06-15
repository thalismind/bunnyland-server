# Garden-sim farming

Garden-sim is the farm loop provided by the `bunnyland.gardensim` plugin. It includes
soil, crops, trees, edible produce, processing machines, animals, fishing, mining,
foraging, gifts, festivals, bundles, seasonal availability, greenhouse exceptions, and
daily farm reset. The full farm-to-sale path also uses `bunnyland.lifesim` for money,
customers, and businesses, and can use `bunnyland.colonysim` ownership if you want to mark
a bed as yours. See [Farm production](farm-production.md) for the machine, animal,
gathering, gift, festival, and bundle loops.

## Find a plot

A usable plot is a nearby entity with soil. In prompts and context it appears as something like:

```text
Nearby soil: garden bed.
Nearby tilled soil: garden bed.
Nearby crop: turnip in garden bed (stage 2).
Nearby tree: sugar maple in old maple (ready to tap).
```

You can garden any reachable soil bed. For gardening commands, reachable means the bed is in your current room or inventory. Ownership is optional bookkeeping, not a gardening requirement. If the world supports colony-sim ownership and you want to mark the bed as yours, claim it first:

```text
!claim-ownership garden bed
```

Engine notation for the same command is `claim-ownership`, without the Discord prefix.
The command fails if the bed is not reachable or someone else already owns it. Home and
room claims are separate life-sim commands and are not required for farming.

## Get seeds

Seeds are portable items with a crop type, growth time, valid seasons, and a harvest yield. You need the seed in your inventory or current room before planting. If seeds are lying nearby, take them:

```text
!take turnip seeds
```

If a merchant has seeds for sale, buy them:

```text
!buy radish seeds from Marigold
```

Buying requires the seller to be reachable, the item to be in the seller's inventory, a positive price, and enough household funds. When the seller owns a business, its default price is used unless a command supplies another price.

## Prepare and plant

Till the soil once:

```text
!till garden bed
```

Then plant a seed packet in that bed:

```text
!plant soil_id="garden bed" seed_id="turnip seeds"
```

Planting requires prepared soil and a plantable seed. The seed is consumed when planted. A bed can hold only one crop at a time.
If the world has an environment calendar, seeds can only be planted in their valid seasons
unless the soil is a greenhouse bed.

Fertilizer is optional. If you have reachable fertilizer, apply it to the soil:

```text
!fertilize garden bed with speed fertilizer
```

Fertilizer is consumed and its multiplier affects crop growth on that soil.

## Water and grow

Water the bed:

```text
!water-crop garden bed
```

Watering lasts one in-game day. Crops only gain growth progress while watered, so keep watering and waiting until the crop becomes ready. A one-day crop usually needs one watered day to mature:

```text
!water-crop garden bed
!wait
```

Crop state appears in nearby context as stages, `ready`, or `dead`. If the environment calendar has a season and the crop does not support that season, the crop withers and cannot be harvested. Default seeds grow in spring, summer, and autumn; winter crops need seeds that explicitly support winter.

Clear a dead crop before planting again:

```text
!clear-dead-crop garden bed
```

## Harvest

When the crop is ready, harvest the bed:

```text
!harvest garden bed
```

Harvesting fails if the crop is missing, dead, or not ready. A successful harvest removes
the crop from the soil and puts the produce in your inventory as a resource stack. If the
yield is more than one, the item name includes the quantity, such as `radish x2`. Seeds can
also mark produce as edible, allowing the same harvest to feed recipes, bundles, gifts, or
the `eat` command.

The bed stays tilled after harvest, so you can plant another seed in it.

## Trees and sap

Trees are reachable garden entities. A tree can be growing, ready to tap, tapped, sap
ready, or dead. Growing trees become ready as world time passes, so waiting is part of the
tree loop:

```text
!wait
```

When a tree is ready, tap it:

```text
!tap-tree sugar maple
```

Tapping fails if the target is not a tree, is dead, is still growing, or is already tapped.
Once tapped, the bucket needs collection time. Wait until nearby context says the tree has
sap ready:

```text
!wait
```

Then collect the sap:

```text
!harvest sugar maple
```

Harvesting sap fails if the tree is not tapped or the sap is not ready yet. A successful
harvest puts a portable sap resource stack in your inventory and resets the bucket so it
can fill again after more waiting. If colony-sim crafting is available, that sap can feed
recipes such as a sugar-shack evaporator recipe.

The `maple-farm-demo` world is a Canadian sugarbush built around this loop. It includes
maples that need time, trees ready to tap, a tapped tree, a sugar shack, a sap stockpile,
an evaporator workstation, and a maple syrup recipe.

## Sell the harvest

Selling produce uses the life-sim business system. First open a business or farm stand:

```text
!open-business name="Hazel's Farm Stand" default_price=8
```

Then sell the harvested item to a reachable customer:

```text
!sell-item item_id="radish x2" customer_id=Marigold price=8
```

Selling requires:

- the item in your inventory;
- an open business owned by your character;
- a reachable target with a customer budget;
- a positive price;
- enough customer budget to cover that price.

If the sale succeeds, the item leaves your inventory, your household funds increase, the customer's budget decreases, and your business sales count increases. If no price is supplied, the business default price is used.

## Complete cycle

One verified end-to-end cycle looks like this:

```text
!claim-ownership garden bed
!till garden bed
!fertilize garden bed with speed fertilizer
!plant soil_id="garden bed" seed_id="radish seeds"
!water-crop garden bed
!wait
!harvest garden bed
!wait
!tap-tree sugar maple
!wait
!harvest sugar maple
!open-business name="Hazel's Farm Stand" default_price=8
!sell-item item_id="radish x2" customer_id=Marigold price=8
```

The claim step is optional for crop mechanics, but it is useful in shared colony-style worlds where players want the prompt context to show who owns a bed.
