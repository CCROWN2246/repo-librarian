"""Golden-file tests: index the demo corpus, byte-compare against tests/golden/.

Regenerate deliberately after a rendering change (verify FIRST so provenance.json
exists — STALENESS.md reads it for the failing-check section):
    cd examples/demo-repo && LIBRARIAN_TODAY=2026-07-01 python3 -m librarian verify \
        && LIBRARIAN_TODAY=2026-07-01 python3 -m librarian index \
        && cp _index/CATALOG.md _index/STALENESS.md _index/catalog.json \
           _index/provenance.json ../../tests/golden/
(then commit both the demo _index/ and tests/golden/ together).
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import SRC  # noqa: F401
from librarian import catalog, config, registry, render, verify

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "examples" / "demo-repo"
GOLDEN = REPO / "tests" / "golden"
FROZEN_DATE = "2026-07-01"
POSIX_SH = os.name != "nt" and os.path.exists("/bin/sh")  # verify shells out via /bin/sh


class GoldenTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "demo"
        shutil.copytree(DEMO, self.root)
        os.environ["LIBRARIAN_TODAY"] = FROZEN_DATE
        self.addCleanup(os.environ.pop, "LIBRARIAN_TODAY", None)

    def render_all(self):
        cfg = config.load(self.root)
        arts, errors = registry.load(cfg)
        res = catalog.build(cfg, config.today(), arts, errors)
        # Mirror render.write_all: STALENESS reads the committed provenance.json for the
        # failing-check section (the demo's intentional DRIFT surfaces here).
        failing = verify.failing_checks(cfg)
        return {
            "CATALOG.md": render.catalog_md(cfg, res),
            "STALENESS.md": render.staleness_md(cfg, res, failing),
            "catalog.json": render.catalog_json(res),
        }

    def test_provenance_matches_golden(self):
        # provenance.json is a verify (not index) output — regenerate it live from the
        # demo's offline DB and byte-compare. Deterministic via the frozen clock.
        if not POSIX_SH:
            self.skipTest("verify shells out via /bin/sh — unavailable on native Windows")
        cfg = config.load(self.root)
        run = verify.run(cfg)
        verify.update_provenance(cfg, run, config.today())
        produced = (self.root / "_index" / "provenance.json").read_text(encoding="utf-8")
        expected = (GOLDEN / "provenance.json").read_text(encoding="utf-8")
        self.assertEqual(
            produced,
            expected,
            "provenance.json drifted from tests/golden/ — regenerate (see module docstring)",
        )

    def test_matches_golden(self):
        for name, text in self.render_all().items():
            with self.subTest(file=name):
                expected = (GOLDEN / name).read_text(encoding="utf-8")
                self.assertEqual(
                    text,
                    expected,
                    f"{name} drifted from tests/golden/ — if the change is "
                    "deliberate, regenerate the goldens (see module docstring)",
                )

    def test_demo_index_committed_in_sync(self):
        # The demo repo commits its _index/ so GitHub browsers can read the catalog;
        # it must match what the engine generates.
        for name, text in self.render_all().items():
            with self.subTest(file=name):
                committed = (DEMO / "_index" / name).read_text(encoding="utf-8")
                self.assertEqual(
                    text,
                    committed,
                    f"examples/demo-repo/_index/{name} is out of date — regenerate it (see module docstring)",
                )

    def test_deterministic(self):
        self.assertEqual(self.render_all(), self.render_all())


if __name__ == "__main__":
    unittest.main()
