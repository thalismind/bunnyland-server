# Container image CLI

This note records the usability evaluation behind Bunnyland's single published runtime
image and the conventions future container changes should preserve.

## Method and evidence

The evaluation covered first-run discovery, production server startup, local and remote
terminal play, automation commands, Compose use, image pinning, and release CI. It combined
task walkthroughs against the shipped CLI, registry manifest inspection, CI timing, and
comparison with current Docker and official-image conventions. It did not include external
participant sessions, so it does not claim preference or completion-time data from users.

On 2026-07-16, the `main` manifests for `bunnyland-server`, `bunnyland-tui`, and
`bunnyland-repl` each contained the same 15 layer digests and 545,648,629 compressed layer
bytes. Only the image config objects differed: the server selected `bunnyland serve`, while
the client images selected their standalone executables and assumed a Docker DNS hostname.
The latest successful three-target container CI job took 27 seconds. Storage and build time
were therefore secondary considerations; discoverability and release consistency drove the
decision.

[Docker's Dockerfile guidance](https://docs.docker.com/reference/dockerfile/#entrypoint)
recommends an exec-form `ENTRYPOINT` for an image that behaves like an executable, with
`CMD` providing overridable defaults. Docker also describes
[one concern per container](https://docs.docker.com/build/building/best-practices/#decouple-applications)
as a rule of thumb, not a requirement for a separate image per executable. Official
[PostgreSQL](https://github.com/docker-library/docs/blob/master/postgres/README.md) and
[Redis](https://github.com/docker-library/docs/blob/master/redis/README.md) images use one
image for a daemon plus client or maintenance commands selected at runtime.

## Task comparison

| Task | Three role images | One CLI image |
|---|---|---|
| Discover available modes | Find three package names in documentation | Run the image and read top-level help |
| Start a server | Server starts implicitly with image-specific defaults | Select `serve` and provide the intended configuration |
| Play in a terminal | Pick a TUI or REPL image whose default remote hostname only works in one Compose topology | Select `tui` or `repl`; omit `--server` for local play or provide the real remote URL |
| Run auth or recovery tooling | Know that the server image also contains unrelated commands | Select the command from the same top-level help |
| Pin a release | Track three manifest digests for identical software | Track one manifest digest |
| Verify installed and container CLIs | Test standalone executables plus `bunnyland` | Test the same `bunnyland` command in both environments |

The role-specific defaults save one word only when the user already knows which package to
pull. They make first use less predictable: the server creates a world immediately, while
the client images try a network hostname that is usually absent from an ad hoc `docker run`.

## Decision

Publish only `ghcr.io/thalismind/bunnyland-server` and make it behave as the `bunnyland`
executable:

```text
docker run IMAGE                 -> bunnyland --help
docker run IMAGE serve ...       -> server process
docker run --rm -it IMAGE tui ...
docker run --rm -it IMAGE repl ...
```

This keeps one process and one concern in each running container. It does not run the
server and terminal clients together. Help is the default because the image has several
intentional modes and silently starting a persistent world is harder to undo than adding an
explicit subcommand.

## Conventions

- `bunnyland` is the only public executable. Runtime modes are subcommands, not additional
  image names or console-script aliases.
- A terminal client's subcommand delegates its full argument list to that client. Do not
  duplicate a partial option parser in the top-level CLI.
- The image uses exec-form `ENTRYPOINT ["bunnyland"]` so the selected process receives
  signals as PID 1. Its default command is `--help` and exits successfully.
- Server deployments always select `serve` explicitly. They do not rely on an image default.
- TUI and REPL examples include `-it`. Remote examples require an explicit HTTPS server;
  omitting `--server` means local, in-process play.
- Add another published runtime image only when it has a genuinely different dependency,
  privilege, platform, or security boundary. A different default command is not enough.
- Do not publish compatibility aliases for the retired role images or standalone client
  executables before the public release.
