# Barbarian-sim combat and survival

Barbarian-sim adds direct conflict and survival pressure: challenges, defending, sparring,
attacks, item durability, fortifications, raids, poison, corruption, and pickpocketing.
Some actions are controlled by world policy; if a server has not enabled PvP or
pickpocketing, those commands can be rejected.

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
