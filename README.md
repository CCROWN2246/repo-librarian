# repo-librarian

[![ci](https://github.com/CCROWN2246/repo-librarian/actions/workflows/ci.yml/badge.svg)](https://github.com/CCROWN2246/repo-librarian/actions/workflows/ci.yml)

> A card catalog and a fact-checker for your repo's knowledge — so your coding agent
> reads 2 docs instead of 200, and never asserts a stale number.

Zero runtime dependencies. No embeddings, no vector DB, no server. Deterministic,
git-native, auditable — if you can read a markdown table, you can audit it.

```console
$ pipx install repo-librarian     # or: uvx repo-librarian, pip install repo-librarian
```

## The problem

An information-rich repo — docs, SQL, notebooks, data exports, meeting transcripts — is
an enterprise brain your coding agent can't use well. It either reads everything (a
token bonfire) or greps (which finds the doc that *mentions* a term most, not the one
that's *authoritative* for it). And worst of all: it confidently repeats whatever the
docs say, however stale.

## The drift story

The project this tool was extracted from had docs saying **164 facilities**. Production
said **181**. That number had been asserted in three deliverables before anyone noticed.
`librarian verify` turns each such fact into a check against its live source — the
drift became a red line in CI instead of a wrong number in an exec deck.

## Not a search brain or an auto-wiki

gbrain and LLM wikis make your docs *findable*; repo-librarian makes them *trustworthy* —
it fact-checks each documented claim against its live source and flags the moment one
drifts from reality, deterministically, no embeddings. It's a different job, not a
competitor: point a RAG index *at* a corpus the librarian keeps honest.

## How it works — three moves

1. **Frontmatter on every doc** — `domain`, `read_when` (task phrases: the routing
   signal), `last_verified`/`recheck` (the freshness gate), `status`, and an
   `authority` tier (`verified > curated > unverified`). Non-markdown artifacts (SQL,
   notebooks, exports) get an entry in `librarian-artifacts.toml` instead.
2. **A generated card catalog** — `librarian index` writes `_index/CATALOG.md` (the
   inventory, by domain), `_index/STALENESS.md` (what needs attention: flagged docs,
   open conflicts, coverage gaps, intake queue), and `_index/catalog.json` (the machine
   surface for hooks and `librarian search`).
3. **An agent protocol** — `librarian init` scaffolds `AGENTS.md` (read by Cursor,
   Copilot, Codex, …) and Claude Code glue (`/librarian` command, session-start freshness
   nudge): route via the catalog, never read the whole corpus, freshness-gate facts,
   capture discoveries back into docs, and resolve conflicts **by authority tier, never
   by recency** — a contradicted claim gets quarantined in place, not silently trusted
   or deleted.

And the piece that makes the `verified` tier real: **`librarian verify`** runs
declarative command-runner checks from `.librarian.toml` — any shell command (psql,
mysql, aws athena, curl + jq, grep, pytest…), an extractor, and an expected value
(`assert`, drift fails the run) or tracked baseline (`track`, changes warn).

## 60-second quickstart

```console
$ cd your-big-repo
$ librarian init                       # config + protocol + agent glue + hooks
$ librarian backfill docs/ --write     # skeleton frontmatter onto existing docs
$ librarian index                      # generate _index/CATALOG.md + STALENESS.md
$ $EDITOR .librarian.toml              # add your first [[verify.checks]]
$ librarian verify                     # facts vs live sources
$ git config core.hooksPath .githooks  # catalog refresh on every commit
```

Or take the guided tour in the batteries-included demo (a planted drifting fact, a
stale baseline, a quarantined conflict, an intake queue — all offline):

```console
$ cd examples/demo-repo && librarian verify
[PASS]    demo-db    stations_no_region_column      expect=0 live=0
[PASS]    demo-db    active_station_count           expect=17 live=17
[DRIFT]   demo-db    min_dock_count_is_20           expect=20 live=15
          -> update: docs/schema.md
[CHANGED] demo-db    total_rides                    baseline=1210 live=1284
          -> update: docs/overview.md
```

## Commands

| Command | Does |
|---|---|
| `librarian init` | Scaffold config, protocol, agent glue, hooks (`--upgrade` / `--uninstall`; idempotent) |
| `librarian index` | Rebuild the catalog (`--check` gates CI on `[index].fail_on`) |
| `librarian verify` | Fact-check docs vs live sources (`--update-baselines`, `--stamp`, `--json`) |
| `librarian status` | One-screen health summary (`--hook` powers the session nudge) |
| `librarian search "task phrase"` | Route by `read_when`/`tags`/`title` — cheaper and truer than grep |
| `librarian backfill DIR --write` | Bulk-stamp skeleton frontmatter onto existing docs |
| `librarian suggest [--write]` | Auto-draft registry entries for uncovered SQL/scripts/notebooks/CSVs (harvests comments, docstrings, headers) |
| `librarian ingest FILE` | Triage an `_inbox/` upload: tier → frontmatter → file it |
| `librarian dream [--json] [--mark-done]` | Build the maintenance worklist (conflicts, dup docs, weak routing); drives the `/librarian-dream` propose-only cycle |
| `librarian doctor` | Sanity-check config, registry, hooks, and verify sources |

Exit codes everywhere: `0` clean · `1` findings (drift / gate / attention) · `2` config
error. Every read command takes `--json`.

## The numbers (measured, warts included)

We benchmarked it the hard way: a 200-doc synthetic company repo with planted failure
modes (stale numbers echoed into fresher-dated docs, a fact that lives in *no* doc,
frontmatter-only provisional flags), answered start-to-finish by identical
frontier-model agents — one with the librarian, one without
([methodology + full log](benchmarks/RESULTS.md)):

| | With librarian | Bare repo |
|---|---|---|
| Task accuracy | **8/8** | 7/8 |
| "What's the current backlog?" (truth in no doc) | **ran the registered check, caught the drifted baseline, quoted live: 93** | refused to quote, never found the live source — no answer |
| Provenance (authority + freshness) cited | every answer | most answers |
| Session tokens | 40.3k | 17.9k |

The honest read: **against a strong agent, this is not a token-saver — it's a
correctness layer with a bounded, amortized cost** (~7.5k tokens of always-load
catalog at 200 files; warned at a configurable budget via `librarian status`). It pays
for itself on any fact whose truth lives outside the docs, any corpus where drift
echoes outnumber the source, and any deliverable where one stale number costs more
than a few thousand tokens. Modern agents grep well; docs don't know when they're
wrong. This fixes the second problem.

## What it is not

Not RAG. Retrieval systems retrieve stale facts *faster*; nothing in a vector index
knows the number is wrong. This is the opposite bet: a small deterministic inventory
the agent reads first, plus checks that keep the facts honest. (More in the
[FAQ](docs/faq.md).)

## Docs

[Quickstart](docs/quickstart.md) · [The protocol](docs/protocol.md) ·
[Verify cookbook](docs/verify-cookbook.md) (psql, mysql, Athena, curl, dbt, pytest…) ·
[Taxonomy guide](docs/taxonomy.md) · [Conflict resolution](docs/conflicts.md) ·
[The dream cycle](docs/dream.md) (overnight/on-nudge maintenance) ·
[Adopting in a large repo](docs/adopting.md) · [NAVIGATOR authoring](docs/navigator-guide.md) ·
[FAQ](docs/faq.md)

## Requirements

Python ≥ 3.11, stdlib only. `verify` shells out via `/bin/sh` (Linux, macOS, WSL,
Git Bash); everything else is pure-Python portable.

## License

MIT
