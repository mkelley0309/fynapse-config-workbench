#!/usr/bin/env python3
"""Tests for tools/template-sync/template_sync.py (temp git repos, CLI by subprocess).

Run:  python -B -m unittest tools.tests.test_template_sync   (from Workspace root)
      python -B -m unittest discover -s tools/tests
Stdlib only.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent / "template-sync"
TOOL = TOOL_DIR / "template_sync.py"
sys.path.insert(0, str(TOOL_DIR))

import template_sync  # noqa: E402


def clean_env():
    env = dict(os.environ)
    env.pop("WORKSPACE_ROOT", None)
    for k in [k for k in env if k.startswith("GIT_")]:
        env.pop(k)
    return env


def run_git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                        "-c", "core.autocrlf=false", *args], capture_output=True, env=clean_env())
    assert r.returncode == 0, r.stderr.decode()
    return r.stdout.decode().strip()


def cli(*args, cwd=None):
    r = subprocess.run([sys.executable, "-B", str(TOOL), *map(str, args)], capture_output=True,
                       env=clean_env(), cwd=cwd)
    return r.returncode, r.stdout, r.stderr.decode("utf-8", "replace")


def put(root, rel, data):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode())


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name).resolve()
        self.src = self.tmp / "src"
        self.src.mkdir()
        run_git(self.src, "init", "-q")
        put(self.src, "payload/a.txt", b"alpha\n")
        put(self.src, "payload/sub/b.txt", b"beta\n")
        put(self.src, "payload/__pycache__/x.pyc", b"junk")
        put(self.src, "payload/terms.local.json", b"{}")
        put(self.src, "seed/s.txt", b"seed-upstream\n")
        put(self.src, "docs/guide.md",
            b"keep1\r\n<!-- EDITION:workspace:start -->\r\nsecret\r\n<!-- EDITION:workspace:end -->\r\nkeep2\r\n")
        put(self.src, "tool.py", b"a = 1\n    # EDITION:workspace:start\nb = 2\n    # EDITION:workspace:end\nc = 3\n")
        run_git(self.src, "add", "-A")
        run_git(self.src, "commit", "-q", "-m", "one")
        self.manifest = self.tmp / "manifest.json"
        self.write_manifest()

    def write_manifest(self, entries=None):
        entries = entries or [
            {"source": "s", "path": "payload", "dest": "out", "class": "managed",
             "exclude": ["__pycache__/**", "terms.local.json"]},
            {"source": "s", "path": "seed", "dest": "seed", "class": "seeded"},
            {"source": "s", "path": "docs/guide.md", "dest": "guide.md", "class": "managed", "edition_strip": True},
            {"source": "s", "path": "tool.py", "dest": "tool.py", "class": "managed", "edition_strip": True},
        ]
        m = {"schema": "template-sync-manifest/1", "sources": {"s": {"repo": "src"}}, "entries": entries}
        self.manifest.write_bytes(json.dumps(m).encode())

    def pull(self, dest, *extra, cmd="pull"):
        return cli(cmd, "--manifest", self.manifest, "--dest", dest, *extra)

    def lock(self, dest):
        return json.loads((Path(dest) / "template-sync.lock.json").read_bytes())


class TestSync(Base):
    def test_workspace_root_unset(self):
        self.assertNotIn("WORKSPACE_ROOT", clean_env())

    def test_pull_check_init_roundtrip(self):
        d1, d2 = self.tmp / "d1", self.tmp / "d2"
        rc, out, err = self.pull(d1)
        self.assertEqual(rc, 0, err)
        self.assertEqual((d1 / "out/a.txt").read_bytes(), b"alpha\n")
        self.assertEqual((d1 / "out/sub/b.txt").read_bytes(), b"beta\n")
        self.assertFalse((d1 / "out/__pycache__").exists())
        self.assertFalse((d1 / "out/terms.local.json").exists())
        self.assertEqual((d1 / "seed/s.txt").read_bytes(), b"seed-upstream\n")
        lock = self.lock(d1)
        self.assertEqual(lock["schema"], "template-sync-lock/1")
        self.assertEqual(lock["sources"]["s"]["commit"], run_git(self.src, "rev-parse", "HEAD"))
        self.assertEqual(lock["files"]["out/a.txt"]["class"], "managed")
        raw = (d1 / "template-sync.lock.json").read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))
        rc, out, err = cli("check", "--manifest", self.manifest, "--dest", d1)
        self.assertEqual(rc, 0, out)
        rc, out, err = cli("check", "--dest", d1)  # lock-only
        self.assertEqual(rc, 0, out)
        rc, out, err = self.pull(d2, cmd="init")
        self.assertEqual(rc, 0, err)
        for rel in ("out/a.txt", "seed/s.txt", "guide.md", "tool.py"):
            self.assertEqual((d1 / rel).read_bytes(), (d2 / rel).read_bytes())

    def test_managed_drift_and_force(self):
        d = self.tmp / "d"
        self.pull(d)
        (d / "out/a.txt").write_bytes(b"local edit\n")
        rc, out, _ = cli("check", "--manifest", self.manifest, "--dest", d)
        self.assertEqual(rc, 1)
        self.assertIn(b"edited", out)
        put(self.src, "payload/a.txt", b"alpha2\n")
        run_git(self.src, "commit", "-qam", "two")
        rc, out, err = self.pull(d)
        self.assertEqual(rc, 1)
        self.assertIn("out/a.txt", err)
        self.assertEqual((d / "out/a.txt").read_bytes(), b"local edit\n")
        self.assertEqual((d / "out/sub/b.txt").read_bytes(), b"beta\n")
        rc, out, err = self.pull(d, "--force")
        self.assertEqual(rc, 0, err)
        self.assertEqual((d / "out/a.txt").read_bytes(), b"alpha2\n")
        rc, _, _ = cli("check", "--manifest", self.manifest, "--dest", d)
        self.assertEqual(rc, 0)

    def test_missing_managed_and_upstream_drift(self):
        d = self.tmp / "d"
        self.pull(d)
        (d / "out/sub/b.txt").unlink()
        rc, out, _ = cli("check", "--dest", d)
        self.assertEqual(rc, 1)
        self.assertIn(b"missing", out)
        self.pull(d, "--force")
        # commit that is newer than lock, checked via --commit
        put(self.src, "payload/a.txt", b"alpha3\n")
        run_git(self.src, "commit", "-qam", "three")
        rc, out, _ = cli("check", "--manifest", self.manifest, "--dest", d, "--commit", "HEAD")
        self.assertEqual(rc, 1)
        self.assertIn(b"upstream-differs", out)

    def test_seeded_not_overwritten(self):
        d = self.tmp / "d"
        put(d, "seed/s.txt", b"mine\n")
        rc, out, err = self.pull(d)
        self.assertEqual(rc, 0, err)
        self.assertEqual((d / "seed/s.txt").read_bytes(), b"mine\n")
        rep = json.loads(out)
        rec = [f for f in rep["files"] if f["path"] == "seed/s.txt"][0]
        self.assertEqual(rec["action"], "kept-local-differs")
        self.assertIn("diff", rec)
        rc, out, _ = cli("check", "--manifest", self.manifest, "--dest", d)
        self.assertEqual(rc, 0)  # seeded diffs do not fail
        self.assertIn(b"differs", out)

    def test_init_refuses_source_and_inside(self):
        rc, _, err = self.pull(self.src, cmd="init")
        self.assertEqual(rc, 2)
        self.assertIn("inside", err)
        rc, _, err = self.pull(self.src / "sub" / "dest", cmd="init")
        self.assertEqual(rc, 2)
        self.assertFalse((self.src / "sub").exists())

    def test_pull_into_nested_repo_under_source_allowed(self):
        nested_in_src = self.src / "projects" / "wb"
        nested_in_src.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(nested_in_src)], check=True)
        rc, _, err = self.pull(nested_in_src / "engagement")
        self.assertEqual(rc, 0, err)
        self.assertTrue((nested_in_src / "engagement" / "tool.py").exists())

    def test_poststrip_hash_passes_check(self):
        d = self.tmp / "d"
        self.pull(d)
        g = (d / "guide.md").read_bytes()
        self.assertEqual(g, b"keep1\r\nkeep2\r\n")
        self.assertEqual((d / "tool.py").read_bytes(), b"a = 1\nc = 3\n")
        self.assertEqual(self.lock(d)["files"]["guide.md"]["sha256"], template_sync.sha256(g))
        rc, _, _ = cli("check", "--manifest", self.manifest, "--dest", d)
        self.assertEqual(rc, 0)

    def test_workspace_edition_keeps_markers(self):
        d = self.tmp / "d"
        rc, _, err = self.pull(d, "--edition", "workspace")
        self.assertEqual(rc, 0, err)
        self.assertEqual((d / "tool.py").read_bytes(), (self.src / "tool.py").read_bytes())

    def test_reads_commit_not_working_tree(self):
        put(self.src, "payload/a.txt", b"DIRTY\n")
        put(self.src, "payload/untracked.txt", b"new\n")
        d = self.tmp / "d"
        rc, _, err = self.pull(d)
        self.assertEqual(rc, 0, err)
        self.assertEqual((d / "out/a.txt").read_bytes(), b"alpha\n")
        self.assertFalse((d / "out/untracked.txt").exists())

    def test_pending_source_carried(self):
        m = json.loads(self.manifest.read_bytes())
        m["sources"]["k"] = {"repo": "nowhere"}
        m["entries"].append({"source": "k", "path": "x", "dest": "k", "class": "managed"})
        self.manifest.write_bytes(json.dumps(m).encode())
        d = self.tmp / "d"
        rc, out, err = self.pull(d, "--commit", "k=pending")
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["skipped_pending"], ["k"])
        self.assertEqual(self.lock(d)["sources"]["k"]["commit"], "pending")
        rc, _, _ = cli("check", "--manifest", self.manifest, "--dest", d)
        self.assertEqual(rc, 0)

    def test_dry_run_writes_nothing(self):
        d = self.tmp / "d"
        rc, _, err = self.pull(d, "--dry-run")
        self.assertEqual(rc, 0, err)
        self.assertFalse(d.exists())

    def test_source_flag_overrides_repo(self):
        m = json.loads(self.manifest.read_bytes())
        m["sources"]["s"]["repo"] = "does-not-exist"
        self.manifest.write_bytes(json.dumps(m).encode())
        d = self.tmp / "d"
        rc, _, err = self.pull(d, "--source", self.src)
        self.assertEqual(rc, 0, err)


class TestStrip(unittest.TestCase):
    def strip(self, data, edition="engagement"):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "f.txt"
            p.write_bytes(data)
            return cli("strip", "--edition", edition, p)

    def test_markdown_crlf(self):
        rc, out, _ = self.strip(b"a\r\n<!-- EDITION:workspace:start -->\r\nx\r\n<!-- EDITION:workspace:end -->\r\nb\r\n")
        self.assertEqual((rc, out), (0, b"a\r\nb\r\n"))

    def test_code_indented_lf(self):
        rc, out, _ = self.strip(b"if x:\n    # EDITION:workspace:start\n    y()\n    # EDITION:workspace:end\n    z()\n")
        self.assertEqual((rc, out), (0, b"if x:\n    z()\n"))

    def test_no_trailing_newline_preserved(self):
        rc, out, _ = self.strip(b"a\n# EDITION:workspace:start\nx\n# EDITION:workspace:end\nb")
        self.assertEqual(out, b"a\nb")

    def test_workspace_edition_unchanged(self):
        data = b"a\n# EDITION:workspace:start\nx\n# EDITION:workspace:end\n"
        rc, out, _ = self.strip(data, "workspace")
        self.assertEqual((rc, out), (0, data))

    def test_unbalanced(self):
        for data in (b"# EDITION:workspace:start\nx\n",
                     b"x\n# EDITION:workspace:end\n",
                     b"# EDITION:workspace:start\n# EDITION:workspace:start\n# EDITION:workspace:end\n",
                     b"<!-- EDITION:workspace:start -->\n# EDITION:workspace:end\n"):
            rc, out, err = self.strip(data)
            self.assertNotEqual(rc, 0, data)
            self.assertIn("template_sync:", err)
            self.assertEqual(out, b"")

    def test_help_lists_commands(self):
        rc, out, _ = cli("--help")
        for c in (b"pull", b"check", b"init", b"strip"):
            self.assertIn(c, out)


if __name__ == "__main__":
    unittest.main()
