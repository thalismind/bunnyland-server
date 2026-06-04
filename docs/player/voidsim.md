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
