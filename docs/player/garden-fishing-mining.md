# Garden-sim fishing and mining

Garden-sim includes fishing spots, mine nodes, mine levels, ladders, and geodes. These
loops create inventory resources that can feed bundles, gifts, shipping, museum donation,
or colony recipes.

In Discord, prefix these commands with `!`.

## Fishing

Fish at a reachable fishing spot:

```text
!fish spot_id="mountain lake"
```

Fishing spots can be seasonal and may require bait. A successful catch creates a fish
resource stack in inventory.

## Mining

Mine a reachable node:

```text
!mine node_id="copper rock"
```

Mining creates a resource stack and removes the node. Mine-level entities provide prompt
context for generated cave floors.

Discover a ladder:

```text
!discover-ladder ladder_id="dusty ladder"
```

The ladder records its target room id and whether it has been discovered.

## Geodes

Open an inventory geode:

```text
!open-geode geode_id="mottled geode"
```

Opening consumes the geode and creates its mineral resource.
