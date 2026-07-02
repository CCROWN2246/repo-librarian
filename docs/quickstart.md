# Quickstart

## Install

```console
$ pipx install repo-librarian        # or uvx / pip. Python >= 3.11, zero deps.
```

## 1. Scaffold

```console
$ cd your-repo
$ librarian init                     # --agent claude|agents-md|both|none (default both)
$ git config core.hooksPath .githooks
```

What init writes (all idempotent — run it twice, zero diff):

| Asset | What it is |
|---|---|
| `.librarian.toml` | Config: paths, scan rules, taxonomy, verify checks. Yours to edit. |
| `librarian-artifacts.toml` | Registry for non-markdown artifacts (SQL, notebooks, data). |
| `KNOWLEDGE_PROTOCOL.md` | The full protocol reference. |
| `AGENTS.md` + `CLAUDE.md` | A managed block (markers) — the condensed protocol agents auto-load. Your other content is untouched. |
| `.claude/` | `/kb` command + a SessionStart nudge (`librarian status --hook`). |
| `.githooks/pre-commit` | Refreshes the catalog on commit; warns on gaps; never blocks. |
| `docs/NAVIGATOR.md` | A task→doc routing template (see the [authoring guide](navigator-guide.md)). |
| `_inbox/`, `_archive/` | Intake staging and doc retirement. |

`librarian init --upgrade` later refreshes any scaffolded asset you haven't modified;
`librarian init --uninstall` removes what's still pristine and keeps your config.

## 2. Onboard your existing docs

```console
$ librarian backfill --write                      # everything, as curated drafts
$ librarian backfill transcripts/ --write \
      --domain transcripts --authority unverified --status reference
```

Skeleton frontmatter is stamped onto every `.md` that lacks it (id from path, title
from the first heading). Then refine per doc: real `domain`, `read_when` task phrases,
`status`, `authority`. Working `_index/STALENESS.md` to zero is the onboarding worklist
— see [Adopting in a large repo](adopting.md).

## 3. Index and route

```console
$ librarian index                    # writes _index/CATALOG.md, STALENESS.md, catalog.json
$ librarian search "write a query"   # route by read_when instead of grepping
```

## 4. Make the `verified` tier real

Add a check to `.librarian.toml` for the first fact you never want to go stale:

```toml
[verify.sources.db]
command = "psql \"$DATABASE_URL\" -tA -c {arg}"
skip_if_unset = ["DATABASE_URL"]     # SKIP cleanly where creds are absent

[[verify.checks]]
id      = "orders_no_email_column"
kind    = "assert"                   # drift fails the run (exit 1)
doc     = "docs/schema.md"           # the doc a DRIFT tells you to fix
source  = "db"
arg     = "SELECT count(*) FROM information_schema.columns WHERE table_name='orders' AND column_name='email'"
extract = "scalar"
expect  = "0"
```

```console
$ librarian verify
$ librarian verify --update-baselines    # accept moved `track` values
$ librarian verify --stamp               # refresh last_verified in passing docs
```

Recipes for mysql, Athena, curl+jq, grep, dbt, pytest, notebooks:
[verify cookbook](verify-cookbook.md). Wire a weekly sweep with
[`examples/workflows/librarian-sweep.yml`](../examples/workflows/librarian-sweep.yml).

## 5. Try the demo first (optional)

`examples/demo-repo/` is a complete miniature installation with a planted drifting
fact, a stale baseline, one open and one acknowledged conflict, and an inbox item —
fully offline. Its README is the tour script.
