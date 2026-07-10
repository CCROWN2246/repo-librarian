"""`librarian apply` tests: the fix truth-table, idempotency (twice = zero diff),
single- and multi-file staleness refusal, every typed handler, and the apply-log.
"""

from __future__ import annotations

import json
import unittest

from helpers import RepoCase, make_doc
from librarian import apply as ap
from librarian import proposals


class ApplyCase(RepoCase):
    def target(self, rel, line=None) -> proposals.Target:
        sha = proposals.file_sha256(self.root / rel)
        return proposals.Target(path=rel, base_sha256=sha, line=line)

    def apply(self, p, **kw) -> ap.Outcome:
        return ap.apply_one(self.cfg(), p, **kw)


class FixTests(ApplyCase):
    def test_fix_applies(self):
        self.write("d.md", "the count is 20 stations today\n")
        p = proposals.make(
            "fix", [self.target("d.md", 1)], {"replace": {"old": "20 stations", "new": "17 stations"}}
        )
        oc = self.apply(p)
        self.assertEqual(oc.result, ap.APPLIED)
        self.assertIn("17 stations", self.read("d.md"))
        self.assertNotIn("20 stations", self.read("d.md"))

    def test_fix_idempotent_zero_diff(self):
        self.write("d.md", "value is 20 here\n")
        p = proposals.make("fix", [self.target("d.md", 1)], {"replace": {"old": "20", "new": "17"}})
        self.assertEqual(self.apply(p).result, ap.APPLIED)
        after_first = self.read("d.md")
        # A re-drafted proposal points at the now-changed file; rebuild its guard.
        p2 = proposals.make("fix", [self.target("d.md", 1)], {"replace": {"old": "20", "new": "17"}})
        oc2 = self.apply(p2)
        self.assertEqual(oc2.result, ap.NOOP)
        self.assertEqual(self.read("d.md"), after_first)  # zero diff

    def test_fix_stale_when_file_changed(self):
        self.write("d.md", "value is 20\n")
        p = proposals.make("fix", [self.target("d.md", 1)], {"replace": {"old": "20", "new": "17"}})
        self.write("d.md", "value is 20 (edited elsewhere)\n")  # someone else touched it
        oc = self.apply(p)
        self.assertEqual(oc.result, ap.STALE)
        self.assertIn("20", self.read("d.md"))  # untouched

    def test_fix_truth_table_both_absent(self):
        self.write("d.md", "totally unrelated content\n")
        # forge a proposal whose guard matches the file but whose old/new are absent
        p = proposals.make("fix", [self.target("d.md", 1)], {"replace": {"old": "AAA", "new": "BBB"}})
        oc = self.apply(p)
        self.assertEqual(oc.result, ap.STALE)

    def test_fix_drop_marker(self):
        body = (
            "---\nid: d\ntitle: D\ndomain: x\nstatus: draft\nlast_verified: 2026-06-01\n"
            "recheck: 90d\nread_when: [a task]\ntags: []\n---\n"
            "<!-- KB-CONTRADICTED: min dock is 15 -->\n"
            "The minimum dock count is 20.\n"
        )
        self.write("d.md", body)
        p = proposals.make(
            "fix",
            [self.target("d.md", 12)],
            {"replace": {"old": "is 20.", "new": "is 15."}, "drop_marker": True},
        )
        oc = self.apply(p)
        self.assertEqual(oc.result, ap.APPLIED)
        text = self.read("d.md")
        self.assertIn("is 15.", text)
        self.assertNotIn("KB-CONTRADICTED", text)


class MarkerTests(ApplyCase):
    MARKED = (
        "---\nid: d\ntitle: D\ndomain: x\nstatus: draft\nlast_verified: 2026-06-01\n"
        "recheck: 90d\nread_when: [a task]\ntags: []\n---\n"
        "<!-- KB-CONTRADICTED: kept on purpose -->\n"
        "A transcript line we keep verbatim.\n"
    )

    def test_ack_adds_marker_and_is_idempotent(self):
        # MARKED uses the legacy `<!-- KB-CONTRADICTED -->` token -> proves dual-parse:
        # ack recognizes the old marker and writes the new `librarian:ack` token.
        self.write("d.md", self.MARKED)
        p = proposals.make("ack", [self.target("d.md", 12)], {"mark": "librarian:ack"})
        self.assertEqual(self.apply(p).result, ap.APPLIED)
        self.assertIn("librarian:ack", self.read("d.md"))
        after = self.read("d.md")
        p2 = proposals.make("ack", [self.target("d.md", 12)], {"mark": "librarian:ack"})
        self.assertEqual(self.apply(p2).result, ap.NOOP)
        self.assertEqual(self.read("d.md"), after)

    def test_ack_stale_without_marker(self):
        self.write("d.md", make_doc())
        p = proposals.make("ack", [self.target("d.md", 3)], {"mark": "KB-ACK"})
        self.assertEqual(self.apply(p).result, ap.STALE)


class SetReadWhenTests(ApplyCase):
    def test_sets_and_idempotent(self):
        self.write("d.md", make_doc(read_when=""))
        p = proposals.make(
            "set_read_when", [self.target("d.md")], {"read_when": ["when onboarding", "before ETL work"]}
        )
        self.assertEqual(self.apply(p).result, ap.APPLIED)
        from librarian import frontmatter

        meta = frontmatter.parse(self.read("d.md")).meta
        self.assertEqual(meta["read_when"], ["when onboarding", "before ETL work"])
        p2 = proposals.make(
            "set_read_when", [self.target("d.md")], {"read_when": ["when onboarding", "before ETL work"]}
        )
        self.assertEqual(self.apply(p2).result, ap.NOOP)


class ArchiveTests(ApplyCase):
    def test_archive_moves_and_flips_status(self):
        self.write("docs/old.md", make_doc(status="draft"))
        p = proposals.make(
            "archive", [self.target("docs/old.md")], {"to": "_archive/old.md", "set_status": "archived"}
        )
        self.assertEqual(self.apply(p).result, ap.APPLIED)
        self.assertFalse((self.root / "docs/old.md").exists())
        self.assertTrue((self.root / "_archive/old.md").exists())
        self.assertIn("status: archived", self.read("_archive/old.md"))

    def test_archive_idempotent_noop(self):
        self.write("docs/old.md", make_doc(status="draft"))
        p = proposals.make(
            "archive", [self.target("docs/old.md")], {"to": "_archive/old.md", "set_status": "archived"}
        )
        self.apply(p)
        # re-drafted proposal: source now gone, guard '' matches the missing file
        p2 = proposals.make(
            "archive", [self.target("docs/old.md")], {"to": "_archive/old.md", "set_status": "archived"}
        )
        self.assertEqual(self.apply(p2).result, ap.NOOP)


class MergeTests(ApplyCase):
    def _pair(self):
        self.write("docs/a.md", make_doc(id="a", title="A"))
        self.write("docs/b.md", make_doc(id="b", title="B"))
        return proposals.make(
            "merge",
            [self.target("docs/a.md"), self.target("docs/b.md")],
            {
                "canonical": "docs/a.md",
                "redundant": "docs/b.md",
                "carry_over": ["Section X"],
                "then_archive": True,
            },
        )

    def test_merge_archives_redundant(self):
        p = self._pair()
        self.assertEqual(self.apply(p).result, ap.APPLIED)
        self.assertTrue((self.root / "docs/a.md").exists())  # canonical stays
        self.assertFalse((self.root / "docs/b.md").exists())  # redundant archived
        self.assertTrue((self.root / "_archive/b.md").exists())

    def test_merge_multifile_staleness_refuses(self):
        p = self._pair()
        # mutate the SECOND target after drafting -> apply must refuse the whole thing
        self.write("docs/b.md", make_doc(id="b", title="B edited"))
        oc = self.apply(p)
        self.assertEqual(oc.result, ap.STALE)
        self.assertIn("docs/b.md", oc.detail)
        self.assertTrue((self.root / "docs/a.md").exists())
        self.assertTrue((self.root / "docs/b.md").exists())  # nothing moved

    def test_merge_folds_carry_over_into_canonical(self):
        # Item 3: apply OWNS the fold now (no hand-edit first). The carry_over text lands
        # in the canonical, and the merge does NOT false-STALE on its own edit.
        p = self._pair()
        oc = self.apply(p)
        self.assertEqual(oc.result, ap.APPLIED)
        self.assertIn("Section X", self.read("docs/a.md"))

    def test_merge_refuses_external_canonical_change(self):
        self.write("docs/a.md", make_doc(id="a", title="A"))
        self.write("docs/b.md", make_doc(id="b", title="B"))
        draft_hash = proposals.file_sha256(self.root / "docs/a.md")
        # someone edits the canonical externally after drafting (and carry not yet folded)
        self.write("docs/a.md", make_doc(id="a", title="A edited elsewhere"))
        p = proposals.make(
            "merge",
            [self.target("docs/b.md")],  # only the redundant is a generic-guarded target
            {
                "canonical": "docs/a.md",
                "redundant": "docs/b.md",
                "carry_over": ["Section X"],
                "canonical_sha256": draft_hash,
                "then_archive": True,
            },
        )
        oc = self.apply(p)
        self.assertEqual(oc.result, ap.STALE)
        self.assertIn("canonical", oc.detail)
        self.assertTrue((self.root / "docs/b.md").exists())  # nothing moved


class WritebackSelectTests(ApplyCase):
    def _ack(self, approved=True):
        self.write("docs/x.md", make_doc())
        return proposals.make(
            "ack", [self.target("docs/x.md", line=3)], {"mark": "librarian:disputed"}, approved=approved
        )

    def test_all_skips_applied(self):
        p = self._ack()
        self.assertEqual([q.id for q in ap.select([p], only=None, all_approved=True)], [p.id])
        p.applied = True  # item 4: once applied, --all must not re-select it
        self.assertEqual(ap.select([p], only=None, all_approved=True), [])
        # --only is explicit: re-apply is still allowed
        self.assertEqual([q.id for q in ap.select([p], only={p.id}, all_approved=False)], [p.id])

    def test_applied_fields_roundtrip_and_id_stable(self):
        p = self._ack()
        self.assertNotIn("applied", p.to_dict())  # unapplied serializes as before
        p.applied, p.applied_at, p.result = True, "2026-07-10", "applied"
        d = p.to_dict()
        self.assertEqual((d["applied"], d["applied_at"], d["result"]), (True, "2026-07-10", "applied"))
        p2 = proposals.from_dict(d)
        self.assertTrue(p2.applied)
        self.assertEqual(p2.applied_at, "2026-07-10")
        self.assertEqual(p2.id, p.id)  # writeback fields never move the id


class AddCheckTests(ApplyCase):
    def test_registers_and_config_sees_it(self):
        self.write("docs/x.md", make_doc())
        check = {
            "id": "cov",
            "source": "local",
            "kind": "track",
            "cmd": "echo 3",
            "extract": "scalar",
            "doc": "docs/x.md",
        }
        p = proposals.make(
            "add_check", [self.target("docs/x.md")], {"check_id": "cov", "source": "local", "check": check}
        )
        self.assertEqual(self.apply(p).result, ap.APPLIED)
        from librarian import config

        merged = config.load(self.root)
        self.assertIn("cov", {c.id for c in merged.checks})
        # idempotent
        p2 = proposals.make(
            "add_check", [self.target("docs/x.md")], {"check_id": "cov", "source": "local", "check": check}
        )
        self.assertEqual(self.apply(p2).result, ap.NOOP)


class EnrichCreateTests(ApplyCase):
    def _prop(self):
        # target is the not-yet-existing new file: its guard is '' (missing)
        t = proposals.Target(path="docs/ops/backup.md", base_sha256="")
        return proposals.make(
            "enrich_create",
            [t],
            {
                "new_path": "docs/ops/backup.md",
                "status": "provisional",
                "frontmatter": {
                    "id": "ops-backup",
                    "title": "Backup",
                    "domain": "ops",
                    "status": "provisional",
                },
                "body": "# Backup\n\nprovisional\n",
            },
        )

    def test_creates_provisional_doc(self):
        oc = self.apply(self._prop())
        self.assertEqual(oc.result, ap.APPLIED)
        text = self.read("docs/ops/backup.md")
        self.assertIn("status: provisional", text)
        self.assertIn("# Backup", text)

    def test_refuses_to_clobber_existing_path(self):
        self.write("docs/ops/backup.md", "already here\n")
        oc = self.apply(self._prop())
        self.assertEqual(oc.result, ap.STALE)  # guard '' != existing hash
        self.assertEqual(self.read("docs/ops/backup.md"), "already here\n")


class ResolveAbsenceTests(ApplyCase):
    def test_informational_no_file_change(self):
        self.write("d.md", make_doc())
        before = self.read("d.md")
        p = proposals.make(
            "resolve_absence",
            [self.target("d.md", 1)],
            {"verdict": "stale_claim", "filled_by": "docs/answer.md"},
        )
        self.assertEqual(self.apply(p).result, ap.APPLIED)
        self.assertEqual(self.read("d.md"), before)


class LogTests(ApplyCase):
    def test_apply_log_written(self):
        self.write("d.md", "value 20\n")
        p = proposals.make("fix", [self.target("d.md", 1)], {"replace": {"old": "20", "new": "17"}})
        cfg = self.cfg()
        oc = ap.apply_one(cfg, p)
        ap.log_outcomes(cfg, [oc], now=1000)
        line = self.read("_index/apply-log.jsonl").strip()
        rec = json.loads(line)
        self.assertEqual(rec["id"], p.id)
        self.assertEqual(rec["result"], ap.APPLIED)
        self.assertEqual(rec["ts"], 1000)


if __name__ == "__main__":
    unittest.main()
