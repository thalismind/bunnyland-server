# Nuke-sim settlements and old-world tech

Nuke-sim settlement mechanics turn wasteland locations into salvage, utilities, and
resource pressure. They reuse colony-sim resource stacks and can also interact with
barbarian-sim durability when a settlement can be damaged by overuse.

In Discord, prefix these commands with `!`.

## Claiming a settlement

Claim a reachable settlement:

```text
!claim-settlement settlement_id="Red Rocket burrow"
```

Claiming marks the settlement as yours. Settlement ownership is required before stripping
settlement salvage.

## Settlement salvage

Salvage a claimed settlement:

```text
!salvage-settlement settlement_id="Red Rocket burrow"
```

Settlement salvage can create resource stacks in your inventory, such as `scrap` or
`fuel`. Salvage is single-use per settlement salvage record; after it is taken, the
settlement salvage appears as depleted.

If the settlement also has barbarian-sim durability:

- salvage spends the configured durability cost
- a settlement at zero durability or already broken cannot be salvaged
- stripping the last durability can leave the settlement broken

## Purifiers and generators

Use scrap to build a water purifier at a claimed settlement:

```text
!build-purifier settlement_id="Red Rocket burrow"
```

Use fuel to power a reachable generator:

```text
!power-generator generator_id="patched generator"
```

Purifiers and generators draw from the same resource stacks produced by scavenging,
scrapping junk, void-sim salvage, and settlement salvage.

## Old-world tech

Pre-war devices start unidentified. Identify a reachable device:

```text
!identify-tech tech_id="dusty crate"
```

Restore an identified device with scrap:

```text
!restore-tech tech_id="dusty crate"
```

Restored tech becomes functional. Tech leads can appear in your character context and point
you toward a specific device or location hint.

## Water and settlement recovery

Settlements often sit near water sources. Check context for whether nearby water is clean,
purified, or contaminated. If it is contaminated, purify it before drinking:

```text
!purify-water water_id="rad puddle"
!drink-water water_id="rad puddle"
```

## Settlement loop

```text
!claim-settlement settlement_id="Red Rocket burrow"
!salvage-settlement settlement_id="Red Rocket burrow"
!scrap-item item_id="bent pressure cooker"
!build-purifier settlement_id="Red Rocket burrow"
!power-generator generator_id="patched generator"
!identify-tech tech_id="dusty crate"
!restore-tech tech_id="dusty crate"
```
