import unittest

from helpers import RepoCase
from librarian import catalog, config, registry, suggest


class HarvestTests(RepoCase):
    def _suggest_one(self, rel, content):
        self.write(rel, content)
        cfg = self.cfg()
        arts, errors = registry.load(cfg)
        res = catalog.build(cfg, config.today(), arts, errors)
        suggestions = suggest.build_suggestions(cfg, res)
        self.assertEqual(len(suggestions), 1, res.uncovered)
        return suggestions[0]

    def test_sql_leading_comment(self):
        s = self._suggest_one(
            "queries/rollup.sql",
            "-- Monthly rollup per station.\n-- Grain: one row per station-month.\nSELECT 1;\n",
        )
        self.assertEqual(s.title, "Monthly rollup per station.")
        self.assertEqual(s.kind, "sql")
        self.assertIn("Grain", s.desc)

    def test_py_docstring(self):
        s = self._suggest_one("etl/load.py", '"""Load ride exports.\n\nRuns nightly."""\nx = 1\n')
        self.assertEqual(s.title, "Load ride exports")
        self.assertEqual(s.kind, "script")

    def test_sh_comment_skips_shebang(self):
        s = self._suggest_one("bin/deploy.sh", "#!/bin/bash\n# Push the dashboard definition.\nset -e\n")
        self.assertEqual(s.title, "Push the dashboard definition.")

    def test_csv_header(self):
        s = self._suggest_one("data/stations.csv", "station_id,name,dock_count\n1,Harbor,20\n2,Union,20\n")
        self.assertEqual(s.title, "Stations")  # falls back to filename
        self.assertIn("columns: station_id, name, dock_count", s.desc)
        self.assertIn("2 data rows", s.desc)
        self.assertEqual(s.kind, "csv")

    def test_notebook_first_markdown_heading(self):
        nb = (
            '{"cells": [{"cell_type": "markdown", "source": ["# Utilization study\\n", "text"]}],'
            ' "nbformat": 4, "nbformat_minor": 5, "metadata": {}}'
        )
        s = self._suggest_one("notebooks/util.ipynb", nb)
        self.assertEqual(s.title, "Utilization study")
        self.assertEqual(s.kind, "notebook")

    def test_json_top_level_keys(self):
        s = self._suggest_one("conf/policy.json", '{"Version": "1", "Statement": []}')
        self.assertIn("top-level keys: Statement, Version", s.desc)

    def test_fallback_title_from_filename(self):
        s = self._suggest_one("misc/raw_dump.sql", "SELECT 1;\n")
        self.assertEqual(s.title, "Raw Dump")

    def test_registered_files_not_suggested(self):
        self.write("q/a.sql", "-- known\nSELECT 1;\n")
        self.write(
            "librarian-artifacts.toml",
            '[[artifact]]\npath = "q/a.sql"\nid = "a"\ntitle = "A"\ndomain = "d"\n'
            'kind = "sql"\nstatus = "reference"\n',
        )
        cfg = self.cfg()
        arts, errors = registry.load(cfg)
        res = catalog.build(cfg, config.today(), arts, errors)
        self.assertEqual(suggest.build_suggestions(cfg, res), [])


class WriteTests(RepoCase):
    def test_toml_roundtrips_through_registry(self):
        self.write("queries/rollup.sql", '-- Rollup query with "quotes" in it.\nSELECT 1;\n')
        cfg = self.cfg()
        arts, errors = registry.load(cfg)
        res = catalog.build(cfg, config.today(), arts, errors)
        blocks = [
            suggest.to_toml(s, config.today(), domain="data") for s in suggest.build_suggestions(cfg, res)
        ]
        suggest.append_to_registry(cfg, blocks)
        arts, errors = registry.load(cfg)
        self.assertEqual(errors, [])
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0]["path"], "queries/rollup.sql")
        self.assertEqual(arts[0]["domain"], "data")
        self.assertEqual(arts[0]["read_when"], [])
        # coverage gap is now closed
        res = catalog.build(cfg, config.today(), arts, [])
        self.assertEqual(res.uncovered, [])

    def test_append_preserves_existing_registry(self):
        self.write(
            "librarian-artifacts.toml",
            '# my registry\n\n[[artifact]]\npath = "x.sql"\n'
            'id = "x"\ntitle = "X"\ndomain = "d"\nkind = "sql"\nstatus = "reference"\n',
        )
        self.write("x.sql", "SELECT 1;\n")
        self.write("new.py", '"""New tool."""\n')
        cfg = self.cfg()
        arts, errors = registry.load(cfg)
        res = catalog.build(cfg, config.today(), arts, errors)
        blocks = [suggest.to_toml(s, config.today()) for s in suggest.build_suggestions(cfg, res)]
        suggest.append_to_registry(cfg, blocks)
        arts, errors = registry.load(cfg)
        self.assertEqual(errors, [])
        self.assertEqual({a["id"] for a in arts}, {"x", "new-py"})
        self.assertIn("# my registry", self.read("librarian-artifacts.toml"))


if __name__ == "__main__":
    unittest.main()
