"""Tests for tools/engagement_new.py and the hop-1 lock.

Run from the wb root with WORKSPACE_ROOT unset:
    python -B -m unittest discover -s tests -t .
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WB = Path(__file__).resolve().parent.parent
SLUG = "acme-demo"
CRITERIA = """# Success criteria

- Journal postings reconcile to the example ledger
* Bulk configuration validates with zero errors
1. Sandbox upload accepted

Example sign-off recorded
"""
N_CRITERIA = 4
GATES = ("sandbox-probe", "client-data-pack", "remote-permitted")


def env():
    return {k: v for k, v in os.environ.items() if k != "WORKSPACE_ROOT"}


def run(cmd, cwd):
    return subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=env(), capture_output=True, text=True)


def git(cwd, *args):
    r = run(["git", *args], cwd)
    if r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {r.stderr}")
    return r.stdout


def snapshot_clone(dest):
    """Clone wb and overlay its working tree (tracked + untracked, not ignored), then commit in the clone."""
    git(dest.parent, "clone", "-q", str(WB), str(dest))
    git(dest, "config", "core.autocrlf", "false")
    files = [p for p in git(WB, "ls-files", "-co", "--exclude-standard", "-z").split("\0") if p]
    for p in git(dest, "ls-files", "-z").split("\0"):
        if p and not (WB / p).exists():
            (dest / p).unlink()
    for p in files:
        src = WB / p
        if src.is_file():
            out = dest / p
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(src.read_bytes())
    git(dest, "add", "-A")
    if git(dest, "status", "--porcelain").strip():
        git(dest, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
            "commit", "-q", "-m", "snapshot")


def kr_count(index_text):
    m = re.search(r"^## Key Results\n(.*?)(?=^## |\Z)", index_text, re.M | re.S)
    if not m:
        return 0
    rows, after = 0, False
    for ln in m.group(1).splitlines():
        if ln.startswith("|---"):
            after = True
            continue
        if after and ln.startswith("|") and "*(none yet)*" not in ln:
            rows += 1
    return rows


def tree_state(root):
    out = {}
    for p in Path(root).rglob("*"):
        if p.is_file() and ".git" not in p.relative_to(root).parts:
            out[p.relative_to(root).as_posix()] = p.read_bytes()
    return out


class EngagementNewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wb-test-"))
        cls.clone = cls.tmp / "wb"
        snapshot_clone(cls.clone)
        cls.tool = cls.clone / "tools" / "engagement_new.py"
        cls.criteria = cls.tmp / "criteria.md"
        cls.criteria.write_text(CRITERIA, encoding="utf-8", newline="\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def new_target(self, name):
        t = self.tmp / name
        t.mkdir()
        git(t, "init", "-q")
        return t

    def instantiate(self, target, *extra):
        return run([sys.executable, "-B", self.tool, target, "--name", SLUG,
                    "--success-criteria", self.criteria, "--ref", "HEAD", *extra], self.tmp)

    def test_instantiate_and_rerun(self):
        t = self.new_target("eng-instantiate")
        r = self.instantiate(t)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        nxt = run([sys.executable, "-B", "tools/objective.py", "next", SLUG], t)
        self.assertEqual(nxt.returncode, 0, nxt.stdout + nxt.stderr)

        chk = run([sys.executable, "-B", t / "tools" / "template-sync" / "template_sync.py", "check",
                   "--dest", t, "--lock", t / "template.lock.json"], t)
        self.assertEqual(chk.returncode, 0, chk.stdout + chk.stderr)

        for g in GATES:
            self.assertTrue((t / "control-plane" / "gates" / f"{g}.md").is_file(), g)

        idx = (t / "control-plane" / "objectives" / SLUG / "index.md").read_text(encoding="utf-8")
        self.assertEqual(kr_count(idx), N_CRITERIA)

        before = tree_state(t)
        again = self.instantiate(t)
        self.assertEqual(again.returncode, 1, again.stdout + again.stderr)
        self.assertIn("already instantiated", again.stderr)
        self.assertEqual(tree_state(t), before)

    def test_target_inside_wb_refused(self):
        r = self.instantiate(self.clone / "nested-target")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse((self.clone / "nested-target").exists())

    def test_adopt(self):
        local = b"# local readme\n"
        t1 = self.new_target("eng-keep")
        (t1 / "README.md").write_bytes(local)
        r = self.instantiate(t1)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((t1 / "README.md").read_bytes(), local)

        t2 = self.new_target("eng-adopt")
        (t2 / "README.md").write_bytes(local)
        r = self.instantiate(t2, "--adopt")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((t2 / "README.md").read_bytes(), (self.clone / "engagement" / "README.md").read_bytes())
        self.assertIn("--- a/README.md", r.stdout)


class HarnessLockTest(unittest.TestCase):
    def test_workspace_commit_is_40_hex(self):
        lock = json.loads((WB / "harness.lock.json").read_text(encoding="utf-8"))
        self.assertRegex(lock["sources"]["workspace"]["commit"], r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
