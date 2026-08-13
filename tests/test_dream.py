import datetime
import unittest

from helpers import RepoCase, make_doc
from librarian import catalog, config, dream, registry


class FailingChecksBucketTests(unittest.TestCase):
    def test_excluded_from_gate_and_hash(self):
        wl = dream.Worklist()
        h0 = wl.content_hash()
        wl.failing_checks = [{"id": "c1", "status": "DRIFT", "doc": "d.md", "expect": "9", "live": "10"}]
        self.assertTrue(wl.empty)  # a failing check does not make the worklist "non-empty"
        self.assertEqual(wl.total, 0)  # excluded from total
        self.assertEqual(wl.counts()["failing_checks"], 1)  # but visible in counts/to_dict
        self.assertIn("failing_checks", wl.to_dict())
        self.assertEqual(wl.content_hash(), h0)  # never re-arms the delta-gate nudge (eng-review 7)


def _wl(cfg):
    arts, errors = registry.load(cfg)
    res = catalog.build(cfg, config.today(), arts, errors)
    return res, dream.from_catalog_result(res, cfg.dream_merge_similarity)


class MergeCandidateTests(RepoCase):
    def test_near_duplicates_same_domain_flagged(self):
        self.write(
            "docs/a.md",
            make_doc(
                id="a",
                title="Carrier scorecard grading",
                domain="ops",
                read_when="grade carriers, scorecard rules",
            ),
        )
        self.write(
            "docs/b.md",
            make_doc(
                id="b",
                title="Carrier scorecard grading rules",
                domain="ops",
                read_when="grade carriers, scorecard",
            ),
        )
        _, wl = self._wl()
        self.assertEqual(len(wl.merge_candidates), 1)
        pair = wl.merge_candidates[0]
        self.assertEqual({pair["a"], pair["b"]}, {"docs/a.md", "docs/b.md"})
        self.assertGreaterEqual(pair["similarity"], 0.6)

    def test_different_domains_not_paired(self):
        self.write(
            "docs/a.md",
            make_doc(
                id="a",
                title="Carrier scorecard grading",
                domain="ops",
                read_when="grade carriers, scorecard rules",
            ),
        )
        self.write(
            "docs/b.md",
            make_doc(
                id="b",
                title="Carrier scorecard grading",
                domain="finance",
                read_when="grade carriers, scorecard rules",
            ),
        )
        _, wl = self._wl()
        self.assertEqual(wl.merge_candidates, [])

    def test_archived_excluded(self):
        self.write(
            "docs/a.md",
            make_doc(
                id="a", title="Lane pricing floors", domain="fin", read_when="price a lane, pricing floors"
            ),
        )
        self.write(
            "docs/b.md",
            make_doc(
                id="b",
                title="Lane pricing floors",
                domain="fin",
                status="archived",
                read_when="price a lane, pricing floors",
            ),
        )
        _, wl = self._wl()
        self.assertEqual(wl.merge_candidates, [])

    def test_threshold_config_respected(self):
        self.write(
            "docs/a.md",
            make_doc(
                id="a", title="Dock scheduling windows", domain="ops", read_when="book a dock, dock windows"
            ),
        )
        self.write(
            "docs/b.md",
            make_doc(
                id="b",
                title="Dock scheduling appointments",
                domain="ops",
                read_when="book a dock, appointment cutoffs",
            ),
        )
        # high threshold -> no candidate; low -> candidate (write full config each time)
        self.write(".librarian.toml", "schema_version = 1\n[dream]\nmerge_similarity = 0.95\n")
        _, wl_hi = _wl(config.load(self.root))
        self.assertEqual(wl_hi.merge_candidates, [])
        self.write(".librarian.toml", "schema_version = 1\n[dream]\nmerge_similarity = 0.2\n")
        _, wl_lo = _wl(config.load(self.root))
        self.assertEqual(len(wl_lo.merge_candidates), 1)

    def _wl(self, extra=""):
        return _wl(self.cfg(extra))


class WorklistTests(RepoCase):
    def test_read_when_todos(self):
        self.write("docs/empty.md", make_doc(id="empty", read_when=""))
        self.write("docs/todo.md", make_doc(id="todo", read_when="TODO write these"))
        self.write("docs/good.md", make_doc(id="good", read_when="a real task"))
        _, wl = _wl(self.cfg())
        paths = {t["path"] for t in wl.read_when_todos}
        self.assertIn("docs/empty.md", paths)
        self.assertIn("docs/todo.md", paths)
        self.assertNotIn("docs/good.md", paths)

    def test_retirement_candidates_surface_terminal_status(self):
        self.write("docs/live.md", make_doc(id="live", status="authoritative", read_when="a task"))
        self.write("docs/retired.md", make_doc(id="retired", status="retired", read_when="a task"))
        self.write("docs/done.md", make_doc(id="done", status="shipped", read_when="a task"))
        _, wl = _wl(self.cfg("\n[taxonomy]\nstatuses = ['authoritative', 'retired', 'shipped']\n"))
        paths = {r["path"] for r in wl.retirement_candidates}
        self.assertEqual(paths, {"docs/retired.md", "docs/done.md"})
        self.assertNotIn("docs/live.md", paths)
        ev = {r["path"]: r["evidence"] for r in wl.retirement_candidates}
        self.assertEqual(ev["docs/retired.md"], "status=retired")

    def test_retirement_empty_when_all_live(self):
        self.write("docs/a.md", make_doc(id="a", status="authoritative", read_when="a task"))
        _, wl = _wl(self.cfg())
        self.assertEqual(wl.retirement_candidates, [])

    def test_coverage_gaps_in_worklist_but_not_in_nudge(self):
        # an authoritative doc asserting an unguarded number is a coverage gap...
        self.write("docs/a.md", make_doc(id="a", read_when="a task") + "\nThe table has 9 columns.\n")
        _, wl = _wl(self.cfg())
        self.assertTrue(any(g["path"] == "docs/a.md" for g in wl.coverage_gaps))
        # ...but coverage alone does NOT make the dream due (no nudge fatigue)
        self.assertTrue(wl.empty)
        self.assertEqual(wl.total, 0)

    def test_conflicts_and_absence_surface(self):
        body = make_doc(id="c", read_when="x") + (
            "\nclaim <!-- KB-CONTRADICTED: conflicts with [verified: y] -->\n"
            "\nThe rate source is not yet identified.\n"
        )
        self.write("docs/c.md", body)
        _, wl = _wl(self.cfg())
        self.assertEqual(len(wl.open_conflicts), 1)
        self.assertEqual(len(wl.absence_claims), 1)

    def test_json_builder_matches_result_builder(self):
        import json

        from librarian import render

        self.write(
            "docs/a.md",
            make_doc(
                id="a", title="Carrier scorecard grading", domain="ops", read_when="grade carriers, scorecard"
            ),
        )
        self.write(
            "docs/b.md",
            make_doc(
                id="b",
                title="Carrier scorecard grading rules",
                domain="ops",
                read_when="grade carriers, scorecard",
            ),
        )
        self.write("docs/t.md", make_doc(id="t", read_when=""))
        cfg = self.cfg()
        res, wl_res = _wl(cfg)
        data = json.loads(render.catalog_json(res))
        wl_json = dream.from_catalog_json(data, cfg.dream_merge_similarity)
        self.assertEqual(wl_res.content_hash(), wl_json.content_hash())


class DueGateTests(RepoCase):
    def _empty_wl(self):
        return dream.Worklist()

    def _busy_wl(self):
        return dream.Worklist(open_conflicts=[{"path": "d.md", "line": 3, "text": "x"}])

    def test_empty_never_due(self):
        due, _ = dream.is_due(self.cfg(), self._empty_wl())
        self.assertFalse(due)

    def test_disabled_never_due(self):
        cfg = self.cfg("[dream]\nnudge_after_days = 0\n")
        due, reason = dream.is_due(cfg, self._busy_wl())
        self.assertFalse(due)
        self.assertIn("disabled", reason)

    def test_never_dreamt_is_due(self):
        due, reason = dream.is_due(self.cfg(), self._busy_wl())
        self.assertTrue(due)
        self.assertIn("never", reason)

    def test_mark_done_then_not_due(self):
        cfg = self.cfg()
        wl = self._busy_wl()
        dream.mark_done(cfg, wl, now=1_000_000)
        due, _ = dream.is_due(cfg, wl, now=1_000_100)
        self.assertFalse(due)

    def test_changed_worklist_is_due_again(self):
        cfg = self.cfg()
        wl1 = self._busy_wl()
        dream.mark_done(cfg, wl1, now=1_000_000)
        wl2 = dream.Worklist(
            open_conflicts=[
                {"path": "d.md", "line": 3, "text": "x"},
                {"path": "e.md", "line": 9, "text": "z"},
            ]
        )
        due, reason = dream.is_due(cfg, wl2, now=1_000_100)
        self.assertTrue(due)
        self.assertIn("changed", reason)

    def test_aged_past_nudge_is_due(self):
        cfg = self.cfg("[dream]\nnudge_after_days = 7\n")
        wl = self._busy_wl()
        dream.mark_done(cfg, wl, now=1_000_000)
        later = 1_000_000 + 8 * 86400
        due, reason = dream.is_due(cfg, wl, now=later)
        self.assertTrue(due)
        self.assertIn("unreviewed", reason)


class ContentHashTests(unittest.TestCase):
    def test_stable_and_sensitive(self):
        a = dream.Worklist(open_conflicts=[{"path": "d.md", "line": 1, "text": "x"}])
        b = dream.Worklist(open_conflicts=[{"path": "d.md", "line": 1, "text": "x"}])
        c = dream.Worklist(open_conflicts=[{"path": "d.md", "line": 2, "text": "x"}])
        self.assertEqual(a.content_hash(), b.content_hash())
        self.assertNotEqual(a.content_hash(), c.content_hash())


class ReportTests(unittest.TestCase):
    """The unattended-run artifact. Deterministic half only: cron computes the worklist,
    a human does the judgment in-chat."""

    def _wl(self):
        return dream.Worklist(
            open_conflicts=[{"path": "d.md", "line": 3, "text": "x"}],
            read_when_todos=[
                {"path": "q.sql", "id": "q", "kind": "sql", "title": "Q", "domain": "d", "read_when": []}
            ],
        )

    def test_report_is_deterministic(self):
        today = datetime.date(2026, 8, 13)
        a = dream.render_report(self._wl(), today, True, "never dreamt")
        b = dream.render_report(self._wl(), today, True, "never dreamt")
        self.assertEqual(a, b)

    def test_report_lists_every_populated_bucket(self):
        out = dream.render_report(self._wl(), datetime.date(2026, 8, 13), True, "never dreamt")
        self.assertIn("Open conflicts (1)", out)
        self.assertIn("d.md:3", out)
        self.assertIn("Routing TODOs (1)", out)
        self.assertIn("q.sql", out)
        self.assertIn("**DUE**", out)

    def test_empty_worklist_says_so(self):
        out = dream.render_report(dream.Worklist(), datetime.date(2026, 8, 13), False, "nothing to do")
        self.assertIn("Nothing outstanding", out)
        self.assertIn("**Not due**", out)

    def test_report_states_no_proposals_were_drafted(self):
        # the honesty line: an unattended run computes, it never generates
        out = dream.render_report(dream.Worklist(), datetime.date(2026, 8, 13), False, "clean")
        self.assertIn("no proposals were drafted", out)


class ReportCliTests(RepoCase):
    def run_sub(self, command, *argv):
        import contextlib
        import io

        from librarian import cli

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([command, "--root", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()

    def seed(self):
        self.write("docs/a.md", make_doc(id="a", status="retired", read_when=""))
        self.run_sub("index")

    def test_cron_writes_report_and_greeting_announces_it(self):
        self.seed()
        code, out, _ = self.run_sub("dream", "--report")
        self.assertEqual(code, 1)  # due
        report = self.root / "_index" / dream.REPORT_FILE
        self.assertTrue(report.is_file())
        _, hook_out, _ = self.run_sub("status", "--hook")
        self.assertIn("a dream report is waiting", hook_out)

    def test_rerun_is_byte_identical(self):
        self.seed()
        self.run_sub("dream", "--report")
        first = (self.root / "_index" / dream.REPORT_FILE).read_text(encoding="utf-8")
        self.run_sub("dream", "--report")
        self.assertEqual((self.root / "_index" / dream.REPORT_FILE).read_text(encoding="utf-8"), first)

    def test_mark_done_clears_the_report(self):
        self.seed()
        self.run_sub("dream", "--report")
        self.run_sub("dream", "--mark-done")
        self.assertFalse((self.root / "_index" / dream.REPORT_FILE).exists())
        _, hook_out, _ = self.run_sub("status", "--hook")
        self.assertNotIn("dream report is waiting", hook_out)


if __name__ == "__main__":
    unittest.main()
