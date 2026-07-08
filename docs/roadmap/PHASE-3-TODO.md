# Phase 3 — surfaces (deferred TODOs)

Status: **not started.** Phases 0–2 (the whole core product) are built on `librarian/phase-0`.
Phase 3 is the "how the value reaches agents and teams" layer. Both items have their implementation
decided (CEO/eng review + Chris, 2026-07-08); they were deferred so Chris can review the core first.
Neither may erode the zero-runtime-dependency rule for the core install.

## E1b — MCP query-on-demand server

**What:** an MCP server exposing the catalog as a query tool, so an agent gets sourced,
freshness-stamped answers on demand instead of preloading `CATALOG.md`. Thin wrapper over the existing
`librarian query` (and later `librarian why`) — no new retrieval logic.

**Decided implementation:** **hand-roll a pure-stdlib JSON-RPC-over-stdio server.** MCP's stdio
transport is line-delimited JSON-RPC 2.0; implement `initialize` / `tools/list` / `tools/call` with
`json` + `sys.stdin`/`stdout` only. This keeps even the optional extra dependency-free — do NOT take the
official `mcp` SDK. Ship it as `pip install repo-librarian[mcp]` only if any extra is ever needed;
ideally the extra is empty and the server is pure stdlib.

**Requirements:**
- Tools: `query` (wraps `librarian query` filters → the pointer+freshness rows) and `why` (wraps the
  provenance chain). Every answer carries freshness metadata (last_verified, stale flag) — R5, the
  "RAG-that-lies" guard: never return a fact without its age.
- Reads `catalog.json` / `provenance.json`; never shells into an LLM. Deterministic.
- Entry point e.g. `librarian mcp` (stdio server) or a `python -m librarian.mcp` module.
- Tests: drive the JSON-RPC handshake + a `tools/call` over an in-memory pipe; assert freshness fields.
- Accounting mode for the benchmark: tokens for "answer N questions" on-demand vs always-load catalog.

## E4 — Librarian PR bot

**What:** turn a dream/enrich branch into a reviewable PR; approval = checking boxes in the PR UI
(each box = one proposal id). The team-scale path for the in-chat `apply` approval flow.

**Decided implementation:** **`gh` CLI, manual `librarian pr`, default off.** Shell out to the installed
GitHub CLI (`gh pr create …`) — no token handling in our code, no third-party GitHub lib, degrades
gracefully (exit 0 with a note) if `gh` is absent. A human runs `librarian pr` to open the PR from the
current dream/enrich branch. NOT urllib+token, NOT an auto-on-push GitHub Action.

**Requirements:**
- `librarian pr [--title …] [--dry-run]`: reads `_index/proposals.json`, renders the PR body as a
  checklist (one `- [ ]` per proposal id + type + rationale + target), runs `gh pr create` from the
  current branch. Never on `main`.
- Round-trip note: how a checked box maps back to `librarian apply --only <id>` is a follow-up
  (parsing PR review state is out of scope for v1 — the checklist is the human's apply worklist).
- Reversible/no-op if not in a git repo or `gh` missing. Default off / never automatic.
- Tests: `--dry-run` renders the checklist deterministically; skips cleanly without `gh`.

## Housekeeping (not blocked on the above)

- **Regenerate the demo golden for `provenance.json`** — `verify` now emits it; the demo `_index/` +
  `tests/golden/` don't yet include it. Regenerate deliberately (recipe in `tests/test_golden.py`).
- **Enrich-loop demo** — add a planted gap + a source to the demo repo so the README can show the
  active-analyst loop, not just verify catching drift.
- **PyPI trusted publishing** — set it up at pypi.org, then flip repo var `PYPI_PUBLISH=true`.
