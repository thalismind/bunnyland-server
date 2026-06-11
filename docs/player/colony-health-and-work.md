# Colony health and work

Colony-sim adds shared work control, room quality, medical recovery, colony wealth, and
mental-state pressure on top of resource gathering, stockpiles, jobs, and crafting.

## Work priorities

Set a character's work priorities with:

```text
!set-work-priority work_type=doctor priority=1
!set-work-priority work_type=haul priority=3
```

Priority `1` is highest. Priority `4` is lowest. Priority `0` clears that work type from
the character's priority table. The prompt shows active priorities so other characters
can coordinate around them.

## Allowed areas

Restrict a character's work area to known room ids:

```text
!set-allowed-area room_ids="clinic,stockpile-room"
```

An empty allowed area means unrestricted. Allowed areas are bookkeeping for colony AI and
player coordination; they do not teleport or block movement by themselves.

## Room quality

Rooms and fixtures can contribute beauty, cleanliness, comfort, and wealth. Colony-sim
computes a room quality summary and exposes it in prompts:

```text
Room quality: dining room, impressiveness 7.0.
```

Room quality feeds colony context and mental-state checks. Decor, cleanliness fixtures,
comfortable seating, and valuable room contents improve the score.

## Colony wealth and expectations

Colony wealth is calculated from resource stacks, room wealth, and workstations. The
colony marker tracks the current wealth and expectation band:

```text
Colony wealth is 110; expectations are moderate.
```

Higher expectations make poor rooms, low mood, and unmet needs more important in colony
storytelling and character prompts.

## Tending wounds

Tend a patient's wound with optional medicine:

```text
!tend-wound patient_id=Hazel injury_id=<injury-id> medicine_id="herbal medicine"
```

The wound must belong to the patient. Medicine must be reachable and have medicine uses.
Tending marks the injury treated, reduces pain and bleeding according to medicine quality,
and consumes a medicine use.

## Rescue and bed rest

Rescue a downed character to a reachable medical bed:

```text
!rescue-to-bed patient_id=Hazel bed_id="clinic bed"
```

The patient must be downed. The bed must be reachable and marked as a medical bed. Rescue
moves the patient to the bed's room, starts bed rest, and leaves them asleep. Bed rest
recovers health over time based on bed quality. Infection immunity improves faster while
the patient is resting.

## Mental states

Colony-sim can set visible mental states:

- crisis-level needs can trigger a mild mental break;
- high positive mood can trigger inspiration;
- states expire after their duration and return to stable.

Mental states appear in prompts so other characters can respond in-world.
