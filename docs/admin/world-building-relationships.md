# Relationships, factions, and social pressure

Relationships make identical facts produce different choices. A stranger may hear caution; a
resentful rival hears condescension. Bunnyland models that difference as directed state rather
than a single universal “friendship score.”

## Think in directed bonds

`SocialBond` is an edge from one character to another. It carries affinity, trust, fear,
resentment, and familiarity. Because it is directed, Sable can trust Fen more than Fen trusts
Sable.

Use the dimensions deliberately:

| Dimension | High value suggests | It does not necessarily mean |
|-----------|---------------------|------------------------------|
| Affinity | warmth, liking, preference for company | trustworthiness |
| Trust | belief that the other will act reliably | affection |
| Fear | expectation of danger or power | hatred |
| Resentment | remembered grievance or hostility | unfamiliarity |
| Familiarity | accumulated contact and recognition | a positive bond |

A familiar rival and an unfamiliar ally should not feel the same.

## Seed history, then let play update it

Initial relationships should explain present behavior without predetermining the future.
For Lantern Ferry:

| Source | Target | Initial shape | Reason |
|--------|--------|---------------|--------|
| Fen | Sable | familiar, low trust, moderate resentment | Fen believes Sable wasted emergency oil. |
| Sable | Fen | familiar, some trust, shame rather than resentment | Sable knows Fen once helped the ferry. |
| Rowan | Sable | low familiarity, moderate trust | couriers rely on ferry operators. |
| Lark | Fen | familiar, mild affinity | both preserve village records. |

Use biography or memory to explain why the bond exists. The edge holds current social state;
the evidence and recollections give it narrative meaning.

Speech can change bonds when the social plugin is active. Interpretation considers the
listener's mood and existing relationship, so warm words are not guaranteed to land warmly.
This is a source of drama, not a substitute for consent or world policy.

## Use named relationship edges for categorical facts

Some relationships are not attitudes. Partnership, parenthood, ownership, household,
membership, command, and faction standing have different rules and should use their
registered edge types.

Use `SocialBond` for how someone feels. Use a categorical relationship for what socially or
legally connects them. A sibling can be deeply resentful; a guild member can distrust the
guildmaster; an owner can feel no affinity for an inherited house.

Many categorical relationships need reciprocity or inverse edges to be visible from both
directions. Follow the mechanic's cardinality and creation handler rather than manually
inventing an inverse edge name.

## Build factions as institutions

A faction should do more than label a group. Define:

- what it controls or protects;
- what membership or standing permits;
- what behavior changes standing;
- how outsiders perceive its authority;
- where its rules and services are visible;
- what internal disagreement exists.

`FactionComponent` provides identity and ideology, while package-specific relationships can
represent standing, membership, service access, or reputation. Use the installed catalogue
because civic mechanics vary by sim package.

For Bracken Reach, a Ferrymen's Compact might control crossing maintenance and emergency
stores. Membership grants access to the work chest; standing falls when supplies disappear;
the shrine ledger records compact business. That turns the faction into playable structure.

## Connect relationships to consequences

Let state influence choices and let choices alter state:

- a fulfilled obligation can improve trust;
- a failed obligation can reduce trust and increase resentment;
- repeated conversation grows familiarity;
- praise, comfort, apology, threat, and insult can shift bonds;
- quest outcomes can alter faction standing or access;
- memories can preserve why a character interprets a later event strongly.

Do not apply relationship changes because a narrator says two people reconciled. Tie the
change to a handled action, resolved obligation, accepted policy transition, or consequence
that observed authoritative state.

Use coarse, legible changes. Tiny adjustments on every tick create noise and make it hard to
understand why a relationship moved.

## Respect boundaries and agency

World policy decides which sensitive mechanics are allowed and who must opt in. A high
affinity score does not override consent. A persona instruction does not override server
policy. Rejection should remain authoritative even when an LLM narrates confidence.

Likewise, social pressure should create choices rather than mind control. Fear can influence
an autonomous controller, but it should not silently teleport a character, transfer property,
or accept an obligation.

## Make social state discoverable without making it omniscient

Characters perceive their own relationship context and nearby social cues. Other people may
observe behavior, public roles, and events, but should not receive raw private bond numbers.

Show social change through:

- altered willingness to help or trade;
- greetings, avoidance, praise, guarded speech, or apology;
- public standing and service access;
- fulfilled or failed commitments;
- memories of the event that caused the change.

These are interpretable consequences. A debug inspector can show exact fields to an admin;
the fiction should not depend on characters reading a meter.

## Relationship review

- Important bonds are directed and can be asymmetric.
- Affinity, trust, fear, resentment, and familiarity have distinct reasons.
- Categorical ties use their registered relationship types.
- Factions control real services, places, rules, or resources.
- Social changes follow authoritative actions and consequences.
- Requests, attraction, fear, and affinity never bypass agency or policy.
- Characters perceive relevant cues without gaining omniscient private state.
- The world retains evidence explaining major changes.

Next, make authored beats repeatable and observable in
[Events, scripts, and consequences](world-building-events.md).
