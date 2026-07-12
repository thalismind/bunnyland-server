# The Toon client

Toon-sim turns a Bunnyland world into something you can see. It attaches three pieces of
presentation data to entities - a sprite image, a float X/Y position, and an integer draw
layer - so a graphical client can show a room as a stack of sprites. Rooms sit at the
back as the scene's background, furniture and props layer above them, interactive items
and doors above that, and characters on top. The simulation itself ignores all of this;
it is purely there for clients to draw.

The client that reads it is **Bunnyland Toon**, a web page that shows one room at a time
with its contents layered on top and doors leading to the neighbouring rooms.

## Opening Bunnyland Toon

Open the Bunnyland Toon page. On a hosted deployment the **Server** box is pre-filled with
the site's API (`/api/`) and the page connects automatically; otherwise type your server's
address and press **Connect Live**. Once the status reads connected, choose your character
from the **Player** menu. The view centres on the room your character is in, and your
character's sprite is highlighted.

The client keeps one player-scoped live connection for room activity, action results, and
character refreshes. If it drops, the page reconnects and uses recent activity as a temporary
fallback, so a short interruption should not require reloading the page or duplicate events.

If a world was generated without sprite art, entities still appear: each falls back to an
icon based on its kind, and rooms show their name as a labeled backdrop. Art can be filled
in later without changing anything about how you play.

## Reading the room

The left panel is the room. From back to front you see:

- the **room** itself as the background,
- **furniture and props** resting in place,
- **items and doors** you can interact with,
- **characters**, including you, drawn on top.

Items can also carry a toon-only `PlacedOn` relationship to furniture such as tables,
desks, shelves, and counters. The room still contains both the furniture and the item;
`PlacedOn` only tells Bunnyland Toon to draw the item resting on that surface instead of
as a loose floor object.

Transparent containers use the normal container data already present in the world. When a
container has `ContainerComponent.transparent = true`, Bunnyland Toon
can query or read that container's `Contains` relationships and draw those contents as
visible through the container without changing core reachability or inventory rules.

**Doors** are pinned to the edge of the room that matches their direction - a north exit
sits at the top, an east exit on the right. While you are looking at your own room, clicking
a door **queues a move** through that exit - the same action as the **Move** verb, without
the target picker. While you are *spectating* a room your character is not in, clicking a
door instead moves the view one room further so you can look around; press **Follow player**
to snap back to your own room.

## Moving around

When you are looking at your own room, move your character by **clicking** where you want
to stand, or with the **arrow keys** or **WASD**. Movement is immediate - your sprite
follows right away - and it costs no action points, because shifting position inside a
room is free. Your new position is sent to the server a few times a second, so everyone
else sees you move too.

Walking *between* rooms is a real action. **Click a door** on the edge of your room, or use
the **Move** action in the menu on the right; either way it spends an action point and only
succeeds if the exit leads somewhere you can go. If you are short on points, the move is
queued and runs as soon as your points regenerate.

## The action menu

The right-hand panel lists the actions available to your character, grouped into **room
actions** and **focus actions**. At the top it shows your current points:

- **Action points (AP)** pay for things you do in the world - moving between rooms, taking
  and using items, eating, drinking, and speaking.
- **Focus points (FP)** pay for quiet, internal actions - taking notes, remembering,
  reflecting. Speaking costs a little of both.

Every action shows its cost. If you cannot afford one right now, it is greyed out until
your points regenerate. Picking an affordable action does one of three things:

- **Free-text actions** (say, take note, remember, reflect) ask you to type the text, then
  send it.
- **Targeted actions** (move, take, drop, use, eat, drink, tell) open a short list of
  nearby targets - exits for move, items in the room for take, things you are carrying for
  drop, the other characters present for tell - and act on the one you choose.
- **Wait** simply passes your turn.

The menu only enables what you can pay for; the server still has the final say and will
refuse an action if the target is out of reach or the moment has passed.

The menu is serialized from the server's installed action registry and current target
groups. It does not carry its own fallback verb list; while that metadata is unavailable,
the action area remains empty or disabled until the next live refresh.

## The same actions everywhere

Bunnyland Toon is one way to drive a character. The actions in its menu are the same verbs
available through chat and Discord - `move`, `take`, `say`, `eat`, and the rest - so a
character you play here behaves exactly like one played any other way.
