import json
import os
import unittest

from helpers import RepoCase, make_doc
from librarian import config, verify

POSIX_SH = os.name != "nt" and os.path.exists("/bin/sh")


def check_toml(id, kind, cmd, *, expect=None, doc="docs/a.md", extra=""):
    lines = ["[[verify.checks]]", f"id = '{id}'", f"kind = '{kind}'", f"doc = '{doc}'", f'cmd = "{cmd}"']
    if expect is not None:
        lines.append(f"expect = '{expect}'")
    if extra:
        lines.append(extra)
    return "\n".join(lines) + "\n"


@unittest.skipUnless(POSIX_SH, "verify shells out via /bin/sh (POSIX only)")
class ProvenanceTests(RepoCase):
    def test_persists_command_source_value_timestamp(self):
        cfg = self.cfg(check_toml("count", "assert", "echo 17", expect="17"))
        run = verify.run(cfg)
        verify.update_provenance(cfg, run, config.today())
        data = json.loads(self.read("_index/provenance.json"))
        self.assertEqual(data["schema_version"], 1)
        rec = {r["check_id"]: r for r in data["records"]}["count"]
        self.assertEqual(rec["command"], "echo 17")
        self.assertEqual(rec["live"], "17")
        self.assertEqual(rec["status"], "PASS")
        self.assertEqual(rec["verified_at"], self.TODAY)

    def test_skip_records_excluded(self):
        cfg = self.cfg(check_toml("later", "assert", "exit 3", expect="x"))
        verify.update_provenance(cfg, verify.run(cfg), config.today())
        data = json.loads(self.read("_index/provenance.json"))
        self.assertEqual(data["records"], [])  # SKIP is not provenance

    def test_filtered_run_merges_not_clobbers(self):
        cfg = self.cfg(
            check_toml("a", "assert", "echo 1", expect="1") + check_toml("b", "assert", "echo 2", expect="2")
        )
        verify.update_provenance(cfg, verify.run(cfg), config.today())
        # a filtered re-run must keep b's record
        verify.update_provenance(cfg, verify.run(cfg, only_id="a"), config.today())
        ids = {r["check_id"] for r in json.loads(self.read("_index/provenance.json"))["records"]}
        self.assertEqual(ids, {"a", "b"})

    def test_orphan_pruned(self):
        cfg = self.cfg(check_toml("keep", "assert", "echo 1", expect="1"))
        verify.save_provenance(cfg, {"gone": {"check_id": "gone"}, "keep": {"check_id": "keep"}})
        verify.update_provenance(cfg, verify.run(cfg), config.today())
        ids = {r["check_id"] for r in json.loads(self.read("_index/provenance.json"))["records"]}
        self.assertEqual(ids, {"keep"})


@unittest.skipUnless(POSIX_SH, "verify shells out via /bin/sh (POSIX only)")
class VerifyTests(RepoCase):
    def test_assert_pass_and_drift(self):
        cfg = self.cfg(
            check_toml("good", "assert", "echo 17", expect="17")
            + check_toml("bad", "assert", "echo 18", expect="17")
        )
        run = verify.run(cfg)
        by_id = {r.id: r for r in run.results}
        self.assertEqual(by_id["good"].status, "PASS")
        self.assertEqual(by_id["bad"].status, "DRIFT")
        self.assertTrue(run.failed)

    def test_track_new_ok_changed(self):
        cfg = self.cfg(check_toml("count", "track", "echo 42"))
        run = verify.run(cfg)
        self.assertEqual(run.results[0].status, "NEW")
        self.assertFalse(run.failed)
        verify.update_baselines(cfg, run, config.today())
        run2 = verify.run(cfg)
        self.assertEqual(run2.results[0].status, "OK")
        verify.save_baselines(cfg, {"count": {"value": "41", "recorded": "2026-01-01"}})
        run3 = verify.run(cfg)
        self.assertEqual(run3.results[0].status, "CHANGED")
        self.assertEqual(run3.results[0].baseline, "41")
        self.assertFalse(run3.failed)  # track never fails the run

    def test_error_on_nonzero_exit(self):
        cfg = self.cfg(check_toml("boom", "assert", "exit 5", expect="x"))
        run = verify.run(cfg)
        self.assertEqual(run.results[0].status, "ERROR")
        self.assertTrue(run.failed)

    def test_skip_exit_code_contract(self):
        cfg = self.cfg(check_toml("later", "assert", "exit 3", expect="x"))
        run = verify.run(cfg)
        self.assertEqual(run.results[0].status, "SKIP")
        self.assertFalse(run.failed)

    def test_skip_if_unset(self):
        cfg = self.cfg(
            check_toml(
                "dbcheck",
                "assert",
                "echo hi",
                expect="hi",
                extra="skip_if_unset = ['LIBRARIAN_TEST_NOT_SET_VAR']",
            )
        )
        os.environ.pop("LIBRARIAN_TEST_NOT_SET_VAR", None)
        run = verify.run(cfg)
        self.assertEqual(run.results[0].status, "SKIP")
        os.environ["LIBRARIAN_TEST_NOT_SET_VAR"] = "1"
        self.addCleanup(os.environ.pop, "LIBRARIAN_TEST_NOT_SET_VAR", None)
        run = verify.run(cfg)
        self.assertEqual(run.results[0].status, "PASS")

    def test_source_template_and_probe(self):
        marker = self.root / "probe_ran"
        toml = (
            f"[verify.sources.db]\n"
            f'command = "echo prefix {{arg}}"\n'
            f'skip_unless = "touch {marker.as_posix()}.$$ && test -e {marker.as_posix()}.enable"\n'
            "[[verify.checks]]\nid = 'q1'\nkind = 'assert'\ndoc = 'd.md'\n"
            "arg = 'hello world'\nsource = 'db'\nextract = \"regex:prefix (.*)\"\nexpect = 'hello world'\n"
            "[[verify.checks]]\nid = 'q2'\nkind = 'assert'\ndoc = 'd.md'\n"
            "arg = 'x'\nsource = 'db'\nexpect = 'x'\n"
        )
        cfg = self.cfg(toml)
        run = verify.run(cfg)
        self.assertEqual({r.status for r in run.results}, {"SKIP"})  # probe fails
        probes = [p for p in self.root.iterdir() if p.name.startswith("probe_ran")]
        self.assertEqual(len(probes), 1, "probe must be cached — one execution for two checks")
        (self.root / "probe_ran.enable").write_text("")
        run = verify.run(cfg)
        by_id = {r.id: r for r in run.results}
        self.assertEqual(by_id["q1"].status, "PASS")  # {arg} shell-quoted through the template
        self.assertEqual(by_id["q1"].live, "hello world")

    def test_filters(self):
        cfg = self.cfg(
            check_toml("a_one", "assert", "echo 1", expect="1") + check_toml("b_two", "track", "echo 2")
        )
        self.assertEqual([r.id for r in verify.run(cfg, only_id="a_*").results], ["a_one"])
        self.assertEqual([r.id for r in verify.run(cfg, only_kind="track").results], ["b_two"])

    def test_update_baselines_prunes_orphans(self):
        cfg = self.cfg(check_toml("live", "track", "echo 9"))
        verify.save_baselines(cfg, {"ghost": {"value": "1", "recorded": "2026-01-01"}})
        actions = verify.update_baselines(cfg, verify.run(cfg), config.today())
        baselines = verify.load_baselines(cfg)
        self.assertIn("live", baselines)
        self.assertNotIn("ghost", baselines)
        self.assertTrue(any("pruned" in a for a in actions))

    def test_stamp_docs_only_on_all_pass(self):
        self.write("docs/a.md", make_doc(last_verified="2026-01-01"))
        self.write("docs/b.md", make_doc(id="doc-b", last_verified="2026-01-01"))
        cfg = self.cfg(
            check_toml("ok1", "assert", "echo 1", expect="1", doc="docs/a.md")
            + check_toml("skp", "assert", "exit 3", expect="1", doc="docs/a.md")
            + check_toml("bad", "assert", "echo 2", expect="1", doc="docs/b.md")
        )
        actions = verify.stamp_docs(cfg, verify.run(cfg), config.today())
        self.assertIn("last_verified: 2026-07-02", self.read("docs/a.md"))  # SKIP doesn't block
        self.assertIn("last_verified: 2026-01-01", self.read("docs/b.md"))  # DRIFT blocks
        self.assertTrue(any("stamped docs/a.md" in a for a in actions))

    def test_stamp_docs_prose_pointer_unstampable(self):
        cfg = self.cfg(check_toml("ok", "assert", "echo 1", expect="1", doc="see docs/a.md section 3"))
        actions = verify.stamp_docs(cfg, verify.run(cfg), config.today())
        self.assertTrue(any("cannot stamp" in a for a in actions))

    def test_last_verified_stamp(self):
        cfg = self.cfg(check_toml("ok", "assert", "echo 1", expect="1"))
        verify.stamp_last_verified(cfg)
        stamp = (self.root / "_index" / ".last_verified").read_text()
        self.assertTrue(stamp.strip().isdigit())

    def test_result_json_roundtrip(self):
        cfg = self.cfg(check_toml("ok", "assert", "echo 1", expect="1"))
        payload = [r.to_dict() for r in verify.run(cfg).results]
        parsed = json.loads(json.dumps(payload))
        self.assertEqual(parsed[0]["status"], "PASS")
        self.assertEqual(parsed[0]["live"], "1")


class FailingCheckSignalTests(RepoCase):
    def test_failing_checks_reads_provenance(self):
        cfg = self.cfg()
        verify.save_provenance(
            cfg,
            {
                "ok": {"check_id": "ok", "status": "PASS", "doc": "a.md"},
                "bad": {
                    "check_id": "bad",
                    "status": "DRIFT",
                    "expect": "9",
                    "live": "10",
                    "doc": "b.md",
                    "verified_at": "2026-07-01",
                },
            },
        )
        fc = verify.failing_checks(cfg)
        self.assertEqual([c["id"] for c in fc], ["bad"])  # only DRIFT/ERROR
        self.assertEqual(fc[0]["live"], "10")
        self.assertEqual(verify.last_verified_date(cfg), "2026-07-01")

    def test_accept_expect_updates_generated_check(self):
        from librarian import proposals

        cfg = self.cfg()
        proposals.save_generated_checks(
            cfg, [{"id": "c1", "kind": "assert", "expect": "9", "source": "s", "doc": "d.md"}]
        )
        self.assertTrue(verify.accept_expect(cfg, "c1", "10"))
        self.assertEqual(proposals.load_generated_checks(cfg)[0]["expect"], "10")
        self.assertFalse(verify.accept_expect(cfg, "nope", "1"))  # unknown -> caller guides TOML edit


if __name__ == "__main__":
    unittest.main()
