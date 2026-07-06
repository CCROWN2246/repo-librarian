# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning follows SemVer.

## [Unreleased]

### Added
- `librarian suggest [--write] [--domain X]` — auto-drafts `[[artifact]]` registry entries
  for every uncovered code/data file by harvesting its self-description: SQL leading
  comments, Python docstrings, shell header comments, a notebook's first markdown
  heading, CSV header rows (columns + row count), JSON top-level keys. Drafts land with
  `read_when = []  # TODO` so routing phrases still get a human/agent pass.
- Data files are now watched by default: `covered_ext` gains `.csv`, `.tsv`,
  `.parquet`, `.xlsx`.

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
- Agent glue: AGENTS.md managed block, Claude Code `/kb` command + SessionStart
  freshness nudge, tracked `.githooks/pre-commit`.
- Knowledge protocol (five reflexes incl. the absence-claim guard), NAVIGATOR template,
  intake (`_inbox/`) and archive (`_archive/`) conventions.
- Citybikes demo corpus (offline verify via stdlib sqlite), 123-test suite, CI matrix
  (3 OS × py3.11–3.13), release workflow.
