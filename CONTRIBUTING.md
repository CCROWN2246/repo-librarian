# Contributing

Thanks for helping make repo-librarian better.

## Dev setup

```console
$ git clone https://github.com/CCROWN2246/repo-librarian && cd repo-librarian
$ python3 -m unittest discover -s tests        # zero deps — this just works
```

Optional (what CI runs): `pip install ruff` then `ruff check src tests` and
`ruff format --check src tests`.

## The one inviolable rule

**Runtime stays zero-dependency.** stdlib only, Python ≥ 3.11. Dev-tools (pytest, ruff)
are fine as dev-dependencies; nothing may creep into `[project.dependencies]`.

## Ground rules

- Generated output is deterministic: no timestamps except the explicit
  `.last_verified` stamp; sorted iteration everywhere; run-twice = zero diff.
- Every behavior change that alters rendered output updates the golden files
  **deliberately** (regeneration recipe in `tests/test_golden.py`'s docstring) and
  keeps `examples/demo-repo/_index/` in sync — the test suite enforces both.
- `_index/STALENESS.md` line 3 is a compatibility surface (shell hooks in the wild
  grep it); don't reorder its phrases.
- Engine modules (`catalog.py`, `verify.py`) stay pure — they take
  `(root, config, today)` and return result objects; I/O lives in `render.py`/`cli.py`.
- Tests are stdlib-`unittest` style so `python -m unittest discover` works with no
  installs (pytest collects them fine too).

## Releasing

Tag `vX.Y.Z` on main → the release workflow runs tests, builds, publishes to PyPI
(trusted publishing), and drafts a GitHub release. Update `CHANGELOG.md` and
`__version__` in the same PR as the tag-worthy change.
