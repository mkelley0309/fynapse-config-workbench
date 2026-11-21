#!/usr/bin/env python3
"""Mixed-EOL round-trip tests for every mutating subcommand of intake.py: capture, triage, set,
consume, drop, archive, split, backlog (--done/--drop/--move), gate add/resolve/drop/set, render.

Each case seeds a temp workspace (LF), rewrites every .md to alternating CRLF/LF lines, runs one
command as a subprocess (WORKSPACE_ROOT), then asserts that only the lines the command meant to
touch changed: untouched files stay byte-identical, edited files change <= `cap` lines, and a
moved file (archive/split) keeps every other line's exact bytes.

Run:  python -B -m unittest tools.tests.test_intake_eol
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_eol_roundtrip import changed_lines, mix_eol, run, snapshot  # noqa: E402

NL = chr(10)
BACKLOG = NL.join(["# Backlog", "", "Intro prose line one.", "Intro prose line two.", "",
                   "| id | item | status | route |", "|---|---|---|---|",
                   "| 1 | first | open | |", "| 2 | second | open | |", "| 3 | third | open | |",
                   "", "Trailing prose one.", "Trailing prose two.", ""])
LOCKS = NL.join(["| lock | probe | meaning |", "|---|---|---|",
                 "| vault | git-dirty:knowledge/vault | vault busy |", ""])
BL = "outputs/prod/backlog.md"
I = "control-plane/intake/"
MS1 = "control-plane/objectives/demo/milestones/01-m.md"


class IntakeEol(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.ws = Path(self._d.name).resolve()
        (self.ws / "control-plane" / "intake").mkdir(parents=True)

    def tearDown(self):
        self._d.cleanup()

    # ---- seeding (LF; mix_eol runs afterwards)
    def seed(self, rel, text):
        f = self.ws / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8", newline=NL)

    def intake(self, slug, **over):
        fm = {"note_type": "intake", "kind": "item", "status": "triaged", "captured": "2026-11-01",
              "source": "s", "objective": "demo", "route": "tools", "depends_on": "[]", "related": "[]",
              "locks": "[]", "inputs": "[]", "backlog": "[]"}
        fm.update(over)
        lines = ["---"] + [f"{k}: {v}" for k, v in fm.items()] + ["---", "", f"# {slug}", "",
                 "body one", "body two", "body three", "body four", ""]
        self.seed(f"{I}{slug}.md", NL.join(lines))

    def milestone(self, n=1):
        self.seed(f"control-plane/objectives/demo/milestones/{n:02d}-m.md", NL.join(
            ["---", "note_type: milestone", f"id: demo#{n}", f"title: m{n}", "status: open", "---", "",
             "x", "y", "z", ""]))

    def gate(self, slug="g"):
        self.seed(f"control-plane/gates/{slug}.md", NL.join(
            ["---", "note_type: gate", f"title: {slug}", "gate_type: human", "who: me", "criteria: c",
             "objective: none", "status: open", "---", "", "body", ""]))

    def backlog(self):
        self.seed(BL, BACKLOG)

    def locks(self):
        self.seed("control-plane/locks.md", LOCKS)

    def pre(self, *argv):
        run(self.ws, "intake.py", *argv)

    # ---- harness
    @staticmethod
    def body(b):
        ls = b.splitlines(keepends=True)
        end = next(i for i, l in enumerate(ls[1:], 1) if l.rstrip(bytes([13, 10])) == b"---")
        return b"".join(ls[end + 1:])

    @staticmethod
    def locate(rel, after):
        if rel in after:
            return rel
        parts = rel.split("/")
        if parts[:2] == ["control-plane", "intake"] and len(parts) == 3:
            cand = I + "_archive/" + parts[2]
            if cand in after:
                return cand
        return None

    def case(self, *argv, cap=6, changed=(), new=()):
        """Mix EOL, run `intake.py argv`, assert minimal churn.
        changed: rel paths that must differ (<= cap changed lines); every other pre-existing file
        must be byte-identical, except a moved file, which is held to the same cap."""
        mix_eol(self.ws)
        before = snapshot(self.ws)
        run(self.ws, "intake.py", *argv)
        after = snapshot(self.ws)
        for rel in new:
            self.assertIn(rel, after, f"{rel} not created")
        for rel, old in before.items():
            rn = self.locate(rel, after)
            self.assertIsNotNone(rn, f"{rel} vanished")
            cur = after[rn]
            if rel in changed or rn != rel:
                n = changed_lines(old, cur)
                self.assertLessEqual(n, cap, f"{rel}: {n} lines changed (whole-file rewrite?)")
                if old.startswith(b"---") and rel.startswith(I):    # frontmatter edit: body bytes survive
                    self.assertEqual(self.body(old), self.body(cur), f"{rel}: body bytes changed")
                self.assertIn(b"\r\n", cur, f"{rel}: lost all CRLF")
                self.assertIn(b"\n", cur.replace(b"\r\n", b""), f"{rel}: lost all LF")
            else:
                self.assertEqual(old, cur, f"{rel}: modified but should be untouched")
        for rel in changed:
            self.assertNotEqual(before[rel], after[self.locate(rel, after)], f"{rel}: expected a change")
        return before, after

    # ------------------------------------------------------------------ capture
    def test_capture(self):
        self.intake("other")
        self.milestone()
        self.case("capture", "fresh", "--title", "T", "--source", "S", new=[I + "fresh.md"])

    def test_capture_milestone_route(self):
        self.milestone()
        self.case("capture", "fresh", "--title", "T", "--source", "S", "--route", "milestone:demo#1",
                  new=[I + "fresh.md"])

    # ------------------------------------------------------------------ triage
    def test_triage(self):
        self.intake("a", status="captured", route="none", objective="none")
        self.intake("other")
        self.locks()
        self.backlog()
        self.gate()
        self.case("triage", "a", "--objective", "demo", "--route", "tools", "--depends-on", "intake:other",
                  "--related", "gate:g", "--locks", "vault", "--inputs", BL, "--backlog", BL,
                  "--keep-until", "gate:g", changed=[I + "a.md"], cap=10)

    # ------------------------------------------------------------------ set
    def test_set_scalars(self):
        self.intake("a")
        self.case("set", "a", "--source", "new source", "--route", "assignment:x", changed=[I + "a.md"])

    def test_set_lists(self):
        self.intake("a")
        self.intake("other")
        self.locks()
        self.case("set", "a", "--depends-on", "intake:other", "--locks", "vault", changed=[I + "a.md"])

    # ------------------------------------------------------------------ consume / drop
    def test_consume(self):
        self.intake("a")
        self.intake("other")
        self.case("consume", "a", "--by", "assignment:foo", changed=[I + "a.md"])

    def test_drop(self):
        self.intake("a")
        self.intake("other")
        self.case("drop", "a", "--reason", "not needed", changed=[I + "a.md"])

    # ------------------------------------------------------------------ archive / split
    def test_archive_dropped(self):
        self.intake("a")
        self.intake("other")
        self.pre("drop", "a", "--reason", "r")
        before, after = self.case("archive", "a")
        self.assertEqual(before[I + "a.md"], after[I + "_archive/a.md"])   # pure move: same bytes

    def test_archive_consumed(self):
        self.intake("a")
        self.pre("consume", "a", "--by", "assignment:foo")
        before, after = self.case("archive", "a")
        self.assertEqual(before[I + "a.md"], after[I + "_archive/a.md"])

    def test_split(self):
        self.intake("p")
        self.intake("other")
        _, after = self.case("split", "p", "--into", "a,b", "--route", "a=assignment:x",
                             new=[I + "p-a.md", I + "p-b.md"])
        self.assertIn(I + "_archive/p.md", after)

    # ------------------------------------------------------------------ backlog
    def test_backlog_done(self):
        self.backlog()
        self.intake("a")
        self.case("backlog", BL, "--done", "2", changed=[BL], cap=2)

    def test_backlog_drop(self):
        self.backlog()
        self.intake("a")
        self.case("backlog", BL, "--drop", "1", "--reason", "stale", changed=[BL], cap=5)

    def test_backlog_move_unit(self):
        self.backlog()
        self.intake("a")
        self.case("backlog", BL, "--move", "2", "--to", "assignment:foo", changed=[BL], cap=3,
                  new=[I + "prod-handover-1.md"])

    def test_backlog_move_milestone(self):
        self.backlog()
        self.milestone()
        self.case("backlog", BL, "--move", "1", "--to", "milestone:demo#1", changed=[BL, MS1], cap=3)

    # ------------------------------------------------------------------ gate
    def test_gate_add(self):
        self.gate("existing")
        self.intake("a")
        self.case("gate", "add", "g2", "--title", "G", "--type", "human", "--who", "me", "--criteria", "c",
                  new=["control-plane/gates/g2.md"])

    def test_gate_resolve(self):
        self.gate()
        self.gate("other")
        self.case("gate", "resolve", "g", "--evidence", "proof", changed=["control-plane/gates/g.md"])

    def test_gate_drop(self):
        self.gate()
        self.gate("other")
        self.case("gate", "drop", "g", "--reason", "moot", changed=["control-plane/gates/g.md"])

    def test_gate_set(self):
        self.gate()
        self.gate("other")
        self.case("gate", "set", "g", "--who", "someone else", changed=["control-plane/gates/g.md"])

    # ------------------------------------------------------------------ render
    def seed_queue_index(self):
        self.seed(I + "index.md", NL.join(
            ["# Intake", "", "Intro one.", "Intro two.", "", "## Live Queue", "", "old hand-kept queue", "",
             "## Notes", "", "tail one", "tail two", ""]))

    def test_render_adopt(self):
        self.seed_queue_index()
        self.intake("a")
        self.case("render", "--adopt", changed=[I + "index.md"], cap=12)

    def test_render_refresh(self):
        self.seed_queue_index()
        self.intake("a")
        self.pre("render", "--adopt")
        self.intake("b")                       # queue now stale
        self.case("render", changed=[I + "index.md"], cap=4)


if __name__ == "__main__":
    unittest.main()
