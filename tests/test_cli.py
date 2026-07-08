import contextlib
import io
import json
import os
import time
import unittest

from helpers import RepoCase, make_doc
from librarian import cli


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


if __name__ == "__main__":
    unittest.main()
