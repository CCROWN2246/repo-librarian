"""Cross-cutting invariant tests (Phase B — the 'test the crap out of it' harness).

These assert the contracts that must hold for EVERY command on ANY corpus, and are
the durable proof behind the synthetic-corpus fuzzer (benchmarks/fuzz.py):

  * no command CRASHES on adversarial input (empty / malformed frontmatter /
    malformed .librarian.toml / corrupt sidecars / unicode / binary / dangling
    references / huge) — it returns a clean exit code, never a traceback;
  * the exit-code contract (0 clean / 1 findings / 2 error) is uniform;
  * index/dream/verify are deterministic (run-twice zero diff);
  * untrusted path inputs stay inside the repo root (no `..` escape);
  * malformed proposals fail LOUD at propose time, not with a stack trace.

Every bug the fuzzer surfaces earns a regression test here.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path

from helpers import RepoCase  # noqa: F401 — also puts src/ on sys.path
from librarian import cli

BENCH = Path(__file__).resolve().parent.parent / "benchmarks"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))

GOOD_DOC = (
    "---\nid: doc-a\ntitle: Doc A\ndomain: data\nstatus: authoritative\n"
    "last_verified: 2026-06-01\nrecheck: 90d\nread_when: [a task]\ntags: []\n---\n# Doc A\n\nbody\n"
)

# Read / analysis commands that must never crash on any corpus. propose (reads stdin)
# and archive (needs a path) get dedicated tests below; init mutates and is covered by
# test_scaffold.
READ_MATRIX = [
    ["index"],
    ["index", "--check"],
    ["status"],
    ["status", "--hook"],
    ["search", "a", "task"],
    ["verify"],
    ["doctor"],
    ["query"],
    ["query", "task"],
    ["todos"],
    ["dream"],
    ["why"],
    ["enrich"],
    ["suggest"],
    ["backfill"],
    ["apply", "--all"],
    ["apply", "--auto"],
    ["ingest"],
]


class InvariantCase(RepoCase):
    def run_sub(self, command, *argv, stdin_text=None):
        buf = io.StringIO()
        old_stdin = sys.stdin
        if stdin_text is not None:
            sys.stdin = io.StringIO(stdin_text)
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = cli.main([command, "--root", str(self.root), *argv])
            return code, buf.getvalue()
        finally:
            sys.stdin = old_stdin

    def assert_no_crash(self, matrix=READ_MATRIX):
        """Every command returns a clean exit code in {0,1,2} and never leaks a traceback."""
        for argv in matrix:
            with self.subTest(cmd=" ".join(argv)):
                try:
                    code, out = self.run_sub(argv[0], *argv[1:])
                except BaseException as e:  # noqa: BLE001 — a raised exception IS the failure
                    self.fail(f"{' '.join(argv)} raised {type(e).__name__}: {e}")
                self.assertIn(code, (0, 1, 2), f"{' '.join(argv)} -> exit {code} (contract is 0/1/2)")
                self.assertNotIn(
                    "Traceback (most recent call last)",
                    out,
                    f"{' '.join(argv)} leaked a traceback into its output",
                )


class NoCrashOnAdversarialInput(InvariantCase):
    def test_config_only_empty_repo(self):
        # RepoCase.setUp already wrote a minimal .librarian.toml; no docs at all.
        self.assert_no_crash()

    def test_truly_empty_dir(self):
        (self.root / ".librarian.toml").unlink()  # no config anywhere -> commands exit 2, never crash
        self.assert_no_crash()

    def test_malformed_frontmatter(self):
        self.write("docs/broken.md", "---\nid: [unclosed\ntitle: : : :\n  bad: indent\n---\n# broken\n")
        self.write("docs/notfm.md", "no frontmatter at all\njust text\n")
        self.write("docs/empty.md", "")
        self.assert_no_crash()

    def test_malformed_toml(self):
        self.write(".librarian.toml", "schema_version = 1\n[taxonomy\ndomains = [unclosed\n== bad ==\n")
        self.write("docs/a.md", GOOD_DOC)
        self.assert_no_crash()

    def test_unknown_config_key_and_wrong_types(self):
        self.write(".librarian.toml", 'schema_version = 1\nunknown_top_key = 42\n[taxonomy]\ndomains = "x"\n')
        self.write("docs/a.md", GOOD_DOC)
        self.assert_no_crash()

    def test_corrupt_sidecars(self):
        self.write("docs/a.md", GOOD_DOC)
        self.write("_index/proposals.json", "{ not valid json ][ ,,, ")
        self.write("_index/generated-checks.json", "NOT JSON")
        self.write("_index/provenance.json", "]]]broken[[[")
        self.write("_index/baselines.json", "{bad")
        self.write("_index/catalog.json", "corrupt")
        self.assert_no_crash()

    def test_unicode_content_and_filenames(self):
        self.write(
            "docs/ünïcodé-🚚.md",
            "---\nid: ünï-🚚\ntitle: Ünïcodé 🚚 café\ndomain: dätä\nstatus: authoritative\n"
            "last_verified: 2026-06-01\nrecheck: 90d\nread_when: [héllo, 日本語のタスク]\n"
            "tags: [café, 日本語]\n---\n# Ünïcodé 🚚\n\nbödy 🎉 中文 and ​ zero-width.\n",
        )
        self.assert_no_crash()

    def test_binary_non_utf8_md(self):
        (self.root / "docs").mkdir(parents=True, exist_ok=True)
        (self.root / "docs/binary.md").write_bytes(b"\xff\xfe\x00\x01 not utf8 \x80\x81\xff")
        self.write("docs/a.md", GOOD_DOC)
        self.assert_no_crash()

    def test_dangling_references(self):
        self.write("docs/a.md", GOOD_DOC)
        self.write(
            "librarian-artifacts.toml",
            '[[artifact]]\npath = "sql/does_not_exist.sql"\nid = "ghost"\ntitle = "Ghost"\n'
            'domain = "data"\nkind = "sql"\nstatus = "authoritative"\nlast_verified = "2026-06-01"\n'
            'read_when = ["nothing"]\n',
        )
        self.write(
            "_index/proposals.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "proposals": [
                        {
                            "schema_version": 1,
                            "id": "p_deadbeef0000",
                            "type": "fix",
                            "targets": [{"path": "docs/gone.md", "base_sha256": "0" * 64}],
                            "action": {"replace": {"old": "x", "new": "y"}},
                            "status": "approved",
                        }
                    ],
                }
            ),
        )
        self.assert_no_crash()

    def test_schema_violating_proposals(self):
        self.write("docs/a.md", GOOD_DOC)
        self.write(
            "_index/proposals.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "proposals": [
                        {"id": "x", "type": "nonexistent_type", "targets": []},
                        {"type": "fix"},
                        {"schema_version": 1, "id": "y", "type": "fix", "targets": "not-a-list"},
                        42,
                        "a string proposal",
                    ],
                }
            ),
        )
        self.assert_no_crash([["todos"], ["apply", "--all"], ["apply", "--auto"], ["status"], ["dream"]])

    def test_valid_but_non_dict_sidecars(self):
        # Regression (fuzzer seed=1023): a sidecar containing valid JSON that is NOT the
        # expected object (null / [] / 42 / "s") slipped past the JSONDecodeError guard and
        # crashed with AttributeError/TypeError on `.get()`. Every command must stay clean.
        self.write("docs/a.md", GOOD_DOC)
        sidecars = [
            "proposals.json",
            "provenance.json",
            "baselines.json",
            "generated-checks.json",
            "catalog.json",
            ".last_dream",
            "apply-log.jsonl",
        ]
        for payload in ("null", "[]", "42", '"s"'):
            with self.subTest(payload=payload):
                for name in sidecars:
                    self.write(f"_index/{name}", payload)
                self.assert_no_crash()

    def test_huge_input(self):
        big = "word " * 200_000  # ~1 MB body
        self.write(
            "docs/huge.md",
            "---\nid: huge\ntitle: Huge\ndomain: data\nstatus: authoritative\n"
            "last_verified: 2026-06-01\nrecheck: 90d\nread_when: [big]\ntags: []\n---\n# Huge\n\n"
            + big
            + "\n",
        )
        for i in range(30):
            self.write(f"docs/bulk/d{i}.md", GOOD_DOC.replace("doc-a", f"doc-{i}"))
        self.assert_no_crash()


class ExitCodeContract(InvariantCase):
    def test_clean_index_exit0(self):
        self.write("docs/a.md", GOOD_DOC)
        code, _ = self.run_sub("index")
        self.assertEqual(code, 0)

    def test_no_config_exit2(self):
        (self.root / ".librarian.toml").unlink()
        code, _ = self.run_sub("index")
        self.assertEqual(code, 2)

    def test_malformed_config_exit2(self):
        self.write(".librarian.toml", "schema_version = 1\n[bad\n")
        code, _ = self.run_sub("index")
        self.assertEqual(code, 2)

    def test_unknown_config_key_exit2(self):
        # CLAUDE.md: unknown key = error (strict config validation).
        self.write(".librarian.toml", "schema_version = 1\nbogus_key = true\n")
        code, _ = self.run_sub("index")
        self.assertEqual(code, 2)


class PathContainment(InvariantCase):
    """Untrusted path inputs must never read/move/write outside the repo root."""

    def test_archive_traversal_refused_and_file_untouched(self):
        self.write("docs/a.md", GOOD_DOC)
        outside = self.root.parent / "OUTSIDE_SENTINEL_inv.md"
        outside.write_text("do not touch\n", encoding="utf-8")
        try:
            code, out = self.run_sub("archive", "../OUTSIDE_SENTINEL_inv.md")
            self.assertEqual(code, 2, out)
            self.assertIn("escapes the repo root", out)
            self.assertTrue(outside.exists(), "traversal target was moved/deleted")
            self.assertEqual(outside.read_text(encoding="utf-8"), "do not touch\n")
        finally:
            if outside.exists():
                outside.unlink()

    def test_ingest_dest_traversal_refused(self):
        self.write("_inbox/n.md", "# n\n\ncontent\n")
        code, out = self.run_sub("ingest", "n.md", "--authority", "unverified", "--dest", "../")
        self.assertEqual(code, 2, out)
        self.assertIn("escapes the repo root", out)


class FailLoudRegressions(InvariantCase):
    """Regressions for bugs the fuzzer surfaced: malformed input fails loud, not a crash."""

    def test_malformed_fix_action_fails_loud_not_crash(self):
        self.write("docs/a.md", GOOD_DOC)
        bad = json.dumps(
            {"type": "fix", "targets": [{"path": "docs/a.md"}], "action": {"replace": "not-a-dict"}}
        )
        code, out = self.run_sub("propose", stdin_text=bad)
        self.assertEqual(code, 2, out)  # ProposalError, not AttributeError
        self.assertNotIn("Traceback (most recent call last)", out)
        self.assertIn("replace", out)

    def test_valid_fix_proposal_still_accepted(self):
        self.write("docs/a.md", GOOD_DOC.replace("body", "20 stations"))
        good = json.dumps(
            {
                "type": "fix",
                "targets": [{"path": "docs/a.md"}],
                "action": {"replace": {"old": "20 stations", "new": "17 stations"}},
            }
        )
        code, out = self.run_sub("propose", "--approved", stdin_text=good)
        self.assertEqual(code, 0, out)
        self.assertTrue((self.root / "_index/proposals.json").exists())

    def test_ingest_no_authority_non_interactive_fails_loud(self):
        # The trust tier must never be a silent default; no --authority + no TTY => exit 2,
        # and the inbox file is NOT moved.
        self.write("_inbox/n.md", "# n\n\ncontent\n")
        code, out = self.run_sub("ingest", "n.md")
        self.assertEqual(code, 2, out)
        self.assertTrue((self.root / "_inbox/n.md").exists(), "file was filed despite the refusal")


class ArchiveRobustness(InvariantCase):
    def test_archive_binary_doc_moves_bytes_without_crash(self):
        # Regression (fuzzer seed=1003): archiving a non-UTF8 .md crashed with
        # UnicodeDecodeError. It must move the file verbatim, byte-preserving, exit 0.
        raw = b"\xff\xfe\x00\x01 not utf8 \x80\x81\xff"
        (self.root / "docs").mkdir(parents=True, exist_ok=True)
        (self.root / "docs/binary.md").write_bytes(raw)
        code, out = self.run_sub("archive", "docs/binary.md")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.root / "docs/binary.md").exists())
        moved = self.root / "_archive" / "binary.md"
        self.assertTrue(moved.exists(), out)
        self.assertEqual(moved.read_bytes(), raw, "binary bytes were altered on archive")


class Determinism(unittest.TestCase):
    """index/dream/verify run-twice zero diff on a generated corpus (any corpus)."""

    def _snapshot(self, root: Path) -> dict:
        idx = root / "_index"
        return {p.name: p.read_bytes() for p in sorted(idx.glob("*")) if p.is_file()}

    def test_index_dream_verify_run_twice_zero_diff(self):
        import tempfile

        import gen_corpus  # from benchmarks/ (on sys.path)

        os.environ["LIBRARIAN_TODAY"] = "2026-07-01"
        self.addCleanup(os.environ.pop, "LIBRARIAN_TODAY", None)
        with tempfile.TemporaryDirectory() as td:
            corpus = Path(td) / "corpus"
            gen_corpus.build(corpus, n_docs=40, seed=101, bare=False)

            def run_trio():
                for cmd in (["index"], ["dream"], ["verify"]):
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        cli.main([cmd[0], "--root", str(corpus), *cmd[1:]])

            run_trio()
            first = self._snapshot(corpus)
            run_trio()
            second = self._snapshot(corpus)
            self.assertEqual(sorted(first), sorted(second), "the set of _index files changed on re-run")
            for name in first:
                self.assertEqual(
                    first[name], second[name], f"_index/{name} changed on re-run (non-deterministic)"
                )


if __name__ == "__main__":
    unittest.main()
