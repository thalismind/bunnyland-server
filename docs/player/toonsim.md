# Toon-sim and the Bunnyland Toon client

Toon-sim turns a Bunnyland world into something you can see. It attaches three pieces of
presentation data to entities - a sprite image, a float X/Y position, and an integer draw
layer - so a graphical client can show a room as a stack of sprites. Rooms sit at the
back as the scene's background, furniture and props layer above them, interactive items
and doors above that, and characters on top. The simulation itself ignores all of this;
it is purely there for clients to draw.

The client that reads it is **Bunnyland Toon**, a web page that shows one room at a time
with its contents layered on top and doors leading to the neighbouring rooms.

## Opening Bunnyland Toon

Open the Bunnyland Toon page, type your server's address into the **Server** box, and
press **Connect Live**. Once the status reads connected, choose your character from the
**Player** menu. The view centres on the room your character is in, and your character's
sprite is highlighted.

If a world was generated without sprite art, entities still appear: each falls back to an
icon based on its kind, and rooms show their name as a labeled backdrop. Art can be filled
in later without changing anything about how you play.

## Reading the room

The left panel is the room. From back to front you see:

- the **room** itself as the background,
- **furniture and props** resting in place,
- **items and doors** you can interact with,
- **characters**, including you, drawn on top.

**Doors** are pinned to the edge of the room that matches their direction - a north exit
sits at the top, an east exit on the right. Clicking a door moves the view into that room
so you can look around. While you are looking at a room your character is not in, the title
bar shows *spectating* and you cannot move there; press **Follow player** to snap back to
your own room.

## Moving around

When you are looking at your own room, move your character by **clicking** where you want
to stand, or with the **arrow keys** or **WASD**. Movement is immediate - your sprite
follows right away - and it costs no action points, because shifting position inside a
room is free. Your new position is sent to the server a few times a second, so everyone
else sees you move too.

Walking *between* rooms is a real action. Use the **Move** action in the menu on the right
(or walk through the world's normal exits); it spends an action point and only succeeds if
the exit leads somewhere you can go.

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

## The same actions everywhere

Bunnyland Toon is one way to drive a character. The actions in its menu are the same verbs
available through chat and Discord - `move`, `take`, `say`, `eat`, and the rest - so a
character you play here behaves exactly like one played any other way.
