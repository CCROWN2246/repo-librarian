# FAQ

## Why not RAG / embeddings / a vector DB?

Different bet entirely. Retrieval optimizes *finding text that looks relevant*;
nothing in a vector index knows the number it retrieves is wrong — a retrieval system
serves stale facts *faster and more confidently*. repo-librarian optimizes the other
two problems:

- **Authority**: `read_when` + `domain` route to the doc that's *authoritative* for a
  topic, not the one that mentions it most (similarity has the same failure mode as
  grep, just fuzzier).
- **Correctness**: `verify` checks facts against live sources; `authority` tiers and
  the conflict quarantine keep contradicted claims from circulating.

It's also deterministic (same input → byte-identical catalog, diffable in PRs),
git-native, auditable (markdown tables, not similarity scores), and zero-infra —
nothing to host, embed, re-index, or pay for. For a corpus of hundreds of docs, an
agent + a card catalog doesn't need semantic search; if yours grows to thousands,
bolt one on *next to* the catalog — the correctness layer still holds.

## Why not just grep?

For distinctive terms, grep is great — the protocol says so. The measured failure is
common terms: in the origin project, the docs that *mentioned* the hot term most were
a narrative KB (28×), a video script (19×), and a user guide (15×); the schema
reference you actually needed wasn't in the top three. Authors encode routing
knowledge in `read_when`; `librarian search` uses it.

## Does it save tokens?

Honestly: no — not against a frontier agent, and we measured it twice so you don't
have to trust vibes. The origin project's spike and our own [benchmark](../benchmarks/RESULTS.md)
agree: capable agents grep well, and a librarian-guided session costs ~2× (the
always-load catalog ≈ 7.5k tokens at 200 files, bounded and warned at a configurable
budget). What that premium buys, measured: the answer no document holds (live verify),
zero stale facts asserted, and authority/freshness provenance on every claim. **The
decisive, validated value is correctness** (the 164-vs-181 drift story in the README).
Adopt it for verify; enjoy the routing.

## How is this different from just having a CLAUDE.md / AGENTS.md?

Instruction files tell an agent how to behave; they don't inventory what exists, track
freshness, or check facts. The protocol *lives* in AGENTS.md — the catalog, staleness
report, and verify engine are the machinery an instruction file can't be.

## Monorepo?

Run one installation per knowledge boundary. `.librarian.toml` discovery walks up
from cwd, so `packages/foo/.librarian.toml` and `packages/bar/.librarian.toml`
coexist; each has its own `_index/`.

## Windows?

Everything except `verify` is pure-Python portable and tested on Windows CI. `verify`
executes checks via `/bin/sh` — use WSL or Git Bash (where `/bin/sh` exists), or keep
verify to CI/WSL and run index/search/status natively.

## Is any of this useful without an AI agent?

Yes — that was a design goal. STALENESS.md is a human triage worklist; verify is a
docs-vs-reality CI gate; CATALOG.md is the new-teammate map; the intake lifecycle is
just good hygiene. The agent is the power user, not the requirement.

## Why is there no PostToolUse / file-watcher auto-reindex?

Measured as low-value in the origin project's spike: indexing is cheap but the catalog
rarely changes mid-session, and the pre-commit hook catches everything at the
boundary that matters. Fewer moving parts wins.

## Why no MCP server?

`catalog.json` + the CLI *are* the machine surface, readable by anything that can run
a command or read a file — no server to run contradicts nothing in an agent's
workflow and keeps the zero-infra promise. If a compelling non-file-reading client
appears, the schema is already stable.
