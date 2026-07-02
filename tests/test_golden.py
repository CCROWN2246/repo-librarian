"""Golden-file tests: index the demo corpus, byte-compare against tests/golden/.

Regenerate deliberately after a rendering change:
    cd examples/demo-repo && LIBRARIAN_TODAY=2026-07-01 \
        python3 -m librarian index && cp _index/CATALOG.md _index/STALENESS.md \
        _index/catalog.json ../../tests/golden/
(then commit both the demo _index/ and tests/golden/ together).
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import SRC  # noqa: F401
from librarian import catalog, config, registry, render

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "examples" / "demo-repo"
GOLDEN = REPO / "tests" / "golden"
FROZEN_DATE = "2026-07-01"


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
        return {
            "CATALOG.md": render.catalog_md(cfg, res),
            "STALENESS.md": render.staleness_md(cfg, res),
            "catalog.json": render.catalog_json(res),
        }

    def test_matches_golden(self):
        for name, text in self.render_all().items():
            with self.subTest(file=name):
                expected = (GOLDEN / name).read_text(encoding="utf-8")
                self.assertEqual(text, expected,
                                 f"{name} drifted from tests/golden/ — if the change is "
                                 "deliberate, regenerate the goldens (see module docstring)")

    def test_demo_index_committed_in_sync(self):
        # The demo repo commits its _index/ so GitHub browsers can read the catalog;
        # it must match what the engine generates.
        for name, text in self.render_all().items():
            with self.subTest(file=name):
                committed = (DEMO / "_index" / name).read_text(encoding="utf-8")
                self.assertEqual(text, committed,
                                 f"examples/demo-repo/_index/{name} is out of date — "
                                 "regenerate it (see module docstring)")

    def test_deterministic(self):
        self.assertEqual(self.render_all(), self.render_all())


if __name__ == "__main__":
    unittest.main()
