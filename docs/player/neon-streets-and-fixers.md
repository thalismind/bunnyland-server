# Neon-sim streets, cyberware, and fixers

This guide covers neon-sim's street economy and heat, cybernetic implants, and fixer
missions. For districts, surveillance, and hacking, see [Neon-sim cyberpunk
city](neonsim.md).

In Discord, prefix these commands with `!`.

Money is **scrip**, the same colony-sim resource stack used elsewhere. Debts and bounties
reuse dagger-sim law state, so a street bounty is the same record the law uses, just placed
by a runner instead of a court.

## Street economy

Buy contraband from a black-market vendor and fence stolen data with a broker:

```text
!buy-contraband target_id="back-alley vendor"
!sell-data broker_id="data fence" data_id="payroll database"
```

Sensitive data sells for double. Selling and carrying contraband raises your heat (see
below). Call in a favor a contact owes you, and settle a debt before it sinks you:

```text
!call-favor target_id="Padre"
!pay-debt
```

Put a price on a target's head, or flip a police informant to your side (both cost scrip):

```text
!post-bounty target_id="corpo rat" amount=500
!turn-informant target_id="street snitch"
```

## Heat, wanted levels, and the law

Crimes and contraband build **heat**. Heat decays slowly on its own, but while it is high it
escalates your **wanted level** in tiers, and each new tier triggers a law response and
trips nearby alarms. Two ways to cool off: lay low in a safehouse you have claimed, or pay
to clear an outstanding warrant:

```text
!hide-from-law
!clear-warrant
```

Your current heat, wanted level, and debt show in your character context.

## Cyberware

Implants slot into your augmentation capacity, and each one carries its own trade-off: power
draw, maintenance, legality, and sometimes a side effect. Install an implant you are
carrying at a clinic; licensed clinics fit only legal chrome, while unlicensed street
surgeons will install illegal implants but the back-alley job adds heat:

```text
!install-implant implant_id="reflex booster" clinic_id="ripperdoc"
```

Maintain, push, or shut down an installed implant:

```text
!service-implant implant_id="reflex booster" clinic_id="ripperdoc"
!overclock-implant implant_id="reflex booster"
!disable-implant implant_id="reflex booster"
!remove-implant implant_id="reflex booster"
```

Neglected implants misfire into their side effect; servicing resets the clock.
Overclocking adds power and performance but shortens the maintenance interval. Legalize an
illegal implant so it stops drawing scrutiny:

```text
!license-implant implant_id="wired claws"
```

Implants are also a target. Scan a person's chrome, then exploit a vulnerable implant with
the same exploit tools you would use on a terminal — a successful breach shuts the implant
down:

```text
!scan-implant target_id="corpo guard"
!exploit-implant target_id="corpo guard"
```

## Fixers and missions

Fixers offer runner contracts. Take a job, meet the handler, deliver the goods (usually
exfiltrated data), then collect your payout:

```text
!take-fixer-job target_id="data run"
!meet-handler target_id="the broker"
!deliver-data contract_id="data run" data_id="stolen schematics"
!collect-payout target_id="data run"
```

Not every job is clean — a double-cross pays nothing and spikes your heat when you go to
collect. Burn a contact who set you up:

```text
!burn-contact target_id="Padre"
```

## Corporate intrigue

Frame a target by planting evidence, lean on them with leverage you hold, or burn them by
leaking it publicly. Extract a defecting asset to pull them out:

```text
!plant-evidence target_id="rival exec"
!blackmail-target target_id="rival exec" file_id="the photos"
!leak-file target_id="incriminating dossier"
!extract-asset target_id="defector"
```

Blackmail makes the target owe you a favor; leaking a file piles heat on whoever it
incriminates.

## Example loop

```text
!take-fixer-job target_id="data run"
!buy-contraband target_id="back-alley vendor"
!hide-from-law
!deliver-data contract_id="data run" data_id="stolen schematics"
!collect-payout target_id="data run"
!install-implant implant_id="reflex booster" clinic_id="ripperdoc"
```
