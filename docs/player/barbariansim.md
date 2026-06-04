# Barbarian-sim combat and survival

Barbarian-sim adds direct conflict and survival pressure: challenges, defending, sparring,
attacks, item durability, fortifications, raids, poison, corruption, and pickpocketing.
Some actions are controlled by world policy; if a server has not enabled PvP or
pickpocketing, those commands can be rejected.

In Discord, prefix these commands with `!`.

## Challenges and sparring

Start a non-lethal contest by issuing a challenge:

```text
challenge target_id=Ash terms="first touch"
```

Spar with a reachable target:

```text
spar target_id=Ash
```

Sparring still creates combat events and injuries, but it is marked as sparring so other
systems can treat it differently from a real attack.

## Defend and attack

Defend to spend stamina and reduce incoming harm:

```text
defend reduction=2
```

Attack a reachable target, optionally with a weapon in your inventory:

```text
attack target_id=Ash weapon_id=Axe
```

Attacks cost stamina, damage the target, and can create injury events. A weapon with
durability can wear down as it is used.

## Repair gear

Repair a damaged item:

```text
repair-item item_id=Axe amount=1
```

Repairing raises durability up to the item's maximum. It is useful before a raid or after
repeated attacks.

## Fortify and raid

Build or strengthen a reachable fortification:

```text
fortify target_id="wooden palisade" strength=2
```

Raid that target:

```text
raid target_id="wooden palisade" intensity=5
```

Fortifications track durability. Raids apply damage against that durability.

## Poison and corruption

Poison a reachable character:

```text
poison-character target_id=Ash severity=2
```

Treat poison:

```text
treat-poison target_id=Ash
```

Some worlds also track corruption:

```text
gain-corruption amount=3
cleanse-corruption
```

## Pickpocketing

If pickpocketing is enabled, steal a reachable item from another character:

```text
pickpocket target_id=Ash item_id=Coin
```

The item must be in the target's inventory and reachable through the normal name
resolution rules.

## Core loop

A simple conflict loop:

```text
challenge target_id=Ash terms="first touch"
defend reduction=2
spar target_id=Ash
attack target_id=Ash weapon_id=Axe
repair-item item_id=Axe amount=1
fortify target_id="wooden palisade" strength=2
raid target_id="wooden palisade" intensity=5
```
