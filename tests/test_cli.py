import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from helpers import RepoCase, make_doc
from librarian import cli, frontmatter


class CliCase(RepoCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--root", str(self.root), *argv] if argv and argv[0] != "--root" else list(argv))
        return code, out.getvalue(), err.getvalue()

    def run_sub(self, command, *argv):
        # --root must follow the subcommand for subparser flags
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([command, "--root", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()


class CliTests(CliCase):
    def test_index_clean_exit0(self):
        self.write("docs/a.md", make_doc(last_verified="2026-07-01"))
        code, out, _ = self.run_sub("index")
        self.assertEqual(code, 0)
        self.assertIn("1 catalogued", out)
        self.assertTrue((self.root / "_index" / "catalog.json").exists())

    def test_index_check_gate(self):
        self.write("docs/plain.md", "# no fm\n")
        self.write(".librarian.toml", "schema_version = 1\n[index]\nfail_on = ['missing_frontmatter']\n")
        code, _, err = self.run_sub("index", "--check")
        self.assertEqual(code, 1)
        self.assertIn("missing_frontmatter", err)

    def test_index_json_valid(self):
        self.write("docs/a.md", make_doc(last_verified="2026-07-01"))
        code, out, _ = self.run_sub("index", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["summary"]["docs"], 1)

    @unittest.skipUnless(os.name != "nt", "verify shells out via /bin/sh (POSIX only)")
    def test_verify_drift_exit1(self):
        self.write(
            ".librarian.toml",
            "schema_version = 1\n[[verify.checks]]\nid='x'\nkind='assert'\n"
            "doc='d.md'\ncmd='echo 2'\nexpect='1'\n",
        )
        code, out, _ = self.run_sub("verify")
        self.assertEqual(code, 1)
        self.assertIn("DRIFT", out)
        self.assertIn("-> update: d.md", out)

    @unittest.skipUnless(os.name != "nt", "verify shells out via /bin/sh (POSIX only)")
    def test_verify_json(self):
        self.write(
            ".librarian.toml",
            "schema_version = 1\n[[verify.checks]]\nid='x'\nkind='assert'\n"
            "doc='d.md'\ncmd='echo 1'\nexpect='1'\n",
        )
        code, out, _ = self.run_sub("verify", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["results"][0]["status"], "PASS")
        self.assertEqual(data["exit_code"], 0)

    def test_status_flow(self):
        self.write("docs/a.md", make_doc(last_verified="2026-07-01"))
        code, out, _ = self.run_sub("status")
        self.assertEqual(code, 1)  # no catalog yet
        self.run_sub("index")
        code, out, _ = self.run_sub("status")
        self.assertEqual(code, 0)  # clean (no checks configured)
        self.assertIn("clean", out)
        # hook mode: always exit 0, silent when clean
        code, out, _ = self.run_sub("status", "--hook")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")
        # introduce attention: an inbox item
        self.write("_inbox/raw.md", "x\n")
        self.run_sub("index")
        code, out, _ = self.run_sub("status", "--hook")
        self.assertEqual(code, 0)
        self.assertIn("awaiting intake", out)

    def _seed_attention(self):
        # an inbox item makes status non-clean, so the hook has something to nudge about
        self.write("docs/a.md", make_doc(last_verified="2026-07-01"))
        self.write("_inbox/raw.md", "x\n")
        self.run_sub("index")

    def test_throttle_nudges_then_silent_within_window(self):
        self._seed_attention()
        code, out, _ = self.run_sub("status", "--hook", "--throttle")
        self.assertEqual(code, 0)
        self.assertIn("awaiting intake", out)  # first prompt of the block nudges
        code, out, _ = self.run_sub("status", "--hook", "--throttle")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")  # within the work-block: silent
        self.assertTrue((self.root / "_index" / ".last_nudge").exists())

    def test_throttle_fast_paths_before_catalog_load(self):
        self._seed_attention()
        self.run_sub("status", "--hook", "--throttle")  # stamps .last_nudge
        (self.root / "_index" / "catalog.json").unlink()  # would error if it tried to load+report
        code, out, _ = self.run_sub("status", "--hook", "--throttle")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")  # early-exit, never touched catalog.json

    def test_throttle_re_nudges_on_work_resumption(self):
        self._seed_attention()
        self.run_sub("status", "--hook", "--throttle")
        # backdate the stamp beyond the window (default 240 min) -> resumed work
        nudge = self.root / "_index" / ".last_nudge"
        nudge.write_text(str(int(time.time()) - 240 * 60 - 10), encoding="utf-8")
        code, out, _ = self.run_sub("status", "--hook", "--throttle")
        self.assertEqual(code, 0)
        self.assertIn("awaiting intake", out)  # re-nudges after the idle gap

    def test_throttle_disabled_when_zero(self):
        self._seed_attention()
        self.write(".librarian.toml", "schema_version = 1\n[hooks]\nnudge_throttle_minutes = 0\n")
        self.run_sub("index")
        code, out, _ = self.run_sub("status", "--hook", "--throttle")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")  # UserPromptSubmit nudge disabled

    def test_sessionstart_hook_still_nudges_and_stamps(self):
        self._seed_attention()
        code, out, _ = self.run_sub("status", "--hook")  # no --throttle
        self.assertEqual(code, 0)
        self.assertIn("awaiting intake", out)
        self.assertTrue((self.root / "_index" / ".last_nudge").exists())

    def test_catalog_token_budget_warning(self):
        self.write("docs/a.md", make_doc(last_verified="2026-07-01"))
        self.write(".librarian.toml", "schema_version = 1\n[index]\ncatalog_token_budget = 1\n")
        self.run_sub("index")
        code, out, _ = self.run_sub("status")
        self.assertEqual(code, 1)
        self.assertIn("budget", out)
        code, out, _ = self.run_sub("status", "--hook")
        self.assertEqual(code, 0)
        self.assertIn("CATALOG.md", out)
        # budget 0 disables the warning
        self.write(".librarian.toml", "schema_version = 1\n[index]\ncatalog_token_budget = 0\n")
        self.run_sub("index")
        code, _, _ = self.run_sub("status")
        self.assertEqual(code, 0)

    def test_search(self):
        self.write("docs/schema.md", make_doc(id="schema", read_when="write athena query"))
        self.write("docs/other.md", make_doc(id="other", title="Other", read_when="deploy"))
        self.run_sub("index")
        code, out, _ = self.run_sub("search", "write", "athena", "query")
        self.assertEqual(code, 0)
        self.assertLess(out.index("schema"), out.index("other") if "other" in out else len(out) + 1)
        code, _, _ = self.run_sub("search", "zzz-no-match-zzz")
        self.assertEqual(code, 1)

    def test_search_tokenizes_folds_and_guards(self):
        # P0 (round-3 A1): a quoted multi-word query arrives as ONE arg with
        # spaces; it must split on whitespace, not collapse to one literal
        # substring that matches nothing.
        self.write("docs/a.md", make_doc(id="alpha", read_when="write athena query"))
        self.write("docs/b.md", make_doc(id="beta", read_when="deploy production"))
        self.write("docs/c.md", make_doc(id="gamma", read_when="per-shipment tracking"))
        self.run_sub("index")
        # quoted phrase as a single arg -> tokenized -> ranked hit
        code, out, _ = self.run_sub("search", "write query")
        self.assertEqual(code, 0)
        self.assertIn("alpha", out)
        # trailing-s fold: a plural query matches a singular term in read_when
        code, out, _ = self.run_sub("search", "shipments")
        self.assertEqual(code, 0)
        self.assertIn("gamma", out)
        # empty-query guard: a pure-stopword query must NOT match every doc via
        # the `"" in rw` all-match trap. "of" matches none of these docs.
        code, _, _ = self.run_sub("search", "of")
        self.assertEqual(code, 1)

    def test_search_body_fallback(self):
        # A1b two-tier: a body-only word (absent from title/tags/read_when/id)
        # resolves via the zero-hit fallback that re-reads doc bodies.
        doc = make_doc(id="ops", read_when="on call").replace(
            "body text", "the escalation procedure for paging on-call"
        )
        self.write("docs/ops.md", doc)
        self.run_sub("index")
        code, out, _ = self.run_sub("search", "escalation")
        self.assertEqual(code, 0)
        self.assertIn("ops", out)
        # deterministic: run twice, identical output
        _c2, out2, _ = self.run_sub("search", "escalation")
        self.assertEqual(out, out2)

    def test_archive_moves_flips_and_reindexes(self):
        self.write("docs/old.md", make_doc(id="old", status="draft", last_verified="2026-07-01"))
        self.run_sub("index")
        code, out, _ = self.run_sub("archive", "docs/old.md", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["result"], "applied")
        self.assertEqual(data["dest"], "_archive/old.md")
        self.assertTrue(data["reindexed"])
        self.assertFalse((self.root / "docs/old.md").exists())
        self.assertIn("status: archived", self.read("_archive/old.md"))
        # gone from the catalog (archive dir is excluded from the scan)
        cat = json.loads(self.read("_index/catalog.json"))
        self.assertNotIn("old", {e["id"] for e in cat["entries"]})

    def test_archive_custom_dest(self):
        self.write("docs/old.md", make_doc(id="old", status="draft"))
        self.run_sub("index")
        code, _, _ = self.run_sub("archive", "docs/old.md", "--to", "_archive/2026/old.md")
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "_archive/2026/old.md").exists())

    def test_archive_dry_run_writes_nothing(self):
        self.write("docs/old.md", make_doc(id="old", status="draft"))
        self.run_sub("index")
        code, out, _ = self.run_sub("archive", "docs/old.md", "--dry-run", "--json")
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "docs/old.md").exists())
        self.assertFalse((self.root / "_archive/old.md").exists())

    def test_archive_missing_doc_is_finding(self):
        self.write("docs/present.md", make_doc())
        self.run_sub("index")
        code, _, _ = self.run_sub("archive", "docs/nope.md", "--json")
        self.assertEqual(code, 1)  # stale: nothing to archive

    def test_archive_idempotent_second_noop(self):
        self.write("docs/old.md", make_doc(id="old", status="draft"))
        self.run_sub("index")
        self.run_sub("archive", "docs/old.md")
        code, out, _ = self.run_sub("archive", "docs/old.md", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["result"], "noop")

    def test_why_shows_provenance(self):
        from librarian import verify

        cfg = self.cfg()
        verify.save_provenance(
            cfg,
            {
                "dock_count": {
                    "check_id": "dock_count",
                    "doc": "docs/schema.md",
                    "source": "warehouse",
                    "command": "psql -c 'select count(*)'",
                    "live": "17",
                    "expect": "17",
                    "status": "PASS",
                    "verified_at": "2026-07-02",
                }
            },
        )
        code, out, _ = self.run_sub("why", "dock", "--json")
        self.assertEqual(code, 0)
        rec = json.loads(out)["records"][0]
        self.assertEqual(rec["command"], "psql -c 'select count(*)'")
        self.assertEqual(rec["live"], "17")
        # human output surfaces the command + backing doc
        code, out, _ = self.run_sub("why", "dock_count")
        self.assertIn("command:", out)
        self.assertIn("docs/schema.md", out)

    def test_why_no_match_exit1(self):
        from librarian import verify

        verify.save_provenance(self.cfg(), {"x": {"check_id": "x", "doc": "d.md", "source": "s"}})
        code, _, _ = self.run_sub("why", "nonexistent-fact", "--json")
        self.assertEqual(code, 1)

    def test_why_without_provenance_exit1(self):
        self.cfg()
        code, _, _ = self.run_sub("why", "--json")
        self.assertEqual(code, 1)

    def test_config_error_exit2(self):
        self.write(".librarian.toml", "schema_version = 1\n[bogus]\nx=1\n")
        code, _, err = self.run_sub("index")
        self.assertEqual(code, 2)
        self.assertIn("bogus", err)

    def test_no_config_exit2(self):
        import tempfile

        with tempfile.TemporaryDirectory() as empty:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["index", "--root", empty])
        self.assertEqual(code, 2)
        self.assertIn("librarian init", err.getvalue())

    def test_backfill_dry_run_then_write(self):
        self.write("docs/naked.md", "# Naked\n")
        code, out, _ = self.run_sub("backfill")
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertNotIn("---", self.read("docs/naked.md"))
        code, out, _ = self.run_sub("backfill", "--write", "--domain", "data")
        self.assertEqual(code, 0)
        self.assertIn("domain: data", self.read("docs/naked.md"))

    def test_dream_due_then_marked_done(self):
        body = make_doc(last_verified="2026-07-01") + (
            "\nclaim <!-- KB-CONTRADICTED: conflicts with [verified: y] -->\n"
        )
        self.write("docs/c.md", body)
        self.run_sub("index")
        # due: exit 1, names the conflict path
        code, out, _ = self.run_sub("dream")
        self.assertEqual(code, 1)
        self.assertIn("DUE", out)
        self.assertIn("docs/c.md", out)
        # --json carries the due flag + worklist
        code, out, _ = self.run_sub("dream", "--json")
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertTrue(data["due"])
        self.assertEqual(data["worklist"]["counts"]["open_conflicts"], 1)
        # mark-done resets the gate -> exit 0
        code, _, _ = self.run_sub("dream", "--mark-done")
        self.assertEqual(code, 0)
        code, out, _ = self.run_sub("dream")
        self.assertEqual(code, 0)

    def test_status_surfaces_dream_nudge(self):
        body = make_doc(last_verified="2026-07-01") + (
            "\nclaim <!-- KB-CONTRADICTED: conflicts with [verified: y] -->\n"
        )
        self.write("docs/c.md", body)
        self.run_sub("index")
        code, out, _ = self.run_sub("status", "--hook")
        self.assertEqual(code, 0)
        self.assertIn("/librarian-dream", out)

    def test_doctor_runs(self):
        code, out, _ = self.run_sub("doctor")
        self.assertIn(code, (0, 1))
        self.assertIn("[OK]", out)


@unittest.skipUnless(shutil.which("git"), "needs git")
class InitCommitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        os.environ["LIBRARIAN_TODAY"] = "2026-07-02"
        self.addCleanup(os.environ.pop, "LIBRARIAN_TODAY", None)
        self._git("init", "-q")
        self._git("config", "user.email", "t@t")
        self._git("config", "user.name", "t")

    def _git(self, *a):
        return subprocess.run(["git", "-C", str(self.root), *a], capture_output=True, text=True)

    def _run_init(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["init", "--root", str(self.root), *argv])
        return code, out.getvalue() + err.getvalue()

    def test_clean_repo_autocommits_scaffolding(self):
        code, _ = self._run_init("--agent", "none")
        self.assertEqual(code, 0)
        self.assertEqual(self._git("status", "--porcelain").stdout.strip(), "")  # clean tree after
        self.assertIn("scaffold repo-librarian", self._git("log", "--oneline").stdout)

    def test_no_commit_flag_leaves_scaffolding_uncommitted(self):
        code, _ = self._run_init("--agent", "none", "--no-commit")
        self.assertEqual(code, 0)
        self.assertNotEqual(self._git("status", "--porcelain").stdout.strip(), "")

    def test_dirty_tree_is_not_swept_in(self):
        (self.root / "wip.txt").write_text("my work\n", encoding="utf-8")
        code, _ = self._run_init("--agent", "none")
        self.assertEqual(code, 0)
        # the user's WIP is still uncommitted (init did not commit anything)
        self.assertIn("wip.txt", self._git("status", "--porcelain").stdout)
        self.assertNotIn("scaffold repo-librarian", self._git("log", "--oneline").stdout or "")


class FailingCheckSurfaceTests(CliCase):
    def test_status_hook_surfaces_failing_check(self):
        # Item 2: a persisted DRIFT must reach the greeting (status --hook), not just `why`.
        from librarian import verify

        self.write("docs/a.md", make_doc())
        self.run_sub("index")
        verify.save_provenance(
            self.cfg(),
            {"bad": {"check_id": "bad", "status": "DRIFT", "doc": "docs/a.md", "verified_at": "2026-07-01"}},
        )
        _code, out, _err = self.run_sub("status", "--hook")
        self.assertIn("FAILING check", out)


class TodosTests(CliCase):
    def test_todos_lists_pending_hides_applied(self):
        from librarian import proposals

        self.write("docs/x.md", make_doc())
        h = proposals.file_sha256(self.root / "docs/x.md")
        p1 = proposals.make(
            "fix",
            [proposals.Target("docs/x.md", h, 1)],
            {"replace": {"old": "a", "new": "b"}},
            rationale="fix the number",
            approved=True,
        )
        p2 = proposals.make("ack", [proposals.Target("docs/x.md", h, 5)], {"mark": "x"}, rationale="ack it")
        p2.applied, p2.applied_at, p2.result = True, "2026-07-01", "applied"
        proposals.save(self.cfg(), [p1, p2])
        code, out, _ = self.run_sub("todos")
        self.assertEqual(code, 1)  # pending remain
        self.assertIn("fix the number", out)
        self.assertNotIn("ack it", out)  # applied is not "pending"
        self.assertIn("1 already applied", out)

    def test_todos_reconciles_log_applied_despite_stale_flag(self):
        # Finding B: the apply-log records the id applied, but proposals.json's flag is stale
        # (writeback crashed). todos must treat it as applied (log wins) — not re-surface it.
        from librarian import apply as ap
        from librarian import proposals

        self.write("docs/x.md", make_doc())
        h = proposals.file_sha256(self.root / "docs/x.md")
        p = proposals.make(
            "ack", [proposals.Target("docs/x.md", h, 5)], {"mark": "x"}, rationale="ack it", approved=True
        )
        proposals.save(self.cfg(), [p])  # applied flag is False on disk
        ap.log_outcomes(self.cfg(), [ap.Outcome(p.id, p.type, ap.APPLIED, "", ["docs/x.md"])], now=1000)
        code, out, _ = self.run_sub("todos")
        self.assertEqual(code, 0)  # nothing pending — reconciled from the log
        self.assertNotIn("ack it", out)
        self.assertIn("1 already applied", out)


class ProposeReactivationTests(CliCase):
    """Finding B: re-proposing an already-applied id resets it to unapplied. Warn loudly."""

    PARTIAL = {
        "type": "fix",
        "targets": [{"path": "docs/x.md"}],
        "action": {"replace": {"old": "20", "new": "17"}},
        "rationale": "fix it",
    }

    def _partial_file(self):
        import json as _json

        path = self.root / "p.json"
        path.write_text(_json.dumps(self.PARTIAL), encoding="utf-8")
        return str(path)

    def test_reproposing_applied_id_warns(self):
        from librarian import apply as ap

        self.write("docs/x.md", "value is 20\n")
        pf = self._partial_file()
        code, out, _ = self.run_sub("propose", pf, "--json")
        self.assertEqual(code, 0)
        pid = json.loads(out)["added"][0]
        # simulate a landed apply whose writeback crashed (log only)
        ap.log_outcomes(self.cfg(), [ap.Outcome(pid, "fix", ap.APPLIED, "", ["docs/x.md"])], now=1000)
        code, out, err = self.run_sub("propose", pf, "--json")
        self.assertEqual(code, 0)
        self.assertIn(pid, json.loads(out)["reactivated"])
        self.assertIn("already applied", err)

    def test_reproposing_unapplied_id_does_not_warn(self):
        self.write("docs/x.md", "value is 20\n")
        pf = self._partial_file()
        self.run_sub("propose", pf, "--json")
        code, out, err = self.run_sub("propose", pf, "--json")  # re-propose, never applied
        self.assertEqual(json.loads(out)["reactivated"], [])
        self.assertNotIn("already applied", err)


class IngestSafetyTests(CliCase):
    """W1: fail-loud on the trust tier in a non-interactive (no-TTY) context — the path
    an agent driving the CLI actually hits. The test runner has no TTY, matching it."""

    def test_no_tty_no_authority_refuses(self):
        self.write("_inbox/customer-call-notes.md", "# Call\n\nEnterprise tier, prorated billing.\n")
        code, _out, err = self.run_sub("ingest", "customer-call-notes.md")
        self.assertEqual(code, 2)
        self.assertIn("interactive terminal", err)  # 1.1: plain English, not "no TTY" jargon
        self.assertNotIn("no TTY", err)
        self.assertIn("suggested: unverified", err)  # E4 cue: "call"/"notes" -> unverified
        # nothing filed, nothing clobbered
        self.assertTrue((self.root / "_inbox" / "customer-call-notes.md").exists())
        self.assertFalse((self.root / "docs" / "customer-call-notes.md").exists())

    def test_explicit_authority_files_and_discloses_domain_default(self):
        self.write("_inbox/notes.md", "# Notes\n\nsomething\n")
        code, out, _err = self.run_sub("ingest", "notes.md", "--authority", "unverified")
        self.assertEqual(code, 0)
        self.assertIn("filed:", out)
        self.assertIn("default(s) used", out)  # domain=uncategorized disclosed
        self.assertIn("conflict-check", out)  # D3 reminder for below-verified
        meta = frontmatter.parse(self.read("docs/notes.md")).meta
        self.assertEqual(meta["authority"], "unverified")

    def test_verified_tier_skips_conflict_reminder(self):
        self.write("_inbox/spec.md", "# Spec\n")
        code, out, _ = self.run_sub("ingest", "spec.md", "--authority", "verified", "--domain", "eng")
        self.assertEqual(code, 0)
        self.assertNotIn("conflict-check", out)

    def test_dry_run_writes_nothing(self):
        self.write("_inbox/notes.md", "# Notes\n")
        code, out, _ = self.run_sub("ingest", "notes.md", "--authority", "curated", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertTrue((self.root / "_inbox" / "notes.md").exists())  # not moved
        self.assertFalse((self.root / "docs" / "notes.md").exists())

    def test_dest_md_path_errors(self):
        self.write("_inbox/notes.md", "# Notes\n")
        code, _out, err = self.run_sub(
            "ingest", "notes.md", "--authority", "unverified", "--dest", "docs/notes.md"
        )
        self.assertEqual(code, 2)
        self.assertIn("--dest must be a directory", err)

    def test_inbox_prefix_path_normalized(self):
        # 1.2: an arg carrying the _inbox/ prefix resolves to the same file the
        # refusal message quotes — no _inbox/_inbox/ path-doubling.
        self.write("_inbox/note.md", "# Note\n")
        code, out, _ = self.run_sub("ingest", "_inbox/note.md", "--authority", "unverified", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)

    def test_dry_run_previews_defaults_and_conflict_check(self):
        # 1.4: dry-run surfaces the "defaults used" + conflict-check consequences
        # the real filing shows, as "would ..." lines.
        self.write("_inbox/note.md", "# Note\n")
        code, out, _ = self.run_sub("ingest", "note.md", "--authority", "unverified", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("would note", out)  # default domain disclosed
        self.assertIn("would require", out)  # conflict-check for below-verified
        self.assertFalse((self.root / "docs" / "notes.md").is_dir())


class IngestRoutingAndConflictTests(CliCase):
    """WS-A A2/A3: read_when auto-suggest plumbing (D4) + ingest conflict-check (D3)."""

    def test_read_when_flag_lands_in_frontmatter(self):
        # A2 (D4): repeatable --read-when reaches ingest_file and stamps the doc's routing.
        self.write("_inbox/guide.md", "# Guide\n\nhow to do X\n")
        code, _out, _ = self.run_sub(
            "ingest",
            "guide.md",
            "--authority",
            "curated",
            "--domain",
            "eng",
            "--read-when",
            "onboarding a new hire",
            "--read-when",
            "setting up X",
        )
        self.assertEqual(code, 0)
        meta = frontmatter.parse(self.read("docs/guide.md")).meta
        self.assertEqual(meta["read_when"], ["onboarding a new hire", "setting up X"])

    def test_conflict_check_surfaces_overlapping_doc(self):
        # A3 (D3-conflict): ingest runs a conflict-check over the PRE-ingest catalog and
        # prints an overlapping doc as a candidate — the tool reports, the human decides.
        self.write(
            "docs/deployment.md",
            make_doc(id="deployment", title="Deployment", domain="eng", read_when="deploy"),
        )
        self.run_sub("index")
        self.write("_inbox/new-deploy.md", "# Deploy\n\nWe now deploy via GitHub Actions, not Jenkins.\n")
        code, out, _ = self.run_sub("ingest", "new-deploy.md", "--authority", "unverified", "--domain", "eng")
        self.assertEqual(code, 0)
        self.assertIn("possible conflict", out)
        self.assertIn("docs/deployment.md", out)

    def test_conflict_check_no_false_positive_on_unrelated(self):
        # An unrelated existing doc must NOT surface (no shared terms -> no candidate).
        self.write(
            "docs/pricing.md",
            make_doc(id="pricing", title="Pricing", domain="product", read_when="pricing questions"),
        )
        self.run_sub("index")
        self.write("_inbox/backup.md", "# Backup\n\nNightly database snapshots to S3.\n")
        code, out, _ = self.run_sub("ingest", "backup.md", "--authority", "curated", "--domain", "ops")
        self.assertEqual(code, 0)
        self.assertNotIn("possible conflict", out)
        self.assertNotIn("docs/pricing.md", out)

    def test_conflict_check_on_fresh_repo_does_not_error(self):
        # First-ingest guard: no catalog.json yet -> build in-memory, exclude self, no crash.
        self.write("_inbox/first.md", "# First\n\nthe very first note in this repo\n")
        code, out, _ = self.run_sub("ingest", "first.md", "--authority", "unverified", "--domain", "ops")
        self.assertEqual(code, 0)
        self.assertIn("filed:", out)
        self.assertNotIn("possible conflict", out)  # nothing to conflict with


if __name__ == "__main__":
    unittest.main()
