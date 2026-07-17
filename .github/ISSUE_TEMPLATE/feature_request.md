---
name: Feature request
about: Propose a new mechanic, system, or capability
title: "[feature] "
labels: enhancement
---

## The idea

What you want Bunnyland to be able to do, in one or two sentences.

## Why

The player, agent, or maintainer problem this solves. What is hard or impossible
today?

## Where it belongs

Core spine, bundled in-tree plugin, content-library fragment, external plugin in
its own repo, client, or script? Run it through the inclusion rubric in
[`docs/developer/vision.md`](../../docs/developer/vision.md) — broadly reusable
mechanics can land in-tree, while setting-specific, large, private,
provider-specific, optional-dependency, or experimental work belongs in its own
external plugin repo. If the home is unclear, say so here before any code.

## Sketch

How it might work in the ECS model — components, handlers, prompt-visible state,
rejection paths. Rough is fine.

## Test angle

How would we prove it works? Which layer (unit handler, prompt-fragment, plugin,
e2e, playtest)? New mechanics need tests, so it helps to think about this early.

## Performance and compatibility

How should the work scale with world size? Call out full-world scans, relationship
degree, serialization, persistence, or component-index behavior that could affect
gameplay latency. Bunnyland is still pre-release: prefer a direct migration over a
compatibility alias or shim.

## Alternatives considered

Anything you ruled out, and why.
