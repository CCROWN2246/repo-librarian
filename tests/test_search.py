"""Unit tests for the pure search ranker (round-3 A1b)."""

import unittest

from helpers import RepoCase  # noqa: F401  (also puts src on sys.path)
from librarian import search


class TokenTests(unittest.TestCase):
    def test_splits_quoted_phrase(self):
        # a quoted multi-word query arrives as ONE arg; it must split
        self.assertEqual(search.tokens(["pricing salary"]), ["pricing", "salary"])

    def test_trailing_s_fold(self):
        self.assertEqual(search.tokens(["shipments"]), ["shipment"])

    def test_double_s_not_folded(self):
        # "class" -> not "clas"
        self.assertEqual(search.tokens(["class"]), ["class"])


class RankTests(unittest.TestCase):
    def _entries(self):
        return [
            {
                "id": "a",
                "path": "docs/a.md",
                "read_when": ["pricing tiers"],
                "tags": [],
                "title": "A",
                "domain": "product",
            },
            {
                "id": "b",
                "path": "docs/b.md",
                "read_when": ["salary bands"],
                "tags": [],
                "title": "B",
                "domain": "hr",
            },
        ]

    def test_ranked_or_not_strict_and(self):
        # "pricing salary": pricing matches a, salary matches b -> BOTH score (OR)
        got = {e["id"] for _s, e in search.rank(self._entries(), ["pricing salary"])}
        self.assertEqual(got, {"a", "b"})

    def test_phrase_bonus_uses_raw_tokens(self):
        # an exact read_when phrase (incl. a stopword) still wins via the phrase bonus
        entries = [
            {
                "id": "x",
                "path": "docs/x.md",
                "read_when": ["write a query"],
                "tags": [],
                "title": "X",
                "domain": "d",
            },
            {
                "id": "y",
                "path": "docs/y.md",
                "read_when": ["run a query"],
                "tags": [],
                "title": "Y",
                "domain": "d",
            },
        ]
        top_id = search.rank(entries, ["write a query"])[0][1]["id"]
        self.assertEqual(top_id, "x")

    def test_empty_query_guard_no_all_match(self):
        # a pure-stopword query must not phrase-match every doc via "" in rw
        self.assertEqual(search.rank(self._entries(), ["of"]), [])

    def test_deterministic_tiebreak_by_path(self):
        r1 = search.rank(self._entries(), ["pricing salary"])
        r2 = search.rank(self._entries(), ["pricing salary"])
        self.assertEqual([e["path"] for _s, e in r1], [e["path"] for _s, e in r2])


class RankBodiesTests(RepoCase):
    def test_body_hit_and_oserror_skip(self):
        self.write("docs/a.md", "# A\nthe escalation runbook for on-call\n")
        entries = [
            {"id": "a", "path": "docs/a.md"},
            {"id": "gone", "path": "docs/missing.md"},  # OSError -> skipped, not crash
        ]
        got = [e["id"] for _s, e in search.rank_bodies(self.cfg(), entries, ["escalation"])]
        self.assertEqual(got, ["a"])

    def test_body_miss_returns_empty(self):
        self.write("docs/a.md", "# A\nnothing relevant here\n")
        entries = [{"id": "a", "path": "docs/a.md"}]
        self.assertEqual(search.rank_bodies(self.cfg(), entries, ["escalation"]), [])


class ClaimTermsTests(unittest.TestCase):
    """A3 term extraction: distinctive, deduped, punctuation-clean, trailing-s folded."""

    def test_distinctive_tokens(self):
        terms = search.claim_terms("We deploy via GitHub Actions, not Jenkins. Deploy again!")
        self.assertIn("deploy", terms)
        self.assertIn("github", terms)
        self.assertIn("action", terms)  # comma stripped, trailing-s folded
        self.assertIn("jenkin", terms)  # period stripped, trailing-s folded
        self.assertEqual(terms.count("deploy"), 1)  # deduped
        self.assertNotIn("we", terms)  # stopword dropped

    def test_respects_limit(self):
        text = " ".join(f"token{i}" for i in range(200))
        self.assertEqual(len(search.claim_terms(text, limit=10)), 10)

    def test_empty_text(self):
        self.assertEqual(search.claim_terms(""), [])


if __name__ == "__main__":
    unittest.main()
