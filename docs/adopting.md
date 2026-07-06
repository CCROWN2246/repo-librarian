# Adopting in a large existing repo

The kit was extracted from a real installation: a QuickSight analytics project with
~36 knowledge docs, ~50 registered artifacts (Athena views, patch scripts, IAM
policies, exports), interview transcripts, and 18 verify checks against a live
warehouse. This is the onboarding path that worked there.

## 1. Init, but don't index the world

`librarian init`, then edit `.librarian.toml` **before** the first index:

- `[scan].skip_dirs`: add build outputs, vendored code, backup folders — anything
  that isn't knowledge.
- `[paths].docs` if knowledge lives under one subtree.

## 2. Backfill per folder, with honest defaults

Don't stamp the whole repo with one identity. Run per folder so the defaults are true:

```console
$ librarian backfill docs/     --write --domain data-platform --status draft
$ librarian backfill notes/    --write --domain company --status reference
$ librarian backfill transcripts/ --write --authority unverified --status reference
```

Everything lands as `draft`/`reference` and shows in STALENESS — that's the design.
**STALENESS.md is your onboarding worklist.** Work it to zero:

1. Refine each doc: real `domain`, `read_when` task phrases (see the
   [taxonomy guide](taxonomy.md)), promote to `authoritative` when reviewed.
2. Register non-markdown artifacts: `librarian suggest --write` auto-drafts an entry
   for every file on the coverage backlog (harvesting SQL comments, docstrings, CSV
   headers), then you review each — set the real domain, write `read_when`, and use
   `desc`/`source_of_truth` for "this is an EXPORT, regenerate don't edit".
3. Triage `_inbox/` with `librarian ingest`.

## 3. Seed verify with the facts that already burned you

Don't aim for coverage; aim for scar tissue. The first checks worth writing are:

- the number a stakeholder deck got wrong once (`track` it),
- the schema assumption that broke a query once (`assert` it),
- any claim a doc makes about a system it doesn't own (that's where drift lives).

Aim for 5–15 checks initially. Wire the weekly sweep (`examples/workflows/`), or a
local cron where credentials live.

## 4. Let the conflicts surface

With frontmatter + checks in place, run the intake discipline on your *oldest* docs —
that's where contradicted claims hide. Quarantine, don't delete:
[conflict resolution](conflicts.md).

## 5. Keep it maintained by default

- pre-commit hook: catalog refresh + gap warnings on every commit (`git config
  core.hooksPath .githooks`, once per clone).
- Session hook: the freshness nudge (`librarian status --hook`) fires only when
  something needs attention.
- CI: `librarian index --check` with `[index].fail_on = ["open_conflicts", "orphans"]`
  is a sensible, non-annoying gate to start with.

## The order of value

If you do only one thing: **frontmatter + `librarian index`** (findability).
If you do two: **add verify checks** (correctness — empirically the biggest win; the
origin project's spike measured routing token savings as modest but caught a
164-vs-181 drift that had already reached three deliverables).
