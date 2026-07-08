"""`librarian query` (the pure-stdlib retrieval slice) + `librarian apply` CLI
integration (approval flow, reindex, mark-done-only-when-empty)."""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from helpers import RepoCase, make_doc
from librarian import cli, proposals


class CliCase(RepoCase):
    def run_sub(self, command, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([command, "--root", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()


class QueryTests(CliCase):
    def seed(self):
        self.write("docs/etl.md", make_doc(id="etl", title="ETL", domain="data",
                                            status="provisional", read_when="run the etl"))
        self.write("docs/ops.md", make_doc(id="ops", title="Ops runbook", domain="ops",
                                           status="authoritative", read_when="on call"))
        self.run_sub("index")

    def test_filter_by_domain_json(self):
        self.seed()
        code, out, _ = self.run_sub("query", "--domain", "ops", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["id"], "ops")
        # pointer + freshness, not bodies
        self.assertEqual(set(data["results"][0]) >= {"path", "status", "last_verified", "stale"}, True)

    def test_terms_require_all_present(self):
        self.seed()
        code, out, _ = self.run_sub("query", "runbook", "--json")
        self.assertEqual(code, 0)
        self.assertEqual([r["id"] for r in json.loads(out)["results"]], ["ops"])

    def test_no_match_exit_1(self):
        self.seed()
        code, out, _ = self.run_sub("query", "--domain", "nonexistent", "--json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["count"], 0)

    def test_status_filter_and_stale_flag(self):
        # a provisional doc is flagged stale by the catalog; query surfaces it
        self.seed()
        code, out, _ = self.run_sub("query", "--status", "provisional", "--json")
        self.assertEqual(code, 0)
        r = json.loads(out)["results"][0]
        self.assertEqual(r["id"], "etl")
        self.assertTrue(r["stale"])

    def test_path_substring(self):
        self.seed()
        code, out, _ = self.run_sub("query", "--path", "ops.md", "--json")
        self.assertEqual([r["id"] for r in json.loads(out)["results"]], ["ops"])


CONFLICT_DOC = (
    "---\nid: schema\ntitle: Schema\ndomain: data\nstatus: authoritative\n"
    "last_verified: 2026-07-01\nrecheck: 90d\nread_when: [schema questions]\ntags: []\n---\n"
    "<!-- KB-CONTRADICTED: min dock is 15 -->\n"
    "The minimum dock count is 20.\n"
)


class ApplyCliTests(CliCase):
    def _seed_proposal(self, approved=True):
        self.write("docs/schema.md", CONFLICT_DOC)
        self.run_sub("index")
        cfg = self.cfg()
        sha = proposals.file_sha256(self.root / "docs/schema.md")
        t = proposals.Target(path="docs/schema.md", base_sha256=sha, line=11)
        p = proposals.make("fix", [t],
                           {"replace": {"old": "is 20.", "new": "is 15."}, "drop_marker": True},
                           approved=approved)
        proposals.save(cfg, [p])
        return p

    def test_apply_all_applies_approved(self):
        p = self._seed_proposal(approved=True)
        code, out, _ = self.run_sub("apply", "--all", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["applied"], 1)
        self.assertEqual(data["outcomes"][0]["id"], p.id)
        text = self.read("docs/schema.md")
        self.assertIn("is 15.", text)
        self.assertNotIn("KB-CONTRADICTED", text)
        self.assertTrue((self.root / "_index" / "apply-log.jsonl").exists())

    def test_apply_all_skips_unapproved(self):
        self._seed_proposal(approved=False)
        code, out, _ = self.run_sub("apply", "--all", "--json")
        self.assertEqual(code, 0)
        # nothing selected -> human message, file untouched
        self.assertIn("20.", self.read("docs/schema.md"))

    def test_apply_marks_done_when_worklist_empties(self):
        # the only worklist item is this doc's open conflict; fixing it empties it
        self._seed_proposal(approved=True)
        code, out, _ = self.run_sub("apply", "--all", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["marked_done"])
        self.assertTrue((self.root / "_index" / ".last_dream").exists())

    def test_apply_only_reports_stale(self):
        p = self._seed_proposal(approved=False)
        self.write("docs/schema.md", CONFLICT_DOC.replace("is 20.", "is 20 (edited)."))
        code, out, _ = self.run_sub("apply", "--only", p.id, "--json")
        self.assertEqual(code, 1)  # stale is a finding
        self.assertEqual(json.loads(out)["outcomes"][0]["result"], "stale")

    def test_apply_dry_run_writes_nothing(self):
        self._seed_proposal(approved=True)
        code, out, _ = self.run_sub("apply", "--all", "--dry-run", "--json")
        self.assertEqual(code, 0)
        self.assertIn("20.", self.read("docs/schema.md"))  # unchanged
        self.assertFalse((self.root / "_index" / "apply-log.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
