"""`librarian propose` — the dream producer. The agent supplies judgment (type,
targets, action, rationale) as partial JSON; the CLI fills base_sha256 + id + risk
and upserts into proposals.json. Also the full producer->apply round trip."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest

from helpers import RepoCase, make_doc
from librarian import cli, proposals


class ProposeCase(RepoCase):
    def run_sub(self, command, *argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        old_stdin, sys.stdin = sys.stdin, io.StringIO(stdin)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main([command, "--root", str(self.root), *argv])
        finally:
            sys.stdin = old_stdin
        return code, out.getvalue(), err.getvalue()


class BuildFromPartialTests(RepoCase):
    def test_fills_hash_id_and_risk(self):
        self.write("docs/x.md", "value is 20\n")
        cfg = self.cfg()
        partial = {
            "type": "fix",
            "targets": [{"path": "docs/x.md", "line": 1}],  # no base_sha256
            "action": {"replace": {"old": "20", "new": "17"}},
            "rationale": "it's 17",
        }
        p = proposals.build_from_partial(cfg, partial)
        self.assertEqual(p.targets[0].base_sha256, proposals.file_sha256(self.root / "docs/x.md"))
        self.assertTrue(p.id.startswith("p_"))
        self.assertFalse(p.risk.reversible)  # fix default: irreversible text edit
        self.assertFalse(p.approved)

    def test_missing_file_hashes_to_empty(self):
        cfg = self.cfg()
        partial = {
            "type": "enrich_create",
            "targets": [{"path": "docs/new.md"}],
            "action": {"new_path": "docs/new.md", "body": "x"},
            "provenance": {"command": "echo 3", "evidence": "3", "source": "warehouse"},
        }
        p = proposals.build_from_partial(cfg, partial)
        self.assertEqual(p.targets[0].base_sha256, "")  # not-yet-existing target

    def test_enrich_create_empty_source_rejected(self):
        # the empty-source guard (R1): no source evidence -> refuse to build the draft
        cfg = self.cfg()
        partial = {
            "type": "enrich_create",
            "targets": [{"path": "docs/new.md"}],
            "action": {"new_path": "docs/new.md", "body": "x"},
            "provenance": {"command": "echo ''", "source": "warehouse"},  # no evidence
        }
        with self.assertRaises(proposals.ProposalError):
            proposals.build_from_partial(cfg, partial)

    def test_bad_type_rejected(self):
        cfg = self.cfg()
        with self.assertRaises(proposals.ProposalError):
            proposals.build_from_partial(cfg, {"type": "nope", "targets": [{"path": "d"}], "action": {}})

    def test_unknown_provenance_key_rejected(self):
        self.write("docs/x.md", "y\n")
        cfg = self.cfg()
        with self.assertRaises(proposals.ProposalError):
            proposals.build_from_partial(
                cfg,
                {
                    "type": "ack",
                    "targets": [{"path": "docs/x.md", "line": 1}],
                    "action": {"mark": "KB-ACK"},
                    "provenance": {"bogus": 1},
                },
            )

    def test_upsert_dedupes_redrafts(self):
        self.write("docs/x.md", "20\n")
        cfg = self.cfg()
        base = {"type": "fix", "targets": [{"path": "docs/x.md"}]}
        p1 = proposals.build_from_partial(cfg, {**base, "action": {"replace": {"old": "20", "new": "17"}}})
        # same old-text -> same id; different new-text -> still same id (redraft)
        p2 = proposals.build_from_partial(cfg, {**base, "action": {"replace": {"old": "20", "new": "18"}}})
        merged = proposals.upsert([p1], [p2])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].action["replace"]["new"], "18")  # latest wins


class ProposeCliTests(ProposeCase):
    def test_propose_from_stdin_appends(self):
        self.write("docs/x.md", "value is 20\n")
        partial = json.dumps(
            {
                "type": "fix",
                "targets": [{"path": "docs/x.md", "line": 1}],
                "action": {"replace": {"old": "20", "new": "17"}},
                "rationale": "it's 17",
            }
        )
        code, out, _ = self.run_sub("propose", "--json", stdin=partial)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["total"], 1)
        saved = proposals.load(self.cfg())
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].type, "fix")

    def test_propose_list_and_idempotent_upsert(self):
        self.write("docs/x.md", "20\n")
        self.write("docs/y.md", make_doc(id="y", read_when=""))
        payload = json.dumps(
            [
                {
                    "type": "fix",
                    "targets": [{"path": "docs/x.md"}],
                    "action": {"replace": {"old": "20", "new": "17"}},
                },
                {
                    "type": "set_read_when",
                    "targets": [{"path": "docs/y.md"}],
                    "action": {"read_when": ["a task"]},
                },
            ]
        )
        self.run_sub("propose", stdin=payload)
        self.assertEqual(len(proposals.load(self.cfg())), 2)
        # re-proposing the same two upserts, doesn't duplicate
        self.run_sub("propose", stdin=payload)
        self.assertEqual(len(proposals.load(self.cfg())), 2)

    def test_propose_invalid_json_exit2(self):
        code, _, err = self.run_sub("propose", stdin="{not json")
        self.assertEqual(code, 2)
        self.assertIn("invalid JSON", err)

    def test_producer_to_apply_round_trip(self):
        # the whole spine: propose -> approve -> apply changes the file
        self.write("docs/x.md", "the value is 20 today\n")
        partial = json.dumps(
            {
                "type": "fix",
                "targets": [{"path": "docs/x.md", "line": 1}],
                "action": {"replace": {"old": "is 20", "new": "is 17"}},
                "rationale": "corrected",
            }
        )
        self.run_sub("propose", "--approved", stdin=partial)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["apply", "--root", str(self.root), "--all", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["applied"], 1)
        self.assertIn("is 17", self.read("docs/x.md"))


if __name__ == "__main__":
    unittest.main()
