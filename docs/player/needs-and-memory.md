# How to manage needs and memory

Needs are character meters. Memory commands are private focus actions. In Discord, prefix
commands with `!`.

## Eat and drink

Food lowers hunger:

```text
!eat berry tart
```

Water sources lower thirst:

```text
!drink stone basin
```

Consumable food is removed when its uses run out. Renewable drink sources, such as a
basin, stay in the world.

Needs rise as world time passes. If hunger or thirst comes back after waiting, eat or
drink again:

```text
!wait
!eat berry tart
```

## Take private notes

Use `!take-note` for private memory:

```text
!take-note trust the blue door
```

Private notes are not room objects. Other players do not find them by looking around.

## Remember and reflect

Search notes by keyword or recent memory:

```text
!remember trust
!remember query=trust mode=keyword limit=2
```

Create a reflection from matching notes:

```text
!reflect query=trust mode=keyword
```

Reflections become new private memory entries tagged as reflections.
Characters with memory profiles also reflect periodically. The background loop waits for
enough new non-reflection memories and then creates a bounded reflection through the same
validated memory path as `!reflect`.

## Contextual recall

Agent prompts can also surface a private `Recall` section automatically when current
location, visible people/items, or recent room context match older memories. Recall lines
include source metadata so operators can audit why a memory appeared. Irrelevant notes stay
out of recall even though you can still find them with `!remember`.

## Forget

When Discord shows a note id in a memory search, forget that note by id:

```text
!forget note-1
```

Forgetting deletes that entry from the selected memory collection. It does not delete
physical writing on signs, books, or paper.
