"""End-to-end: drive the real CLI over a copy of the demo corpus."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import SRC  # noqa: F401

from librarian import cli

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "examples" / "demo-repo"
POSIX_SH = os.name != "nt" and Path("/bin/sh").exists()


@unittest.skipUnless(POSIX_SH, "verify shells out via /bin/sh (POSIX only)")
class DemoE2ETests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "demo"
        shutil.copytree(DEMO, self.root)
        os.environ["LIBRARIAN_TODAY"] = "2026-07-01"
        self.addCleanup(os.environ.pop, "LIBRARIAN_TODAY", None)

    def run_cli(self, command, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([command, "--root", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_index_verify_status_search_flow(self):
        code, out, _ = self.run_cli("index")
        self.assertEqual(code, 0)
        self.assertIn("10 catalogued", out)

        code, out, _ = self.run_cli("verify", "--json")
        self.assertEqual(code, 1, "the planted dock-count drift must fail the run")
        data = json.loads(out)
        by_id = {r["id"]: r for r in data["results"]}
        self.assertEqual(by_id["min_dock_count_is_20"]["status"], "DRIFT")
        self.assertEqual(by_id["min_dock_count_is_20"]["live"], "15")
        self.assertIn("docs/schema.md", by_id["min_dock_count_is_20"]["doc"])
        self.assertEqual(by_id["total_rides"]["status"], "CHANGED")
        self.assertEqual(by_id["stations_no_region_column"]["status"], "PASS")
        self.assertEqual(by_id["active_station_count"]["status"], "PASS")

        code, out, _ = self.run_cli("status")
        self.assertEqual(code, 1)   # open conflict + inbox item -> attention
        self.assertIn("OPEN conflict", out)

        code, out, _ = self.run_cli("search", "write", "a", "query")
        self.assertEqual(code, 0)
        first_line = next(ln for ln in out.splitlines() if ln.strip())
        self.assertIn("schema", first_line)

        # accept the moved baseline -> CHANGED becomes OK; drift remains
        code, _, _ = self.run_cli("verify", "--update-baselines", "--quiet")
        self.assertEqual(code, 1)
        code, out, _ = self.run_cli("verify", "--id", "total_rides")
        self.assertEqual(code, 0)
        self.assertIn("[OK]", out)

    def test_fixing_the_doc_clears_the_drift(self):
        schema = self.root / "docs" / "schema.md"
        text = schema.read_text(encoding="utf-8").replace(
            "Every station has 20 docks", "Docks per station vary (15–20)")
        schema.write_text(text, encoding="utf-8")
        cfg_path = self.root / ".librarian.toml"
        cfg_text = cfg_path.read_text(encoding="utf-8").replace(
            'expect  = "20"', 'expect  = "15"')
        cfg_path.write_text(cfg_text, encoding="utf-8")
        code, _, _ = self.run_cli("verify", "--id", "min_dock_count_is_20")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
