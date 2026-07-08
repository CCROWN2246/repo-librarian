# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning follows SemVer.

## [Unreleased]

### Added — Phase 2 (producer wiring)
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
