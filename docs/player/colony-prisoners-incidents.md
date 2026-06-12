# Colony prisoners, incidents, and surgery

Colony-sim supports explicit prisoner policy, recruitment, incident resolution, and
body-part health. Sensitive table concepts should still be gated by world policy and
server rules.

In Discord, prefix these commands with `!`.

## Prisoners and recruitment

Set a prisoner's policy:

```text
!set-prisoner-policy prisoner_id=Pip policy=recruit
```

Valid policies are `hold`, `recruit`, and `release`.

Progress recruitment:

```text
!recruit-prisoner prisoner_id=Pip progress=3
```

When recruitment reaches the prisoner's difficulty, the prisoner component is removed.

## Incidents

Resolve an active colony incident:

```text
!resolve-incident incident_id="mad hare"
```

Resolution marks the incident entity resolved. It does not delete history or override
storyteller incident records.

## Surgery and body parts

Surgery bills target a patient and a body part:

```text
!perform-surgery patient_id=Juniper surgery_id="left paw surgery"
```

Body parts are separate entities linked to the patient, so a character can have many
tracked parts without violating the one-component-per-type ECS rule. Surgery can repair,
amputate, or install a prosthetic depending on the surgery bill state.
