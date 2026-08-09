# Quests, goals, and obligations

Quests, goals, and obligations all describe unfinished business, but they belong to different
owners. Keeping them distinct makes character choices believable and completion state
reliable.

## Choose the right form

| Form | Owned by | Answers | Example |
|------|----------|---------|---------|
| Goal | one character | What do I currently want? | Sable wants to relight the ferry lantern. |
| Quest | world content offered to participants | What structured undertaking can be accepted and completed? | Reopen the crossing and deliver the medicine. |
| Obligation | parties to a commitment | What have I promised, offered, or otherwise committed to another person? | Sable promised Fen to replace the missing oil. |
| Request | speaker, until accepted | What would I like someone else to do? | Rowan asks Lark to find the ledger. |

A request must not automatically become the listener's obligation. People can refuse, ignore,
negotiate, misunderstand, or simply fail to commit. Create an obligation only when the
debtor's own promise, offer, agreement, accepted request, debt, or enforced rule establishes
one.

## Author character goals

`GoalComponent.active_goals` is a concise list of motives surfaced to that character. Goals
guide judgment but do not prove completion. “Deliver the medicine to the far bank” can
motivate Rowan; the medicine's location, receipt, quest objective, or delivery event must
still establish whether it happened.

Write goals that contain a desired world change:

- weak: “think about the ferry”;
- better: “find a safe way to deliver the medicine across the flooded river”;
- over-scripted: “go west, take oil, go east twice, use lantern.”

The better version allows planning and alternate solutions. Add constraints only when the
character knows and cares about them.

Review goals as state changes. Remove, replace, or revise goals after their authoritative
condition is met. A permanent “repair the lantern” goal attached to an already repaired lamp
creates repetitive or contradictory behavior.

## Build a quest graph

The quest system is provided by `bunnyland.dragonsim`. A quest entity normally carries:

- `QuestComponent` with stable quest id, title, and description;
- `QuestStateComponent` with offered, active, completed, failed, or declined state;
- `QuestHasObjective` edges to objective entities;
- `QuestHasReward` edges to reward entities;
- acceptance and tracking relationships for participating characters.

Each objective is a separate entity with `QuestObjectiveComponent`. Each reward is a separate
entity with `QuestRewardComponent`. This supports several ordered objectives and rewards
without putting duplicate singleton components on the quest.

For Lantern Ferry:

| Order | Objective | Authoritative completion evidence |
|-------|-----------|-----------------------------------|
| 1 | restore the lantern | repaired/lit lantern state |
| 2 | reopen the crossing | route, ferry, or public notice state |
| 3 | deliver the medicine | medicine custody plus receipt or delivery event |

Do not mark an objective complete because a character said it was done or wrote a private
note. Dialogue and memory are beliefs. Completion must follow the actual mechanic or an
admin-authored resolution grounded in inspected state.

## Make acceptance meaningful

A quest offer is an opportunity, not an obligation. Let characters accept, decline, or leave
it alone. Track the quest for characters who need it in prompt context, but do not make every
nearby person a participant.

Consider whether the quest is:

- personal, shared, competitive, or faction-owned;
- offered publicly or discovered privately;
- reversible before acceptance;
- time-limited through `due_at_epoch`;
- branchable through explicit quest state;
- still understandable after the original quest giver leaves.

Represent the offer on a person, notice board, contract, radio message, or discoverable
record that makes sense in the setting.

## Author obligations between parties

An obligation is its own entity with `ObligationComponent`. Directed edges identify the
debtor and creditor. Open obligations can appear in their prompt context until resolved as
fulfilled, failed, or canceled.

Write an obligation as a commitment that both sides can recognize:

```text
kind: promise
text: Replace the store's lamp oil after the ferry reopens.
debtor: Ferrymaster Sable
creditor: Storekeeper Fen
due: moonrise, if enforced by world epoch
```

Fulfillment and failure can affect trust and resentment, so do not use obligations as a
generic task list. A civic duty, employment contract, favor, promise, debt, or bargain may fit.
A personal curiosity or unsolicited request does not.

Resolve obligations through `resolve-obligation` only when the world supports the selected
status. Add a resolution note for audit and narrative continuity, but remember that the note
describes the resolution; it does not substitute for the completed action.

## Design rewards as consequences

A reward can be an item, access, standing, knowledge, repaired relationship, property right,
or new route. Attach reward entities and grant relationships explicitly when the quest
mechanic supports them.

Avoid rewards that only appear in narration. Also avoid cloning a permanent reward every
time completion is rechecked. Reward claims should be idempotent and visibly recorded.

The best reward changes future possibilities. Reopening the ferry makes travel easier;
earning Fen's trust changes later negotiations; learning the ledger's truth creates a new
social choice.

## Arc review

- Goals express character desires without prescribing exact action sequences.
- Quest participation requires acceptance or an explicit authored rule.
- Objectives and rewards are separate linked entities in deterministic order.
- Completion follows authoritative world state, not speech or private notes.
- Requests remain requests until the requested person commits.
- Obligations name debtor, creditor, commitment, status, and any real deadline.
- Resolved goals and obligations stop producing stale prompt pressure.
- Rewards are durable, inspectable, and impossible to claim repeatedly.

Next, make those commitments emotionally meaningful in
[Relationships, factions, and social pressure](world-building-relationships.md).
