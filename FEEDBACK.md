# Feedback — my reactions (rough notes welcome)

> Jot anything: confusing, delightful, awkward, "wait what," "this is great," "I'd never use this."
> Don't organize it. I'll sort it out. Even a single word per stage is useful.

## 1 · Discover (README — do I get it?)
-

## 2 · Set it up (`librarian init` — obvious what happened?)
- CONFIRMED BUG: ran `/librarian-enrich` at Step 6 and got "unknown command." Root cause confirmed —
  `librarian enrich` is a fully real, documented CLI subcommand (`librarian enrich --help` works fine,
  and its own help text says "drives /librarian-enrich"), but `librarian init` never wrote
  `.claude/commands/librarian-enrich.md` the way it wrote `librarian.md` and `librarian-dream.md`. So
  the CLI and the docs both assume the slash command exists, but `init`'s command-template step is
  just missing it. This is a straightforward fix: add the missing command template to `init`'s output
  (mirror the shape of `librarian-dream.md`). Confirmed real user impact: START-HERE's Step 6 sends a
  first-time user straight into a dead end with no workaround offered.
- DESIGN PRINCIPLE (should hold everywhere, not just enrich): after `librarian init`, the user should
  never need to drop back to a terminal to interact with the librarian day-to-day — everything should
  be reachable as a Claude Code slash command. This enrich gap is a direct violation of that: the
  feature exists and works from the terminal (`librarian enrich`), but is invisible/unreachable from
  inside Claude Code, which is where the guide (and presumably real usage) lives. Worth auditing ALL
  CLI subcommands (`suggest`, `verify`, `search`, `backfill`, `ingest`, `query`, `why`, `archive`,
  `propose`, `apply`, `doctor` — see full list from `librarian --help`) against what `init` actually
  wires up as slash commands, to catch any other silent gaps like this one before they surface the same
  way `/librarian-enrich` just did.
- PATH FORWARD — real repo-librarian tool: fix `librarian init` to generate a `librarian-enrich.md`
  command file (and audit the other subcommands per the design principle above) so this is fixed at
  the source, not patched per-sandbox.
- PATH FORWARD — this test sandbox, right now: hand-author `.claude/commands/librarian-enrich.md`
  locally (mirroring `librarian-dream.md`'s shape) purely so we can keep testing the *feature* itself
  today via the real slash-command path a user would take. This is a testing workaround, not a fix to
  the tool — the sandbox file should NOT be mistaken for the real fix landing in `init`.

## 3 · The catalog (CATALOG.md / STALENESS.md — useful at a glance?)
- CATALOG.md and STALENESS.md: both very helpful and easy to read overall.
- TODO/bug: STALENESS.md still surfaces old branding — "KB-ACK", "KB-CONTRADICTED" markers, and bare
  "the KB" — as user-facing terms (see the conflict-resolution legend line and the "OPEN conflicts"
  header). "KB" (knowledge base) is leftover naming from an earlier product iteration and means nothing
  to a new user. Needs a full sweep/rename across the tool (markers, docs, any other surfaced strings)
  to whatever the current product vocabulary is — not just this one file.

## 4 · Using it in Claude Code (finds docs? helpful or in the way?)
- CONFIRMED GOOD: tested "not documented" cases (PTO policy, mobile app auth) — Answer line is exactly
  right (clear "not documented" + why nothing routes, e.g. "no HR domain exists"). But Confidence and
  Source lines should be terse for the no-match case too: just "N/A" and "none." — no extra editorializing
  sentence tacked on ("absence, not a fact...", "This would be a real gap for someone to file..."). Same
  answer-first/no-padding discipline as the earlier confirmed-good format should apply to the negative
  case, not just the positive one.
- CONFIRMED GOOD: re-asked "how do backups work here?" with the tighter Answer/Confidence/Source
  format (answer first, no routing dump) — user called it "PERFECT." Worth codifying this response
  shape (short answer, confidence tier, one-line citation) as the expected pattern in the librarian
  protocol / CLAUDE.md guidance, since it's clearly the right UX and shouldn't depend on Claude
  guessing right each time. Also: no duplicate-render this time, so the earlier apparent duplicate was
  most likely a one-off terminal glitch, not a systemic bug — downgrading confidence on that item.
- TODO/UX: for "how do backups work here?", Claude's response led with routing/metadata (catalog hit,
  status, "no conflict flags") BEFORE the actual answer. User feedback: too much upfront info — they
  want the concise answer first, plus a confidence score and citation, not a data dump of librarian's
  internals. This is a Claude-side response-shape issue, not a librarian data issue — but if the intent
  is for the librarian protocol to shape how Claude answers, the protocol/CLAUDE.md guidance should
  probably specify a lead-with-the-answer, cite-briefly format rather than leaving it to Claude's
  judgment.
- Unconfirmed: user's terminal appeared to show the answer twice (once truncated mid-render, once in
  full, both prefixed with "●"). Most likely a terminal scrollback/copy artifact (only one response was
  actually sent) — but flagging as "worth a second look" since it couldn't be independently confirmed
  from inside the session.
- "Where's our deploy process documented?" worked well: routed straight to `docs/eng/deployment.md`
  via the catalog, and correctly surfaced the planted Jenkins/GitHub-Actions conflict flag instead of
  stating the stale fact as true. Good sign for trustworthiness.
- TODO/bug: opened a fresh Claude Code session and saw NO session-start message, even though
  START-HERE Step 4 says to expect one. Root cause: the SessionStart hook (`.claude/hooks/librarian-session.sh`
  -> `librarian status --hook`) DOES fire and DOES produce output ("Librarian: 1 OPEN conflict(s) · 5
  maintenance item(s) ready — run /librarian-dream — see _index/STALENESS.md") when run directly — but
  that stdout is only injected into Claude's context, not shown to the user as a visible chat message.
  The generated CLAUDE.md block never instructs Claude to actually relay/greet with it. So the "helpful
  hello" the guide promises depends entirely on whether Claude decides to mention it — inconsistent and
  easy for a real user to miss entirely. Needs either an explicit instruction in the generated CLAUDE.md
  ("always surface the SessionStart hook output to the user at the start of the session") or a different
  delivery mechanism that's guaranteed visible.

## 5 · The clean-up loop (`/librarian-dream` — trustworthy or scary?)
- CONFIRMED GOOD: successfully switched to the dream branch and reviewed MORNING-REPORT.md — format
  is "near perfect." Liked how it read.
- TODO/UX (report needs closing instructions): every MORNING-REPORT.md should end with 1-2 short,
  literal sentences telling the user exactly what to type to Claude to apply fixes (e.g. "tell Claude
  'apply the deploy fix' to apply that proposal"), PLUS explicit instructions on what to do after fixes
  are applied — including any git actions (merging/switching back, what happens to the dream branch,
  whether/when to delete it). Right now this is implicit/left to Claude's judgment in the moment;
  should be baked into the report template itself so it's consistent every time.
- TODO/product (branch-model assumptions — bigger think, not urgent): the whole dream-branch flow here
  assumes a simple repo (basically just `master`). Real repos often run `main` + `qa`/`staging` +
  `development` + a pile of experimental feature branches. Needs investigation: which branch should a
  dream branch fork FROM (main? the user's current working branch, whatever it is?), what happens if
  the user is mid-feature-branch when the nudge fires, and how do applied fixes get back to wherever
  the "real" source of truth lives without generating a ton of extra commits/pushes/PRs every single
  morning just to review a report. Don't want the librarian's own maintenance loop to add PR-review
  overhead on top of the user's actual work. Not solving now — flag as a branch-strategy question to
  think through before this ships into a repo with a real branching model.
- TODO/product (dream automation — bigger think, not urgent): the "morning report" concept only makes
  sense if it's actually waiting in the morning. Right now `/librarian-dream` is a manual command the
  user runs on-demand, so if they run it mid-day or at end-of-day, they get a "morning report" that's
  either misnamed or effectively extends their workday (they have to review it right then instead of
  next morning). The intended user story is: dreaming happens automatically overnight (e.g. a scheduled
  job), and the user's first action of the day — possibly resuming an existing Claude Code session they
  never fully closed (laptop sleep, not logout) — is met with a fresh report waiting for them, no manual
  step required. Needs real product/UX design time: how does overnight automation get triggered without
  the user's machine being the trigger (a laptop asleep doesn't run cron), how does a resumed session
  detect "there's a new report since you last looked," and does the manual `/librarian-dream` command
  still exist as a fallback/on-demand option alongside the automated nightly one. Flagging as a known
  gap to design properly later, not something to patch reactively.
- TODO/UX (branch hand-holding): after `/librarian-dream` finishes, the report lives on a throwaway
  branch (`kb/dream-YYYYMMDD`) and the user needs to `git switch` over to read it, then switch back.
  Many Claude Code power users never learned or have forgotten basic git — a naive Google search for
  "how do I switch branches in git" surfaces `git checkout`, which is one wrong flag away from
  something destructive (e.g. discarding uncommitted changes). Just telling the user "it's on branch
  X" and expecting them to go find it themselves is a real risk surface, not just an inconvenience.
  Needs an interactive, guided flow — e.g. Claude offers to switch them over with a clear explanation
  of what will happen and how to get back, rather than assuming git fluency. Even better: consider
  surfacing the report content directly in the chat (or copying/rendering it back on main) so the user
  never has to leave their current branch or touch git at all to review proposals. Not solving this
  now — flagging for a dedicated UX pass on the review step of the dream cycle.
- TODO/bug (workflow gap): running `/librarian-dream` right after `librarian init` hit a "repo isn't
  clean" wall — `init` leaves a big pile of uncommitted/untracked output (`.claude/`, `.githooks/`,
  `AGENTS.md`, `CLAUDE.md`, `KNOWLEDGE_PROTOCOL.md`, `_archive/`, `_inbox/`, `_index/`,
  `docs/NAVIGATOR.md`, `librarian-artifacts.toml`) and the dream skill's own contract explicitly
  requires a clean tree before branching (so it doesn't mix user WIP into the dream branch). START-HERE
  never instructs the user to commit init's output before moving on, and a first-time user would hit
  this same wall with no warning — likely confusing/startling, especially since it surfaces as a
  git-status problem rather than a librarian message. Needs either: (a) `librarian init` to prompt/offer
  to commit its own output as a first step, or (b) the START-HERE guide to explicitly say "commit what
  init created before you go further," or (c) the dream skill to auto-stash safely instead of erroring.
  The first-time workflow needs more hand-holding here.

## 6 · The analyst loop (`/librarian-enrich` — comfortable with provisional drafts?)
- CONFIRMED GOOD: functionality itself worked really well once the missing slash command was patched
  in (see Step 2 note). Gap detection was accurate, the drafted doc was properly provisional/unverified,
  cited its source, cross-referenced the existing metrics-glossary definition, and explicitly called out
  what it did NOT know rather than guessing. Very happy with the output quality.
- TODO/UX (same "what do I do next" gap as Step 5): after the analyst loop finishes, there's no crisp,
  skimmable "here's exactly what to do now" — neither in the drafted doc nor in Claude's chat response.
  This is the same underlying gap already logged for `/librarian-dream` (needs literal next-step
  instructions), but it applies here too: promote to authoritative? edit first? re-run `librarian
  index`? Should be a short, consistent checklist — in the doc itself, the chat response, or both —
  every time either loop finishes, not something Claude free-styles per session.

## 7 · Living with it (nudges — helpful librarian or nag?)
- CONFIRMED (re-tests the Step 4 finding): made 3 real doc edits (including one that introduced a
  self-contradiction — see below), started a genuinely fresh Claude Code session in a new terminal
  (`cd` + `export PATH` + `claude --dangerously-skip-permissions`), and saw nothing librarian-specific
  at session start — looked like a completely default session. Manually running
  `librarian status --hook` afterward confirms the hook DOES fire and DID have real content this time
  ("1 OPEN conflict(s) · 5 maintenance item(s) ready"). Ruled out `--dangerously-skip-permissions` /
  the permission-prompt system as the cause — hooks run regardless. This is the same root cause
  already logged in Step 4 (hook output lands in Claude's context but nothing instructs Claude to
  relay it to the user), now confirmed a second time under realistic day-2 conditions. This is the
  single most important fix for the "day-2 feel" the guide asks about — right now there is NO reliable
  moment where the tool proactively surfaces anything to the user; it's 100% opt-in on Claude's part.
- Bonus organic find while editing for this step: the user's own edit to
  `docs/data/active-customers-query.md` accidentally introduced a self-contradiction within the SAME
  doc — body text was changed to say "at least three shipments... trailing 120 days" while a
  cross-reference two lines later still quotes "at least one shipment... trailing 90 days" (and the
  underlying SQL still says 90 days). Good real-world test case for whether `librarian verify`/`dream`
  catches an in-doc self-contradiction, not just doc-vs-doc or doc-vs-source conflicts — worth checking
  whether the next dream cycle actually flags this.
- TESTED THE ABOVE: ran `librarian dream --json` — worklist came back completely unchanged from before
  the edit, the self-contradiction was NOT caught. Root cause (by inspection): `dream`'s worklist is
  built entirely from explicit/structural signals — pre-planted `KB-CONTRADICTED` markers, doc-pair
  similarity scores, placeholder `read_when: [TODO]`, `status: retired` — there's no semantic/free-text
  consistency check, so a doc contradicting itself in prose (or silently drifting from its own cited
  source) is invisible to it. `librarian verify` (fact-checking against live sources) might catch the
  doc-vs-SQL mismatch specifically since that's a live-source check, but nothing currently catches
  doc-vs-itself. Worth deciding whether this is in-scope for the tool (a real semantic-consistency pass)
  or an accepted limitation to document clearly so users don't over-trust the "it'll catch conflicts"
  promise.
- FOLLOWED UP: ran `librarian verify` too — "0 checks · 0 DRIFT" — it had literally nothing to check,
  repo-wide. Root cause: `verify` only re-checks facts with an explicit `[[verify.checks]]` entry
  registered; it's opt-in per-fact, not automatic. Per KNOWLEDGE_PROTOCOL.md itself (its own "Capture on
  discovery" step): "A high-value *checkable* fact should also become a `[[verify.checks]]` entry so it
  can never silently rot" — but neither the analyst-loop-drafted `active-customers-query.md` NOR my
  hand-authored `librarian-enrich.md` workaround command actually did this for the "90 days" claim
  against the SQL. So: dream doesn't catch self-contradictions (no semantic check), and verify doesn't
  catch source drift unless someone remembers to register the check — meaning THIS SPECIFIC "doc quietly
  wrong about a number, drifted from its live source" scenario, which is arguably the tool's core
  promise ("a correctness layer, not a token-saver"), currently falls through every safety net unless a
  human/agent proactively wires up a verify.checks entry at draft time. Real fix candidates: (a) the
  analyst loop's own instructions/template should explicitly require drafting a `[[verify.checks]]`
  entry alongside any checkable fact it captures (mine didn't — worth fixing my sandbox workaround too,
  but more importantly the REAL `librarian init`-generated `librarian-enrich.md` should bake this in),
  or (b) `librarian doctor`/`index` should flag docs that assert checkable facts with zero registered
  verify checks as a coverage gap of its own.

## Anything else — biggest "huh?" / biggest "nice!" / would I actually use this?
-
