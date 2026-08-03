# Barbarian-sim combat and survival

Barbarian-sim adds direct conflict and survival pressure: challenges, defending, sparring,
attacks, item durability, fortifications, raids, poison, corruption, and pickpocketing.
Some actions are controlled by world policy; if a server has not enabled PvP or
pickpocketing, those commands can be rejected.

## Wetness and shelter

Wetness is a private character meter from 0 to 100. Your survival prompt always summarizes
it, but other characters do not see that private state.

| Wetness | Prompt state |
| ---: | --- |
| 0–39 | `You are dry.` |
| 40–69 | `You are damp.` |
| 70–89 | `You are wet.` |
| 90–100 | `You are soaked.` |

Wetness changes according to elapsed game time, not real-world time. Each game hour:

- Outdoor rain adds `20 × weather intensity` wetness before rain protection. Ordinary
  generated rain has intensity `0.7`, so it adds 14 points without shelter.
- Outdoor storms use the same calculation. Their generated intensity is `1.0`, so they
  add 20 points without shelter.
- An explicitly moist room adds up to 40 points at maximum room moisture. This source is
  separate from weather and adds to rain or storm wetness when both apply.
- The meter stops at 100 even if a long tick or multiple sources would push it higher.

### What counts as shelter

Environmental shelter can come from the room, your character, and valid worn gear. Their
temperature buffers add together. Rain and wind protection also add together, with each
final protection value limited to 100 percent.

Indoor rooms always provide full rain and wind protection plus an implicit five-degree
temperature buffer. Outdoor camps, lean-tos, cloaks, and similar gear can provide partial
protection. Partial rain protection reduces weather wetness proportionally: 50 percent
rain protection turns ordinary rain's 14 points per hour into 7.

Shelter blocks weather, not immersion. A flooded room, river, pool, swamp, or sump can
still wet you indoors. When both rain and room moisture are active, their remaining rates
add together. If protection reduces rain wetting to zero, you can dry during the rain as
long as the room itself is not wet.

In worlds with Wildsim, wind protection also reduces its outdoor base chill, cold-weather
chill, and night chill. Biome cold still applies, and carried pelts keep their separate
insulation role.

### Drying out

When neither weather nor room moisture is wetting you, you dry by
`10 × (1 - humidity)` points per game hour. Humidity is limited to the range from 0 to 1:

- At humidity `0`, you dry by 10 points per hour.
- At the normal humidity `0.5`, you dry by 5 points per hour.
- At humidity `0.8`, you dry by 2 points per hour.
- At humidity `1`, natural drying stops.

Wetness stops at 0. There is no `seek-shelter` command; move to a protected or drier room
and let game time pass. A simple player loop is:

```text
!look
!move in
!wait
!look
```

Wetness is informational in this version. It does not increase cold exposure, change
health, or cause structural weather damage. Those interactions remain future mechanics.

In Discord, prefix these commands with `!`.

## Challenges and sparring

Start a non-lethal contest by issuing a challenge:

```text
!challenge target_id=Ash terms="first touch"
```

Spar with a reachable target:

```text
!spar target_id=Ash
```

Sparring still creates combat events and injuries, but it is marked as sparring so other
systems can treat it differently from a real attack.

## Defend and attack

Defend to spend stamina and reduce incoming harm:

```text
!defend reduction=2
```

Attack a reachable target, optionally with a weapon in your inventory:

```text
!attack target_id=Ash weapon_id=Axe
```

Attacks cost stamina, damage the target, and can create injury events. A weapon with
durability can wear down as it is used.

## Repair gear

Repair a damaged item:

```text
!repair-item item_id=Axe amount=1
```

Repairing raises durability up to the item's maximum. It is useful before a raid or after
repeated attacks.

## Fortify and raid

Build or strengthen a reachable fortification:

```text
!fortify target_id="wooden palisade" strength=2
```

Raid that target:

```text
!raid target_id="wooden palisade" intensity=5
```

Fortifications track durability. Raids apply damage against that durability.

## Storyteller raid incidents

Barbarian raids are also storyteller incidents when both `bunnyland.barbariansim` and
`bunnyland.colonysim` are enabled. The storyteller budget can select a `barbarian_raid`,
place an active incident in a room, and split the attack budget into a swarm of weak
raiders led by a few officers and a warlord. Defeating or pacifying the whole swarm lets
an admin resolve the incident with the normal storyteller command:

```text
!resolve-incident incident_id="barbarian raid"
```

## Poison and corruption

Poison a reachable character:

```text
!poison-character target_id=Ash severity=2
```

Treat poison:

```text
!treat-poison target_id=Ash
```

Some worlds also track corruption:

```text
!gain-corruption amount=3
!cleanse-corruption
```

## Thralls and followers

Once a foe is defeated (downed in combat), you can subdue them into a thrall — a bound
worker who serves you:

```text
!subdue target_id=Ash task=haul
```

You can also recruit a willing, conscious character in the same room as a follower:

```text
!recruit-follower target_id=Ash
```

Give a thrall a new task or a follower new orders:

```text
!command target_id=Ash instruction="guard the burrow"
```

Release a thrall or dismiss a follower when you no longer need them:

```text
!release-thrall target_id=Ash
```

Your prompt lists the thralls and followers you command and what each is set to do, and
tells a bound character that they serve a leader.

## Pickpocketing

If pickpocketing is enabled, steal a reachable item from another character:

```text
!pickpocket target_id=Ash item_id=Coin
```

The item must be in the target's inventory and reachable through the normal name
resolution rules.

## Survival gaps, buildings, and purges

Some survival worlds expose named gaps such as missing shelter, water, tools, or food.
Bridge a reachable gap when you have the required supplies:

```text
!bridge-survival-gap gap_id="no shelter"
```

Buildings can decay, be upgraded, and be demolished:

```text
!decay-building building_id="log wall" amount=1
!upgrade-building building_id="log wall" integrity=5
!demolish-building building_id="ruined shack"
```

Prepare a base for a siege, then resolve a purge wave against it:

```text
!prepare-siege base_id="river camp" score=3
!start-purge-wave base_id="river camp" intensity=4
```

## Rituals, danger zones, and treasure

Use a shrine and ritual when both are reachable:

```text
!perform-ritual shrine_id="stone shrine" ritual_id="ember blessing"
```

Explore a danger zone, defeat its boss, and unlock treasure with the right key:

```text
!explore-danger-zone zone_id="serpent pass"
!defeat-boss boss_id="serpent queen"
!unlock-treasure treasure_id="sealed hoard" key_id="serpent key"
!claim-treasure treasure_id="sealed hoard"
```

Climbing is a traversal gate or skill check, not a free movement system:

```text
!climb gate_id="cliff path"
```

## Core loop

A simple conflict loop:

```text
!challenge target_id=Ash terms="first touch"
!defend reduction=2
!spar target_id=Ash
!attack target_id=Ash weapon_id=Axe
!repair-item item_id=Axe amount=1
!fortify target_id="wooden palisade" strength=2
!raid target_id="wooden palisade" intensity=5
!prepare-siege base_id="river camp" score=3
!start-purge-wave base_id="river camp" intensity=4
```
