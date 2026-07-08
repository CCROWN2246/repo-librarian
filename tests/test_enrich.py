"""B5 enrichment: deterministic gap detection, the `librarian enrich` worklist CLI,
and the provisional-doc quarantine TTL surfaced in staleness."""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from helpers import RepoCase, make_doc
from librarian import cli, config, enrich, proposals


def _catalog(cfg):
    from librarian import catalog, registry

    arts, errs = registry.load(cfg)
    return catalog.build(cfg, config.today(), arts, errs)


class GapDetectionTests(RepoCase):
    def test_uncovered_files_are_gaps(self):
        self.write("docs/a.md", make_doc(id="a", read_when="a task"))
        self.write("etl/pipeline.py", "print('etl')\n")  # covered_ext .py, unregistered
        cfg = self.cfg()
        gaps = enrich.detect_gaps(cfg, _catalog(cfg), proposals.load(cfg))
        refs = {(g.kind, g.ref) for g in gaps}
        self.assertIn(("uncovered", "etl/pipeline.py"), refs)

    def test_confirmed_absence_is_a_gap(self):
        self.write("docs/a.md", make_doc(id="a", read_when="a task"))
        cfg = self.cfg()
        p = proposals.make(
            "resolve_absence",
            [proposals.Target(path="docs/a.md", base_sha256="x" * 64, line=4)],
            {"verdict": "confirmed_gap", "domain": "ops"},
            rationale="no backup doc exists",
        )
        proposals.save(cfg, [p])
        gaps = enrich.detect_gaps(cfg, _catalog(cfg), proposals.load(cfg))
        absence = [g for g in gaps if g.kind == "confirmed_absence"]
        self.assertEqual(len(absence), 1)
        self.assertEqual(absence[0].ref, "docs/a.md:4")
        self.assertEqual(absence[0].domain, "ops")

    def test_stale_claim_is_not_a_gap(self):
        # only confirmed_gap verdicts enrich; a stale_claim is handled by a fix
        self.write("docs/a.md", make_doc(id="a", read_when="a task"))
        cfg = self.cfg()
        p = proposals.make(
            "resolve_absence",
            [proposals.Target(path="docs/a.md", base_sha256="x" * 64, line=4)],
            {"verdict": "stale_claim", "filled_by": "docs/b.md"},
        )
        proposals.save(cfg, [p])
        gaps = enrich.detect_gaps(cfg, _catalog(cfg), proposals.load(cfg))
        self.assertEqual([g for g in gaps if g.kind == "confirmed_absence"], [])


class EnrichCliTests(RepoCase):
    def run_sub(self, command, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([command, "--root", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_enrich_lists_gaps_and_sources(self):
        self.write("docs/a.md", make_doc(id="a", read_when="a task"))
        self.write("etl/pipeline.py", "x\n")
        self.write(
            ".librarian.toml",
            'schema_version = 1\n[verify.sources.warehouse]\ncommand = "psql -c {arg}"\n',
        )
        code, out, _ = self.run_sub("enrich", "--json")
        self.assertEqual(code, 1)  # gaps exist -> findings
        data = json.loads(out)
        self.assertTrue(any(g["ref"] == "etl/pipeline.py" for g in data["gaps"]))
        self.assertIn("warehouse", data["sources"])

    def test_enrich_clean_exit0(self):
        self.write("docs/a.md", make_doc(id="a", read_when="a task"))
        code, out, _ = self.run_sub("enrich", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["count"], 0)


class ProvisionalQuarantineTests(RepoCase):
    def test_provisional_past_ttl_flagged_unaudited(self):
        self.write(".librarian.toml", "schema_version = 1\n[enrich]\nprovisional_ttl_days = 10\n")
        # RepoCase.TODAY = 2026-07-02; 40 days earlier = well past a 10-day TTL
        self.write(
            "docs/draft.md",
            make_doc(id="draft", status="provisional", last_verified="2026-05-23", read_when="x"),
        )
        res = _catalog(config.load(self.root))
        reasons = {id_: why for (id_, _p, why) in res.stale}
        self.assertIn("un-audited enrichment", reasons["draft"])
        self.assertIn("status=provisional", reasons["draft"])

    def test_provisional_within_ttl_not_flagged_unaudited(self):
        self.write(".librarian.toml", "schema_version = 1\n[enrich]\nprovisional_ttl_days = 90\n")
        self.write(
            "docs/draft.md",
            make_doc(id="draft", status="provisional", last_verified="2026-06-30", read_when="x"),
        )
        res = _catalog(config.load(self.root))
        reasons = {id_: why for (id_, _p, why) in res.stale}
        self.assertIn("status=provisional", reasons["draft"])
        self.assertNotIn("un-audited", reasons["draft"])


if __name__ == "__main__":
    unittest.main()
