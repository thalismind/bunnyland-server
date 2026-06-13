# Nuke-sim wasteland survival

Nuke-sim adds radiation sources, radiation dose, sickness, mutation pressure,
decontamination, rad medicine, chems, dirty water, scavenging, scrapping, settlements,
old-world tech, and wasteland crafting loops that reuse colony-sim resource stacks and
recipes.

In Discord, prefix these commands with `!`.

For settlement claiming, salvage, purifiers, generators, and old-world tech recovery, see
[Nuke-sim settlements and old-world tech](nuke-settlements-tech.md).

## Radiation

Scan a reachable source:

```text
!scan-radiation target_id="cracked isotope case"
```

Radiation sources expose reachable active characters over time. Protection from
`RadProtectionComponent` or shared `RadiationShieldComponent` reduces the rate.

Seal a reachable source when the world offers a plausible way to contain it:

```text
!seal-radiation-source target_id="cracked isotope case"
```

Sealed sources stop adding passive exposure.

## Decontamination and medicine

Use a reachable decontamination station:

```text
!decontaminate target_id="Mara" station_id="decon arch"
```

Use rad medicine from your inventory or current room:

```text
!use-rad-medicine item_id="rad-away"
```

Both reduce radiation dose, sickness, and radiation mutation pressure.

## Chems, addiction, and water

Take a reachable chem to relieve radiation sickness fast — at the cost of a growing
addiction to that chem type:

```text
!take-chem chem_id=stimpak
```

Addiction levels show in your character context and decay on their own over time as the
chem clears your system (withdrawal). Take the same chem again and the addiction climbs.

Wasteland water is often contaminated. Drinking from a dirty source adds radiation:

```text
!drink-water water_id="rad puddle"
```

Purify a water source first so it is safe to drink:

```text
!purify-water water_id="rad puddle"
```

Nearby chems and water sources, with each source's contamination, show in your character
context.

## Mutation

Radiation exposure adds radiation mutation pressure. When pressure crosses the current
threshold, the character manifests a deterministic radiation mutation.

Stabilize an unstable mutation:

```text
!stabilize-mutation mutation_id=rad-adapted
```

## Scavenging and scrapping

Scavenge a reachable site:

```text
!scavenge site_id="pharmacy backroom cache"
```

Scavenging creates resource stacks in your inventory. Hazardous sites can add immediate
radiation exposure.

Scrap junk for parts:

```text
!scrap-item item_id="bent pressure cooker"
```

Scrapped output uses the same `ResourceStackComponent` as colony-sim, so recipes can use
resources found in the wasteland.

Mark a hotspot, use a suppressant, harvest a sample, and study it:

```text
!mark-hotspot source_id="cracked isotope case" label="hot hallway"
!use-suppressant item_id="rad foam"
!harvest-sample sample_type="glowing moss"
!study-sample sample_id="glowing moss sample"
```

## Old-world tech

The wasteland is littered with ruined pre-war devices. Scavengers can recover them in two
steps. First identify what a device actually is:

```text
!identify-tech tech_id="dusty crate"
```

Once identified, restore it to working order using scrap you have on hand (each device lists
how much scrap it needs):

```text
!restore-tech tech_id="dusty crate"
```

Restoring consumes scrap from your inventory and marks the device functional. Notes and
rumors can also point you toward specific old-world tech as salvage leads, which show up in
your character context.

## Settlement salvage

Claim a reachable wasteland settlement before working its salvage:

```text
!claim-settlement settlement_id="Red Rocket burrow"
```

If the settlement has a salvage component, strip useful materials from it:

```text
!salvage-settlement settlement_id="Red Rocket burrow"
```

Settlement salvage creates colony-sim resource stacks in your inventory. When the
settlement also has barbarian-sim durability, salvage spends durability and can leave the
site broken if you strip it too hard. The dedicated settlement guide covers the full
claim, salvage, purifier, generator, and tech recovery loop.

Build a purifier or power a generator with resources from scavenging, scrapping, or
settlement salvage:

```text
!build-purifier settlement_id="Red Rocket burrow"
!power-generator generator_id="patched generator"
```

Unlock crates, study artifacts, claim faction salvage, and repair field gear:

```text
!unlock-crate crate_id="sealed ammo crate"
!study-wasteland-artifact artifact_id="vault relic"
!claim-faction-salvage salvage_id="Minutemen cache"
!install-mod item_id="pipe rifle" schematic_id="scope schematic"
!field-repair item_id="patched rad poncho" kit_id="sewing kit"
```

Brew chems and activate wasteland infrastructure:

```text
!brew-chem recipe_id="rad tonic recipe"
!activate-beacon beacon_id="settlement beacon"
!open-trader-route route_id="south road caravan"
!increase-raider-pressure target_id="Red Rocket burrow" amount=2
!boot-terminal terminal_id="vault terminal" access_level=2
```

## Example loop

```text
!scan-radiation target_id="cracked isotope case"
!seal-radiation-source target_id="cracked isotope case"
!take item_id="patched rad poncho"
!claim-settlement settlement_id="Red Rocket burrow"
!salvage-settlement settlement_id="Red Rocket burrow"
!scavenge site_id="pharmacy backroom cache"
!scrap-item item_id="bent pressure cooker"
!mark-hotspot source_id="cracked isotope case" label="hot hallway"
!harvest-sample sample_type="glowing moss"
!decontaminate target_id="Mara" station_id="decon arch"
!craft recipe_id=pipe-filter
```
