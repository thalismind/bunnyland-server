# Void-sim contracts, fabrication, and salvage

Void-sim links ship work to the shared colony resource economy. Fabricators can spend
resource stacks, salvage can create resource stacks, and contracts/cargo give the ship
crew reasons to move between stations, wrecks, and destinations.

In Discord, prefix these commands with `!`.

## Resource-backed fabrication

Blueprints describe a part or upgrade that a fabricator can build:

```text
!fabricate fabricator_id=nanoforge blueprint_id="shield booster"
```

A blueprint can require:

- a reachable fabricator
- a reachable blueprint
- a researched colony-sim technology
- one or more carried resource stacks, such as `scrap`, `fuel`, or `crystal`

When resource inputs are present, fabrication checks every requirement before spending
anything. If any required stack is missing or too small, the command is refused and no
resource stack changes.

The fabricated part appears in your inventory. Install it on a matching ship system:

```text
!install-upgrade upgrade_id="shield booster" system_id="shield emitter"
```

Upgrades only fit their own system type. Installing an upgrade improves integrity and can
bring a damaged system back online.

## Contracts

Accept a reachable contract:

```text
!accept-contract contract_id="derelict salvage writ"
```

Contracts can describe cargo work, salvage rights, payouts, due dates, and destinations.
Accepted contracts are assigned to your character and appear in context while active.

## Cargo work

Cargo is loaded onto a ship, moved, and delivered at its destination:

```text
!load-cargo cargo_id="ore crates" ship_id="Burrow Runner"
!deliver-cargo cargo_id="ore crates"
```

Cargo must be reachable and not already loaded. Delivery requires the cargo to be loaded
and the destination rules to match the current world state.

## Salvage claims

Some contracts grant rights to a salvage claim. Claim salvage after accepting the relevant
contract:

```text
!claim-salvage claim_id="derelict hulk rights" contract_id="derelict salvage writ"
```

Salvage claims can create colony-sim resource stacks directly in your inventory. These
resources can then fund fabrication, nuke-sim settlement repairs, or colony crafting.

If a claim is tied to a contract, the contract must be accepted by you before the claim can
be taken. Once claimed, the salvage record is marked as claimed and cannot be claimed
again.

## Crew watches

Crew duty shifts let a ship track who is covering a watch:

```text
!assign-crew-shift shift_id="alpha watch" station=reactor
!relieve-crew-shift shift_id="alpha watch"
```

Your context shows the assigned watch and whether the current ship time puts you on duty.
Shift windows can wrap past midnight, such as a 22:00-06:00 overnight watch.

## Ship economy loop

```text
!accept-contract contract_id="derelict salvage writ"
!plot-course ship_id="Burrow Runner" destination_id="derelict hulk"
!jump ship_id="Burrow Runner"
!claim-salvage claim_id="derelict hulk rights" contract_id="derelict salvage writ"
!fabricate fabricator_id=nanoforge blueprint_id="shield booster"
!install-upgrade upgrade_id="shield booster" system_id="shield emitter"
!assign-crew-shift shift_id="alpha watch" station=reactor
```
