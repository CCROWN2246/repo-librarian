import unittest

from helpers import RepoCase, make_doc
from librarian import backfill, config, frontmatter


class BackfillTests(RepoCase):
    def test_slug_and_title(self):
        self.assertEqual(backfill.slug("docs/My File_v2.md"), "docs-my-file-v2")
        self.assertEqual(backfill.title_of("# The Real Title\ntext", "x.md"), "The Real Title")
        self.assertEqual(backfill.title_of("no heading", "some-notes.md"), "Some Notes")

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
