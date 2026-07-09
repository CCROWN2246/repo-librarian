## Knowledge protocol

Follow the **librarian protocol** in `AGENTS.md` (full reference: `KNOWLEDGE_PROTOCOL.md`): start every
session from `_index/CATALOG.md` + `_index/STALENESS.md`, route via `domain`/`read_when` instead of
reading the whole corpus, freshness-gate facts (`librarian verify`), capture discoveries back into docs,
and resolve conflicts by authority tier — never by recency.

**At session start, greet with the status.** A `SessionStart` hook runs `librarian status`; when it emits
a `Librarian: …` line (open conflicts / stale facts / maintenance due), **open your first reply to the
user by surfacing it** — a short `🗂️ Librarian: <status> — want me to take a look?` so the user actually
sees it (the hook line only lands in your context, not on their screen). If it emitted nothing, say nothing.

**Answering a knowledge question — lead with the answer, not the plumbing.** Do NOT open with routing or
metadata ("catalog hit", the doc's status, "no conflict flags"). Reply in this shape:
- **Answer:** the direct answer, first, in a sentence or two.
- **Confidence:** the doc's `authority` (`verified` / `curated` / `unverified`), or `N/A` if not documented.
- **Source:** one-line citation `path/to/doc.md`, or `none` if not documented.

For a not-documented question, keep it just as terse: `Answer:` says so plainly (and why nothing routes,
e.g. "no HR domain exists"), `Confidence: N/A`, `Source: none` — no editorializing sentence.

**Day-to-day needs no terminal.** When the user asks in plain English, YOU run the librarian for them:
"check our facts" → `librarian verify`; "what's stale?" / "refresh the catalog" → `librarian index` then
read STALENESS; "apply the deploy fix" → `librarian apply`. The deliberate rituals are slash commands:
`/librarian` (health + what-can-I-do), `/librarian-dream` (maintenance), `/librarian-enrich` (fill gaps),
`/librarian-verify` (fact-check).
