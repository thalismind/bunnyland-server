# Life-sim homes, work, and family

Life-sim tracks durable everyday state: aspirations, skills, careers, household funds,
businesses, homes, room claims, partnerships, pregnancy, birth, adoption, rent, and bills.
Homes are explicit room markers. They do not move you, protect the room, or create a
lease by themselves; they give your character durable world state and prompt context about
where they live, which household they belong to, and which rooms they claim.

In Discord, prefix these commands with `!`.

## Aspirations and skills

Choose an aspiration:

```text
choose-aspiration {"name":"Cozy Homemaker","milestones":["meet a friend"]}
```

Complete one of its milestones:

```text
complete-milestone milestone="meet a friend" reward_name="woven keepsake"
```

Practice or study a skill:

```text
practice-skill skill=cooking xp=60
study-skill skill=cooking xp=50
```

Skills accumulate XP and can level up. Milestones can grant reward items.

## Careers and businesses

Find a job:

```text
find-job title="Burrow Barista" hourly_pay=12 shift_duration_seconds=7200 shift_interval_seconds=3600 next_shift_epoch=0
```

Go to work:

```text
go-to-work performance_gain=1
```

Work pays into household funds and can improve career level.

Open a business:

```text
open-business name="Juniper Table" default_price=10
```

Sell an inventory item to a reachable customer:

```text
sell-item item_id="berry tart" customer_id=Marigold price=15
```

Selling removes the item, reduces the customer's budget, and increases your household
funds.

## Find a home

Look at your current room and exits. Room titles, nearby characters, household funds, unpaid bills, and existing life-sim context appear in the character prompt and room summary. Move through exits until you find a place you want to live:

```text
go north
go south
```

Generated wilderness rooms can be claimed the same way as indoor rooms. The current implementation does not require a room to be marked wilderness, empty, indoor, or unowned before you claim it, so use server/table rules to decide what is fair in a shared world.

## Join a household

If you want the home tied to a household, join or create that household first:

```text
join household moss-burrow
```

Discord can include both an id and display name:

```text
join-household household_id=burrow-1 name="Moss Burrow"
```

This sets your `HouseholdComponent`. The prompt then includes:

```text
Your household is moss-burrow.
```

If a command or tool supplies a separate display name, the prompt uses that name instead of the id.

## Claim a wilderness home

Claim the current room or name a reachable/adjacent room:

```text
claim home
claim home North Tunnel
```

This marks the room with `HomeComponent`, storing your character as owner and your current household id if you have one. After claiming, life-sim context includes:

```text
Your home is North Tunnel.
```

You can also claim an individual room:

```text
claim room
claim room North Tunnel
```

That marks the room with `RoomClaimComponent` and adds context like:

```text
Rooms you claim: North Tunnel.
```

Use `claim home` for the place your household lives. Use `claim room` for a bedroom, stall, workshop, or other personally claimed space inside or near that home.

## Partnerships and family

Start a partnership with a reachable character:

```text
start-partnership target_id=Hazel
```

Start a pregnancy:

```text
start-pregnancy co_parent_id=Hazel due_in_seconds=1
```

Resolve a due birth:

```text
resolve-birth child_name=Fern
```

Adopt a reachable child:

```text
adopt-child Clover
```

These commands create durable family relationships and prompt context. Pregnancy and some
relationship commands may require the world policy to allow romance, adult, and pregnancy
mechanics.

## Rent a home

Rent is represented as a bill. A landlord and tenant must be in the same room when rent is charged:

```text
charge rent Hazel 12
```

That creates an unpaid bill on the tenant. The tenant's life-sim context shows the debt:

```text
Unpaid bills: rent (12).
```

The tenant pays it with:

```text
pay bill
```

`pay bill` pays the first unpaid bill. If the client shows a specific bill id, you can also pay that exact bill:

```text
pay bill <bill-id>
```

Paying rent subtracts the amount from the tenant's household funds, marks the bill paid, and transfers the same amount to the landlord if the rent bill has a creditor. It does not automatically claim a home or room for the tenant; use `claim home` or `claim room` as part of the rental agreement if the world should record the rented space.

## What a home gives you now

Implemented benefits:

- persistent ECS state showing your household, home, and claimed rooms;
- prompt context that reminds the character where they live and which rooms they claim;
- a rent/bill loop for charging rent, showing unpaid bills, paying them, and transferring funds.

Not implemented yet:

- automatic eviction or lease expiration;
- rent schedules;
- access control or protection from other players;
- sleep, spawn, storage, or stat bonuses tied to a home.
