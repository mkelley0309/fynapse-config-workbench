#!/usr/bin/env python3
"""Tests for eol-churn.py against a throwaway git repo. Stdlib only."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("eol_churn", HERE / "eol-churn.py")
ec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ec)


def git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false",
                    *args], cwd=repo, check=True, capture_output=True)


class TestClassify(unittest.TestCase):
    def test_eol_only(self):
        old = b"a\nb\nc\nd\n"
        new = b"a\r\nb\r\nc\r\nd\r\n"
        self.assertEqual(ec.classify(old, new, 4, 4)[0], "eol-only")

    def test_single_line_edit_not_flagged(self):
        old = b"a\nb\nc\nd\n"
        new = b"a\nB\nc\nd\n"
        self.assertIsNone(ec.classify(old, new, 1, 1)[0])

    def test_nn(self):
        self.assertEqual(ec.classify(b"a\nb\nc\n", b"x\ny\nz\n", 3, 3)[0], "N/N")

    def test_small_nn_not_flagged(self):
        self.assertIsNone(ec.classify(b"a\n", b"b\n", 1, 1)[0])

    def test_new_file_not_flagged(self):
        self.assertIsNone(ec.classify(None, b"a\nb\nc\n", 3, 0)[0])


class TestRepo(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.r = Path(self.d.name)
        git(self.r, "init", "-q")
        (self.r / "f.md").write_bytes(b"a\nb\nc\nd\ne\n")
        (self.r / "g.md").write_bytes(b"a\nb\nc\nd\ne\n")
        git(self.r, "add", ".")
        git(self.r, "commit", "-qm", "base")

    def tearDown(self):
        self.d.cleanup()

    def test_staged_flags_flip_only(self):
        (self.r / "f.md").write_bytes(b"a\r\nb\r\nc\r\nd\r\ne\r\n")
        (self.r / "g.md").write_bytes(b"a\nb\nC\nd\ne\n")
        git(self.r, "add", ".")
        flagged = ec.scan(staged=True, cwd=self.r)
        self.assertEqual([f["path"] for f in flagged], ["f.md"])
        self.assertEqual(ec.main(["--staged", "--cwd", str(self.r)]), 1)

    def test_clean_exit_zero(self):
        (self.r / "g.md").write_bytes(b"a\nb\nC\nd\ne\n")
        git(self.r, "add", ".")
        self.assertEqual(ec.main(["--staged", "--cwd", str(self.r)]), 0)

    def test_range_and_json(self):
        (self.r / "f.md").write_bytes(b"a\r\nb\r\nc\r\nd\r\ne\r\n")
        git(self.r, "add", ".")
        git(self.r, "commit", "-qm", "flip")
        flagged = ec.scan(rng="HEAD~1..HEAD", cwd=self.r)
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["reason"], "eol-only")
        json.dumps(flagged)


if __name__ == "__main__":
    unittest.main()
