# Social play and boundaries

Social state comes from explicit commands and from speech. Boundaries are world policy:
they decide which sensitive mechanics are enabled and who must opt in.

## Build relationships through speech

Say something to everyone awake in the room:

```text
!say thank you Hazel
```

Tell one present character:

```text
!tell Hazel please guard the basket
```

Speech records text, inferred intent, and the final interpretation. Praise, apologies,
requests, promises, insults, and threats can shift social bonds when the social mechanic is
enabled.

Promises, offers, requests, and threats also become explicit obligations when social
mechanics are enabled. A promise or offer makes the speaker owe the listener; a request
makes the listener owe the speaker. Resolve an obligation when it is fulfilled, failed, or
canceled:

```text
!resolve-obligation obligation_id=entity_42 status=fulfilled note="fixed before dusk"
!resolve-obligation obligation_id=entity_43 status=failed
```

Fulfilled obligations improve trust toward the debtor. Failed obligations reduce trust
and add resentment. Open obligations appear in prompts until resolved.

Listeners do not interpret speech from text alone. Their current mood and relationship to
the speaker can change how a line lands: a warm comment may reassure a trusted friend but
sound insulting to someone who is already angry and resentful.

Social prompts also surface meaningful nonverbal state. A familiar character may be
watching quietly, an angry or tense character may be brooding silently, and a hostile
listener may be pointedly silent after your last remark. These cues are projections of
world state and recent events, not new state invented by narration.

For immediate turn-taking, use a conversation thread. The first command creates a
conversation entity with participants, timeout, and whose turn it is; each
`conversation-line` advances the turn and also emits ordinary speech for social systems:

```text
!start-conversation target_ids=Hazel topic=watch rotation
!conversation-line conversation_id=entity_12 text="Please check the east tunnel."
!end-conversation conversation_id=entity_12 reason=resolved
```

When memory is enabled, conversation lines are also stored as private memories for
profiled participants. Later `remember` searches and prompt recall can surface who spoke,
who heard it, and how the line landed.

Conversation lines also create structured gossip claims for the people present. If a
character later uses speech with `intent=gossip`, listeners can learn attributed,
lower-confidence versions of claims they did not personally hear. This spreads social
knowledge without treating hearsay as authoritative world state.

## Use explicit relationship commands in life-sim

Some durable relationship state is command-driven:

```text
!set-relationship-status target_id=Hazel status=friend
!start-partnership target_id=Hazel
!spread-gossip target_id=Hazel text="kept watch all night" reputation_delta=1
```

Family commands are also explicit:

```text
!start-pregnancy co_parent_id=Hazel due_in_seconds=1
!resolve-birth child_name=Fern
!adopt-child Clover
```

## Respect world boundaries

World policy can disable or restrict categories such as romance, pregnancy, PvP, and
pickpocketing. If a command says a mechanic is disabled or someone has not consented, use
ordinary speech or another non-restricted action instead.

Prose alone does not create sensitive state. Say what your character means, then use the
explicit command when the world allows that mechanic.
