"""Tests for engagement/tools/fynapse/config_assemble.py.

Run from the wb root with WORKSPACE_ROOT unset:
    python -B -m unittest discover -s tests -t .
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WB = Path(__file__).resolve().parent.parent
TOOL = WB / "engagement" / "tools" / "fynapse" / "config_assemble.py"
FIXTURE = WB / "fixtures" / "config-demo"

sys.path.insert(0, str(TOOL.parent))
import config_assemble  # noqa: E402


def env():
    return {k: v for k, v in os.environ.items() if k != "WORKSPACE_ROOT"}


def assemble(cwd, name="acme"):
    return subprocess.run([sys.executable, "-B", str(TOOL), name], cwd=str(cwd), env=env(),
                          capture_output=True, text=True)


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = obj if isinstance(obj, str) else json.dumps(obj, indent=2) + "\n"
    path.write_bytes(data.encode("utf-8"))


class MiniEngagement(unittest.TestCase):
    """A fictional engagement root built in code."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        write(self.root / "config/instance/acme.export.json", {"version": "v20990101", "configuration": {}})
        parts = self.root / "config/parts"
        write(parts / "journalTypes/types.json", [{"code": "Perm", "behavior": "PERMANENT"}])
        write(parts / "businessEventTypes/b.json", [{"name": "EVT_B"}])
        write(parts / "businessEventTypes/a.json", {"name": "EVT_A"})
        write(parts / "journalDefinition/jld.json", {"active": True, "fields": [{"name": "account", "role": "account"}]})
        write(parts / "businessEventTypes/a.source.md", "# provenance\nnot JSON, ignored\n")

    def tearDown(self):
        self.td.cleanup()

    def out(self):
        return self.root / "config/build/acme.bulk.json"

    def test_assembles_with_envelope_and_order(self):
        r = assemble(self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        bulk = json.loads(self.out().read_text(encoding="utf-8"))
        self.assertEqual(list(bulk), ["version", "configuration"])
        self.assertEqual(list(bulk["configuration"]), ["journalTypes", "journalDefinition", "businessEventTypes"])
        self.assertEqual([t["name"] for t in bulk["configuration"]["businessEventTypes"]], ["EVT_A", "EVT_B"])

    def test_version_comes_from_export(self):
        write(self.root / "config/instance/acme.export.json", {"version": "v20770707", "configuration": {}})
        self.assertEqual(assemble(self.root).returncode, 0)
        self.assertEqual(json.loads(self.out().read_text(encoding="utf-8"))["version"], "v20770707")

    def test_byte_determinism(self):
        self.assertEqual(assemble(self.root).returncode, 0)
        first = self.out().read_bytes()
        self.assertEqual(assemble(self.root).returncode, 0)
        self.assertEqual(self.out().read_bytes(), first)
        self.assertTrue(first.endswith(b"}\n"))
        self.assertNotIn(b"\r", first)

    def test_duplicate_key_names_both_files(self):
        write(self.root / "config/parts/businessEventTypes/c.json", [{"name": "EVT_A"}])
        r = assemble(self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("config/parts/businessEventTypes/a.json", r.stderr)
        self.assertIn("config/parts/businessEventTypes/c.json", r.stderr)
        self.assertIn("EVT_A", r.stderr)

    def test_two_singleton_fragments_is_error(self):
        write(self.root / "config/parts/journalDefinition/jld2.json", {"active": False})
        r = assemble(self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("singleton", r.stderr)

    def test_unknown_section_is_error(self):
        write(self.root / "config/parts/notASection/x.json", {"name": "x"})
        r = assemble(self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown section 'notASection'", r.stderr)

    def test_missing_export_is_error(self):
        (self.root / "config/instance/acme.export.json").unlink()
        r = assemble(self.root)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stderr.startswith("error: config/instance/acme.export.json:"), r.stderr)

    def test_export_without_version_is_error(self):
        write(self.root / "config/instance/acme.export.json", {"configuration": {}})
        r = assemble(self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("version", r.stderr)

    def test_source_md_ignored(self):
        r = assemble(self.root)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_usage_error(self):
        r = subprocess.run([sys.executable, "-B", str(TOOL)], cwd=str(self.root), env=env(),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


class Constants(unittest.TestCase):
    def test_sections_are_the_dto_keys(self):
        self.assertEqual(len(config_assemble.SECTIONS), 28)
        self.assertNotIn("accounts", config_assemble.SECTIONS)
        self.assertEqual(set(config_assemble.EMIT_ORDER),
                         set(config_assemble.SECTIONS) | set(config_assemble.EXTENSION_SECTIONS))


class Fixture(unittest.TestCase):
    def test_fixture_assembles(self):
        with tempfile.TemporaryDirectory() as td:
            eng = Path(td) / "eng"
            shutil.copytree(FIXTURE, eng, ignore=shutil.ignore_patterns("build"))
            r = assemble(eng, "demo")
            self.assertEqual(r.returncode, 0, r.stderr)
            bulk = json.loads((eng / "config/build/demo.bulk.json").read_text(encoding="utf-8"))
            export = json.loads((eng / "config/instance/demo.export.json").read_text(encoding="utf-8"))
            self.assertEqual(set(bulk), {"version", "configuration"})
            self.assertEqual(bulk["version"], export["version"])
            for s in ("journalTypes", "journalDefinition", "businessEventDefinition", "dimensionSets",
                      "accountingConfigurations", "nodes", "businessEventTypes", "postingComponents",
                      "postingComponentIdentifications", "accountLookups"):
                self.assertIn(s, bulk["configuration"])


if __name__ == "__main__":
    unittest.main()
