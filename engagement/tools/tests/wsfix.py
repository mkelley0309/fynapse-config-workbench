"""Shared temp-workspace fixture for the Phase 3 tests (create flags, close checks, handoff fixture).

Every command runs as a subprocess with WORKSPACE_ROOT pointed at a temp directory, so no live
control-plane file is ever touched.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import harnesslib as H  # noqa: E402

BACKLOG3 = ("| id | item | status | route |\n|---|---|---|---|\n"
            "| r1 | first | open | |\n| r2 | second | open | |\n| r3 | third | open | |\n")
LOCKS = ("| lock | probe | meaning |\n|---|---|---|\n"
         "| vault-edit | git-dirty:knowledge/vault | one unit edits the vault |\n")
OBJ_INDEX = ("# obj\n\n## Key Decisions Log\n\n| Decision | Rationale | By | Date |\n|---|---|---|---|\n"
             "| chose x | because | operator | 2026-11-09 |\n\n## Definition of Done\n\nx\n")
FOLDER = {"workstream.py": "workstreams", "assignment.py": "assignments", "cadence.py": "cadences"}


class WSBase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name).resolve()
        self.cp = self.root / "control-plane"
        (self.cp / "intake").mkdir(parents=True)
        self.write("control-plane/locks.md", LOCKS)
        self.write("control-plane/objectives/obj/index.md", OBJ_INDEX)
        self.milestone(1)
        self.milestone(2)

    # -- files
    def write(self, rel, text):
        f = self.root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8", newline="\n")
        return f

    def milestone(self, n, status="open", **extra):
        fm = {"note_type": "milestone", "id": f"obj#{n}", "title": f"m{n}", "status": status}
        fm.update(extra)
        lines = ["---"] + [f"{k}: {H.render_value(v)}" for k, v in fm.items()] + ["---", "", "x", ""]
        self.write(f"control-plane/objectives/obj/milestones/{n:02d}-m.md", "\n".join(lines))

    def raw_intake(self, slug, **over):
        fm = {"note_type": "intake", "kind": "item", "status": "triaged", "captured": "2026-11-01",
              "source": "s", "objective": "obj", "route": "tools", "depends_on": [], "related": [],
              "locks": [], "inputs": [], "backlog": []}
        fm.update(over)
        lines = ["---"] + [f"{k}: {H.render_value(v)}" for k, v in fm.items()] + ["---", "", f"# {slug}", ""]
        self.write(f"control-plane/intake/{slug}.md", "\n".join(lines))

    def gate(self, slug, status="open"):
        self.write(f"control-plane/gates/{slug}.md",
                   f"---\nnote_type: gate\ntitle: g\ngate_type: human\nwho: operator\ncriteria: c\n"
                   f"status: {status}\nobjective: obj\n---\n\n# g\n")

    def backlog_file(self, rel="outputs/prod/gaps.md", text=BACKLOG3):
        return self.write(rel, text)

    # -- commands
    def run_(self, script, *args):
        env = dict(os.environ, WORKSPACE_ROOT=str(self.root))
        r = subprocess.run([sys.executable, "-B", str(TOOLS / script), *args], cwd=self.root, env=env,
                           capture_output=True, text=True, encoding="utf-8")
        return r.returncode, r.stdout, r.stderr

    def ok(self, script, *args):
        code, out, err = self.run_(script, *args)
        self.assertEqual(code, 0, out + err)
        return out

    def snap(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in sorted(self.root.rglob("*")) if p.is_file()}

    def refused(self, script, *args, text=None):
        """The call exits 1 and leaves every file byte-identical."""
        before = self.snap()
        code, out, err = self.run_(script, *args)
        self.assertEqual(code, 1, out + err)
        self.assertEqual(self.snap(), before, "a refused call must not write anything")
        if text:
            self.assertIn(text, err)
        return err

    # -- reads
    def unit_index(self, script, name):
        return self.cp / FOLDER[script] / name / "index.md"

    def ufm(self, script, name):
        return H.fm_read(self.unit_index(script, name))[0]

    def ifm(self, slug, archived=False):
        return H.fm_read(self.cp / "intake" / ("_archive" if archived else "") / f"{slug}.md")[0]

    def mfm(self, n):
        return H.fm_read(self.cp / "objectives" / "obj" / "milestones" / f"{n:02d}-m.md")[0]

    def residuals(self, script, name, *bullets):
        p = self.unit_index(script, name)
        t = p.read_text(encoding="utf-8")
        import re
        new, n = re.subn(r"(## Residuals\n\n).*?(## Cross-links)",
                         lambda m: m.group(1) + "\n".join(bullets) + "\n\n" + m.group(2), t, count=1, flags=re.S)
        assert n == 1, "Residuals section not found"
        p.write_text(new, encoding="utf-8", newline="\n")

    def close_args(self, script, name):
        return ["retire", name, "--reason", "done"] if script == "cadence.py" else ["complete", name]
