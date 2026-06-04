# How to respond to storyteller incidents

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

## Resolve the incident

When the incident entity is reachable, resolve it by name:

```text
!resolve-incident incident_id="resource drop"
```

Resolving marks the incident complete. It does not automatically collect any spawned
items, so take useful objects separately:

```text
!take supply bundle
```

## Keep checking context

Incidents are paced by world time. If nothing is active, continue normal play and check
again after waiting, traveling, or completing other work.
