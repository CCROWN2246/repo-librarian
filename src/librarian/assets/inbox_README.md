# _inbox/ — intake staging

Drop raw, un-triaged material here (a pasted doc, an exported transcript, a dump). `librarian index`
lists anything in `_inbox/` as **awaiting intake** so it doesn't get silently lost or silently trusted.

**Intake lifecycle** (`librarian ingest <file>` walks you through it): triage → assign trust **tier**
(`authority`, from provenance: who wrote it, do they have direct/technical access?) → **conflict-check**
against existing verified facts → add **frontmatter** (or a `librarian-artifacts.toml` entry) → **file**
it into the repo (and out of `_inbox/`). Interview transcripts and third-party notes come in as
`authority: unverified` — their claims are context to verify, not fact.

(This README and `.gitkeep` are ignored by the intake counter.)
