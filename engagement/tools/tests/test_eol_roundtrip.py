#!/usr/bin/env python3
"""File-level EOL round-trip tests for every mutating command of objective.py,
assignment.py, cadence.py and workstream.py (incl. set-unit on all three units,
workstream complete/archive/delete, create --intake-source/--milestone/--locks
and objective render with a touched intake record and milestone). Intake's own
commands live in test_intake_eol.py.

Each case builds a temp workspace, rewrites every .md to mixed EOL (alternating
CRLF/LF lines), runs one command as a subprocess, then asserts that only the
lines the command meant to touch changed: all other lines keep their exact bytes.

Run:  python -B -m unittest tools.tests.test_eol_roundtrip
"""

import difflib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
MAX_CHANGED = 12  # generous cap per file; a whole-file rewrite is 20+ lines


def run(ws, script, *args, check=True):
    env = dict(os.environ, WORKSPACE_ROOT=str(ws))
    r = subprocess.run([sys.executable, "-B", str(TOOLS / script), *args], cwd=ws,
                       env=env, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise AssertionError(f"{script} {args} failed: {r.stdout}\n{r.stderr}")
    return r


def mix_eol(ws):
    """Rewrite every .md under ws with alternating CRLF/LF lines."""
    for p in Path(ws).rglob("*.md"):
        lines = p.read_bytes().replace(b"\r\n", b"\n").split(b"\n")
        out = []
        for i, ln in enumerate(lines[:-1]):
            out.append(ln + (b"\r\n" if i % 2 else b"\n"))
        if lines[-1]:
            out.append(lines[-1])
        p.write_bytes(b"".join(out))


def snapshot(ws):
    return {p.relative_to(ws).as_posix(): p.read_bytes() for p in Path(ws).rglob("*.md")}


def byte_lines(b):
    return b.splitlines(keepends=True)


def changed_lines(old, new):
    sm = difflib.SequenceMatcher(None, byte_lines(old), byte_lines(new), autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")


def find_new_path(rel, after):
    if rel in after:
        return rel
    # moved by complete/abandon into objectives/_archive/<bucket>/<name>/...
    parts = rel.split("/")
    if len(parts) > 3 and parts[:2] == ["control-plane", "objectives"]:
        for bucket in ("closed", "abandoned"):
            cand = "/".join(parts[:2] + ["_archive", bucket] + parts[2:])
            if cand in after:
                return cand
    return None


class RoundTrip(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.ws = Path(self._d.name)
        for d in ("objectives", "workstreams", "assignments", "cadences"):
            (self.ws / "control-plane" / d).mkdir(parents=True)

    def tearDown(self):
        self._d.cleanup()

    def setup_steps(self, steps):
        for step in steps:
            if callable(step):              # seed callback: step(self)
                step(self)
                continue
            script, *args = step
            if script == "@residuals":      # fill `## Residuals` so a close command is accepted
                f = self.ws / "control-plane" / args[0] / args[1] / "index.md"
                anchor = "-->" + chr(10) * 2 + "## Cross-links"
                f.write_text(f.read_text(encoding="utf-8").replace(
                    anchor, "-->" + chr(10) * 2 + "- none" + chr(10) * 2 + "## Cross-links"),
                    encoding="utf-8", newline=chr(10))
                continue
            run(self.ws, script, *args)

    def seed(self, rel, text):
        f = self.ws / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8", newline=chr(10))

    def seed_locks(self):
        self.seed("control-plane/locks.md", chr(10).join([
            "| lock | probe | meaning |", "|---|---|---|",
            "| vault | git-dirty:knowledge/vault | vault busy |", ""]))

    def seed_intake(self, slug="src"):
        fm = ["---", "note_type: intake", "kind: item", "status: triaged", "captured: 2026-11-01",
              "source: s", "objective: obj", "route: tools", "depends_on: []", "related: []",
              "locks: []", "inputs: []", "backlog: []", "---", "", f"# {slug}", "", "body one", "body two", ""]
        self.seed(f"control-plane/intake/{slug}.md", chr(10).join(fm))

    def seed_portfolio(self):
        self.seed("control-plane/workstreams/index.md", chr(10).join([
            "# Workstreams", "", "## Active", "", "| name | note |", "|---|---|", "| [ws](ws/index.md) | x |", "",
            "## Recently Completed", "", "| entry | description | date |", "|---|---|---|",
            "| [old](_log/old.md) | older | 2026-01-01 |", "", "footer line", ""]))

    def case(self, setup, script, *args, new_ok=True, cap=MAX_CHANGED):
        """setup steps (LF), mix EOL, run command, assert minimal churn."""
        self.setup_steps(setup)
        mix_eol(self.ws)
        before = snapshot(self.ws)
        run(self.ws, script, *args)
        after = snapshot(self.ws)
        touched = 0
        for rel, old in before.items():
            rel_new = find_new_path(rel, after)
            if rel_new is None:
                continue  # deleted by the command
            new = after[rel_new]
            if new == old:
                continue
            touched += 1
            n = changed_lines(old, new)
            self.assertLessEqual(n, cap, f"{rel}: {n} lines changed (whole-file rewrite?)")
            # an untouched-EOL check: CRLF lines the command did not edit must survive
            self.assertIn(b"\r\n", new, f"{rel}: lost all CRLF")
            self.assertIn(b"\n", new.replace(b"\r\n", b""), f"{rel}: lost all LF")
        return touched

    # ------------------------------------------------------------------ objective
    OBJ = [("objective.py", "create", "obj")]

    def test_objective_create_second(self):
        self.case(self.OBJ, "objective.py", "create", "obj2")

    def test_objective_health(self):
        self.assertGreaterEqual(self.case(self.OBJ, "objective.py", "health", "obj", "at-risk"), 1)

    def test_objective_set_cadence(self):
        self.case(self.OBJ, "objective.py", "set-cadence", "obj", "monthly")

    def test_objective_add_kr(self):
        self.case(self.OBJ, "objective.py", "add-kr", "obj", "reach", "10")

    def test_objective_update_kr(self):
        self.case(self.OBJ + [("objective.py", "add-kr", "obj", "reach", "10")],
                  "objective.py", "update-kr", "obj", "reach", "5")

    def test_objective_add_milestone(self):
        self.case(self.OBJ, "objective.py", "add-milestone", "obj", "--title", "first thing")

    MS = OBJ + [("objective.py", "add-milestone", "obj", "--title", "first thing")]

    def test_objective_check_milestone(self):
        self.case(self.MS, "objective.py", "check-milestone", "obj", "1")

    def test_objective_set_milestone(self):
        self.case(self.MS, "objective.py", "set-milestone", "obj", "1", "--order", "5")

    def test_objective_drop_milestone(self):
        self.case(self.MS, "objective.py", "drop-milestone", "obj", "1", "--reason", "no longer needed")

    def test_objective_log_decision(self):
        self.case(self.OBJ, "objective.py", "log-decision", "obj", "decide", "because")

    def test_objective_link_workstream(self):
        self.case(self.OBJ + [("workstream.py", "create", "ws1")],
                  "objective.py", "link-workstream", "obj", "ws1")

    def test_objective_checkpoint(self):
        self.case(self.OBJ, "objective.py", "checkpoint", "obj", "--date", "2026-01-01")

    def test_objective_complete(self):
        self.case(self.OBJ, "objective.py", "complete", "obj", "--reason", "done")

    def test_objective_abandon(self):
        self.case(self.OBJ, "objective.py", "abandon", "obj", "--reason", "nope")

    # ------------------------------------------------------------------ assignment
    ASG = [("assignment.py", "create", "asg"), ("@residuals", "assignments", "asg")]

    def test_assignment_create_second(self):
        self.case(self.ASG, "assignment.py", "create", "asg2")

    def test_assignment_validate(self):
        self.case(self.ASG, "assignment.py", "validate", "asg")

    def test_assignment_complete(self):
        self.case(self.ASG + [("assignment.py", "validate", "asg")], "assignment.py", "complete", "asg")

    def test_assignment_delete(self):
        self.case(self.ASG + [("assignment.py", "validate", "asg"), ("assignment.py", "complete", "asg")],
                  "assignment.py", "delete", "asg")

    # ------------------------------------------------------------------ cadence
    CAD = [("cadence.py", "create", "cad"), ("@residuals", "cadences", "cad")]

    def test_cadence_create_second(self):
        self.case(self.CAD, "cadence.py", "create", "cad2")

    def test_cadence_run(self):
        self.case(self.CAD, "cadence.py", "run", "cad", "--note", "did it", "--learned", "faster")

    def test_cadence_pause(self):
        self.case(self.CAD, "cadence.py", "pause", "cad")

    def test_cadence_resume(self):
        self.case(self.CAD + [("cadence.py", "pause", "cad")], "cadence.py", "resume", "cad")

    def test_cadence_retire(self):
        self.case(self.CAD, "cadence.py", "retire", "cad", "--reason", "automated")

    def test_cadence_abandon(self):
        self.case(self.CAD, "cadence.py", "abandon", "cad", "--reason", "gone")

    def test_cadence_delete(self):
        self.case(self.CAD + [("cadence.py", "retire", "cad", "--reason", "x")],
                  "cadence.py", "delete", "cad", "--force")

    # ------------------------------------------------------------------ workstream
    WS = [("workstream.py", "create", "ws")]

    def test_workstream_create_second(self):
        self.case(self.WS, "workstream.py", "create", "ws2")

    def test_workstream_advance(self):
        self.case(self.WS, "workstream.py", "advance", "ws", "research")

    def test_workstream_block_unblock(self):
        self.case(self.WS, "workstream.py", "block", "ws", "stuck")
        run(self.ws, "workstream.py", "unblock", "ws")

    def test_workstream_check_step(self):
        ws_dir = self.ws / "control-plane" / "workstreams" / "ws"
        self.setup_steps(self.WS)
        (ws_dir / "blueprint.md").write_text(
            "# Blueprint\n\n## Steps\n\n- [ ] 1.1 first\n- [ ] 1.2 second\n- [ ] 1.3 third\n", encoding="utf-8")
        mix_eol(self.ws)
        before = (ws_dir / "blueprint.md").read_bytes()
        run(self.ws, "workstream.py", "check-step", "ws", "1.1")
        after = (ws_dir / "blueprint.md").read_bytes()
        self.assertEqual(changed_lines(before, after), 1)  # one tick = one line
        self.assertEqual(byte_lines(before)[0], byte_lines(after)[0])

    def test_workstream_link(self):
        self.case(self.WS + [("assignment.py", "create", "asg")], "workstream.py", "link", "ws", "asg")

    def test_workstream_aside(self):
        self.case(self.WS, "workstream.py", "aside", "ws", "side-job", "--reason", "came up")

    # ------------------------------------------------------------------ set-unit
    SEEDED = [lambda t: t.seed_locks(), lambda t: t.seed_intake()]

    def test_workstream_set_unit(self):
        self.assertGreaterEqual(self.case(self.WS + self.SEEDED, "workstream.py", "set-unit", "ws",
                                          "--locks", "vault", "--intake-source", "intake:src"), 1)

    def test_assignment_set_unit(self):
        self.assertGreaterEqual(self.case([("assignment.py", "create", "asg")] + self.SEEDED,
                                          "assignment.py", "set-unit", "asg",
                                          "--locks", "vault", "--intake-source", "intake:src"), 1)

    def test_cadence_set_unit(self):
        self.assertGreaterEqual(self.case([("cadence.py", "create", "cad")] + self.SEEDED,
                                          "cadence.py", "set-unit", "cad",
                                          "--locks", "vault", "--intake-source", "intake:src"), 1)

    def test_workstream_set_unit_milestone(self):
        self.assertGreaterEqual(self.case(self.MS + [("workstream.py", "create", "ws")],
                                          "workstream.py", "set-unit", "ws", "--milestone", "obj#1"), 1)

    # ------------------------------------------------------------------ create with bindings
    def test_workstream_create_bound(self):
        self.assertGreaterEqual(self.case(self.MS + self.SEEDED, "workstream.py", "create", "wsb",
                                          "--intake-source", "intake:src", "--milestone", "obj#1",
                                          "--locks", "vault"), 1)

    def test_assignment_create_bound(self):
        self.assertGreaterEqual(self.case(self.MS + self.SEEDED, "assignment.py", "create", "asgb",
                                          "--intake-source", "intake:src", "--milestone", "obj#1",
                                          "--locks", "vault"), 1)

    # ------------------------------------------------------------------ workstream close path
    WSR = [lambda t: t.seed_portfolio(), ("workstream.py", "create", "ws"), ("@residuals", "workstreams", "ws")]

    def test_workstream_complete(self):
        self.case(self.WSR, "workstream.py", "complete", "ws")

    def test_workstream_complete_settles_intake_and_milestone(self):
        setup = self.MS + self.SEEDED + [("workstream.py", "create", "wsc", "--intake-source", "intake:src",
                                          "--milestone", "obj#1"), ("@residuals", "workstreams", "wsc")]
        self.assertGreaterEqual(self.case(setup, "workstream.py", "complete", "wsc"), 2)

    def test_workstream_archive(self):
        self.case(self.WSR, "workstream.py", "archive", "ws", "--log-date", "2026-11-10", "--description", "d")

    def test_workstream_delete(self):
        self.case(self.WSR, "workstream.py", "delete", "ws")

    def test_objective_render(self):
        self.assertGreaterEqual(self.case(
            self.MS + [("objective.py", "render", "obj", "--adopt"),
                       ("workstream.py", "create", "wsr", "--milestone", "obj#1")],
            "objective.py", "render", "obj"), 1)

    def test_objective_render_adopt(self):
        # --adopt inserts whole new sections (pure insertion, not churn); existing lines keep their bytes
        self.case(self.MS, "objective.py", "render", "obj", "--adopt", cap=24)


if __name__ == "__main__":
    unittest.main()
