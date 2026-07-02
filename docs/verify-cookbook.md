# Verify cookbook

One recipe per backend. Every recipe is a complete, paste-able block for
`.librarian.toml`. Reminders that apply to all of them:

- `kind = "assert"` + `expect` → mismatch is **DRIFT**, run fails (exit 1).
- `kind = "track"` → compared to `_index/baselines.json`; a change **warns** (accept
  with `librarian verify --update-baselines`).
- `doc` is the repo-relative doc holding the asserted fact — a DRIFT names it.
- Skip contract: `skip_if_unset` (env vars) or `skip_unless` (probe command) on a
  source or a check, **or the command exiting 3**, all report SKIP and keep the run
  green — checks activate automatically once the source is reachable.
- Commands run via `/bin/sh -c` from the repo root, with `{arg}` shell-quoted into the
  source's `command` template.

## sqlite (the demo — fully offline)

```toml
[verify.sources.demo-db]
command = "python3 db/query.py {arg}"     # stdlib sqlite3 against a seeded :memory: db

[[verify.checks]]
id = "active_station_count"
kind = "assert"
doc = "docs/schema.md"
source = "demo-db"
arg = "SELECT count(*) FROM stations WHERE active = 1"
expect = "17"
```

## PostgreSQL (psql)

```toml
[verify.sources.pg]
command = "psql \"$DATABASE_URL\" -tA -c {arg}"    # -tA: tuples-only, unaligned
skip_if_unset = ["DATABASE_URL"]

[[verify.checks]]
id = "orders_no_email_column"
kind = "assert"
doc = "docs/schema.md"
source = "pg"
arg = "SELECT count(*) FROM information_schema.columns WHERE table_name='orders' AND column_name='email'"
expect = "0"

[[verify.checks]]
id = "customer_count"
kind = "track"                                     # legitimately grows
doc = "docs/overview.md"
source = "pg"
arg = "SELECT count(*) FROM customers"
```

## MySQL / MariaDB

```toml
[verify.sources.mysql]
command = "mysql --defaults-extra-file=$MYSQL_CNF -N -B -e {arg}"   # -N no header, -B tab-separated
skip_if_unset = ["MYSQL_CNF"]

[[verify.checks]]
id = "shift_invitation_has_accepted_at"
kind = "assert"
doc = "docs/raw-db-schema.md"
source = "mysql"
arg = "SELECT count(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='shift_invitation' AND column_name='accepted_at'"
extract = "scalar"
expect = "1"
```

## AWS Athena

Athena is async (start → poll → fetch), so wrap it in a repo-local runner script and
point the source at that. The script should exit **3** when credentials aren't
configured, so the checks SKIP instead of ERROR on machines without AWS access.

```toml
[verify.sources.athena]
command = "python3 scripts/athena_query.py {arg}"
skip_unless = "aws sts get-caller-identity"        # probed once per run, cached
timeout = 180

[[verify.checks]]
id = "staff_summary_no_user_id"
kind = "assert"
doc = "docs/athena-schema.md"
source = "athena"
arg = "SHOW COLUMNS IN staff_summary_report"
extract = "column_absent:user_id"                  # first token of any line = column name
expect = "absent"
```

## HTTP API (curl + jq)

```toml
[verify.sources.api]
command = "curl -sf --max-time 20 {arg}"
skip_unless = "curl -sf --max-time 5 https://api.example.com/health"

[[verify.checks]]
id = "api_regions_count"
kind = "track"
doc = "docs/api-notes.md"
source = "api"
arg = "https://api.example.com/v2/regions"
extract = "json:regions.length"                    # no jq needed — json: is built in
```

## Grep a schema/DDL file (the cheapest useful check)

```toml
[[verify.checks]]
id = "ddl_orders_has_no_email"
kind = "assert"
doc = "docs/schema.md"
cmd = "grep -c 'email' sql/schema.sql || true"     # `|| true`: grep exits 1 on zero matches
extract = "scalar"
expect = "0"
```

## Test-suite exit code (pytest, anything)

```toml
[[verify.checks]]
id = "contract_tests_pass"
kind = "assert"
doc = "docs/data-contracts.md"
cmd = "python3 -m pytest -q tests/contracts >/dev/null 2>&1; echo $?"
extract = "scalar"
expect = "0"
```

(Or `extract = "exit_code"` directly on the test command — with that extractor a
nonzero exit is a value, not an error.)

## dbt

```toml
[verify.sources.dbt]
command = "dbt test --quiet --select {arg} >/dev/null 2>&1; echo $?"
skip_unless = "dbt --version"

[[verify.checks]]
id = "dim_customers_contract"
kind = "assert"
doc = "docs/models.md"
source = "dbt"
arg = "dim_customers"
expect = "0"
```

## Notebook executes cleanly

```toml
[[verify.checks]]
id = "utilization_notebook_runs"
kind = "assert"
doc = "docs/analyses.md"
cmd = "jupyter nbconvert --to notebook --execute --stdout notebooks/utilization.ipynb >/dev/null 2>&1; echo $?"
expect = "0"
timeout = 300
```

## Layered sources (raw DB vs warehouse)

When the same fact must be checked at two pipeline layers, make two sources and two
checks — a fact's truth is layer-qualified:

```toml
[verify.sources.raw-db]     # the OLTP source of truth
command = "mysql --defaults-extra-file=$RAW_CNF -N -B -e {arg}"
skip_if_unset = ["RAW_CNF"]

[verify.sources.warehouse]  # the curated copy dashboards read
command = "psql \"$WAREHOUSE_URL\" -tA -c {arg}"
skip_if_unset = ["WAREHOUSE_URL"]
```

## Extractor reference

| `extract =` | Yields |
|---|---|
| `scalar` (default) | last cell (tab-split) of the last non-empty line |
| `regex:<pattern>` | first capture group of the first match (`<no-match>` if none) |
| `json:<path>` | dotted path with `[n]` indexes; `.length` for array length |
| `lines` | count of non-empty lines |
| `column_present:<name>` / `column_absent:<name>` | `present`/`absent` — name = first token of any line |
| `exit_code` | the command's exit code (nonzero not treated as an error) |
