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

## V — "Wire verify to your data" onboarding (CSVs / a read-only DB / a folder of files)

**Status of the engine (verified 2026-07-13):** the mechanism is CAPABLE today. A `[verify.sources]`
entry is any shell command; extractors cover `scalar` (a query/cell value), `lines` (row count),
`json:<path>` (an API/`jq` field), `regex:`, and `column_present:`/`column_absent:` (schema drift). Read-only
DBs work through the user's `psql`/`sqlite3`/`bq` CLI; CSVs through `awk`/`head`/`wc`. The `skip_unless`
probe auto-skips a check when the source isn't reachable. **What's missing is the UX to reach that** — so a
user handed "a folder of CSVs" or "a read-only DB" cannot get to the pitched experience without hand-writing
TOML, knowing the `extract` spec syntax (currently only in `extractors.py`'s docstring), and seeding each
`expect` by hand. `suggest` drafts *catalog* entries, NOT verify checks. Close this before beta.

**Checklist (priority order):**
- [x] **V1 — the guide + recipes** ✅ **DONE (2026-07-13):** shipped as `docs/verify-recipes.md` (linked
  from the README) — mental model, the `extract` spec table (promoted out of the code docstring), and
  drop-in recipes for a folder of CSVs (row/distinct/column-presence), read-only SQLite, read-only Postgres
  (with the SKIP-until-connected DSN pattern), an HTTP API `json:` field, and a one-off `cmd` check.
- [ ] **V2 — `librarian add-check`:** guided single wiring — run the command once, seed `expect` from the
  live value behind a confirm gate.
- [ ] **V3 — `librarian connect <dir>`:** the "point it at a folder of CSVs and it drafts a check per file"
  bulk story, riding the propose→apply spine you already built.
- [ ] **V4 — extractor conveniences (`distinct`) + a data-side coverage nudge** ("you have data files no
  check guards").
- [ ] **V5 — read-only DB safety pattern** (SELECT-only role, `skip_unless` as the reachability probe;
  verify only ever reads).

**V1 — "Wire verify to your data" guide + copy-paste recipes.** A user-facing doc (and README section)
that explains sources/checks, `assert` vs `track`, and the `extract` spec in plain language, with drop-in
recipes for: a CSV row count / distinct count / column-presence; a SQLite scalar; a Postgres query
(read-only role); an HTTP API `json:` field. Promote the `extract` spec out of the code docstring into
real docs. This alone unblocks a motivated user.

**V2 — `librarian add-check` (guided single wiring).** A command that turns raw-TOML authoring into a
ritual: given a command (or a CSV path + an intent like `rows`/`distinct <col>`/`columns`), run it ONCE,
show the live value, and write the `[verify.sources]` + `[[verify.checks]]`. For `assert`, seed `expect`
from the live value behind a "confirm this is the correct value" gate; for `track`, auto-baseline. Writes
to the `generated-checks.json` sidecar (already the machine surface) or prints TOML for a hand-owned source.
Pairs with the existing `verify --accept`.

**V3 — `librarian connect <dir>` / extend `suggest` to draft verify checks (the bulk story).** Scan a
folder of data files (CSV/TSV/parquet-via-CLI) or a list of SQL files and DRAFT one check per file as
`add_check` proposals (row-count via `lines`, or column-presence for schema) the user accepts through the
normal propose→apply spine. This is what makes "connect a folder of CSVs and it just works" a single guided
step instead of N hand-edits. Reuses the proposal objects + `librarian apply` already built.

**V4 — Extractor coverage + a data-side coverage nudge.** Add the high-value conveniences that today need
shell gymnastics (`distinct:<col>`, a simple `count_where`), or document the shell recipes explicitly.
Extend the correctness-coverage scan (currently doc-side) so `doctor`/STALENESS also nudges: "you have data
files (`data/*.csv`, a `*.db`) that no verify check guards" — pulling the user toward wiring, the same way
the doc coverage-gap surfaces an unchecked claim.

**V5 — Read-only DB safety pattern.** Document (and where possible guard) that the source command should
use a **read-only role / SELECT-only** — the tool shells out and cannot enforce it, so make the recipe
default to a read-only connection string and lean on `skip_unless` as the "is the DB reachable" probe. State
plainly that verify never writes to the source; it only reads.

**Why this is pre-beta, not Phase 3:** the pitch to testers is "point a one-line command at your source of
truth and it flags drift." That's honest about the *engine* but not the *onboarding*. V1 (docs) is cheap and
should land before the beta post; V2/V3 are the difference between "capable" and "delightful."

## D4 — Overnight / async dream automation (+ the "dream" rename decision)

**What:** decide (and then build) how the dream cycle runs *unattended*, and resolve the naming that
depends on that decision. Today `/librarian-dream` is fully **synchronous and in-chat** — the user runs
it and watches it happen, start to finish.

**Why (flagged twice, round 1 + round 2):** the name "dream" implies something *passive / overnight /
in the background*, but nothing about the current flow is. The mismatch is a **symptom of an unmade
product decision**, not a naming bug: is this ritual eventually async, or forever a synchronous cleanup
you run and watch? Renaming before answering that would pre-commit the answer by cosmetics. A "morning
report" only delivers value if it's actually *waiting* in the morning — today it's a manual command.

**The fork (decide first, in a design session):**
- **(a) Make it genuinely async.** A scheduled/background job drafts proposals while the user is away
  (propose-only, never auto-apply beyond the trust-ladder cap), so a real report is waiting at session
  start. Then "dream" is *accurate* and stays.
- **(b) Keep it synchronous and rename.** Retire the sleep/dream metaphor for an active-ritual name
  (e.g. `/librarian-sweep`, `/librarian-tidy`) with a dual-alias for back-compat. Cheap while the
  consumer count is ~1.

**Design considerations for (a):**
- Overnight trigger *without the laptop on* — cron on a server / CI schedule / a hosted runner; the
  local hooks can't fire when the machine is asleep. Ties into the same scheduling story as a future
  nightly `verify`.
- **Resumed-session detection:** when a new report was generated while away, the SessionStart greeting
  should notice it and surface "a dream report is waiting" (a new `_index/` artifact + a freshness check),
  distinct from the live `status --hook` nudge.
- **Keep the manual `/librarian-dream` as the fallback** — async is additive, never the only path.
- Propose-only invariant holds: an unattended run drafts to `proposals.json`, it does not apply.

**Decision owner:** Chris, in a Phase-3 design session. Parked deliberately from the round-2 hardening
batch (FEEDBACK2 marks it out-of-scope for that round). The in-chat / apply-on-current-branch model
already solved the *solo* review pain; this is the team/scheduling story on top.

## Housekeeping (not blocked on the above)

- **Regenerate the demo golden for `provenance.json`** — `verify` now emits it; the demo `_index/` +
  `tests/golden/` don't yet include it. Regenerate deliberately (recipe in `tests/test_golden.py`).
- **Enrich-loop demo** — add a planted gap + a source to the demo repo so the README can show the
  active-analyst loop, not just verify catching drift.
- **PyPI trusted publishing — DONE.** Configured at pypi.org, repo var `PYPI_PUBLISH=true`, `repo-librarian`
  v0.3.0 is live (`pipx install repo-librarian` works). **Real pre-beta step:** cut a release of the
  round-2-hardened code — it's all unreleased on `librarian/phase-0` (PyPI still serves v0.3.0). After
  round 3: bump version + CHANGELOG, merge phase-0 → main, tag `vX.Y.Z` → `release.yml` auto-publishes the
  hardened build. Do NOT run the beta on v0.3.0 (it predates every round-2 fix).
