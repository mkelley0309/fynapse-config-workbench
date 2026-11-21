#!/usr/bin/env python3
"""Tests for gate.py — first coverage for this module (was zero before this assignment).

Covers `load_checks` (config-file vs inline `--check`, error modes) and `cmd_run`'s
verdict/exit-code behavior (GO/NO-GO, empty-command guard, no-checks guard).

Run:  python -B tools/tests/test_gate.py
Stdlib only (unittest) — no pytest dependency.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gate  # noqa: E402


def make_args(**kw):
    ns = type("Args", (), {})()
    ns.config = kw.get("config")
    ns.check = kw.get("check")
    return ns


class GateFileTestCase(unittest.TestCase):
    """Run each test inside a fresh temp cwd so gate.json defaults don't collide."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._orig_cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self.addCleanup(lambda: os.chdir(self._orig_cwd))


class TestLoadChecks(GateFileTestCase):
    def test_inline_checks_parsed(self):
        checks = gate.load_checks(None, ["tests=pytest -q", "lint=ruff check ."])
        self.assertEqual(checks, [
            {"name": "tests", "command": "pytest -q"},
            {"name": "lint", "command": "ruff check ."},
        ])

    def test_inline_check_without_equals_sign_dies(self):
        with self.assertRaises(SystemExit) as ctx:
            gate.load_checks(None, ["not-a-check"])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_config_file_dies(self):
        with self.assertRaises(SystemExit) as ctx:
            gate.load_checks(Path("nonexistent.json"), [])
        self.assertEqual(ctx.exception.code, 2)

    def test_reads_checks_from_config_file(self):
        Path("gate.json").write_text(
            json.dumps({"checks": [{"name": "x", "command": "exit 0"}]}), encoding="utf-8"
        )
        checks = gate.load_checks(None, [])
        self.assertEqual(checks, [{"name": "x", "command": "exit 0"}])

    def test_explicit_config_path_used_over_default(self):
        Path("custom.json").write_text(
            json.dumps({"checks": [{"name": "y", "command": "exit 0"}]}), encoding="utf-8"
        )
        checks = gate.load_checks(Path("custom.json"), [])
        self.assertEqual(checks[0]["name"], "y")

    def test_inline_checks_take_priority_over_config_file(self):
        Path("gate.json").write_text(
            json.dumps({"checks": [{"name": "from-file", "command": "exit 0"}]}), encoding="utf-8"
        )
        checks = gate.load_checks(None, ["from-cli=exit 0"])
        self.assertEqual(checks[0]["name"], "from-cli")


class TestCmdInit(GateFileTestCase):
    def test_writes_template(self):
        rc = gate.cmd_init(make_args(config=None))
        self.assertEqual(rc, 0)
        data = json.loads(Path("gate.json").read_text(encoding="utf-8"))
        self.assertEqual(data, gate.TEMPLATE)

    def test_does_not_overwrite_existing(self):
        Path("gate.json").write_text('{"checks": []}', encoding="utf-8")
        gate.cmd_init(make_args(config=None))
        data = json.loads(Path("gate.json").read_text(encoding="utf-8"))
        self.assertEqual(data, {"checks": []})

    def test_respects_explicit_config_path(self):
        gate.cmd_init(make_args(config="custom.json"))
        self.assertTrue(Path("custom.json").exists())
        self.assertFalse(Path("gate.json").exists())


class TestCmdRun(GateFileTestCase):
    def test_all_checks_pass_is_go(self):
        rc = gate.cmd_run(make_args(config=None, check=["a=exit 0", "b=exit 0"]))
        self.assertEqual(rc, 0)

    def test_one_failing_check_is_no_go(self):
        rc = gate.cmd_run(make_args(config=None, check=["a=exit 0", "b=exit 1"]))
        self.assertEqual(rc, 1)

    def test_no_config_and_no_inline_checks_dies(self):
        """With neither a gate.json nor --check, load_checks itself dies (SystemExit 2)
        before cmd_run ever gets to its own "no checks" guard."""
        with self.assertRaises(SystemExit) as ctx:
            gate.cmd_run(make_args(config=None, check=[]))
        self.assertEqual(ctx.exception.code, 2)

    def test_empty_checks_list_in_config_is_error(self):
        """A gate.json with an explicit empty checks list reaches cmd_run's own guard."""
        Path("gate.json").write_text(json.dumps({"checks": []}), encoding="utf-8")
        rc = gate.cmd_run(make_args(config=None, check=None))
        self.assertEqual(rc, 2)

    def test_empty_command_in_config_is_error(self):
        Path("gate.json").write_text(
            json.dumps({"checks": [{"name": "empty", "command": ""}]}), encoding="utf-8"
        )
        rc = gate.cmd_run(make_args(config=None, check=None))
        self.assertEqual(rc, 2)

    def test_run_from_config_file(self):
        Path("gate.json").write_text(
            json.dumps({"checks": [{"name": "x", "command": "exit 0"}]}), encoding="utf-8"
        )
        rc = gate.cmd_run(make_args(config=None, check=None))
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    os.environ.setdefault("WORKSPACE_ROOT", str(Path(__file__).resolve().parent.parent))
    unittest.main(verbosity=2)
