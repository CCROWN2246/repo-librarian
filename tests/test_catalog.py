import unittest

from helpers import RepoCase, make_doc
from librarian import catalog, config, registry, render


class CatalogTests(RepoCase):
    def build(self, extra_toml: str = ""):
        cfg = self.cfg(extra_toml)
        arts, errors = registry.load(cfg)
        return cfg, catalog.build(cfg, config.today(), arts, errors)

    def test_good_doc_not_flagged(self):
        self.write("docs/a.md", make_doc(last_verified="2026-07-01"))
        _, res = self.build()
        self.assertEqual(len(res.items), 1)
        self.assertEqual(res.stale, [])
        self.assertEqual(res.missing_fm, [])

    def test_missing_frontmatter(self):
        self.write("docs/plain.md", "# no frontmatter\n")
        _, res = self.build()
        self.assertEqual(res.missing_fm, ["docs/plain.md"])

    def test_provisional_flagged(self):
        self.write("docs/a.md", make_doc(status="provisional", last_verified="2026-07-01"))
        _, res = self.build()
        self.assertTrue(any("status=provisional" in why for _, _, why in res.stale))

    def test_overdue_vs_fresh(self):
        self.write("docs/old.md", make_doc(id="old", last_verified="2026-01-01", recheck="30d"))
        self.write("docs/new.md", make_doc(id="new", last_verified="2026-07-01", recheck="30d"))
        _, res = self.build()
        whys = {i: why for i, _, why in res.stale}
        self.assertIn("old", whys)
        self.assertIn("overdue", whys["old"])
        self.assertNotIn("new", whys)

    def test_missing_required_fields(self):
        self.write("docs/a.md", "---\nid: a\ntitle: T\n---\nbody\n")
        _, res = self.build()
        self.assertTrue(any("missing fields" in why for _, _, why in res.stale))

    def test_conflict_marker_open_vs_ack(self):
        body = make_doc(last_verified="2026-07-01") + (
            "\nclaim one <!-- KB-CONTRADICTED: conflicts with [verified: x] -->\n"
            "claim two <!-- KB-CONTRADICTED: KB-ACK conflicts with [verified: y] -->\n"
        )
        self.write("docs/a.md", body)
        _, res = self.build()
        self.assertEqual(len(res.conflicts), 1)
        self.assertEqual(len(res.conflicts_ack), 1)

    def test_prose_describing_marker_not_flagged(self):
        body = (
            make_doc(last_verified="2026-07-01") + "\nUse a `KB-CONTRADICTED` marker to quarantine a line.\n"
        )
        self.write("docs/a.md", body)
        _, res = self.build()
        self.assertEqual(res.conflicts, [])

    def test_disputed_claims_flagged(self):
        doc = make_doc(last_verified="2026-07-01").replace("tags: []", "tags: []\nhas_disputed_claims: true")
        self.write("docs/a.md", doc)
        _, res = self.build()
        self.assertTrue(any("disputed" in why for _, _, why in res.stale))

    def test_unverified_tier_listed(self):
        doc = make_doc(last_verified="2026-07-01").replace(
            "status: authoritative", "status: reference\nauthority: unverified"
        )
        self.write("docs/t.md", doc)
        _, res = self.build()
        self.assertEqual(len(res.unverified), 1)

    def test_orphan_artifact(self):
        self.write(
            "librarian-artifacts.toml",
            '[[artifact]]\npath = "gone.sql"\nid = "gone"\ntitle = "G"\n'
            'domain = "data"\nkind = "sql"\nstatus = "reference"\n',
        )
        _, res = self.build()
        self.assertEqual(res.orphans, [("gone", "gone.sql")])
        self.assertFalse(any(d.get("id") == "gone" for d in res.items))

    def test_coverage_scan(self):
        self.write("scripts/etl.py", "print('hi')\n")
        self.write("scripts/run.sh", "echo hi\n")
        _, res = self.build()
        self.assertIn("scripts/etl.py", res.uncovered)
        self.assertIn("scripts/run.sh", res.uncovered)

    def test_coverage_skip_config(self):
        self.write("scripts/etl.py", "print('hi')\n")
        _, res = self.build("[scan]\ncoverage_skip = ['etl.py']\n")
        self.assertEqual(res.uncovered, [])

    def test_skip_dirs(self):
        self.write("node_modules/x.md", "# x\n")
        self.write("_archive/old.md", "# old\n")
        _, res = self.build()
        self.assertEqual(res.missing_fm, [])

    def test_inbox_pending(self):
        self.write("_inbox/README.md", "# intake\n")
        self.write("_inbox/raw-dump.md", "stuff\n")
        _, res = self.build()
        self.assertEqual(res.inbox_pending, ["raw-dump.md"])

    def test_absence_guard(self):
        body = (
            make_doc(last_verified="2026-07-01")
            + "\nThe rates source is not yet identified.\nWe don't have HPPD targets.\n"
        )
        self.write("docs/a.md", body)
        _, res = self.build()
        self.assertEqual(len(res.absence_claims), 2)

    def test_absence_guard_suppressed_lines_and_off_switch(self):
        body = (
            make_doc(last_verified="2026-07-01")
            + "\nTBD <!-- KB-CONTRADICTED: conflicts with [verified: z] -->\n"
        )
        self.write("docs/a.md", body)
        _, res = self.build()
        self.assertEqual(res.absence_claims, [])  # marker line suppressed
        self.write("docs/b.md", make_doc(id="b", last_verified="2026-07-01") + "\nTBD later\n")
        _, res = self.build("[index]\nabsence_guard = false\n")
        self.assertEqual(res.absence_claims, [])

    def test_closed_domain_taxonomy(self):
        self.write("docs/a.md", make_doc(domain="rogue", last_verified="2026-07-01"))
        _, res = self.build("[taxonomy]\ndomains = ['data', 'company']\n")
        self.assertTrue(any("taxonomy" in why for _, _, why in res.stale))

    def test_gate_failures(self):
        self.write("docs/plain.md", "# no fm\n")
        cfg, res = self.build("[index]\nfail_on = ['missing_frontmatter']\n")
        self.assertEqual(res.gate_failures(cfg.fail_on), ["missing_frontmatter"])
        self.assertEqual(res.gate_failures([]), [])

    def test_idempotent_write(self):
        self.write("docs/a.md", make_doc(last_verified="2026-07-01"))
        cfg, res = self.build()
        render.write_all(cfg, res)
        first = {p.name: p.read_text() for p in (self.root / "_index").iterdir()}
        arts, errors = registry.load(cfg)
        render.write_all(cfg, catalog.build(cfg, config.today(), arts, errors))
        second = {p.name: p.read_text() for p in (self.root / "_index").iterdir()}
        self.assertEqual(first, second)

    def test_staleness_line3_summary_format(self):
        self.write("docs/a.md", make_doc(last_verified="2026-07-01"))
        cfg, res = self.build()
        line3 = render.staleness_md(cfg, res).splitlines()[2]
        for token in (
            "awaiting intake",
            "flagged",
            "orphaned",
            "OPEN conflicts",
            "md need frontmatter",
            "code/data unregistered",
        ):
            self.assertIn(token, line3)

    def test_catalog_json_shape(self):
        import json

        self.write("docs/a.md", make_doc(last_verified="2026-07-01"))
        cfg, res = self.build()
        data = json.loads(render.catalog_json(res))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["summary"]["docs"], 1)
        self.assertEqual(data["entries"][0]["path"], "docs/a.md")
        self.assertIn("open_conflicts", data["flags"])

    def test_fm_warnings_surface(self):
        self.write(
            "docs/a.md",
            "---\nid: a\ntitle: T\ndomain: d\nstatus: reference\n"
            "last_verified: 2026-07-01\nnested:\n  x: 1\n---\nbody\n",
        )
        cfg, res = self.build()
        self.assertTrue(res.fm_warnings)
        self.assertIn("Frontmatter warnings", render.staleness_md(cfg, res))


if __name__ == "__main__":
    unittest.main()
