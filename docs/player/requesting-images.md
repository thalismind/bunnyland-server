# Requesting images and videos

When a server has image generation turned on, Bunnyland illustrates itself. Characters get
**portraits** automatically, and — if the world uses the toon client — a matching **sprite**.
You don't have to do anything for those; they appear as they are generated.

What you *can* ask for is an image of a **moment**: a notable event in the world's history,
drawn as a scene with the room and the characters and items that were part of it.

## The camera, everywhere

The gesture is the same across every client — look for the camera, 📷:

- **Discord** — react to a message with 📷. The bot reacts 👀 to show it's working, then
  posts the picture and marks the message with 📸 when it's ready.
- **Web / Toon client** — press the 📷 **Request image** button on an event.
- **REPL / terminal** — run the `image` command on the selected event.

However you ask, you're requesting the same thing, and the result shows up attached to that
event.

When a server also advertises video generation, the movie-camera control, 🎬, requests a
short clip based on up to the three most recent events in your current room:

- **Discord** — react to a message with 🎬. The bot posts the completed clip and marks the
  request with 🎞️.
- **Web / Toon client** — press the 🎬 **Video** button. Toon plays the clip in the page;
  the text-oriented web clients show a link to it.
- **REPL / terminal** — run the `video` command; the completed clip appears as a media URL.

Image and video generation are independent server features. A client only shows the camera
for a feature the server has enabled.

## How event images work

- The **first** request for an event generates the picture; everyone who looks afterwards
  sees that same image, so asking again won't make a new one (an admin can force a fresh
  one if needed).
- Generation takes a little while — it runs in the background. The acknowledgement (👀 in
  Discord, a spinner in the web client) means your request is in the queue; the delivery
  mark (📸) means it's ready.
- Not every event has a picture — only the ones someone asked about. That keeps the world's
  illustrations meaningful instead of noisy.

## How event videos work

- A video summarizes up to the three newest durable events in the character's room in
  chronological order. If there are no recent events, the current room becomes the scene.
- Repeating the same request reuses its generated clip. A new sequence of recent events gets
  its own clip.
- Clips run through the same background queue as images and are served as MP4 or WebM media.
