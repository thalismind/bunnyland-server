# The Vision

bunnyland is an asynchronous social sandbox where humans and LLM agents share a persistent
world. The world is not a fixed game with one ruleset. It is an ECS graph that can be
extended indefinitely by adding components, edges, verbs, systems, prompt fragments,
generators, scripts, clients, and content libraries.

The experiment is human/robot interaction in a shared simulated world. The desired outcome
is emergent behavior: humans, LLM agents, scripts, and world systems surprising each other
inside rules that are explicit enough to inspect and change.

The short version:

1. Use ECS to build an infinitely pluggable, extensible world.
2. Appoint an LLM as the DM/GM and generate worlds using the components that are actually
   available.
3. Unify world actions as text-adventure verbs backed by tool calls.
4. Render the world as a prompt from each character's perspective.
5. Let LLM agents and human players coexist in the same sandbox.
6. Keep every mutation inside validated engine boundaries.
7. Treat emergent behavior as the goal.
8. Profit, or at least popcorn.

## Design pillars

### The ECS is the source of truth

Everything durable in the world should be represented as ECS data:

- entities for rooms, characters, items, controllers, incidents, recipes, jobs, notes, and
  other things that may be referenced or changed;
- components for singleton state on an entity;
- edges for repeatable relationships, containment, control, exits, ownership, assignments,
  and other links between entities.

The ECS rule matters: one entity can only have one component of each type. If something can
repeat, it belongs on edges or on separate linked entities. A character can have many
thoughts, injuries, debts, relationships, or jealousies only by linking to thought/injury
entities or relationship edges, not by stacking several same-type components.

### The DM proposes, the engine disposes

LLMs do not mutate the world directly. A DM/world-generator LLM proposes structured data.
The server validates it, translates it into ECS patches or command submissions, and applies
those through the same machinery used by human editors and players.

This is the central safety and coherence boundary:

- the DM can use live ECS schemas and content-library examples;
- the DM can suggest rooms, doors, characters, items, incidents, encounters, and recipes;
- the engine decides which components and edges are legal;
- malformed or impossible output fails validation instead of corrupting the world.

Generation should become increasingly schema-aware. The DM should know what component and
edge types are loaded in the current world, what reusable fragment libraries are available,
and what plugin mechanics exist. It should not assume every bunnyland installation has the
same mechanics.

### Verbs are the action surface

Every actor uses the same text-adventure-style verb surface. A human, an LLM controller, a
Discord user, and a scripted integration should all submit commands like:

- `move north`
- `take berry`
- `say "hello"`
- `craft berry-snack`
- `open east door`
- `take-note "the bell rings at dusk"`

Natural language is welcome at the edges, but the engine should resolve it into typed
commands with explicit payloads. Tool calling is the LLM-facing version of the same idea:
the agent picks a verb and arguments, then the world actor validates cost, reachability,
state, policy, and command generation.

An LLM should never get a privileged mutation channel simply because it is an LLM. If a
human could not do it through verbs or protected admin tools, an agent should not do it
either.

### Prompts are perspectives, not omniscience

The prompt for a character is a projection from that character's point of view. It should
include what the character can perceive, remember, infer, and do. It should not leak
private state, remote rooms, hidden entities, admin metadata, or future plans unless a
loaded mechanic explicitly grants that knowledge.

Prompt fragments belong with the mechanics that own them. Hunger describes hunger. Weather
describes weather. Social bonds describe nearby social context. A plugin that adds magic,
spaceships, dungeons, jobs, laws, recipes, or rumors should also add the prompt fragments
that make those mechanics legible to agents.

For component-owned prompt formatting conventions and migration guidance, see
[`prompts.md`](prompts.md).

### Humans and agents coexist

Characters are persistent entities. Controllers are swappable entities linked to characters.
That makes human takeover, LLM handoff, suspension, Discord control, and future clients part
of the same model instead of special cases.

The world should tolerate mixed play:

- an LLM can control a villager;
- a human can claim a generated character;
- a Discord user can play through chat;
- an admin can pause the server, patch the world, or save it;
- scripts and projections can observe events without owning truth.

The sandbox should feel alive when humans are absent and still fair when humans arrive.

### Some content never belongs

bunnyland can support many genres, tones, and private worlds, but some content is outside
the project boundary:

- inappropriate adult content: never;
- illegal content: never;
- content whose main purpose is to bypass moderation, consent, safety, or law: never.

These exclusions apply to core, bundled plugins, external plugins promoted by the project,
content libraries, scripts, demos, prompts, docs, tests, clients, and hosted deployments.

## What belongs in core

Core is the smallest stable spine needed for every bunnyland world. It should be boring,
predictable, and hard to regret.

Core should include:

- ECS primitives and helpers for entities, components, edges, containment, reachability,
  controller assignment, and replacement;
- the world actor, command queue, tick cycle, action/focus cost gates, and typed domain
  events;
- basic lifecycle state such as suspended, sleeping, downed, dead, and world clock;
- room, character, identity, description, item/container, door, inventory, and controller
  primitives;
- game mechanisms that support the core rules and the bundled x-sim modules, such as
  containment, inventory, doors, locks, buttons, readable/writable objects, basic item use,
  and other broadly reusable interaction rules;
- the plugin model and loader;
- persistence for ECS snapshots and bunnyland metadata;
- patch application for protected live editing;
- schema endpoints that describe loaded ECS types;
- API contracts and small test fixtures needed to exercise the server;
- tests that lock down cross-cutting contracts.

Core should avoid:

- genre-specific mechanics;
- large content catalogs;
- model-provider-specific assumptions outside thin adapters;
- UI opinions beyond basic development/admin clients;
- exotic mechanics that only make sense for one world theme;
- erotic mechanics or adult-oriented systems;
- irreversible abstractions for systems that are still experimental.

If a feature is required for nearly every possible bunnyland world, it can be core. If it is
only required for many worlds, it is probably a bundled plugin. If it is required for one
game, setting, deployment, or client, it should live outside core.

## What belongs in bundled plugins

Bundled plugins are reusable mechanics that demonstrate the platform and are broadly useful,
but not mandatory. They can ship in this repo because they are reference implementations and
integration tests for the plugin architecture.

Bundled plugins may include:

- common survival/life mechanics: needs, sleep, health, affect, memory;
- general environment mechanics: time of day, weather, fire, light;
- social mechanics: speech interpretation, relationships, reputation, boundaries;
- storytelling mechanics: incident budgets, encounters, event pacing;
- reusable genre packages such as colony, garden, dungeon, fantasy, survival, life-sim, and
  spaceship mechanics;
- small demo worlds that prove a plugin works end to end.

Bundled plugins must own their surface area:

- components and edges;
- verbs and command handlers;
- systems and consequences;
- typed events;
- prompt fragments;
- demo generators or fragment examples when useful;
- tests.

Bundled plugins should not rely on hidden core behavior. If a plugin needs a concept, it
should contribute that concept explicitly.

## What belongs in content libraries

Content libraries are reusable JSON fragments: items, recipes, resource nodes, doors,
workstations, NPC templates, room kits, encounter seeds, notes, and other ECS patch
snippets that can populate a world.

They are not mechanics. A recipe fragment can create a `RecipeComponent`, but the crafting
verb and its validation belong to the plugin that defines recipes. A berry fragment can
create food components, but hunger and eating belong to the needs/consumables mechanics.

Content libraries should include:

- small, composable examples;
- patch operations using public component and edge names;
- a stable fragment id, title, kind, tags, description, and optional attach edge;
- examples that help the DM choose valid ECS structures quickly;
- fragments that can be imported into the editor and exported back out.

Content libraries should not include:

- Python command handlers or systems;
- server-specific secrets or deployment configuration;
- copyrighted setting text, large lore dumps, or model prompts masquerading as data;
- assumptions that every world has every plugin loaded.

The core repo can carry a small base library to provide examples and quick-start content.
Large setting catalogs, commercial game data, or project-specific libraries should live in
their own repositories.

## What belongs in external plugins

External plugins are the right home for mechanics that are useful but not universal, large
enough to evolve independently, tied to a particular setting, or owned by a different team.

Use an external plugin repo for:

- a full game built on bunnyland;
- proprietary or private setting logic;
- large content/mechanics packs;
- integrations that require optional dependencies;
- experimental mechanics that should not destabilize core;
- model-provider-specific features beyond generic LLM adapters;
- exotic mechanics that do not support the common core or bundled x-sim modules;
- erotic or adult-oriented mechanics, where legal and appropriate for the independent
  project, but never as endorsed, bundled, hosted, or promoted bunnyland content;
- domain-specific moderation, economy, law, combat, magic, construction, or quest systems.

An external plugin should expose `bunnyland_plugins()` and contribute ordinary plugin
objects. It should be installable as a wheel with a `bunnyland.plugins` entry point and
should not require patching this repo.

## What belongs in clients

Clients are views and input surfaces. They should submit commands, display projections, and
call public or admin APIs. They should not become the source of truth for simulation rules.
All clients should live out of tree.

Clients may include:

- the world editor;
- graph/inspector views;
- Discord bots;
- web play clients;
- terminal clients;
- moderation dashboards;
- custom game UIs.

Graphical clients are encouraged. They are also out of tree. Web editors, graph clients,
3D views, mobile interfaces, Discord bots, terminal frontends, and bespoke game UIs should
have their own repositories, release cadence, dependencies, build tooling, branding, and
deployment.

The bunnyland core repo should define server APIs, schemas, patch formats, event streams,
and documentation that make clients straightforward to build. It should not become the
home for those clients.

Client-side convenience is fine. Client-side authority is not. If a rule matters, enforce it
on the server or in the world actor.

## What belongs in scripts

Scripts are deterministic world behavior and test fixtures expressed outside Python code.
They are useful for:

- tutorials;
- scripted events;
- acceptance tests;
- small scenario setup;
- simple timed or event-driven world patches.

Scripts should not replace plugins when the behavior needs complex validation, custom
commands, systems, events, or reusable mechanics. If a script grows into a ruleset, promote
it to a plugin.

## What should not be included

bunnyland should resist becoming:

- a single hard-coded game;
- a bag of special cases for one demo world;
- a model prompt collection with no engine-backed rules;
- a client-authoritative multiplayer app;
- a monorepo for every possible frontend and content pack;
- exotic mechanics inside core or bundled plugins when they do not support shared rules;
- inappropriate adult content;
- illegal content;
- a place for secrets, private deployment details, or provider credentials;
- a pile of one-off components that cannot be understood by prompts or editors.

Avoid adding a feature unless it has a clear home:

- core spine;
- bundled reusable plugin;
- content library;
- external plugin;
- client;
- script;
- documentation.

If the home is unclear, document the uncertainty before coding it.

## Inclusion rubric

When deciding where something belongs, ask:

1. Does every world need this to function?
   If yes, consider core.
2. Does this define reusable mechanics with validation and events?
   If yes, make it a plugin.
3. Is this only data made from existing components and edges?
   If yes, make it a content-library fragment.
4. Is this a UI or integration surface?
   If yes, make it an out-of-tree client.
5. Is this deterministic scenario glue?
   If yes, make it a script.
6. Is this large, branded, private, provider-specific, or setting-specific?
   If yes, put it in its own repo.
7. Does this give an LLM or client new authority over world mutation?
   If yes, redesign it around commands, validated proposals, or patches.
8. Is this an exotic mechanic that does not support the core rules or bundled x-sim modules?
   If yes, put it in its own repo.
9. Is this inappropriate adult content or illegal content?
   If yes, reject it.

## Long-term direction

The platform should grow toward:

- live schema-aware editors for all loaded components and edges;
- DM generation that can produce rooms, characters, items, incidents, recipes, and plugin
  concepts from loaded schemas and libraries;
- content libraries that can be browsed, imported, exported, versioned, and shared;
- stable external plugin packaging;
- multiple clients coexisting against the same server;
- better projections so prompts and UIs see exactly what each actor should see;
- richer event history, moderation, replay, and audit tools;
- long-running worlds that can be paused, patched, saved, resumed, and extended without
  restarting from scratch.

The point is not to make an LLM hallucinate a game and hope. The point is to let an LLM
operate as a DM inside a real simulation substrate: bounded by schemas, verbs, validation,
events, persistence, and player agency.

That is the shape of bunnyland: an extensible world engine where the rules are data and
plugins, the story is emergent, and the popcorn is optional but encouraged.
