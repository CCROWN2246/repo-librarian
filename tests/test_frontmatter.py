import unittest

from helpers import SRC  # noqa: F401  (sys.path setup)

from librarian import frontmatter as fm


class ParseTests(unittest.TestCase):
    def test_valid_block(self):
        r = fm.parse("---\nid: a\ntitle: Hello World\n---\nbody\n")
        self.assertEqual(r.meta, {"id": "a", "title": "Hello World"})
        self.assertEqual(r.warnings, [])

    def test_absent(self):
        self.assertIsNone(fm.parse("# just a doc\n"))

    def test_unterminated(self):
        self.assertIsNone(fm.parse("---\nid: a\nno closing fence\n"))

    def test_crlf(self):
        r = fm.parse("---\r\nid: a\r\ntitle: T\r\n---\r\nbody")
        self.assertEqual(r.meta["id"], "a")
        self.assertEqual(r.meta["title"], "T")

    def test_inline_list(self):
        r = fm.parse("---\ntags: [a, b, c]\n---\n")
        self.assertEqual(r.meta["tags"], ["a", "b", "c"])

    def test_inline_list_quoted_commas(self):
        r = fm.parse('---\nread_when: ["write a query, fast", other]\n---\n')
        self.assertEqual(r.meta["read_when"], ["write a query, fast", "other"])

    def test_empty_inline_list(self):
        r = fm.parse("---\ntags: []\n---\n")
        self.assertEqual(r.meta["tags"], [])

    def test_block_list(self):
        r = fm.parse("---\nread_when:\n  - first task\n  - second task\n---\n")
        self.assertEqual(r.meta["read_when"], ["first task", "second task"])

    def test_quoted_strings_and_escapes(self):
        r = fm.parse('---\ntitle: "He said \\"hi\\""\nother: \'single\'\n---\n')
        self.assertEqual(r.meta["title"], 'He said "hi"')
        self.assertEqual(r.meta["other"], "single")

    def test_booleans(self):
        r = fm.parse("---\nhas_disputed_claims: true\nother: False\n---\n")
        self.assertIs(r.meta["has_disputed_claims"], True)
        self.assertIs(r.meta["other"], False)

    def test_no_int_coercion(self):
        r = fm.parse("---\nid: 007\n---\n")
        self.assertEqual(r.meta["id"], "007")

    def test_trailing_comment_stripped(self):
        r = fm.parse("---\nrecheck: 90d  # flag overdue past this\n---\n")
        self.assertEqual(r.meta["recheck"], "90d")

    def test_hash_inside_quotes_kept(self):
        r = fm.parse('---\ntitle: "issue #42"\n---\n')
        self.assertEqual(r.meta["title"], "issue #42")

    def test_invalid_date_warns(self):
        r = fm.parse("---\nlast_verified: sometime\n---\n")
        self.assertEqual(r.meta["last_verified"], "sometime")
        self.assertTrue(any("not a valid" in w for w in r.warnings))

    def test_nested_map_warns_not_silently_dropped(self):
        r = fm.parse("---\nid: a\nmeta:\n  nested: x\n---\n")
        self.assertEqual(r.meta["id"], "a")
        self.assertNotIn("nested", r.meta)
        self.assertTrue(any("nested" in w or "unsupported" in w for w in r.warnings))

    def test_comment_lines_ignored(self):
        r = fm.parse("---\n# a comment\nid: a\n---\n")
        self.assertEqual(r.meta, {"id": "a"})
        self.assertEqual(r.warnings, [])

    def test_span_ends_after_fence(self):
        text = "---\nid: a\n---\nbody"
        r = fm.parse(text)
        self.assertEqual(text[r.span[1]:], "body")


class SerializeTests(unittest.TestCase):
    def test_field_order_and_roundtrip(self):
        meta = {"tags": ["x"], "id": "a", "title": "T", "zeta": "z", "domain": "d",
                "status": "draft", "last_verified": "2026-01-01", "has_disputed_claims": True}
        out = fm.serialize(meta)
        lines = out.splitlines()
        self.assertEqual(lines[0], "---")
        self.assertLess(lines.index("id: a"), lines.index("title: T"))
        self.assertLess(lines.index("tags: [x]"), lines.index("zeta: z"))  # extras last
        back = fm.parse(out + "body\n")
        self.assertEqual(back.meta["id"], "a")
        self.assertIs(back.meta["has_disputed_claims"], True)
        self.assertEqual(back.meta["tags"], ["x"])

    def test_special_chars_quoted(self):
        out = fm.serialize({"title": "a: b [c]"})
        back = fm.parse(out)
        self.assertEqual(back.meta["title"], "a: b [c]")


class SetFieldTests(unittest.TestCase):
    DOC = "---\nid: a\nlast_verified: 2026-01-01\nstatus: draft\n---\n# Title\n\n---\n\nbody after hrule\n"

    def test_replace_existing(self):
        out = fm.set_field(self.DOC, "last_verified", "2026-07-02")
        self.assertIn("last_verified: 2026-07-02", out)
        self.assertNotIn("2026-01-01", out)
        # body untouched, including the horizontal rule
        self.assertIn("body after hrule", out)
        self.assertEqual(out.count("# Title"), 1)

    def test_insert_missing(self):
        out = fm.set_field(self.DOC, "authority", "verified")
        r = fm.parse(out)
        self.assertEqual(r.meta["authority"], "verified")
        self.assertEqual(r.meta["status"], "draft")

    def test_body_hrule_not_confused_for_fence(self):
        out = fm.set_field(self.DOC, "status", "authoritative")
        self.assertIn("body after hrule", out)
        r = fm.parse(out)
        self.assertEqual(r.meta["status"], "authoritative")

    def test_replaces_block_list(self):
        doc = "---\nid: a\nread_when:\n  - old one\n  - old two\n---\nbody\n"
        out = fm.set_field(doc, "read_when", ["new"])
        r = fm.parse(out)
        self.assertEqual(r.meta["read_when"], ["new"])
        self.assertNotIn("old one", out)

    def test_no_frontmatter_raises(self):
        with self.assertRaises(ValueError):
            fm.set_field("no frontmatter\n", "id", "x")

    def test_crlf_preserved(self):
        doc = "---\r\nid: a\r\nlast_verified: 2026-01-01\r\n---\r\nbody"
        out = fm.set_field(doc, "last_verified", "2026-07-02")
        self.assertIn("last_verified: 2026-07-02\r\n", out)


if __name__ == "__main__":
    unittest.main()
