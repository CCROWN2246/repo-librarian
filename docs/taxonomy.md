# Taxonomy guide — domains, read_when, status, authority, recheck

Good frontmatter is what makes routing beat grep. Fifteen minutes here pays for itself
on every future session.

## `domain` — pick 4–8 nouns, not folders

`domain` is the axis CATALOG groups by. Keep it small and stable:

- Good: `data-platform`, `dashboard`, `company`, `reference`, `project:checkout-v2`
- Bad: one domain per folder (that's what paths are for), one domain per doc, or
  free-associated synonyms (`data`, `data-eng`, `dataplatform` coexisting).

The `project:<name>` prefix convention works well for time-bounded initiatives — they
group together and are easy to retire wholesale. Routing keys off metadata **on
purpose**: you can reorganize folders without touching the knowledge graph.

Once your set has settled, close it — list it in `[taxonomy].domains` and the indexer
flags strays (a real incident: one doc invented a singleton domain and quietly got its
own catalog section nobody looked at).

## `read_when` — task phrases the agent will *think*, not keywords

This is the single highest-leverage field. Write the phrase an agent (or teammate)
would have in mind when this doc is the right one to open:

```yaml
# The schema reference:
read_when: [write a query, check a column, table shapes]
# The ETL learnings doc:
read_when: [touch etl handlers, why agency numbers are provisional]
```

Why not keywords? Measured in the origin project: for the term every doc mentioned
(`call_off`), grep ranked a narrative doc (28 mentions), a video script (19), and a
user guide (15) above the schema reference you actually needed to write a query.
"Mentions most" ≠ "authoritative for." `read_when` encodes the author's routing
knowledge; `librarian search` matches against it.

## `status` vs `authority` — two different axes

- **status** = lifecycle: `authoritative` (current truth) · `provisional` (real but
  unsettled — flagged) · `draft` (being written — flagged) · `reference` (context, not
  binding) · `retired` / `archived`. Keep to the enum — free-text statuses aren't
  flagged as anything and silently escape triage.
- **authority** = epistemic grounding: `verified` (backed by a passing verify check /
  re-checked against source) · `curated` (written with direct or technical knowledge —
  the default) · `unverified` (transcripts, meeting notes, third-party claims).

A doc can be `status: authoritative` yet `authority: curated` (trusted, but nothing
mechanically re-checks it), or `status: reference` + `authority: unverified` (a
transcript kept for context). Conflicts resolve by **authority**, never recency.

**Provisional propagates**: anything built on a provisional fact is provisional too.
Say so in the dependent doc rather than laundering the uncertainty away.

## `recheck` — cadence by volatility

| recheck | Use for |
|---|---|
| `30d` | volatile or correctness-critical: schemas under active change, counts quoted to stakeholders |
| `60–90d` | normal working docs (the default) |
| `180–365d` | stable references, historical records, transcripts |

Overdue docs (age of `last_verified` > `recheck`) surface in STALENESS. If checking a
doc keeps being toil, that's the signal to turn its facts into `[[verify.checks]]` and
let `--stamp` maintain `last_verified` for you.

## Intake defaults (authority by provenance)

Who produced it, and did they have direct/technical access?

| Provenance | Tier |
|---|---|
| Verified against the live source in this repo | `verified` |
| Written by someone with DB/system access, from that access | `curated` |
| Interview transcript, meeting notes, vendor email, exec vision doc | `unverified` |

`librarian backfill <dir> --authority unverified` stamps a whole folder of transcripts
in one pass; `librarian ingest` asks per file.
