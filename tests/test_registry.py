import unittest

from helpers import RepoCase
from librarian import registry

VALID = """
[[artifact]]
path = "q/a.sql"
id = "a-sql"
title = "A query"
domain = "data"
kind = "sql"
status = "authoritative"
"""


class RegistryTests(RepoCase):
    def test_valid_entry_loads(self):
        self.write("librarian-artifacts.toml", VALID)
        self.write("q/a.sql", "select 1;")
        arts, errors = registry.load(self.cfg())
        self.assertEqual(errors, [])
        self.assertEqual(arts[0]["id"], "a-sql")

    def test_missing_file_is_fine(self):
        arts, errors = registry.load(self.cfg())
        self.assertEqual((arts, errors), ([], []))

    def test_broken_entry_does_not_kill_siblings(self):
        self.write("librarian-artifacts.toml", VALID + "\n[[artifact]]\npath = 'x.sql'\nid = 'x'\n")
        arts, errors = registry.load(self.cfg())
        self.assertEqual(len(arts), 1)  # the valid one survives
        self.assertEqual(len(errors), 1)
        self.assertIn("missing", errors[0])

    def test_duplicate_id_and_unknown_field(self):
        dup = VALID + VALID.replace('path = "q/a.sql"', 'path = "q/b.sql"')
        arts, errors = registry.load(self.cfg())
        self.write("librarian-artifacts.toml", dup)
        arts, errors = registry.load(self.cfg())
        self.assertEqual(len(arts), 1)
        self.assertTrue(any("duplicate id" in e for e in errors))
        bad_field = VALID.replace('kind = "sql"', 'kind = "sql"\nbogus = "x"')
        self.write("librarian-artifacts.toml", bad_field)
        _, errors = registry.load(self.cfg())
        self.assertTrue(any("unknown field 'bogus'" in e for e in errors))

    def test_bad_authority(self):
        self.write(
            "librarian-artifacts.toml",
            VALID.replace('status = "authoritative"', 'status = "authoritative"\nauthority = "gospel"'),
        )
        _, errors = registry.load(self.cfg())
        self.assertTrue(any("authority" in e for e in errors))

    def test_to_toml_block_roundtrip(self):
        block = registry.to_toml_block(
            {
                "path": "d/x.csv",
                "id": "x",
                "title": "X",
                "domain": "data",
                "kind": "csv",
                "status": "reference",
                "read_when": ["look at x"],
            }
        )
        self.write("librarian-artifacts.toml", block)
        self.write("d/x.csv", "a,b\n")
        arts, errors = registry.load(self.cfg())
        self.assertEqual(errors, [])
        self.assertEqual(arts[0]["read_when"], ["look at x"])


if __name__ == "__main__":
    unittest.main()
