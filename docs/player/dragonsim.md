# Dragon-sim exploration and quests

Dragon-sim adds open-world adventure structure: discovering locations, accepting quests,
completing objectives, earning rewards, and joining or leaving factions.

In Discord, prefix these commands with `!`.

## Discover locations

Discover a reachable point of interest:

```text
!discover-location old watchtower
```

Discovery marks that location as known and adds adventure context such as the location
type and region.

## Accept quests

Accept a reachable quest:

```text
!accept-quest quest_id="Find the Lost Ring"
```

The quest becomes active for your character. Quest context can include a title, status,
objectives, and rewards.

## Complete objectives

Complete a reachable objective:

```text
!complete-objective objective_id="lost ring objective"
```

Completing the last required objective can complete the quest and grant its reward. Reward
items are moved into your inventory when the quest reward is claimed by completion.

## Factions

Join a faction:

```text
!join-faction faction_id="Moss Wardens" rank=scout
```

Leave it later:

```text
!leave-faction Moss Wardens
```

Faction membership is durable world state. It can affect prompts, reputation, available
work, and server-side story rules.

## Perks

Perks are adventuring talents gated behind your life-sim skills. You raise skills by using
them (life-sim's skill-by-use progression); once a skill reaches a perk's required level you
can unlock that perk:

```text
!unlock-perk perk_id="Power Attack"
```

A perk lists the skill and minimum level it needs. If your skill is too low the unlock is
rejected; once unlocked, the perk is durable world state and shows up in your character
context.

## Great souls and words of power

Ancient beasts carry great souls. When one has been slain, claim its great soul:

```text
!absorb-great-soul beast_id="Ancient Wyrm"
```

Great souls let you learn words of power. A word can require a number of great souls and,
sometimes, a minimum skill level. Learn one you qualify for:

```text
!learn-word-of-power word_id="Unrelenting Force"
```

Then speak a word you have learned:

```text
!speak-word-of-power word_id="Unrelenting Force"
```

Your absorbed great souls and known words show up in your character context.

## Stealth, theft, and bounties

Slip into stealth so witnesses cannot see your next move (toggle it off with the same
command):

```text
!sneak
```

Steal an item another character is carrying in your room:

```text
!steal ruby ring from Mara
```

If you are not sneaking and a faction member sees the theft, you pick up a bounty with
that faction. Pay off a bounty to clear it:

```text
!pay-bounty faction_id="Moss Wardens"
```

Whether you are sneaking and any outstanding bounties show up in your character context.
When barbarian-sim is also enabled, the same world gives you its combat verbs to back up
a life of crime.

## Core loop

A simple adventure loop:

```text
!discover-location old watchtower
!accept-quest quest_id="Find the Lost Ring"
!complete-objective objective_id="lost ring objective"
!join-faction faction_id="Moss Wardens" rank=scout
!leave-faction Moss Wardens
!sneak
!steal ruby ring from Mara
!pay-bounty faction_id="Moss Wardens"
```
