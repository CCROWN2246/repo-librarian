# CLAUDE.md — repo-librarian (developing the tool itself)

This is the source repo for **repo-librarian**, a card-catalog + fact-checker CLI for
information-rich repos. This file orients an agent (or a returning human) working ON the tool.
It is **not** a librarian install — this repo builds the thing that produces `_index/` elsewhere.

## The one inviolable rule
**Zero runtime dependencies.** stdlib only, Python ≥ 3.11 (uses `tomllib`). Dev-only tools
(`pytest`, `ruff`) are fine as dev-deps; nothing may enter `[project.dependencies]`. This is the
headline selling point — guard it.

## What this tool is (one paragraph)
Frontmatter on `.md` docs + a TOML registry for non-doc artifacts → a generated card catalog
(`_index/CATALOG.md` + `STALENESS.md` + `catalog.json`) an agent reads first instead of the whole
corpus → plus a command-runner `verify` engine that fact-checks doc claims against live sources, a
`suggest` harvester, and a delta-gated propose-only maintenance `dream` cycle. Philosophy:
deterministic, git-native, auditable, **no embeddings** — the opposite bet from RAG. Honest
positioning (measured, in `benchmarks/RESULTS.md`): it is a **correctness layer, not a token-saver**
(~2× session premium bought back as correctness + provenance).

## Architecture (src/librarian/)
- `cli.py` — argparse tree + `cmd_*` dispatch; uniform exit codes (0 clean / 1 findings / 2 error); `--json` on read commands.
- `config.py` — `.librarian.toml` load + strict validation (unknown key = error); the `Config` dataclass is the single source of policy (no module-constant policy).
- `frontmatter.py` — the minimal-YAML parser (warns, never silently drops); `set_field` is format-preserving.
- `catalog.py` (pure engine: `(config, today, artifacts) → CatalogResult`) + `render.py` (writes the 3 outputs; **STALENESS.md line 3 is a compatibility surface** — don't reorder its phrases) + `scanner.py`.
- `registry.py` — `librarian-artifacts.toml` loader with per-entry validation.
- `verify.py` + `extractors.py` — command-runner checks; exit-3 = SKIP contract; baselines in `_index/baselines.json`.
- `dream.py` — deterministic maintenance worklist + delta gate (`is_due`/`mark_done`); `/librarian-dream` is the agent half.
- `suggest.py`, `backfill.py`, `ingest.py`, `scaffold.py` (init/upgrade/uninstall via hash manifest), `doctor.py`, `output.py`.
- `assets/` — everything `init` scaffolds into a consuming repo (protocol, NAVIGATOR template, `.claude/` glue, `.githooks/`, config template). Editing agent behavior = edit these.

## Working conventions
- **Tests:** `python3 -m unittest discover -s tests` (stdlib; runs with no installs). 150+ tests.
  Engine modules stay **pure** (take `(root, config, today)`, return results; I/O lives in cli/render).
  Determinism: `LIBRARIAN_TODAY=YYYY-MM-DD` overrides the clock; run-twice = zero diff.
- **Lint:** `ruff check src tests` + `ruff format --check src tests` (CI runs both; line-length 110).
- **Golden files:** `tests/golden/` + `examples/demo-repo/_index/` must stay in sync with the engine —
  a behavior change that alters output means regenerating both **deliberately** (recipe in
  `tests/test_golden.py`). The demo corpus (offline sqlite `verify`) is the README demo + a fixture.
- **Benchmarks:** `benchmarks/` (synthetic corpus generator + golden tasks). Keep `RESULTS.md` honest.

## Shipping
SemVer. Bump `__version__` in `src/librarian/__init__.py` **and** `pyproject.toml`, move the
`CHANGELOG.md` Unreleased block to a dated version, commit, then `git tag -a vX.Y.Z && git push origin vX.Y.Z`.
`release.yml` builds + drafts a GitHub Release; it publishes to PyPI only when repo variable
`PYPI_PUBLISH=true` (trusted publishing not yet configured). CI must be green on 3 OS × py3.11–3.13
before tagging — Windows and the ruff job have caught things local runs didn't.

## Provenance / gotchas
- Origin: extracted and productized from an internal KB in a separate DropStat/QuickSight repo; that
  repo is now just a *consumer*. Nothing DropStat-specific belongs here — this repo is generic.
- Remote is **SSH** (`git@github.com:CCROWN2246/repo-librarian.git`) because the OAuth token lacks
  the `workflow` scope for pushing `.github/workflows/` over HTTPS.
- CONTRIBUTING.md has the contributor-facing version of the rules above.

_(This repo is the tool itself — it is deliberately not "librarian-ized" with its own catalog install.)_
