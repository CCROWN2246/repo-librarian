#!/usr/bin/env bash
# SessionStart hook: one-line knowledge-base nudge. Silent when clean; never blocks.
# Reads machine-readable state (catalog.json + .last_verified) via `librarian status --hook` —
# no fragile markdown parsing.
command -v librarian >/dev/null 2>&1 || exit 0
[ -f .librarian.toml ] || exit 0
librarian status --hook || true
exit 0
