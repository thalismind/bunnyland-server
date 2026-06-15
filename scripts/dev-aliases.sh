#!/usr/bin/env bash
# Convenience aliases for running the Bunnyland TUI and REPL clients.
#
# Source this file from your shell to register the aliases, e.g.:
#
#   source scripts/dev-aliases.sh
#
# Each client is launched with `uv run --all-extras -m ...` so the optional
# `tui`/`repl` extras (textual, httpx) are available without a manual install.
# Trailing arguments are passed through, e.g.:
#
#   bunny-tui --server http://localhost:8765
#   bunny-repl --seed "a quiet marsh" --generator apartment-demo
#   bunny-tui --list-generators

# Terminal UI client (Textual).
alias bunny-tui='uv run --all-extras -m bunnyland.tui'

# Line-based REPL client.
alias bunny-repl='uv run --all-extras -m bunnyland.repl'
