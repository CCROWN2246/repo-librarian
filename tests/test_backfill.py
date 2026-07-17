import unittest

from helpers import RepoCase, make_doc
from librarian import backfill, config, frontmatter


class BackfillTests(RepoCase):
    def test_slug_and_title(self):
        self.assertEqual(backfill.slug("docs/My File_v2.md"), "docs-my-file-v2")
        self.assertEqual(backfill.title_of("# The Real Title\ntext", "x.md"), "The Real Title")
        self.assertEqual(backfill.title_of("no heading", "some-notes.md"), "Some Notes")

    def test_title_skips_fenced_code_comment(self):
        # Layer 3 low: a `#` comment inside a fenced code block must NOT be lifted as the title.
        text = "```bash\n# not the title\nrun --thing\n```\n\n# Real Heading\n\nbody\n"
        self.assertEqual(backfill.title_of(text, "x.md"), "Real Heading")

    def test_plan_disambiguates_colliding_ids(self):
        # Layer 3 medium: two paths that slug to the same id must get UNIQUE ids, or
        # CATALOG.md ends up with two entries sharing one identity key.
        self.write("docs/reports/q1.md", "# Q1 sub\n")  # slug -> docs-reports-q1
        self.write("docs/reports-q1.md", "# Q1 flat\n")  # slug -> docs-reports-q1 (collision)
        targets = backfill.plan(self.cfg())
        ids = sorted(p.id for _, p, _ in targets)
        self.assertEqual(len(ids), len(set(ids)), f"duplicate ids: {ids}")
        self.assertIn("docs-reports-q1", ids)
        self.assertIn("docs-reports-q1-2", ids)

    def test_plan_skips_covered(self):
        self.write("docs/covered.md", make_doc())
        self.write("docs/naked.md", "# Naked\n")
        targets = backfill.plan(self.cfg())
        self.assertEqual([p.path for _, p, _ in targets], ["docs/naked.md"])

    def test_apply_then_idempotent(self):
        self.write("docs/naked.md", "# Naked\n\nbody\n")
        cfg = self.cfg()
        targets = backfill.plan(cfg)
        backfill.apply(
            cfg,
            targets,
            domain="data",
            status="draft",
            authority="unverified",
            recheck="30d",
            today=config.today(),
        )
        text = self.read("docs/naked.md")
        meta = frontmatter.parse(text).meta
        self.assertEqual(meta["id"], "docs-naked")
        self.assertEqual(meta["title"], "Naked")
        self.assertEqual(meta["authority"], "unverified")
        self.assertEqual(meta["last_verified"], self.TODAY)
        self.assertIn("body", text)
        self.assertEqual(backfill.plan(cfg), [])  # second pass finds nothing

    def test_skip_files_respected(self):
        self.write("CLAUDE.md", "# instructions\n")
        self.assertEqual(backfill.plan(self.cfg()), [])


if __name__ == "__main__":
    unittest.main()
