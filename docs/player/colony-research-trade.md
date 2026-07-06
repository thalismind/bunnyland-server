# Colony-sim research and trade

Colony-sim has durable pawn profile, job-bill, research, faction, trade, caravan, and
ownership state. These systems are explicit commands, not hidden automation.

In Discord, prefix these commands with `!`.

## Pawn profile and job bills

Record colony-style backstory, passions, and expectations:

```text
!update-pawn-profile backstory="field medic" passions='{"doctor":2}' expectations=moderate
```

Progress a reachable job bill:

```text
!progress-job-bill bill_id="stone blocks bill" work=2
```

Job bills track `work_done` against `work_required`. When a job bill is complete and the
same entity also has a job component, the job is marked complete.

## Research and tech

Research a project:

```text
!research-project project_id="battery research" work=5
```

When work reaches the project requirement, the project unlocks and receives a tech unlock
component. The unlock is real ECS state that generated worlds and prompt fragments can
inspect.

## Trade and caravans

Complete a reachable trade offer:

```text
!complete-trade offer_id="hill clan trade"
```

The command consumes the resources the offer wants, grants the resources it gives, and
updates faction goodwill.

Form a caravan:

```text
!form-caravan destination="hill market" cargo='{"wood":2}' member_ids="Hazel,Fern"
```

Cargo is removed from inventory and stored on the caravan entity.
