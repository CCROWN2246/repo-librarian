#!/usr/bin/env bash
# UserPromptSubmit hook: nudge on work-RESUMPTION, not just cold session start.
# `--throttle` fast-paths on _index/.last_nudge and early-exits BEFORE loading
# catalog.json, so a busy prompt stream never pays the catalog-load tax — it does
# one real check per work-block ([hooks].nudge_throttle_minutes). Silent when clean;
# never blocks the prompt.
command -v librarian >/dev/null 2>&1 || exit 0
[ -f .librarian.toml ] || exit 0
librarian status --hook --throttle || true
exit 0
