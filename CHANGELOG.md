# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning follows SemVer.

## [Unreleased]

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
