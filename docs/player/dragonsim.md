# Dragon-sim exploration and quests

Dragon-sim adds open-world adventure structure: discovering locations, marking maps,
triggering local encounter zones, accepting quests, completing objectives, earning
rewards, joining or leaving factions, unlocking perks, learning words of power, and
handling stealth theft with faction bounties. Voice phrases are ordinary inscriptions:
they can be written or carved on world objects that support writing or carving.

In Discord, prefix these commands with `!`.

## Discover locations

Discover a reachable point of interest:

```text
!discover-location old watchtower
```

Discovery marks that location as known and adds adventure context such as the location
type and region.

Mark a reachable point of interest on your map:

```text
!mark-map location_id="old watchtower" label="Old Watchtower"
```

Map markers are personal exploration state. Marked locations show in your character
context, so you can keep track of useful roads, ruins, shrines, and landmarks.

Some locations are encounter zones. Enter or trigger a reachable zone when the world
offers one:

```text
!trigger-encounter zone_id="wolf road"
```

Encounter zones record their danger rating and last trigger time. They are local
adventure pressure, separate from dagger-sim's larger procedural world expansion.

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

Voice phrases can also be inscribed on any reachable writable or carvable target:

```text
!inscribe-voice-phrase target_id="scratched slate" word_id="Storm Call" phrase="storm listens"
!study-voice-inscription target_id="scratched slate"
```

Studying a voice inscription teaches the linked word if you do not already know it.

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

## Law, locks, and fixed magic

Faction rank can change over time:

```text
!change-faction-rank faction_id="Moss Wardens" rank=warden
```

If a guard is reachable, a bribe can reduce your bounty with that guard's faction:

```text
!bribe target_id="Moss Guard"
```

Jail sentences clear when their release time has passed:

```text
!serve-jail-time
```

Pick a reachable lock when your lockpicking skill is high enough:

```text
!pick-lock lock_id="old chest"
```

Dragon-sim fixed magic is separate from dagger-sim's custom spellmaker. Learn a prepared
spell, cast it from your magic pool, brew a prepared potion recipe, or trigger a charged
artifact:

```text
!learn-spell spell_id=Spark
!cast-dragon-spell spell_id=Spark
!recover-magic amount=5
!brew-potion recipe_id="blue tonic recipe"
!identify target_id="star mirror"
!use item_id="star mirror"
```

Spells can have cooldowns, and magic recovery respects the character's magic state.

## Quest branches, persuasion, and surrender

Track, decline, or branch a quest:

```text
!track-quest quest_id="Find the Lost Ring"
!choose-quest-branch quest_id="Find the Lost Ring" branch="return it to Mara"
!decline-quest quest_id="Wolf Road Trouble"
```

Social and crime hooks let you change a nearby character's disposition, surrender to a
guard, or report a crime:

```text
!persuade target_id="Moss Guard" amount=2
!surrender target_id="Moss Guard" reason="stolen ring"
!report-crime criminal_id="Bandit" faction_id="Moss Wardens" bounty=10
```

Ancient beasts can be resolved without only fighting:

```text
!appease-ancient-beast beast_id="Ancient Wyrm" method=parley
```

## Core loop

A simple adventure loop:

```text
!discover-location old watchtower
!mark-map location_id="old watchtower" label="Old Watchtower"
!trigger-encounter zone_id="wolf road"
!accept-quest quest_id="Find the Lost Ring"
!track-quest quest_id="Find the Lost Ring"
!choose-quest-branch quest_id="Find the Lost Ring" branch="return it to Mara"
!complete-objective objective_id="lost ring objective"
!join-faction faction_id="Moss Wardens" rank=scout
!leave-faction Moss Wardens
!inscribe-voice-phrase target_id="scratched slate" word_id="Storm Call" phrase="storm listens"
!study-voice-inscription target_id="scratched slate"
!sneak
!steal ruby ring from Mara
!pay-bounty faction_id="Moss Wardens"
!pick-lock lock_id="old chest"
!recover-magic amount=5
```
