# Changelog

All notable changes to Bunnyland are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The compatibility guarantees that begin with `1.0.0` are defined in
[`docs/developer/compatibility.md`](docs/developer/compatibility.md). The stable transport
surface is recorded in `contracts/`.

## [1.0.0] - 2026-08-18

First stable release. Bunnyland 1.x supports CPython 3.12, 3.13, and 3.14.

### Added

- **Media generation.** Image and video generation backed by ComfyUI, split into
  independent image and video services with runtime-configurable workflows. Scene requests
  resolve a real visible event and persist its snapshot, so generated media stays grounded
  in world state.
- **Character chat.** Unified chat across Discord, Web, and the Textual clients, including
  sleeping-character chat, lifecycle states, configurable profile privacy, and exposed tool
  parameters.
- **Terminal clients.** Textual TUI and REPL gained world introduction screens, a sandbox
  LLM launcher, an offline LLM TUI launcher, plugin-aware sandbox world generation, and
  character views at parity with the web clients.
- **Automatic memory recall.** Character prompts surface relevant past memories without an
  explicit lookup.
- **World authoring.** Composable room entry gates, persistent entity action overrides, and
  natural verb routing for pack content (colony harvest, voidsim airlocks, dinosim eggs,
  generated consumables).
- **Observability.** Optional world-health metrics plugin, orphan-entity telemetry, private
  Prometheus metrics, and Discord gateway latency tracking.
- **Benchmarks.** A tutorial benchmark ladder across Ollama and OpenRouter providers, with
  trace capture, cohort reporting, illustrated report packages, and a published model
  compatibility guide.

### Changed

- Command cost and lane are now server-authoritative.
- Sleep and rest recovery are unified; shelter and wetness are canonicalized across
  environment mechanics.
- Shutdown checkpoints are crash-safe, and the operational journal is append-only and
  segmented.
- The test gate runs in parallel; terminal and MCP tests are event-driven rather than
  timing-dependent.

### Security

- Request limiter defaults on, with capped scene images and validated upload bytes.
- Bounded the job and rate-limit maps that previously grew without limit, capped concurrent
  websockets, and enforced body caps on bytes received.
- Argon2 password verification runs off the event loop.
- Hardened API ingress, MCP origin checks, character profile and chat endpoints,
  credentials, and claims.
- nginx rejects public Tempo paths and shares a common security-header set.
- Replaced the Alpine Tempo runtime, moved to a patched Python 3.14 container base, and
  added persistent player moderation.

### Fixed

- Bounded conversation lifecycles with indexed terminal cleanup, so expired conversations
  are removed rather than accumulating.
- Retired detached transient controllers and ensured a default LLM controller exists.
- Empty provider responses are retried; model response rejections use one unified retry
  path.
- Live provider HTTP clients are closed rather than leaked.

## [1.0.0rc2] - 2026-07-21

Second release candidate.

## [1.0.0rc1] - 2026-07-20

First release candidate for the v1 surface.

## [0.2.1] - 2026-07-15

Pre-1.0 development release.

## [0.2.0] - 2026-07-15

Pre-1.0 development release.
