# The librarian protocol

This repo's knowledge (docs, SQL, notebooks, data, transcripts) is catalogued. **Never read the whole
corpus** — route through the card catalog at `_index/` and open only what fits the task.

**Session start:** read `_index/CATALOG.md` (the inventory, grouped by `domain`) and
`_index/STALENESS.md` (what needs attention: flagged docs, open conflicts, coverage gaps, inbox).
If `docs/NAVIGATOR.md` exists, use it to route recurring task types. Then open only the fitting docs.

**Five reflexes** (full reference: `KNOWLEDGE_PROTOCOL.md`):
1. **Find** — route via CATALOG `domain` + each doc's `read_when` list + grep. Distinctive terms → grep;
   common terms → trust `read_when`/`domain` (the doc that *mentions* a term most is rarely the one
   *authoritative* for it). Before asserting the catalog *lacks* something, positively check the catalog +
   grep first — a doc can confidently claim a gap the catalog fills elsewhere.
2. **Re-route on drift** — when the task shifts to a new subsystem/entity/term, re-scan CATALOG before
   answering; don't keep answering from the first docs you opened.
3. **Freshness gate** — before asserting a fact/number/ID, check the doc's `last_verified` vs `recheck`.
   Overdue or correctness-critical → re-verify (`librarian verify` if the fact has a check; else its
   source) and update the doc.
4. **Capture on discovery** — a durable new fact gets written into a doc (with frontmatter) or
   `librarian-artifacts.toml`, then `librarian index`. A checkable fact should also gain a
   `[[verify.checks]]` entry in `.librarian.toml`.
5. **Trust by tier, conflicts by authority — NEVER by recency** — `authority: verified > curated >
   unverified`. An unverified claim (transcript, meeting note) is a claim to verify, not a fact. A
   lower-authority line contradicting a verified fact gets quarantined in place with
   `<!-- librarian:disputed: conflicts with [verified: <fact>, <source>]; retained for context, not fact -->`
   + `has_disputed_claims: true`, and surfaced to the user. Resolve by Fix (preferred) / `librarian:ack` /
   Archive to `_archive/`. Never silently overwrite a verified fact; never delete the doc.

**Answer questions answer-first** — the answer, then `Confidence:` (the doc's authority, or `N/A` if not
documented) and `Source:` (path, or `none`). No routing/metadata preamble. When the user asks in plain
English, run the librarian for them (verify/index/apply); don't make them use the terminal.

**Frontmatter** (every knowledge .md): `id`, `title`, `domain`, `status` (authoritative | provisional |
draft | reference | retired | archived), `authority` (verified | curated | unverified), `last_verified`
(YYYY-MM-DD), `recheck` (e.g. 90d), `read_when` (task phrases — the routing signal), `owner`, `tags`.
Non-.md artifacts are registered in `librarian-artifacts.toml` instead.

**Commands:** `librarian index` (rebuild the catalog — run after adding/editing docs) ·
`librarian verify` (fact-check docs vs live sources; DRIFT names the doc to fix) ·
`librarian status` (health one-liner) · `librarian search "<task phrase>"` (route without grep) ·
`librarian ingest <file>` (triage an `_inbox/` upload). When `status` says maintenance items
are ready, run **/librarian-dream** — it drafts fixes for conflicts, duplicate docs, and weak routing
as proposals on a branch (never auto-applied).
