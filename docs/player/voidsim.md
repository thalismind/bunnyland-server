# Void-sim ships and space travel

Void-sim adds ships, stations, habitat modules, airlocks, bulkheads, life support, power
grids, docking, fuel, sensors, distress signals, orbit, landing, launch, plotted courses,
and jumps.

In Discord, prefix these commands with `!`.

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

Mutation outcomes are intentionally not active yet. The current void-sim implementation
only records chaos mutation pressure. It also defines separate radiation and cybernetic
pressure components as stubs, so the follow-up nuke-sim pack can accumulate radiation,
chaos, and augmentation pressure independently before deciding when actual mutations occur.
