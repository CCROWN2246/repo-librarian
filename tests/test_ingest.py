import unittest

from helpers import RepoCase, make_doc

from librarian import config, frontmatter, ingest


class IngestTests(RepoCase):
    def test_pending_lists_files(self):
        self.write("_inbox/README.md", "# intake\n")
        self.write("_inbox/dump.md", "raw\n")
        self.assertEqual(ingest.pending(self.cfg()), ["dump.md"])

    def test_md_gains_frontmatter_and_moves(self):
        self.write("_inbox/transcript.md", "# Interview\n\nclaims here\n")
        cfg = self.cfg()
        r = ingest.ingest_file(cfg, "transcript.md", domain="company", status="reference",
                               authority="unverified", dest="docs", recheck="90d",
                               today=config.today())
        self.assertEqual(r.moved_to, "docs/transcript.md")
        self.assertTrue(r.frontmatter_added)
        self.assertFalse((self.root / "_inbox" / "transcript.md").exists())
        meta = frontmatter.parse(self.read("docs/transcript.md")).meta
        self.assertEqual(meta["authority"], "unverified")
        self.assertEqual(meta["domain"], "company")

    def test_existing_frontmatter_gets_authority_stamped(self):
        self.write("_inbox/note.md", make_doc(id="note"))
        cfg = self.cfg()
        r = ingest.ingest_file(cfg, "note.md", domain="x", status="reference",
                               authority="unverified", dest="docs", recheck="90d",
                               today=config.today())
        self.assertFalse(r.frontmatter_added)
        meta = frontmatter.parse(self.read("docs/note.md")).meta
        self.assertEqual(meta["authority"], "unverified")
        self.assertEqual(meta["id"], "note")   # original meta preserved

    def test_non_md_emits_artifact_block(self):
        self.write("_inbox/export.csv", "a,b\n1,2\n")
        cfg = self.cfg()
        r = ingest.ingest_file(cfg, "export.csv", domain="data", status="reference",
                               authority="unverified", dest="data", recheck="90d",
                               today=config.today())
        self.assertEqual(r.moved_to, "data/export.csv")
        self.assertIn("[[artifact]]", r.artifact_block)
        self.assertIn('path = "data/export.csv"', r.artifact_block)
        self.assertTrue((self.root / "data" / "export.csv").exists())

    def test_collision_refuses(self):
        self.write("_inbox/x.md", "new\n")
        self.write("docs/x.md", "old\n")
        with self.assertRaises(FileExistsError):
            ingest.ingest_file(self.cfg(), "x.md", domain="d", status="reference",
                               authority=None, dest="docs", recheck="90d", today=config.today())
        self.assertEqual(self.read("docs/x.md"), "old\n")   # nothing clobbered


if __name__ == "__main__":
    unittest.main()
