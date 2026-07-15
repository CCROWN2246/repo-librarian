"""Unit tests for scanner skip_files globbing (round-3 7.1)."""

import unittest

from helpers import RepoCase  # noqa: F401  (also puts src on sys.path)
from librarian import scanner


class SkipGlobTests(RepoCase):
    def test_glob_pattern_skips_family(self):
        # one "FEEDBACK*.md" glob covers every round's feedback doc, in any subdir
        cfg = self.cfg('[scan]\nskip_files = ["FEEDBACK*.md"]\n')
        files = ["docs/a.md", "docs/FEEDBACK3.md", "FEEDBACK.md", "FEEDBACK2.md"]
        self.assertEqual(scanner.md_files(cfg, files), ["docs/a.md"])

    def test_literal_pattern_back_compat(self):
        # a wildcard-free pattern matches exactly (by basename) as the old set did
        cfg = self.cfg('[scan]\nskip_files = ["README.md"]\n')
        files = ["README.md", "docs/README.md", "docs/other.md"]
        self.assertEqual(scanner.md_files(cfg, files), ["docs/other.md"])

    def test_case_sensitive(self):
        # fnmatchcase (not fnmatch): case-sensitive on every OS (determinism)
        cfg = self.cfg('[scan]\nskip_files = ["FEEDBACK*.md"]\n')
        files = ["feedback.md", "FEEDBACK.md"]
        self.assertEqual(scanner.md_files(cfg, files), ["feedback.md"])


if __name__ == "__main__":
    unittest.main()
