# Garden-sim collections and shipping

Garden-sim tracks farm mail, local requests, shipping bins, collections, museum
donations, and rewards. These loops turn produce, fish, minerals, and artisan goods into
durable progress.

In Discord, prefix these commands with `!`.

## Mail and quests

Claim mail:

```text
!claim-mail mail_id="mayor mail"
```

Mail can grant a resource reward and marks itself claimed.

Complete a farm quest:

```text
!complete-farm-quest quest_id="melon request"
```

The command consumes requested inventory resources, marks the quest complete, and grants
its reward if one is configured.

## Shipping

Ship inventory resources:

```text
!ship-items bin_id="shipping bin" resource_type=grape quantity=1 unit_price=3
```

The shipping bin records shipped totals and earnings. The shipped resource is also added
to the character collection if it is new.

## Museum and rewards

Donate a resource:

```text
!donate-museum museum_id="town museum" resource_type=amethyst
```

Claim a configured reward:

```text
!claim-reward reward_id="museum reward"
```

Collections live on the character, while museum donation history lives on the museum
entity.
