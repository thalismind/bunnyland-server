# Void-sim ships and space travel

Void-sim adds ships, stations, habitat modules, airlocks, bulkheads, life support, power
grids, docking, fuel, sensors, distress signals, orbit, landing, launch, plotted courses,
contracts, cargo, salvage, resource-backed fabrication, crew watches, and jumps.

In Discord, prefix these commands with `!`.

For the resource economy, contracts, cargo, salvage claims, and crew watches, see
[Void-sim contracts, fabrication, and salvage](void-contracts-fabrication.md).

## Airlocks, pressure, and bulkheads

Open an airlock:

```text
!open-airlock airlock_id="port airlock"
```

Cycle it:

```text
!cycle-airlock airlock_id="port airlock"
```

Opening an airlock can change module pressure. Cycling can move the airlock through its
state machine.

Seal a bulkhead:

```text
!seal-bulkhead bulkhead_id="aft bulkhead"
```

Bulkheads are useful for isolating damage, pressure loss, or unsafe modules.

## Ship systems and power

Repair a ship system:

```text
!repair-system system_id="life support unit"
```

Reroute power to it:

```text
!reroute-power grid_id="main bus" system_id="life support unit" amount=30
```

Inspect a system:

```text
!inspect-ship-system system_id="life support unit"
```

Ship systems track integrity and online state. Power grids track available power.

## Research, fabrication, and upgrades

Blueprints describe ship-system upgrades you can build at a fabricator. A blueprint may be
gated behind a colony-sim research project: research the technology first (see the
colony-sim guide's `research-project`), then fabricate the part. Fabricate from a
reachable fabricator and blueprint:

```text
!fabricate fabricator_id=nanoforge blueprint_id="shield booster"
```

Some blueprints also require colony-sim resource stacks, such as scrap or crystal, in your
inventory. Fabrication validates every required stack before spending anything; if you do
not have enough resources, the command is refused and nothing is consumed.

The fabricated part lands in your inventory. Install it on a matching ship system to raise
its integrity and bring it back online:

```text
!install-upgrade upgrade_id="shield booster" system_id="shield emitter"
```

A blueprint whose technology has not been researched is refused, and an upgrade only fits
a system of its own type. Reachable fabricators, blueprints, and ready upgrade parts show
up in your character context.

## Evacuation

Move characters out of a module:

```text
!evacuate-module module_id="Mosslit Burrow" destination_id="North Tunnel"
```

The destination must be reachable and safe enough for the world rules in play.

## Docking, fuel, and sensors

Dock with a station:

```text
!dock ship_id="Burrow Runner" station_id="Moss Station"
```

Undock when ready:

```text
!undock ship_id="Burrow Runner" station_id="Moss Station"
```

Refuel and scan:

```text
!refuel ship_id="Burrow Runner"
!scan ship_id="Burrow Runner"
```

Answer a detected distress signal:

```text
!answer-distress-signal signal_id="mayday beacon"
```

## Orbit, landing, launch, and jumps

Enter orbit around a known body:

```text
!enter-orbit ship_id="Burrow Runner" body_id="Moss Moon"
```

Land and launch:

```text
!land ship_id="Burrow Runner"
!launch ship_id="Burrow Runner"
```

Leave orbit:

```text
!leave-orbit ship_id="Burrow Runner"
```

Plot a course and jump:

```text
!plot-course ship_id="Burrow Runner" destination_id="North Tunnel"
!jump ship_id="Burrow Runner"
```

Jumps consume fuel and complete after their route duration. The ship arrives at the plotted
destination when the jump completes.

## Contracts, cargo, and salvage

Accept a reachable contract:

```text
!accept-contract contract_id="derelict salvage writ"
```

Cargo contracts move cargo onto a ship and complete when delivered to the destination:

```text
!load-cargo cargo_id="ore crates" ship_id="Burrow Runner"
!deliver-cargo cargo_id="ore crates"
```

Salvage contracts grant rights to a salvage claim:

```text
!claim-salvage claim_id="derelict hulk rights" contract_id="derelict salvage writ"
```

Claiming salvage can create colony-sim resource stacks in your inventory, such as scrap or
fuel, so space salvage can feed the same resource economy as colony work and wasteland
repair. The dedicated contracts and fabrication guide covers the full resource-backed
ship economy loop.

## Crew duty shifts

A ship runs on watches. A duty shift is its own entity describing a time slot and the role
it covers (for example an `alpha` engineering watch from 08:00 to 16:00). Crew take a watch,
optionally naming the station they cover:

```text
!assign-crew-shift shift_id="alpha watch" station=reactor
```

Stand down from it later:

```text
!relieve-crew-shift shift_id="alpha watch"
```

While the ship clock is inside your watch window you are "on duty", and your character
context shows your assigned watch and current duty status. Watches can wrap past midnight
(for example a 22:00–06:00 overnight watch). Coordinate watches so critical systems are
always crewed.

## Chaos influence and mutation pressure

Some void-sim worlds include warp breaches, machine possessions, daemon whispers, or other
chaos sources. In these worlds, chaos is tracked with the same corruption state used by
barbarian-sim:

```text
!look
```

Look output and character prompts can show nearby chaos sources, wards, your current
chaos corruption, and source-specific mutation pressure.

Chaos sources can:

- add corruption to nearby characters over time
- add chaos mutation pressure for future mutation rules
- damage nearby ship systems if the source is severe

Chaos wards reduce the corruption rate. Radiation shields also help a little, so future
radiation and mutation mechanics can cooperate with the same pressure model.

Mutation outcomes are intentionally not active yet. Void-sim records chaos mutation
pressure using the shared source-specific pressure components, so nuke-sim radiation,
chaos, and future augmentation pressure can accumulate independently before any package
decides when outcomes occur.
