import unittest

from helpers import SRC  # noqa: F401
from librarian.extractors import ExtractError, extract


class ExtractorTests(unittest.TestCase):
    def test_scalar_last_cell_last_line(self):
        self.assertEqual(extract("scalar", "header\n42\n", 0), "42")
        self.assertEqual(extract("scalar", "a\tb\tc\n1\t2\t3\n", 0), "3")
        self.assertEqual(extract("scalar", "", 0), "")

    def test_lines(self):
        self.assertEqual(extract("lines", "a\n\nb\nc\n", 0), "3")

    def test_exit_code(self):
        self.assertEqual(extract("exit_code", "", 7), "7")

    def test_regex_group(self):
        self.assertEqual(extract(r"regex:version (\d+\.\d+)", "app version 3.14 ok", 0), "3.14")
        self.assertEqual(extract(r"regex:nope", "abc", 0), "<no-match>")
        with self.assertRaises(ExtractError):
            extract("regex:(unclosed", "x", 0)

    def test_json_path(self):
        blob = '{"a": {"b": [{"c": 5}, {"c": 6}]}, "ok": true}'
        self.assertEqual(extract("json:a.b[1].c", blob, 0), "6")
        self.assertEqual(extract("json:a.b.length", blob, 0), "2")
        self.assertEqual(extract("json:ok", blob, 0), "true")
        with self.assertRaises(ExtractError):
            extract("json:a.missing", blob, 0)
        with self.assertRaises(ExtractError):
            extract("json:a", "not json", 0)

    def test_column_present_absent(self):
        # base-table shape (name only) and view shape (name<tab>type)
        out = "user_id\nfacility_id\tstring\n"
        self.assertEqual(extract("column_present:user_id", out, 0), "present")
        self.assertEqual(extract("column_present:facility_id", out, 0), "present")
        self.assertEqual(extract("column_absent:email", out, 0), "absent")
        self.assertEqual(extract("column_absent:user_id", out, 0), "present")

    def test_unknown_extractor(self):
        with self.assertRaises(ExtractError):
            extract("bogus", "x", 0)


if __name__ == "__main__":
    unittest.main()
