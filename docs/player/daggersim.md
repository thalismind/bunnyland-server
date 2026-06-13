# Dagger-sim frontier play

Dagger-sim adds a broad frontier-adventure loop: rumors, procedural site expansion,
travel, institutions, generated work, banking, law, custom classes, spells, pacification,
supernatural afflictions, property, civic reputation, and dungeons.

In Discord, prefix these commands with `!`.

For a focused guide to institution reputation, generated work, banking, legal reputation,
and property deeds, see [Dagger-sim civic life and property](dagger-civic-property.md).

## Rumors, expansion, and travel

Ask about a reachable rumor:

```text
!ask-rumor rumor_id="carrot vault rumor"
```

Investigate it:

```text
!investigate-rumor rumor_id="carrot vault rumor"
```

Verified rumors can become expansion hooks. Expand the site when the world exposes one:

```text
!expand-site site_id="Rain Garden Hamlet"
```

Plan travel to a known travel hub:

```text
!plan-travel destination_id="North Tunnel"
```

Travel starts immediately and completes after its route duration. Until it completes, your
character is still subject to normal world time.

## Institutions, services, and generated work

Join a reachable institution:

```text
!join-institution institution_id="Burrow Cartographers"
```

Use an institution service:

```text
!use-institution-service service_id="local map service"
```

Ask for generated work from a template:

```text
!ask-for-work template_id="ratcatcher errand"
```

Then accept and complete the generated quest:

```text
!accept-generated-quest quest_id="Clear the North Tunnel"
!complete-generated-quest quest_id="Clear the North Tunnel"
```

Services and generated work can create items, quest records, rewards, deadlines, and
institution context.

Joining an institution and using its services also changes your institution reputation.
Services you successfully use are recorded as unlocked service access, and both reputation
and access can show in your character context. The dedicated civic guide covers the
reputation, service access, law, banking, and property details.

## Banking, loans, law, and fines

Open an account at a reachable bank:

```text
!open-bank-account bank_id="Carrot Factors Bank"
```

Deposit money:

```text
!deposit bank_id="Carrot Factors Bank" amount=20
```

Withdraw money:

```text
!withdraw bank_id="Carrot Factors Bank" amount=5
```

Take and repay a loan:

```text
!take-loan bank_id="Carrot Factors Bank" amount=25
!repay-loan loan_id="bank loan" amount=25
```

Some regions track crimes and fines:

```text
!commit-crime crime_type=trespass
!pay-fine crime_id="trespass charge"
```

Committing a crime lowers legal reputation for that region. Paying the fine raises it back
toward neutral and removes the active bounty from the crime record. Unpaid loans and fines
are durable state. They can appear in prompts and can be used by story or law systems.

Some worlds expose purchasable property deeds. Buy a reachable property from any bank
account with enough balance:

```text
!buy-property property_id="Moss Road Cottage"
```

Buying property spends from your bank account, marks the deed as owned by you, and adds an
ownership relationship that appears in character context. See the civic guide for the
full property purchase loop.

Issue a letter of credit, store valuables, and escalate an unpaid debt:

```text
!issue-letter-of-credit bank_id="Carrot Factors Bank" amount=50
!store-safe-item storage_id="bank vault" item_id="ruby ring"
!retrieve-safe-item storage_id="bank vault" item_id="ruby ring"
!send-debt-collector debt_id="overdue loan"
```

Courts can sentence an active crime:

```text
!sentence-crime crime_id="trespass charge" sentence=fine
```

## Classes, spells, pacification, and afflictions

Create a custom class from a reachable template:

```text
!create-custom-class template_id="Moonlit Forager template" class_name="Rainpath Scout" primary_skills=foraging,stealth,weather
```

Create and cast a spell:

```text
!create-spell template_id="mend sprout formula" spell_name="Mend Moss"
!cast-spell spell_id="Mend Moss"
```

Enchant a carried item with a spell, then cast through the item:

```text
!enchant-item item_id="moss charm" spell_id="Mend Moss"
!cast-spell spell_id="moss charm"
```

The spell source can be a spell formula or a custom spell you created with
`!create-spell`. Enchanting copies the spell effect onto the item, so the item becomes
the thing you cast from. Use `target_id` when you want to affect someone other than
yourself:

```text
!enchant-item item_id="silver needle" spell_id="mend sprout formula"
!cast-spell spell_id="silver needle" target_id="moon moth"
```

Pacify a creature using a language your character knows:

```text
!attempt-pacify target_id="moon moth" language=Mothwing
```

Contract an affliction and transform:

```text
!contract-affliction affliction_type="moon-form"
!progress-affliction-incubation target_id=Mara
!mark-affliction-stigma target_id=Mara region_id="Moss Coast" severity=2
!request-cure-quest quest_id="moon cure lead"
!transform form_name="moon hare"
```

An affliction grows a feeding need over time. Feed on a reachable character to satisfy it,
end your transformation to return to a dormant state, or seek a cure to lift the curse
entirely:

```text
!feed-on target_id="Wanderer"
!end-transformation
!cure-affliction
```

Your affliction, its stage, your feeding need, and whether you are currently transformed
all show in your character context.

## Dungeons

Request a dungeon from a reachable dungeon hook:

```text
!request-dungeon dungeon_id="Carrot Vault"
```

Enter it:

```text
!enter-dungeon dungeon_id="Carrot Vault"
```

Explore the current dungeon room:

```text
!search-room
!open-secret-door door_id="cracked tiles"
!mark-path
!view-map
```

Set a recall anchor, rest, and leave:

```text
!set-recall
!rest
!leave-dungeon dungeon_id="Carrot Vault"
```

Dungeon exploration records discovered rooms, secret doors, objectives, map marks, and
recall anchors.

## Institutions, travel, and services

Institutions can promote you and collect dues:

```text
!promote-institution institution_id="Mages Guild" rank=adept
!pay-institution-dues institution_id="Mages Guild" amount=25
```

Generated quests can be refused, abandoned, extended, or lied about:

```text
!refuse-generated-quest quest_id="rat cellar job"
!abandon-generated-quest quest_id="rat cellar job"
!extend-generated-quest quest_id="rat cellar job" seconds=86400
!lie-about-quest quest_id="rat cellar job" lie="the rats are gone"
```

Use lodging, camping, supplies, and interruptions while traveling:

```text
!rent-lodging lodging_id="road inn" duration_seconds=86400
!camp risk=low
!buy-travel-supplies quantity=3
!resolve-travel-interruption interruption_id="washed out bridge"
```

Magic services can make potions, recharge enchanted items, and identify ingredients:

```text
!make-potion maker_id="guild potionmaker"
!recharge-enchanted-item item_id="moss charm" service_id="guild enchanter"
!identify-ingredient ingredient_id="moon sugar"
```
