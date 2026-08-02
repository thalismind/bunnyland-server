# Storyteller incidents

Storyteller incidents are timed events spawned by the world. They create visible incident
state, nearby objects, or threats depending on the world budget.

## Find the active incident

Look around after time passes:

```text
!look
```

An active incident can appear in the room summary or prompt context, such as:

```text
Active incident: resource drop.
```

The incident may also create nearby objects. A resource drop can place a supply bundle in
the room.

A barbarian raid begins with a five-minute warning and spawns no enemies during that
warning. Its prompt reports the warning, attack, recovery, and complete phases along with
the defended room's integrity. The Storyteller budget determines one to three waves. A
new wave waits until the previous wave is neutralized, with 30 seconds between waves.

Raiders attack enrolled defenders in stable entity-id order and erode settlement defense
integrity. Victory after the final wave creates budget-scaled raid loot. A breach or loss
of every defender is defeat and creates no reward. Both outcomes enter a two-minute
recovery period before the generic Storyteller incident resolves.

## Finish the incident

Incidents resolve themselves when the work they created is done. For example, take a
resource drop, kill or capture hostile creatures, pacify creatures that can be talked
down, complete spawned quests, or repair settlement damage:

```text
!take supply bundle
```

Manual incident resolution is an admin-only command for moderation and cleanup. Normal
play should handle the spawned objects, threats, quests, or damage and then let the
storyteller close the incident.

Some incident packs expose their own response verbs. For example:

```text
!repair-damage
!attempt-pacify target_id="angry moth" language=Mothwing
```

## Keep checking context

Incidents are paced by world time. If nothing is active, continue normal play and check
again after waiting, traveling, or completing other work.
