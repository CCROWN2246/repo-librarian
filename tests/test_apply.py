"""`librarian apply` tests: the fix truth-table, idempotency (twice = zero diff),
single- and multi-file staleness refusal, every typed handler, and the apply-log.
"""

from __future__ import annotations

import json
import unittest

from helpers import RepoCase, make_doc
from librarian import apply as ap
from librarian import frontmatter, proposals


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

    def test_merge_unions_read_when_frontmatter(self):
        # 3.1: a structured read_when op UNIONS into the canonical's frontmatter (not
        # replace), dedups, and never appends prose to the body.
        self.write("docs/a.md", make_doc(id="a", read_when="existing phrase"))
        self.write("docs/b.md", make_doc(id="b"))
        p = proposals.make(
            "merge",
            [self.target("docs/a.md"), self.target("docs/b.md")],
            {
                "canonical": "docs/a.md",
                "redundant": "docs/b.md",
                "carry_over": [{"target": "read_when", "content": ["new phrase", "existing phrase"]}],
                "then_archive": True,
            },
        )
        self.assertEqual(self.apply(p).result, ap.APPLIED)
        meta = frontmatter.parse(self.read("docs/a.md")).meta
        self.assertEqual(meta["read_when"], ["existing phrase", "new phrase"])  # unioned + deduped

    def test_fold_carry_over_is_idempotent(self):
        # 3.1 per-target idempotency: folding twice unions read_when ONCE (no dup) and
        # never false-STALEs the canonical (the whole-doc `carry in ctext` bug).
        self.write("docs/a.md", make_doc(id="a", read_when="existing"))
        self.write("docs/b.md", make_doc(id="b"))
        p = proposals.make(
            "merge",
            [self.target("docs/a.md"), self.target("docs/b.md")],
            {
                "canonical": "docs/a.md",
                "redundant": "docs/b.md",
                "carry_over": [{"target": "read_when", "content": ["new"]}],
            },
        )
        cfg = self.cfg()
        self.assertIsNone(ap._fold_carry_over(cfg, p, dry=False))  # run 1: folds
        first = self.read("docs/a.md")
        self.assertIsNone(ap._fold_carry_over(cfg, p, dry=False))  # run 2: NOOP, not STALE
        self.assertEqual(self.read("docs/a.md"), first)  # byte-identical: no dup, no re-write
        self.assertEqual(frontmatter.parse(first).meta["read_when"], ["existing", "new"])

    def test_malformed_carry_over_rejected_at_propose(self):
        # D2 (eng-review): a malformed structured carry_over fails LOUD at propose time,
        # never silently at apply. Legacy str/list[str] + valid structured pass.
        self.write("docs/a.md", make_doc(id="a"))
        self.write("docs/b.md", make_doc(id="b"))
        base_action = {"canonical": "docs/a.md", "redundant": "docs/b.md"}
        targets = [{"path": "docs/a.md"}, {"path": "docs/b.md"}]

        def _partial(carry):
            return {"type": "merge", "targets": targets, "action": {**base_action, "carry_over": carry}}

        with self.assertRaises(proposals.ProposalError):
            proposals.build_from_partial(self.cfg(), _partial([{"target": "bogus", "content": "x"}]))
        with self.assertRaises(proposals.ProposalError):
            proposals.build_from_partial(self.cfg(), _partial([{"target": "body", "content": ""}]))
        # valid shapes round-trip
        self.assertEqual(
            proposals.build_from_partial(
                self.cfg(), _partial([{"target": "read_when", "content": ["p"]}])
            ).type,
            "merge",
        )
        self.assertEqual(proposals.build_from_partial(self.cfg(), _partial(["body text"])).type, "merge")


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


class IntraBatchCreationTests(ApplyCase):
    """5.3: a paired enrich_create + add_check must register the check regardless of the
    id-hash apply order, WITHOUT weakening the round-2 external-change gate. The check's
    target is absent at draft (base_sha256 == '') — after enrich_create writes the doc, a
    naive stale gate would false-STALE the check and orphan it."""

    NEWP = "docs/ops/backup.md"

    def _enrich(self):
        return proposals.make(
            "enrich_create",
            [proposals.Target(path=self.NEWP, base_sha256="")],
            {
                "new_path": self.NEWP,
                "status": "provisional",
                "frontmatter": {
                    "id": "ops-backup",
                    "title": "Backup",
                    "domain": "ops",
                    "status": "provisional",
                },
                "body": "# Backup\n\nprovisional\n",
            },
            provenance=proposals.Provenance(evidence="daily at 02:00 UTC (from cron)"),
        )

    def _check(self):
        chk = {
            "id": "backup-cov",
            "source": "local",
            "kind": "track",
            "cmd": "echo 1",
            "extract": "scalar",
            "doc": self.NEWP,
        }
        return proposals.make(
            "add_check",
            [proposals.Target(path=self.NEWP, base_sha256="")],
            {"check_id": "backup-cov", "source": "local", "check": chk},
        )

    def _assert_pair_registers(self, batch):
        outcomes = ap.apply_batch(self.cfg(), batch)
        by_type = {o.type: o for o in outcomes}
        self.assertEqual(by_type["enrich_create"].result, ap.APPLIED)
        self.assertEqual(by_type["add_check"].result, ap.APPLIED, by_type["add_check"].detail)
        self.assertTrue((self.root / self.NEWP).exists())
        ids = {c.get("id") for c in proposals.load_generated_checks(self.cfg())}
        self.assertIn("backup-cov", ids)

    def test_registers_with_enrich_first(self):
        # The dangerous id-order: enrich_create runs first, creating the doc, so the
        # add_check's absent-at-draft guard ('') now mismatches the real on-disk hash.
        # Intra-batch awareness must recognize we created it and register the check.
        self._assert_pair_registers([self._enrich(), self._check()])

    def test_registers_with_check_first(self):
        # The already-safe order (add_check runs while the doc is still absent). Proves the
        # fix does not regress it — both orders must land the check.
        self._assert_pair_registers([self._check(), self._enrich()])

    def test_existed_at_draft_still_refuses_external_change(self):
        # An add_check whose target EXISTED at draft (real base_sha256) that then changed
        # externally must STILL stale — intra-batch awareness must not weaken the gate.
        self.write("docs/x.md", make_doc())
        chk = {
            "id": "c",
            "source": "local",
            "kind": "track",
            "cmd": "echo 1",
            "extract": "scalar",
            "doc": "docs/x.md",
        }
        ac = proposals.make("add_check", [self.target("docs/x.md")], {"check_id": "c", "check": chk})
        self.write("docs/x.md", make_doc(title="edited elsewhere"))  # external change
        outcomes = ap.apply_batch(self.cfg(), [ac])
        self.assertEqual(outcomes[0].result, ap.STALE)
        self.assertEqual(proposals.load_generated_checks(self.cfg()), [])  # never registered

    def test_add_check_orphan_when_doc_not_created_in_batch(self):
        # The doc exists but was NOT created by an enrich_create in this batch (e.g. its
        # paired enrich_create was refused, or a crash-reapply). The check must FAIL LOUD,
        # never silently register against a doc we did not vouch for creating.
        self.write(self.NEWP, "pre-existing, not ours\n")
        outcomes = ap.apply_batch(self.cfg(), [self._check()])  # no enrich_create in the batch
        self.assertEqual(outcomes[0].result, ap.STALE)
        self.assertIn("absent at draft", outcomes[0].detail)
        self.assertEqual(proposals.load_generated_checks(self.cfg()), [])

    def test_apply_batch_dry_run_writes_nothing(self):
        # Dry-run threads the same creation awareness (both preview APPLIED) but writes
        # neither the doc nor the check.
        outcomes = ap.apply_batch(self.cfg(), [self._enrich(), self._check()], dry_run=True)
        self.assertEqual([o.result for o in outcomes], [ap.APPLIED, ap.APPLIED])
        self.assertFalse((self.root / self.NEWP).exists())
        self.assertEqual(proposals.load_generated_checks(self.cfg()), [])


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
