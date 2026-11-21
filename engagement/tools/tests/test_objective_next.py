#!/usr/bin/env python3
"""objective.py next (R5/R6): classification, ordering, blockers, locks, cycles, backlog, JSON."""

import argparse
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import objective  # noqa: E402
import test_objective as TO  # noqa: E402  (module ref only: its test classes must not re-collect here)

H = objective.harnesslib


class NextBase(TO.MilestoneBase):
    # ---- fixtures
    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        return p

    def locks(self, *names):
        rows = "".join(f"| {n} | git-dirty:knowledge/vault | test lock |\n" for n in names)
        self.write("control-plane/locks.md", "# Locks\n\n| lock | probe | meaning |\n|---|---|---|\n" + rows)

    def upd(self, n, **kw):
        H.fm_write(self.ms_dir().glob(f"{n:02d}-*.md").__next__(), kw)

    def intake(self, slug, **kw):
        fm = dict(note_type="intake", kind="item", status="triaged", captured="2026-11-01",
                  source="t", objective="demo", route="candidate:workstream")
        fm.update(kw)
        lines = ["---"] + [f"{k}: {H.render_value(v)}" for k, v in fm.items()] + ["---", "", f"# {slug}", ""]
        self.write(f"control-plane/intake/{slug}.md", "\n".join(lines))

    def gate(self, slug, status="open", who="operator", criteria="decide it"):
        self.write(f"control-plane/gates/{slug}.md",
                   f"---\nnote_type: gate\ntitle: {slug}\ngate_type: decision\nwho: {who}\n"
                   f"criteria: {criteria}\nstatus: {status}\n---\n\n# {slug}\n")

    def nxt(self):
        return objective.compute_next("demo")

    def ids(self, res, key):
        return [x["id"] for x in res[key]]


class TestClassification(NextBase):
    def test_ready_when_no_deps(self):
        self.add("A")
        r = self.nxt()
        self.assertEqual(self.ids(r, "ready"), ["demo#1"])
        self.assertEqual((r["blocked"], r["human"], r["lock"]), ([], [], []))

    def test_blocked_by_open_milestone_then_ready_when_done(self):
        self.add("A")
        self.add("B", depends_on=["demo#1"])
        r = self.nxt()
        self.assertEqual(self.ids(r, "ready"), ["demo#1"])
        self.assertEqual(r["blocked"][0]["id"], "demo#2")
        self.assertEqual(r["blocked"][0]["root_blockers"], ["demo#1"])
        self.upd(1, status="done")
        r = self.nxt()
        self.assertEqual(self.ids(r, "ready"), ["demo#2"])
        self.assertEqual(r["blocked"], [])

    def test_transitive_root_blockers_report_the_leaf(self):
        self.add("A")
        self.add("B", depends_on=["demo#1"])
        self.add("C", depends_on=["demo#2"])
        r = self.nxt()
        by = {x["id"]: x["root_blockers"] for x in r["blocked"]}
        self.assertEqual(by["demo#3"], ["demo#1"])   # not demo#2: that one is itself blocked
        self.assertEqual(by["demo#2"], ["demo#1"])

    def test_root_blockers_include_gate_and_leaf(self):
        self.gate("g1")
        self.add("A")
        self.add("B", depends_on=["demo#1", "gate:g1"])
        self.add("C", depends_on=["demo#2"])
        r = self.nxt()
        by = {x["id"]: x["root_blockers"] for x in r["blocked"]}
        self.assertEqual(sorted(by["demo#3"]), ["demo#1", "gate:g1"])

    def test_human_when_only_open_gates_remain(self):
        self.gate("g1", who="alice", criteria="sign it off")
        self.add("A", depends_on=["gate:g1"])
        r = self.nxt()
        self.assertEqual(r["ready"], [])
        h = r["human"][0]
        self.assertEqual(h["id"], "demo#1")
        self.assertEqual(h["gates"], [{"id": "gate:g1", "who": "alice", "criteria": "sign it off"}])

    def test_gate_resolved_makes_ready(self):
        self.gate("g1", status="done")
        self.add("A", depends_on=["gate:g1"])
        self.assertEqual(self.ids(self.nxt(), "ready"), ["demo#1"])

    def test_dropped_gate_blocks_not_human(self):
        self.gate("g1", status="dropped")
        self.add("A", depends_on=["gate:g1"])
        r = self.nxt()
        self.assertEqual(r["human"], [])
        self.assertEqual(r["blocked"][0]["root_blockers"], ["gate:g1"])

    def test_conditional_dropped_satisfies(self):
        self.add("A", conditional=True)
        self.add("B", depends_on=["demo#1"])
        self.upd(1, status="dropped")
        self.assertEqual(self.ids(self.nxt(), "ready"), ["demo#2"])

    def test_nonconditional_dropped_never_satisfies(self):
        self.add("A")
        self.add("B", depends_on=["demo#1"])
        self.upd(1, status="dropped")
        r = self.nxt()
        self.assertEqual(r["ready"], [])
        self.assertEqual(r["blocked"][0]["root_blockers"], ["demo#1"])

    def test_cross_objective_dependency_shown_with_full_id(self):
        self.run_cmd(objective.cmd_create, name="other", title=None, origin=None, group=None)
        self.run_cmd(objective.cmd_add_milestone, **self.add_kw("O1", name="other"))
        self.add("A", depends_on=["other#1"])
        r = self.nxt()
        self.assertEqual(r["blocked"][0]["root_blockers"], ["other#1"])
        self.assertNotIn("other#1", self.ids(r, "ready"))   # other objective's work is not ranked here

    def test_unit_dependency_open_vs_closed(self):
        self.add("A", depends_on=["workstream:foo"])
        self.write("control-plane/workstreams/foo/index.md", "---\nworkstream: foo\nstatus: active\n---\n")
        self.assertEqual(self.nxt()["blocked"][0]["root_blockers"], ["workstream:foo"])
        self.write("control-plane/workstreams/_log/2026-11-01-foo.md", "log\n")
        self.assertEqual(self.ids(self.nxt(), "ready"), ["demo#1"])

    def test_active_milestones_listed_not_ranked(self):
        self.add("A")
        self.add("B")
        self.upd(1, status="active")
        r = self.nxt()
        self.assertEqual(self.ids(r, "active"), ["demo#1"])
        self.assertEqual(self.ids(r, "ready"), ["demo#2"])

    def test_intake_candidates(self):
        self.intake("cand", route="candidate:assignment")
        self.intake("tool", route="tools")
        self.intake("raw", status="captured")
        self.intake("routed-ms", route="milestone:demo#1")
        self.intake("fedone", route="candidate:workstream")
        self.intake("busy", status="active")
        self.intake("elsewhere", objective="other-obj")
        self.add("A", fed_by=["intake:fedone"])
        r = self.nxt()
        self.assertEqual(sorted(self.ids(r, "ready")), ["demo#1", "intake:cand", "intake:tool"])
        self.assertEqual(self.ids(r, "active"), ["intake:busy"])

    def test_done_milestone_not_a_candidate(self):
        self.add("A")
        self.upd(1, status="done")
        self.assertEqual(self.nxt()["ready"], [])


class TestOrdering(NextBase):
    def test_unblocks_beats_order(self):
        self.add("A", order=1)
        self.add("B", order=2)
        self.add("C", depends_on=["demo#2"])
        self.add("D", depends_on=["demo#2"])
        r = self.nxt()
        self.assertEqual(self.ids(r, "ready"), ["demo#2", "demo#1"])
        self.assertEqual([x["unblocks"] for x in r["ready"]], [2, 0])

    def test_unblocks_is_transitive_and_counts_nonterminal_only(self):
        self.add("A")
        self.add("B", depends_on=["demo#1"])
        self.add("C", depends_on=["demo#2"])
        self.add("D", depends_on=["demo#1"])
        self.upd(4, status="done")
        r = self.nxt()
        self.assertEqual(r["ready"][0]["unblocks"], 2)   # B, C (D is done)

    def test_order_breaks_unblocks_tie(self):
        self.add("A", order=5)
        self.add("B", order=3)
        self.assertEqual(self.ids(self.nxt(), "ready"), ["demo#2", "demo#1"])

    def test_id_breaks_order_tie(self):
        self.add("A", order=1)
        self.add("B", order=1)
        self.assertEqual(self.ids(self.nxt(), "ready"), ["demo#1", "demo#2"])

    def test_other_sets_listed_by_order(self):
        self.add("A")
        self.add("B", depends_on=["demo#1"], order=9)
        self.add("C", depends_on=["demo#1"], order=2)
        self.assertEqual(self.ids(self.nxt(), "blocked"), ["demo#3", "demo#2"])


class TestLocks(NextBase):
    def setUp(self):
        super().setUp()
        self.locks("vault-edit")

    def test_active_record_holds_lock(self):
        self.add("Holder", locks=["vault-edit"])
        self.add("Wants", locks=["vault-edit"])
        self.upd(1, status="active")
        r = self.nxt()
        self.assertEqual(r["ready"], [])
        self.assertEqual(r["lock"], [{"id": "demo#2", "title": "Wants", "order": 2, "backlog": None,
                                      "lock": "vault-edit", "holder": "demo#1"}])

    def test_open_workstream_and_assignment_hold_lock(self):
        self.add("Wants", locks=["vault-edit"])
        self.write("control-plane/workstreams/w/index.md",
                   "---\nworkstream: w\nstatus: active\nlocks: [vault-edit]\n---\n")
        self.assertEqual(self.nxt()["lock"][0]["holder"], "workstream:w")
        (self.root / "control-plane/workstreams/w/index.md").unlink()
        self.write("control-plane/assignments/a/index.md",
                   "---\nassignment: a\nstatus: active\nlocks: [vault-edit]\n---\n")
        self.assertEqual(self.nxt()["lock"][0]["holder"], "assignment:a")

    def test_closed_unit_does_not_hold(self):
        self.add("Wants", locks=["vault-edit"])
        self.write("control-plane/workstreams/w/index.md",
                   "---\nworkstream: w\nstatus: complete\nlocks: [vault-edit]\n---\n")
        self.assertEqual(self.ids(self.nxt(), "ready"), ["demo#1"])

    def test_cadence_holds_only_via_probe(self):
        self.add("Wants", locks=["vault-edit"])
        self.write("control-plane/cadences/c/index.md",
                   "---\ncadence: c\nstatus: active\nlocks: [vault-edit]\n---\n")
        self.assertEqual(self.ids(self.nxt(), "ready"), ["demo#1"])

    def test_probe_fires_in_git_repo(self):
        self.add("Wants", locks=["vault-edit"])
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "knowledge" / "vault").mkdir(parents=True)
        self.assertEqual(self.ids(self.nxt(), "ready"), ["demo#1"])   # clean: nothing dirty
        (self.root / "knowledge" / "vault" / "n.md").write_text("x\n", encoding="utf-8")
        r = self.nxt()
        self.assertEqual(r["ready"], [])
        self.assertEqual((r["lock"][0]["lock"], r["lock"][0]["holder"]), ("vault-edit", "uncommitted changes"))

    def test_probe_fires_in_nested_repo(self):
        self.add("Wants", locks=["vault-edit"])
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false"]
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.write(".gitignore", "knowledge/\n")
        kn = self.root / "knowledge"
        kn.mkdir()
        subprocess.run(["git", "init", "-q", str(kn)], check=True)
        self.write("knowledge/vault/n.md", "x\n")
        r = self.nxt()                                                   # dirty (untracked) -> fires
        self.assertEqual(r["ready"], [])
        self.assertEqual((r["lock"][0]["lock"], r["lock"][0]["holder"]), ("vault-edit", "uncommitted changes"))
        subprocess.run(g + ["-C", str(kn), "add", "-A"], check=True, capture_output=True)
        subprocess.run(g + ["-C", str(kn), "commit", "-qm", "base"], check=True, capture_output=True)
        self.assertEqual(self.ids(self.nxt(), "ready"), ["demo#1"])     # clean -> quiet
        self.write("knowledge/vault/n.md", "y\n")
        self.assertEqual(self.nxt()["ready"], [])                        # modified tracked -> fires

    def test_probe_missing_path_not_fired(self):
        self.add("Wants", locks=["vault-edit"])
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        with self.assertRaises(H.HarnessError):
            H.probe_fires(self.root, "git-dirty:knowledge/vault")
        self.assertEqual(self.ids(self.nxt(), "ready"), ["demo#1"])

    def test_lock_note_when_ready_items_share_free_lock(self):
        self.add("A", locks=["vault-edit"])
        self.add("B", locks=["vault-edit"])
        self.add("C")
        r = self.nxt()
        self.assertEqual(len(r["ready"]), 3)
        self.assertEqual(r["notes"], ["vault-edit: only one of these can open: demo#1, demo#2; top-ranked: demo#1"])

    def test_no_note_for_single_lock_user(self):
        self.add("A", locks=["vault-edit"])
        self.add("B")
        self.assertEqual(self.nxt()["notes"], [])


class TestBacklogAndOutput(NextBase):
    def table(self):
        self.write("outputs/p/b.md", "| id | item | status | route |\n|---|---|---|---|\n"
                   "| r1 | one | done | |\n| r2 | two | open | |\n| r3 | three | moved | x |\n")

    def test_backlog_progress_excludes_moved(self):
        self.table()
        self.add("A")
        self.upd(1, inputs=["outputs/p/b.md"], backlog=["outputs/p/b.md"])
        r = self.nxt()
        self.assertEqual(r["ready"][0]["backlog"], "1/2")
        self.assertIn("backlog 1/2 done", objective.render_next(r))

    def test_no_backlog_is_none(self):
        self.add("A")
        self.assertIsNone(self.nxt()["ready"][0]["backlog"])

    def test_cycle_exits_2_and_names_it(self):
        self.add("A")
        self.add("B")
        self.upd(1, depends_on=["demo#2"])
        self.upd(2, depends_on=["demo#1"])
        err = io.StringIO()
        se, sys.stderr = sys.stderr, err
        try:
            with self.assertRaises(SystemExit) as cm:
                self.run_cmd(objective.cmd_next, name="demo", json=False)
        finally:
            sys.stderr = se
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("demo#1", err.getvalue())
        self.assertIn("demo#2", err.getvalue())

    def test_json_envelope(self):
        self.add("A")
        self.run_cmd(objective.cmd_next, name="demo", json=True)
        s = self._out.getvalue()
        out = json.loads(s[s.index("{"):])
        self.assertEqual((out["schema"], out["kind"]), ("harness-records/1", "next"))
        for k in ("generated", "objective", "ready", "blocked", "human", "lock", "active", "notes"):
            self.assertIn(k, out)
        self.assertEqual(out["ready"][0]["id"], "demo#1")
        for k in ("id", "title", "unblocks", "order", "backlog"):
            self.assertIn(k, out["ready"][0])

    def test_intake_title_comes_from_body_heading(self):
        # Intake keeps its title in the body H1, not frontmatter; next must not fall back to the id.
        self.write("control-plane/intake/titled.md",
                   "---\nnote_type: intake\nkind: item\nstatus: triaged\ncaptured: 2026-11-01\nsource: t\n"
                   "objective: demo\nroute: candidate:assignment\n---\n\n# A Human Title\n\nbody\n")
        res = self.nxt()
        row = [x for x in res["ready"] if x["id"] == "intake:titled"][0]
        self.assertEqual(row["title"], "A Human Title")

    def test_unmigrated_objective_refused(self):
        import shutil
        shutil.rmtree(self.ms_dir())
        self.fails(objective.cmd_next, name="demo", json=False)


if __name__ == "__main__":
    unittest.main()
