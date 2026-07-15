"""CI gate for the synthetic-corpus fuzzer (benchmarks/fuzz.py).

Runs the fuzzer at a small, FIXED scale so that any invariant regression — a command
that starts crashing (or going non-deterministic) on adversarial input — fails the
build. The exhaustive sweep is run manually with more seeds/rounds:

    python3 benchmarks/fuzz.py --seeds 40 --rounds 10

Kept deliberately small here so the suite stays fast and offline.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from helpers import RepoCase  # noqa: F401 — puts src/ on sys.path

BENCH = Path(__file__).resolve().parent.parent / "benchmarks"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))


class FuzzGate(unittest.TestCase):
    def test_small_fixed_seed_sweep_is_clean(self):
        import fuzz

        os.environ["LIBRARIAN_TODAY"] = "2026-07-01"
        self.addCleanup(os.environ.pop, "LIBRARIAN_TODAY", None)
        findings = fuzz.run(seeds=4, rounds=4, n_docs=25, base_seed=7000)
        self.assertEqual(findings, [], f"fuzzer found invariant violation(s): {findings}")


if __name__ == "__main__":
    unittest.main()
