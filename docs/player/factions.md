# Factions and nearby stance

Factions are shared across ordinary worlds. Characters can have several memberships and a
separate standing score with each faction. Factions can also regard other factions as
friendly or hostile. Those directed relationships let one group distrust another even when
the feeling is not mutual.

Join or leave a public faction with:

```text
!join-faction faction_id="Moss Wardens" rank=scout
!leave-faction faction_id="Moss Wardens"
```

Secret factions are different: the public join and leave actions reject them. A secret
membership appears only in that member's private prompt. Other nearby characters may see a
generic cue such as `Nearby Moth is hostile.`, but the cue never names the hidden faction.

Nearby character cues are observer-relative:

- Any hostile relationship from one of your factions to one of theirs makes them hostile.
- Otherwise, a shared faction or a friendly relationship makes them friendly.
- With no matching relationship, they are neutral.

Hostility wins when several memberships disagree. These rules work for civic groups,
supernatural afflictions, species alliances, and predator/prey relationships without
putting genre-specific identities into the shared prompt.
