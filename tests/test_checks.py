"""Tests for the verify-onboarding engine (`add-check` / `connect`).

Covers the drafting rules, the two places a live value gets frozen as `expect`
(the confirm gate and the proposal review), and the refusals that keep a wired
check from silently never running.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import unittest

from helpers import RepoCase, make_doc
from librarian import checks, cli, proposals

CSV = "station_id,name,dock_count,active\n1,Harbor,20,1\n2,Union,12,1\n3,Pier,20,0\n"

# Drafted checks are POSIX shell one-liners, run through /bin/sh exactly as verify runs
# every check. Same guard the rest of the suite uses for shell-dependent tests.
POSIX_SH = os.name != "nt" and os.path.exists("/bin/sh")
SHELL_ONLY = unittest.skipUnless(POSIX_SH, "drafted checks shell out via /bin/sh (POSIX only)")


class DraftCase(RepoCase):
    def run_sub(self, command, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([command, "--root", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()

    def seed(self):
        self.write("data/stations.csv", CSV)
        self.write("docs/schema.md", make_doc(id="schema", title="Schema"))


@SHELL_ONLY
class CommandTemplateTests(DraftCase):
    def test_rows_counts_final_line_without_trailing_newline(self):
        # the whole reason for awk over `tail | wc -l`: wc drops a final unterminated
        # line, which would silently under-report by one.
        self.write("data/x.csv", "a,b\n1,2\n3,4")  # no trailing \n
        cfg = self.cfg()
        self.assertEqual(checks.probe(cfg, checks.rows_cmd("data/x.csv"), "scalar"), "2")

    def test_rows_on_empty_file_is_zero_not_negative(self):
        self.write("data/empty.csv", "")
        cfg = self.cfg()
        self.assertEqual(checks.probe(cfg, checks.rows_cmd("data/empty.csv"), "scalar"), "0")

    def test_rows_header_only_is_zero(self):
        self.write("data/h.csv", "a,b\n")
        cfg = self.cfg()
        self.assertEqual(checks.probe(cfg, checks.rows_cmd("data/h.csv"), "scalar"), "0")

    def test_schema_strips_carriage_returns(self):
        # a CRLF file must not drift against an LF-authored expect
        self.write("data/crlf.csv", "a,b,c\r\n1,2,3\r\n")
        cfg = self.cfg()
        self.assertEqual(checks.probe(cfg, checks.schema_cmd("data/crlf.csv"), "scalar"), "a,b,c")

    def test_schema_of_tsv_keeps_every_column(self):
        # `scalar` tab-splits and keeps the LAST cell, so a raw TSV header would
        # collapse to one column; the draft comma-joins it first.
        self.write("data/t.tsv", "id\tname\tactive\n1\tx\t1\n")
        cfg = self.cfg()
        self.assertEqual(checks.probe(cfg, checks.schema_cmd("data/t.tsv"), "scalar"), "id,name,active")

    def test_distinct_counts_unique_values(self):
        self.seed()
        cfg = self.cfg()
        cmd = checks.distinct_cmd(
            "data/stations.csv", "dock_count", ["station_id", "name", "dock_count", "active"]
        )
        self.assertEqual(checks.probe(cfg, cmd, "scalar"), "2")  # 20 and 12

    def test_distinct_unknown_column_fails_loud(self):
        self.seed()
        with self.assertRaises(checks.CheckDraftError) as ctx:
            checks.distinct_cmd("data/stations.csv", "nope", ["station_id"])
        self.assertIn("no column named", str(ctx.exception))

    def test_paths_with_spaces_are_quoted(self):
        self.write("data/two words.csv", "a,b\n1,2\n")
        cfg = self.cfg()
        self.assertEqual(checks.probe(cfg, checks.rows_cmd("data/two words.csv"), "scalar"), "1")


class DraftingRuleTests(DraftCase):
    def test_csv_drafts_rows_and_schema(self):
        self.seed()
        cfg = self.cfg()
        drafts = checks.drafts_for_file(cfg, "data/stations.csv", doc="docs/schema.md")
        self.assertEqual([d.intent for d in drafts], ["rows", "schema"])
        self.assertEqual([d.kind for d in drafts], ["track", "assert"])

    def test_no_schema_flag_drops_the_header_guard(self):
        self.seed()
        cfg = self.cfg()
        drafts = checks.drafts_for_file(cfg, "data/stations.csv", doc="d.md", schema=False)
        self.assertEqual([d.intent for d in drafts], ["rows"])

    @SHELL_ONLY
    def test_json_array_drafts_a_length_check(self):
        self.write("data/e.json", '[{"a":1},{"a":2}]\n')
        cfg = self.cfg()
        drafts = checks.drafts_for_file(cfg, "data/e.json", doc="d.md")
        self.assertEqual([(d.intent, d.extract) for d in drafts], [("length", "json:length")])
        self.assertEqual(checks.probe(cfg, drafts[0].cmd, drafts[0].extract), "2")

    def test_json_object_is_skipped_with_a_reason(self):
        self.write("data/o.json", '{"a":1}\n')
        cfg = self.cfg()
        self.assertEqual(checks.drafts_for_file(cfg, "data/o.json", doc="d.md"), [])
        self.assertIn("top-level JSON object", checks.skip_reason(cfg, "data/o.json"))

    def test_binary_extensions_are_skipped_with_a_reason(self):
        self.write("data/x.parquet", "nope")
        cfg = self.cfg()
        self.assertIn("binary", checks.skip_reason(cfg, "data/x.parquet"))

    def test_empty_csv_is_skipped_not_drafted(self):
        self.write("data/empty.csv", "")
        cfg = self.cfg()
        self.assertEqual(checks.drafts_for_file(cfg, "data/empty.csv", doc="d.md"), [])
        self.assertIn("empty file", checks.skip_reason(cfg, "data/empty.csv"))

    def test_scan_is_sorted_and_reports_skips(self):
        self.write("data/b.csv", "a\n1\n")
        self.write("data/a.csv", "a\n1\n")
        self.write("data/z.parquet", "x")
        cfg = self.cfg()
        draftable, skipped = checks.scan(cfg, "data")
        self.assertEqual(draftable, ["data/a.csv", "data/b.csv"])
        self.assertEqual([p for p, _ in skipped], ["data/z.parquet"])

    def test_scan_honours_skip_dirs(self):
        # _index is our own state — a `connect .` must never draft against it
        self.write("data/a.csv", "a\n1\n")
        self.write("_index/leak.csv", "a\n1\n")
        cfg = self.cfg()
        draftable, _ = checks.scan(cfg, ".")
        self.assertEqual(draftable, ["data/a.csv"])


class AttributionTests(DraftCase):
    def _items(self, *paths):
        return [{"kind": "doc", "path": p} for p in paths]

    def test_single_citing_doc_is_attributed(self):
        self.write("data/stations.csv", CSV)
        self.write("docs/a.md", make_doc(id="a") + "\nsee data/stations.csv for the list\n")
        cfg = self.cfg()
        self.assertEqual(
            checks.attribute_doc(cfg, "data/stations.csv", self._items("docs/a.md")), "docs/a.md"
        )

    def test_ambiguous_citation_returns_none(self):
        # two docs cite it -> we don't guess which one drift should name
        self.write("data/stations.csv", CSV)
        self.write("docs/a.md", make_doc(id="a") + "\ndata/stations.csv\n")
        self.write("docs/b.md", make_doc(id="b") + "\ndata/stations.csv\n")
        cfg = self.cfg()
        items = self._items("docs/a.md", "docs/b.md")
        self.assertIsNone(checks.attribute_doc(cfg, "data/stations.csv", items))

    def test_no_citation_returns_none(self):
        self.write("data/stations.csv", CSV)
        self.write("docs/a.md", make_doc(id="a"))
        cfg = self.cfg()
        self.assertIsNone(checks.attribute_doc(cfg, "data/stations.csv", self._items("docs/a.md")))


@SHELL_ONLY
class ProbeTests(DraftCase):
    def test_failing_command_raises_not_returns_empty(self):
        cfg = self.cfg()
        with self.assertRaises(checks.CheckDraftError) as ctx:
            checks.probe(cfg, "exit 7", "scalar")
        self.assertIn("exited 7", str(ctx.exception))

    def test_bad_extract_spec_raises(self):
        cfg = self.cfg()
        with self.assertRaises(checks.CheckDraftError):
            checks.probe(cfg, "echo hi", "json:missing")


@SHELL_ONLY
class AddCheckCliTests(DraftCase):
    def test_track_check_writes_without_a_gate(self):
        self.seed()
        code, out, _ = self.run_sub(
            "add-check", "data/stations.csv", "--intent", "rows", "--doc", "docs/schema.md"
        )
        self.assertEqual(code, 0)
        self.assertIn("live value: '3'", out)
        written = proposals.load_generated_checks(self.cfg())
        self.assertEqual([c["id"] for c in written], ["data-stations-csv-rows"])
        self.assertEqual(written[0]["kind"], "track")
        self.assertNotIn("expect", written[0])

    def test_assert_refuses_without_confirmation(self):
        # non-TTY + no --yes/--expect: freezing a value as "correct" needs a human
        self.seed()
        code, out, _ = self.run_sub(
            "add-check", "data/stations.csv", "--intent", "schema", "--doc", "docs/schema.md"
        )
        self.assertEqual(code, 1)
        self.assertIn("NOTHING WRITTEN", out)
        self.assertEqual(proposals.load_generated_checks(self.cfg()), [])

    def test_assert_with_yes_seeds_expect_from_live(self):
        self.seed()
        code, _, _ = self.run_sub(
            "add-check", "data/stations.csv", "--intent", "schema", "--doc", "docs/schema.md", "--yes"
        )
        self.assertEqual(code, 0)
        written = proposals.load_generated_checks(self.cfg())
        self.assertEqual(written[0]["expect"], "station_id,name,dock_count,active")

    def test_explicit_expect_that_mismatches_warns(self):
        self.seed()
        code, out, err = self.run_sub(
            "add-check",
            "data/stations.csv",
            "--intent",
            "rows",
            "--doc",
            "docs/schema.md",
            "--kind",
            "assert",
            "--expect",
            "999",
        )
        self.assertEqual(code, 0)
        self.assertIn("starts as DRIFT", out + err)
        self.assertEqual(proposals.load_generated_checks(self.cfg())[0]["expect"], "999")

    def test_dry_run_writes_nothing(self):
        self.seed()
        code, _, _ = self.run_sub(
            "add-check", "data/stations.csv", "--intent", "rows", "--doc", "docs/schema.md", "--dry-run"
        )
        self.assertEqual(code, 0)
        self.assertEqual(proposals.load_generated_checks(self.cfg()), [])

    def test_print_toml_writes_nothing_and_emits_a_block(self):
        self.seed()
        code, out, _ = self.run_sub(
            "add-check", "data/stations.csv", "--intent", "rows", "--doc", "docs/schema.md", "--print-toml"
        )
        self.assertEqual(code, 0)
        self.assertIn("[[verify.checks]]", out)
        self.assertEqual(proposals.load_generated_checks(self.cfg()), [])

    def test_wired_check_is_picked_up_by_config_and_passes(self):
        # the end-to-end contract: what add-check writes actually RUNS on the next verify
        self.seed()
        self.run_sub(
            "add-check", "data/stations.csv", "--intent", "schema", "--doc", "docs/schema.md", "--yes"
        )
        code, out, _ = self.run_sub("verify")
        self.assertEqual(code, 0)
        self.assertIn("data-stations-csv-schema", out)
        self.assertIn("PASS", out)

    def test_drift_is_caught_after_the_source_changes(self):
        self.seed()
        self.run_sub(
            "add-check", "data/stations.csv", "--intent", "schema", "--doc", "docs/schema.md", "--yes"
        )
        self.write("data/stations.csv", CSV.replace("dock_count", "docks"))
        code, out, _ = self.run_sub("verify")
        self.assertEqual(code, 1)
        self.assertIn("DRIFT", out)

    def test_refuses_an_id_owned_by_hand_written_toml(self):
        # human TOML wins on collision, so a sidecar entry under that id would never run
        self.seed()
        self.cfg(
            '\n[[verify.checks]]\nid = "mine"\nkind = "assert"\ndoc = "docs/schema.md"\n'
            'cmd = "echo 1"\nexpect = "1"\n'
        )
        code, _, err = self.run_sub(
            "add-check", "--cmd", "echo 2", "--id", "mine", "--doc", "docs/schema.md", "--yes"
        )
        self.assertEqual(code, 2)
        self.assertIn("already exists in .librarian.toml", err)
        self.assertEqual(proposals.load_generated_checks(self.cfg()), [])

    def test_raw_cmd_requires_id_and_doc(self):
        self.seed()
        self.assertEqual(self.run_sub("add-check", "--cmd", "echo 1")[0], 2)
        self.assertEqual(self.run_sub("add-check", "--cmd", "echo 1", "--id", "x")[0], 2)

    def test_file_and_cmd_are_mutually_exclusive(self):
        self.seed()
        code, _, err = self.run_sub("add-check", "data/stations.csv", "--cmd", "echo 1")
        self.assertEqual(code, 2)
        self.assertIn("not both", err)

    def test_path_escape_is_refused(self):
        self.seed()
        code, _, err = self.run_sub("add-check", "../outside.csv", "--doc", "docs/schema.md")
        self.assertEqual(code, 2)
        self.assertIn("outside the repo root", err)

    def test_unattributed_doc_falls_back_to_the_file_and_says_so(self):
        self.seed()  # docs/schema.md does NOT cite the csv
        code, out, _ = self.run_sub("add-check", "data/stations.csv", "--intent", "rows")
        self.assertEqual(code, 0)
        self.assertIn("no catalogued doc cites this file", out)
        self.assertEqual(proposals.load_generated_checks(self.cfg())[0]["doc"], "data/stations.csv")

    def test_add_check_json_emits_a_document_on_every_path(self):
        # the CLI contract: --json emits exactly one document, including on the refusal
        # and preview paths (a silent stdout reads as a crash to a caller)
        self.seed()
        cases = [
            (["--intent", "schema"], 1, "unconfirmed"),  # no --yes: refused
            (["--intent", "schema", "--yes", "--print-toml"], 0, "printed"),
            (["--intent", "rows", "--dry-run"], 0, "dry_run"),
            (["--intent", "rows"], 0, "wired"),
        ]
        for extra, want_code, want_outcome in cases:
            with self.subTest(outcome=want_outcome):
                code, out, _ = self.run_sub(
                    "add-check", "data/stations.csv", "--doc", "docs/schema.md", "--json", *extra
                )
                self.assertEqual(code, want_code)
                payload = json.loads(out)
                self.assertEqual(payload["outcome"], want_outcome)
                self.assertEqual(payload["written"], want_outcome == "wired")


@SHELL_ONLY
class ConnectCliTests(DraftCase):
    def test_preview_writes_no_proposals(self):
        self.seed()
        code, out, _ = self.run_sub("connect", "data", "--doc", "docs/schema.md")
        self.assertEqual(code, 0)
        self.assertIn("data-stations-csv-rows", out)
        self.assertEqual(proposals.load(self.cfg()), [])

    def test_write_files_unapproved_add_check_proposals(self):
        # propose-only by default: the review IS the gate for a seeded expect
        self.seed()
        code, _, _ = self.run_sub("connect", "data", "--doc", "docs/schema.md", "--write")
        self.assertEqual(code, 0)
        props = proposals.load(self.cfg())
        self.assertEqual(len(props), 2)
        self.assertEqual({p.type for p in props}, {"add_check"})
        self.assertFalse(any(p.approved for p in props))

    def test_approve_flag_marks_them_applyable(self):
        self.seed()
        self.run_sub("connect", "data", "--doc", "docs/schema.md", "--write", "--approve")
        self.assertTrue(all(p.approved for p in proposals.load(self.cfg())))

    def test_full_loop_connect_apply_verify(self):
        self.seed()
        self.run_sub("connect", "data", "--doc", "docs/schema.md", "--write", "--approve")
        code, _, _ = self.run_sub("apply", "--all")
        self.assertEqual(code, 0)
        ids = {c["id"] for c in proposals.load_generated_checks(self.cfg())}
        self.assertEqual(ids, {"data-stations-csv-rows", "data-stations-csv-schema"})
        code, out, _ = self.run_sub("verify")
        self.assertEqual(code, 0)
        self.assertIn("PASS", out)

    def test_seeded_expect_rides_in_the_proposal(self):
        self.seed()
        self.run_sub("connect", "data", "--doc", "docs/schema.md", "--write")
        schema = next(p for p in proposals.load(self.cfg()) if p.action["check"]["kind"] == "assert")
        self.assertEqual(schema.action["check"]["expect"], "station_id,name,dock_count,active")

    def test_probe_failure_is_reported_not_swallowed(self):
        # an unreadable source must surface as a failure + exit 1, never a silent skip
        self.seed()
        self.write("data/bad.json", "[1,2,3]")
        original = checks.probe

        def boom(c, cmd, extract, **kw):
            if "bad.json" in cmd:
                raise checks.CheckDraftError("simulated source failure")
            return original(c, cmd, extract, **kw)

        checks.probe = boom
        self.addCleanup(setattr, checks, "probe", original)
        code, out, _ = self.run_sub("connect", "data", "--doc", "docs/schema.md")
        self.assertEqual(code, 1)
        self.assertIn("FAILED to probe", out)
        self.assertIn("simulated source failure", out)

    def test_skipped_files_are_listed(self):
        self.seed()
        self.write("data/x.parquet", "binary")
        code, out, _ = self.run_sub("connect", "data", "--doc", "docs/schema.md")
        self.assertEqual(code, 0)
        self.assertIn("data/x.parquet", out)
        self.assertIn("skipped 1 file", out)

    def test_json_output_is_machine_readable(self):
        self.seed()
        code, out, _ = self.run_sub("connect", "data", "--doc", "docs/schema.md", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload["drafts"]), 2)
        self.assertEqual(payload["dir"], "data")
        self.assertFalse(payload["written"])

    def test_rerun_is_idempotent(self):
        # same drafts -> same proposal ids -> upsert, not duplicates
        self.seed()
        self.run_sub("connect", "data", "--doc", "docs/schema.md", "--write")
        first = {p.id for p in proposals.load(self.cfg())}
        self.run_sub("connect", "data", "--doc", "docs/schema.md", "--write")
        self.assertEqual({p.id for p in proposals.load(self.cfg())}, first)
        self.assertEqual(len(proposals.load(self.cfg())), 2)

    def test_not_a_directory_is_refused(self):
        self.seed()
        code, _, err = self.run_sub("connect", "data/stations.csv")
        self.assertEqual(code, 2)
        self.assertIn("not a directory", err)

    def test_empty_directory_says_so(self):
        (self.root / "empty").mkdir()
        code, out, _ = self.run_sub("connect", "empty")
        self.assertEqual(code, 0)
        self.assertIn("No data files", out)


if __name__ == "__main__":
    unittest.main()
