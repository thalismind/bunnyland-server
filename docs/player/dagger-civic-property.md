# Dagger-sim civic life and property

Dagger-sim civic mechanics track your standing with institutions, services, regions, and
property deeds. These systems are durable character state: they can show in your character
context and give the world hooks for future work, law, and social consequences.

In Discord, prefix these commands with `!`.

## Institution standing

Join a reachable institution:

```text
!join-institution institution_id="Burrow Cartographers" rank=member
```

Joining records membership and raises institution reputation by 1. Use a reachable
institution service:

```text
!use-institution-service service_id="local map service"
```

Using a service can create an output item, grants service access, and raises reputation
with that service's institution. If you use the same service again, the access record stays
unlocked; the reputation change still records that you worked with the institution again.

Your context can show:

- institution membership and rank
- institution reputation by institution
- the number of unlocked services

## Generated work

Institutions and sites can expose work templates. Ask for work, accept the generated
quest, then complete it:

```text
!ask-for-work template_id="ratcatcher errand"
!accept-generated-quest quest_id="Clear the North Tunnel"
!complete-generated-quest quest_id="Clear the North Tunnel"
```

Generated work can create quest records, deadlines, rewards, and institution context. It
is separate from dragon-sim's hand-authored quest objectives, but it uses the same player
loop: ask, accept, finish, collect consequences.

## Law and legal reputation

Some regions have law records. Commit a crime when the world prompts or permits it:

```text
!commit-crime crime_type=trespass
```

The crime creates a crime record in your inventory, posts a bounty/fine, and lowers legal
reputation in that region by the fine amount. Pay the fine:

```text
!pay-fine crime_id="trespass charge"
```

Paying marks the crime as paid, removes the active bounty component from that record, and
raises legal reputation back by the fine amount. Legal reputation appears as regional
context, so repeated crimes and repayments can become story fuel.

## Banking and loans

Open an account at a reachable bank:

```text
!open-bank-account bank_id="Carrot Factors Bank"
```

Deposit and withdraw funds:

```text
!deposit bank_id="Carrot Factors Bank" amount=20
!withdraw bank_id="Carrot Factors Bank" amount=5
```

Take and repay a loan:

```text
!take-loan bank_id="Carrot Factors Bank" amount=25
!repay-loan loan_id="bank loan" amount=25
```

Bank accounts are used by property purchases. Loans and unpaid balances remain durable
state for future legal or story systems.

## Buying property

Some worlds expose reachable property deed entities. Buy one from any bank account with
enough balance:

```text
!buy-property property_id="Moss Road Cottage"
```

Buying property:

- spends the deed price from your bank account
- marks the deed with your character as owner
- adds an ownership relationship to your character
- shows the owned property in your character context

Property must be reachable, purchasable, and unowned. If your bank balance is too low, the
purchase is refused and the deed remains unchanged.

## Civic loop

```text
!join-institution institution_id="Burrow Cartographers" rank=member
!use-institution-service service_id="local map service"
!ask-for-work template_id="ratcatcher errand"
!accept-generated-quest quest_id="Clear the North Tunnel"
!complete-generated-quest quest_id="Clear the North Tunnel"
!open-bank-account bank_id="Carrot Factors Bank"
!deposit bank_id="Carrot Factors Bank" amount=40
!buy-property property_id="Moss Road Cottage"
!commit-crime crime_type=trespass
!pay-fine crime_id="trespass charge"
```
