# Daily needs

Life-sim characters can track hunger, thirst, fatigue, hygiene, comfort, fun, social
contact, privacy, and safety. Hunger and thirst are relieved by `eat` and `drink`.
The other daily needs decay over time and recover through self-care actions, room
affordances, sleep, and conversation.

## Needs in prompts

Only pressing needs appear in character context. A character with low hygiene may see:

```text
You need to bathe or clean yourself.
```

A lonely character may see:

```text
You feel lonely and need conversation.
```

These lines are based on the character's ECS need components. If a character does not
have a need component, that need is not simulated for them.

## Self-care actions

Use these commands when the corresponding need is high:

```text
!bathe target_id="bath basin"
!clean-self
!play target_id="toy chest"
!relax target_id="soft chair"
!seek-privacy
!seek-safety
```

Targets are optional for most self-care actions. Reachable objects or rooms with daily
need affordances can improve recovery. For example, a bath basin can provide extra
hygiene recovery, and a comfortable chair can improve relaxation.

## Sleep and fatigue

Fatigue rises while a character is awake and recovers while they are asleep. Life-sim
homes still provide the well-rested skill bonus when a character sleeps long enough in
their claimed home or room; fatigue recovery is separate and works for any sleeping
character that has a fatigue need.

## Social recovery

Talking is part of the needs model. `say` and `tell` reduce social need for the speaker
and listeners while also updating relationship familiarity and affinity. Private `tell`
recovers more social need than room-wide `say`.

## Safety and privacy

`seek-safety` and `seek-privacy` record intentional recovery from fear/exposure or crowding
without moving the character by themselves. Use normal movement commands to relocate if
the room is actually dangerous or crowded.
