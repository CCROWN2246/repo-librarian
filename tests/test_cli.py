import contextlib
import io
import json
import os
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

    def test_search(self):
        self.write("docs/schema.md", make_doc(id="schema", read_when="write athena query"))
        self.write("docs/other.md", make_doc(id="other", title="Other", read_when="deploy"))
        self.run_sub("index")
        code, out, _ = self.run_sub("search", "write", "athena", "query")
        self.assertEqual(code, 0)
        self.assertLess(out.index("schema"), out.index("other") if "other" in out else len(out) + 1)
        code, _, _ = self.run_sub("search", "zzz-no-match-zzz")
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

    def test_doctor_runs(self):
        code, out, _ = self.run_sub("doctor")
        self.assertIn(code, (0, 1))
        self.assertIn("[OK]", out)


if __name__ == "__main__":
    unittest.main()
