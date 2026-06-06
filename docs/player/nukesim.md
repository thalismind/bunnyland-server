# Nuke-sim wasteland survival

Nuke-sim adds radiation sources, radiation dose, sickness, mutation pressure,
decontamination, rad medicine, scavenging, scrapping, and wasteland crafting loops that
reuse colony-sim resource stacks and recipes.

In Discord, prefix these commands with `!`.

## Radiation

Scan a reachable source:

```text
!scan-radiation target_id="cracked isotope case"
```

Radiation sources expose reachable active characters over time. Protection from
`RadProtectionComponent` or void-sim `RadiationShieldComponent` reduces the rate.

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

## Example loop

```text
!scan-radiation target_id="cracked isotope case"
!seal-radiation-source target_id="cracked isotope case"
!take item_id="patched rad poncho"
!scavenge site_id="pharmacy backroom cache"
!scrap-item item_id="bent pressure cooker"
!decontaminate target_id="Mara" station_id="decon arch"
!craft recipe_id=pipe-filter
```
