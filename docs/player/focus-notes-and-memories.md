# Focus, notes, and memories

Focus actions use focus points instead of normal action points. Notes and memory commands
are private: they help your character remember facts without placing a visible object in
the room.

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

Reflections become new private memory entries tagged as reflections. Characters with
memory profiles also reflect periodically. The background loop waits for enough new
non-reflection memories and then creates a bounded reflection through the same validated
memory path as `!reflect`.

## Contextual recall

Agent prompts can surface a private `Recall` section automatically when current location,
visible people/items, or recent room context match older memories. Recall lines include
source metadata so operators can audit why a memory appeared. Irrelevant notes stay out
of recall even though you can still find them with `!remember`.

## Forget

When Discord shows a note id in a memory search, forget that note by id:

```text
!forget note-1
```

Forgetting deletes that entry from the selected memory collection. It does not delete
physical writing on signs, books, or paper.
