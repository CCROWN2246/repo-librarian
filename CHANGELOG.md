# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning follows SemVer.

## [Unreleased]

## [0.4.1] - 2026-07-15

### Hardened — adversarial-input robustness (Phase B fuzzing)
A synthetic-corpus fuzzer (`benchmarks/fuzz.py`) + a permanent invariant suite
(`tests/test_invariants.py`, `tests/test_fuzz.py`) now assert that **no command crashes on
any corpus** (empty / malformed frontmatter / malformed TOML / corrupt or valid-but-wrong-type
sidecars / unicode / binary / dangling references / huge), that the exit-code contract
(0/1/2) holds uniformly, that `index`/`dream`/`verify` are deterministic, and that untrusted
paths stay inside the repo. The fuzzer surfaced four defects, all fixed:
- **Path containment.** `librarian archive` (and a proposal `to`/target path, and `ingest --dest`)
  could take a `..` path that escaped the repo root and read/move/rewrite a file **outside** the
  repository. All untrusted path inputs are now confined to the repo root (clean exit 2 otherwise).
- **Fail loud on malformed proposals.** A `fix` proposal whose `action.replace` wasn't an object
  crashed `propose` with an `AttributeError` traceback (id-computation ran before validation, and
  there was no `fix` validation branch at all). It now validates the shape and fails loud.
- **Binary docs.** Archiving a non-UTF8 `.md` crashed with a `UnicodeDecodeError`; it now moves the
  file verbatim (byte-preserving), and the shared doc reader tolerates non-UTF8 input.
- **Non-dict JSON sidecars.** A state file (`catalog.json`, `baselines.json`, `provenance.json`,
  `.last_dream`, the apply-log, the scaffold manifest) containing valid JSON that wasn't the expected
  object (`null` / `[]` / `42` / `"s"`) slipped past the JSONDecodeError guard and crashed several
  commands on `.get()`. The loaders now treat a wrong-typed sidecar as empty.

## [0.4.0] - 2026-07-15

### Fixed & hardened — round 3 (retrieval honesty + apply/verify integrity + scaffold self-heal)
- **Search no longer returns a false "no matches."** A quoted multi-word query
  (`librarian search "pricing tiers"`) was matched as one literal substring and found nothing; it now
  tokenizes on whitespace, folds a trailing `s` (`shipments`↔`shipment`), and — only when the fast
  metadata pass returns zero hits — falls back to re-reading doc **bodies** (two-tier), naming the closest
  partial match. The body pass is capped for large corpora (skips with a "use grep" note rather than a
  partial read that could miss a real match).
- **Ingest is safer and self-checks.** Fixed `_inbox/_inbox/` path-doubling (basename-normalized before
  the refusal check, so the message and the filed path agree — and a stray path can never delete a repo
  file); replaced the "no TTY" jargon with a plain-English refusal; corrected the "--dest is a directory"
  error; `--dry-run` now previews the defaults + conflict-check consequences. New repeatable `--read-when`
  flag stamps routing phrases at intake, and **ingest itself now runs a conflict-check** and prints
  overlapping docs (you decide — nothing is auto-quarantined).
- **Apply/merge integrity.** A merge's `carry_over` is now **structured** (`read_when`/`tags` union into
  frontmatter, deduped; body text appends to the body) with per-target idempotency (re-apply is a true
  no-op, never a false-STALE), propose-time validation (malformed → error, not silent corruption), and an
  external-change guard on the canonical. A paired `enrich_create` + `add_check` **no longer orphans the
  check** regardless of apply order (intra-batch creation awareness). The apply-log is now reconciled on
  read, so a crash between the log write and the state writeback never lets `apply --all` re-run done work
  (or re-orphan a pair); re-proposing an already-applied id warns; an archive-dest clash suggests a free
  numbered suffix.
- **Verify tells the truth.** `verify --accept` on a hand-written `.librarian.toml` check now exits 1 with
  an honest "NO CHANGE MADE" and the `expect = "..."` line to paste (the tool never writes your TOML),
  instead of a silent false success. Accepting a **generated** check clears its DRIFT immediately (no
  lingering stale-failing signal). STALENESS.md shows a `· N failing check(s)` count (only when > 0), and
  the verify summary glosses `DRIFT (= failing check)`.
- **Scanner / enrich.** `skip_files` now supports globs (`["FEEDBACK*.md"]`, case-sensitive for
  determinism); enrichment gaps carry a `domain` inferred from the path.
- **Scaffold self-heal.** `status` and `doctor` now nudge `librarian init --upgrade` when the scaffolded
  protocol/glue predates the installed tool (reads the recorded `.scaffold.json` version) — retiring a
  class of stale-template false feedback.

### Added — Phase 2 (enrichment + trust-ladder + producer wiring)
- **B5 enrichment + E2 auto-checks — the active-analyst loop.** `librarian enrich` is the deterministic
  gap worklist: it surfaces **uncovered code/data files** and **dream-confirmed absence gaps**
  (`resolve_absence` with `verdict: confirmed_gap`) plus the `[verify.sources]` available to fill them.
  `/librarian-enrich` is the generative half: for each gap it queries a live source and drafts a
  **provisional, source-verified** doc as an `enrich_create` proposal paired with an `add_check` (E2) that
  re-verifies the fact on every `librarian verify`. Accuracy wall, enforced in the schema — an
  `enrich_create` is **rejected** unless it carries non-empty `provenance.evidence` (the **empty-source
  guard**, R1: a source that returned nothing can never justify drafting "we have zero X"). Provisional
  docs are quarantined: flagged in STALENESS.md as "un-audited enrichment" once older than
  `[enrich].provisional_ttl_days`.
- **`librarian apply --auto`** — the trust-ladder consumer (B4). Applies proposals whose configured
  `[automation]` tier is `branch`/`commit`, reading the per-type tier from config as the pre-authorization
  (no per-item approval). Default is every type `off`, so `--auto` is a safe no-op until a type is opted
  in. The generative/irreversible/archive risk caps still bind — config can't lift a `fix` above `branch`.
- **`librarian propose`** — the dream producer. Reads a partial proposal (type / target paths + optional
  line / action / rationale) as JSON on stdin or a file; the CLI fills each target's `base_sha256` (hashing
  the file as it is now), computes the id, applies the risk defaults, validates, and upserts into
  `_index/proposals.json` (dedup by id, so a re-draft replaces cleanly). The agent supplies judgment; the
  CLI supplies determinism — no hand-computed hashes or ids.
- **`/librarian-dream` now emits proposal objects**, not MORNING-REPORT prose: each judgment becomes a
  `librarian propose` call, `proposals.json` is the machine-applyable artifact the human approves and
  `librarian apply` consumes, and the report is its human-readable companion. This turns the whole
  Phase-0/1 spine live end-to-end (dream → propose → approve → apply → reindex → mark-done).

### Added — Phase 1 (packaged commands) + provenance query
- **B1 work-resumption nudge** — a throttled `UserPromptSubmit` hook (`.claude/hooks/librarian-prompt.sh`)
  that nudges when you resume work, not just at cold session start. `librarian status --hook --throttle`
  fast-paths on `_index/.last_nudge` and early-exits **before** loading catalog.json when inside the
  work-block (`[hooks].nudge_throttle_minutes`, default 240; `0` disables). `init` now wires both
  SessionStart and UserPromptSubmit hooks.
- **B3 `librarian archive <path>`** — retire a doc: frontmatter status → archived, move into the archive
  dir (excluded from the scan), reindex. Atomic, reversible (git mv back + un-flip), never deletes.
  Shares its mover with the archive proposal handler.
- **B3 retirement-detection dream job** — a fifth worklist bucket, `retirement_candidates`: docs an author
  already marked with a terminal status (retired/superseded/shipped/…) but that still live in the docs
  tree. Positive-evidence, **propose-only**; the dream agent turns them into reversible archive proposals.
- **E3 `librarian why [terms]`** — prints the provenance chain for a verified fact (the command, source,
  extracted value, timestamp, and backing doc) from `_index/provenance.json`. Pure stdlib.

### Added — Phase 0 (the automation spine)
- **Proposal objects** (`_index/proposals.json`, `schema_version` 1) — a versioned, machine-applyable
  maintenance/generation unit that replaces the dream cycle's hand-retyped prose. Eight types
  (`fix`/`ack`/`archive`/`merge`/`set_read_when`/`resolve_absence`/`enrich_create`/`add_check`); each
  carries a per-file `base_sha256` staleness guard and a content-derived `id` that dedupes re-drafts.
  This is a **compatibility surface** — treat like STALENESS.md line 3.
- **`librarian apply [--all | --only <id>…] [--tier] [--dry-run]`** — executes proposals against the
  working tree: per-target staleness gate (refuses if any file changed since draft), an idempotent
  fix truth-table (run-twice = zero diff), a `_index/apply-log.jsonl` audit trail, a single reindex,
  and `dream --mark-done` **only** when the post-apply worklist is empty. Never touches main, never
  deletes (archive/merge = move + status flip).
- **`librarian query [terms] [--domain/--status/--tag/--id/--path] [--json]`** — pure-stdlib catalog
  retrieval returning pointers + freshness (path, status, `last_verified`, stale flag), not bodies.
  The token-cost-flip primitive the Phase-3 MCP server will wrap.
- **Provenance persistence** (`_index/provenance.json`, committed, sorted-keys) — `verify` now records
  fact → command/source/value/timestamp per non-SKIP check (merges across filtered runs; prunes
  orphans). Feeds the future `librarian why`, MCP sourced answers, and enrichment labels.
- **`[automation]` trust-ladder config** (per-type tier, default `off`/propose-only; strict validation)
  and **`[enrich].provisional_ttl_days`**. Generative/irreversible/archive proposals are hard-capped at
  `branch` regardless of config; nothing reaches main via tier alone.
- **Machine-generated verify checks** — `add_check` proposals write `_index/generated-checks.json`
  (stdlib JSON; `tomllib` is read-only); `config.load` merges the sidecar after the hand-written TOML
  checks, with human checks winning on id collision.

### Changed
- **B6 vocab cleanup** — dream branches are now `librarian/dream-<date>` (was `kb/dream-`) and the
  report commit is `chore(librarian):` (was `chore(kb):`). The `KB-CONTRADICTED`/`KB-ACK` conflict
  markers are unchanged — they are an on-disk data format in consuming repos' doc bodies.

## [0.3.0] - 2026-07-07

### Changed
- **Slash commands renamed to the product** — the scaffolded Claude Code commands are now
  **`/librarian`** (refresh: index + verify; was `/kb`) and **`/librarian-dream`** (the dream
  cycle; was `/kb-dream`). The `kb` prefix was heritage from the pre-productization "knowledge
  base" era. `librarian init --upgrade` installs the new command files; delete any stale
  `.claude/commands/kb*.md` by hand.

## [0.2.0] - 2026-07-07

### Added
- **The dream cycle** — `librarian dream` builds a deterministic maintenance worklist
  (OPEN conflicts, duplicate-doc merge candidates, weak/empty `read_when`, absence-claims)
  for zero tokens, and the scaffolded `/librarian-dream` command drafts fixes for them
  **propose-only on a branch** (a `MORNING-REPORT.md`; never touches main, never
  auto-applies). A delta gate (`--mark-done` + `_index/.last_dream`) means most runs are
  no-ops; `librarian status` nudges only when the worklist is due. Config: `[dream]`
  `nudge_after_days` (default 14, 0=off) + `merge_similarity` (default 0.6). See
  [docs/dream.md](docs/dream.md).
- `librarian suggest [--write] [--domain X]` — auto-drafts `[[artifact]]` registry entries
  for every uncovered code/data file by harvesting its self-description: SQL leading
  comments, Python docstrings, shell header comments, a notebook's first markdown
  heading, CSV header rows (columns + row count), JSON top-level keys. Drafts land with
  `read_when = []  # TODO` so routing phrases still get a human/agent pass.
- Data files are now watched by default: `covered_ext` gains `.csv`, `.tsv`,
  `.parquet`, `.xlsx`.
- Catalog token-cost guard: `librarian status` now shows an estimated always-load
  cost for CATALOG.md and warns past `[index].catalog_token_budget` (default 12k
  tokens ≈ ~450 entries; 0 disables).
- `benchmarks/`: synthetic corpus generator with planted failure modes, golden
  tasks, and a running results log (`RESULTS.md`) including the honest finding:
  measured ~2× session-token premium vs a bare frontier agent, bought back as
  correctness (8/8 vs 7/8; live-verified answers; full provenance).

## [0.1.0] - 2026-07-02

### Added
- Core catalog engine: frontmatter parsing (with warning surfacing instead of silent
  drops), artifact registry (`librarian-artifacts.toml`), generated `_index/CATALOG.md`
  + `STALENESS.md` + `catalog.json`.
- Verify engine: declarative command-runner checks (`assert`/`track`), named sources
  with `{arg}` templates and skip probes, extractors (scalar, regex, json path, lines,
  column presence, exit code), `_index/baselines.json`, the exit-3 SKIP contract,
  `--update-baselines`, `--stamp`.
- CLI: `init` (idempotent scaffold with managed marker blocks, `--upgrade`,
  `--uninstall`), `index` (`--check` CI gate), `verify`, `status` (`--hook`), `search`,
  `backfill`, `ingest`, `doctor`. Uniform exit codes, `--json` everywhere.
- Agent glue: AGENTS.md managed block, Claude Code `/librarian` command + SessionStart
  freshness nudge, tracked `.githooks/pre-commit`.
- Knowledge protocol (five reflexes incl. the absence-claim guard), NAVIGATOR template,
  intake (`_inbox/`) and archive (`_archive/`) conventions.
- Citybikes demo corpus (offline verify via stdlib sqlite), 123-test suite, CI matrix
  (3 OS × py3.11–3.13), release workflow.
