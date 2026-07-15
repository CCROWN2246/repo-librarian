# Wire `verify` to your data — recipes

`librarian verify` is the fact-checker half of the tool. It doesn't connect to anything on its own — you
point each check at a **one-line command that fetches the current truth**, and the tool flags the moment a
documented value stops matching it. This guide is the copy-paste path from "I have some CSVs / a read-only
database" to "my docs fail loud when they drift."

## The mental model (two pieces)

**A source** is a shell command that produces a value. It can be anything on your PATH — `sqlite3`, `psql`,
`curl | jq`, `awk`, `wc`. The tool never talks to a database itself; it shells out to the CLI you already
have. `{arg}` in the command is filled per-check.

```toml
[verify.sources.warehouse]
command = "sqlite3 -readonly data/app.db \"{arg}\""   # {arg} = each check's query
```

**A check** pins one documented claim to a source and says how to compare:

```toml
[[verify.checks]]
id      = "active_customer_count"      # stable name (used by `librarian why`, --accept)
kind    = "assert"                     # assert | track   (see below)
doc     = "docs/data/customers.md"     # the doc this fact lives in — named on drift
source  = "warehouse"                  # which [verify.sources]
arg      = "SELECT count(*) FROM customers WHERE active = 1"
extract = "scalar"                     # how to reduce stdout to a comparable value
expect  = "1843"                       # assert only: the value the doc claims
```

Run `librarian verify`. If the command returns anything other than `1843`, that's **DRIFT** — a red line
naming `docs/data/customers.md` to fix. Fix the doc (not the check), or if the new value is actually
correct, run `librarian verify --accept active_customer_count` to sign off the new number.

### `assert` vs `track`

- **`assert`** — the doc claims a fixed fact ("9 columns", "17 stations"). A mismatch **fails** the run
  (DRIFT). Needs an `expect`.
- **`track`** — a value that *legitimately moves* ("total rides"). A change only **warns** (CHANGED) and
  the new value is recorded as the baseline with `librarian verify --update-baselines`. No `expect`.

## The `extract` spec — reducing stdout to one comparable value

| `extract` | What it returns |
|---|---|
| `scalar` (default) | last cell of the last non-empty line (tab-split) — the usual "one number/string" |
| `lines` | count of non-empty output lines — a **row count** |
| `json:<dotted.path>` | value at a path in JSON stdout; `[n]` indexes, `.length` for array length |
| `regex:<pattern>` | first capture group of the first match |
| `column_present:<name>` | `present`/`absent` — is `<name>` a column? (schema-drift guard) |
| `column_absent:<name>` | the inverse |
| `exit_code` | the command's exit code (nonzero is not treated as an error here) |

## Recipes

### A folder of CSVs
A source that runs an `{arg}` shell snippet against your data dir:

```toml
[verify.sources.csv]
command = "sh -c '{arg}'"
```

```toml
# Row count (kind=track — rows grow over time):
[[verify.checks]]
id = "shipments_rowcount"
kind = "track"
doc = "docs/data/shipments.md"
source = "csv"
arg = "tail -n +2 data/shipments.csv | wc -l"
extract = "scalar"

# Distinct customers (assert — the doc claims a specific number):
[[verify.checks]]
id = "distinct_customers"
kind = "assert"
doc = "docs/data/customers.md"
source = "csv"
arg = "tail -n +2 data/customers.csv | cut -d',' -f2 | sort -u | wc -l"
extract = "scalar"
expect = "412"

# Schema guard — does the header still have a "region" column?
[[verify.checks]]
id = "customers_has_region"
kind = "assert"
doc = "docs/data/customers.md"
source = "csv"
arg = "head -1 data/customers.csv | tr ',' '\\n'"
extract = "column_present:region"
expect = "present"
```

### A read-only SQLite database
```toml
[verify.sources.appdb]
command = "sqlite3 -readonly data/app.db \"{arg}\""
```
```toml
[[verify.checks]]
id = "active_stations"
kind = "assert"
doc = "docs/schema.md"
source = "appdb"
arg = "SELECT count(*) FROM stations WHERE active = 1"
extract = "scalar"
expect = "17"
```

### A read-only Postgres
Use a **read-only role** and connect via `psql`. Gate the whole source on the connection string being set
so it SKIPs cleanly on a machine that isn't connected (see "Connect when ready" below).

```toml
[verify.sources.pg]
command = "psql \"$LIBRARIAN_PG_RO\" -tAc \"{arg}\""   # -tA = tuples-only, unaligned -> clean scalar
skip_if_unset = ["LIBRARIAN_PG_RO"]                    # no DSN set -> SKIP, never ERROR
```
```toml
[[verify.checks]]
id = "facility_count"
kind = "assert"
doc = "docs/ops/facilities.md"
source = "pg"
arg = "SELECT count(*) FROM facilities"
extract = "scalar"
expect = "181"
```

### An HTTP API (JSON)
```toml
[verify.sources.api]
command = "curl -sf https://api.example.com/{arg}"
```
```toml
[[verify.checks]]
id = "published_plan_count"
kind = "assert"
doc = "docs/product/plans.md"
source = "api"
arg = "v1/plans"
extract = "json:data.length"     # array length of $.data
expect = "4"
```

### A one-off command (no reusable source)
A check can carry its own `cmd` instead of a `source`+`arg`:

```toml
[[verify.checks]]
id = "node_major_is_20"
kind = "assert"
doc = "docs/onboarding/dev-setup.md"
cmd = "node --version"
extract = "regex:^v(\\d+)"
expect = "20"
```

## Connect when ready — the SKIP contract

You can commit checks for a source you haven't connected yet; they stay **green** (SKIP) until the source
is reachable, then activate automatically. Two levers:

- `skip_if_unset = ["ENV_VAR", ...]` on a source or check — SKIP while any listed env var is empty (the
  read-only DSN pattern above).
- `skip_unless = "<probe command>"` — SKIP unless the probe exits 0 (e.g. `command -v psql`).
- Any check command that exits with code **3** reports SKIP for that one check.

This is what makes "wire it now, connect the prod replica later" safe: CI stays green, and the check turns
on the day the source is there.

## Read-only, always

`verify` only ever **reads** — it runs your command and compares the output; it never writes to the source.
Keep it that way at the source too: use a **read-only DB role / SELECT-only** connection and a
`-readonly`/`-tA`-style flag. The tool shells out and cannot enforce this for you, so make the recipe
itself read-only.

## The loop

1. Write the `[verify.sources]` + `[[verify.checks]]` (start with `track` if you don't know the value yet).
2. `librarian verify` — see the live value. For a `track` check, `--update-baselines` records it. For an
   `assert`, set `expect` to the value you just saw (or use `--accept <id>` to seed it deliberately).
3. From then on, a drift between the doc and its source is a red line in `librarian verify` and a
   "FAILING check" in the session greeting, dream worklist, and `_index/STALENESS.md`.
