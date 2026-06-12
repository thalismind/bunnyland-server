# Life routines and home objects

Life-sim keeps everyday character state in the world: profile details, whims, home
objects, invitations, routines, claimed rooms, and aging policy. These commands are
bookkeeping verbs; they create ECS state that prompts and other systems can inspect.

In Discord, prefix these commands with `!`.

## Profile and whims

Set profile context:

```text
!update-profile traits="tidy,bookish" interests="reading,cooking" preferred_routine="morning tea"
```

Add a short-term want:

```text
!add-whim want="read before work" reward_xp=7
```

Complete it when the character has done the thing:

```text
!complete-whim whim_id="<whim-id>"
```

Completed whims stay as ECS history and can award life skill XP.

## Home objects

Home objects expose an affordance plus cleanliness, condition, decor, and upgrade state.
Use a reachable home object:

```text
!use-home-object object_id="reading chair"
```

Maintain it:

```text
!maintain-home-object object_id="reading chair" action=clean
!maintain-home-object object_id="reading chair" action=repair
!maintain-home-object object_id="reading chair" action=upgrade
!maintain-home-object object_id="reading chair" action=decorate
```

Broken objects reject use until repaired.

## Invitations and aging

Invite a reachable guest to your current room or a room you own or claim:

```text
!invite-over guest_id=Hazel room_id="Clover Cottage"
```

Configure life-stage progression for the world:

```text
!configure-aging natural_aging=true
```

Age settings are world policy. They do not bypass policy gates for romance, adult, or
pregnancy mechanics.
