#!/usr/bin/env python3
"""Phase 4 tests: generated views (4.1) and `intake.py check --inputs` (4.2).

Temp workspaces only (WORKSPACE_ROOT). Never renders against the live workspace.
"""

import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wsfix import BACKLOG3, WSBase  # noqa: E402
import harnesslib as H  # noqa: E402

OB, IN = "objective.py", "intake.py"
OBJ_IDX = "control-plane/objectives/obj/index.md"
INTAKE_IDX = "control-plane/intake/index.md"

BASE_INDEX = ("# obj\n\n## Objective\n\nwhy\n\n## Milestones\n\n- [ ] hand kept one\n- [x] hand kept two\n\n"
              "## Workstreams\n\n| Workstream | Status | Linked |\n|---|---|---|\n| *(none yet)* | | |\n\n"
              "## Key Decisions Log\n\n| Decision | Rationale | Date |\n|---|---|---|\n"
              "| chose x | because | 2026-11-09 |\n\n## Related Notes\n\n- x\n")


def region_of(text, view):
    m = re.search(rf"<!-- generated:{view} -->\n(.*?)<!-- /generated:{view} sha=([0-9a-f]{{8}}) -->", text, re.S)
    return (m.group(1), m.group(2)) if m else (None, None)


class ViewBase(WSBase):
    def setUp(self):
        super().setUp()
        self.write(OBJ_IDX, BASE_INDEX)

    def idx_bytes(self):
        return (self.root / OBJ_IDX).read_bytes()

    def idx(self):
        return self.idx_bytes().decode("utf-8")

    def adopt(self):
        self.ok(OB, "render", "obj", "--adopt")


class TestMilestoneView(ViewBase):
    def test_line_format_with_deps_gates_unit_and_backlog(self):
        self.backlog_file("outputs/prod/gaps.md", BACKLOG3.replace("| r1 | first | open", "| r1 | first | done"))
        self.gate("g1")
        self.milestone(1, status="done")
        self.milestone(2, depends_on=["obj#1", "gate:g1"], unit="workstream:w", backlog=["outputs/prod/gaps.md"])
        self.milestone(3, status="dropped")
        self.adopt()
        body, _ = region_of(self.idx(), "milestones")
        self.assertEqual(body.splitlines(), [
            "- [x] #1 m1",
            "- [ ] #2 m2 (deps: #1; gates: gate:g1; unit: workstream:w; backlog: 1/3)",
            "- [x] ~~#3 m3~~ (dropped)",
        ])

    def test_adopt_replaces_only_the_target_section(self):
        before = self.idx()
        self.adopt()
        after = self.idx()
        self.assertNotIn("hand kept", after)
        self.assertIn("## Milestones\n\n<!-- generated:milestones -->", after)
        # everything outside the Milestones section is byte-identical
        pre_b, rest_b = before.split("## Milestones\n")
        pre_a, rest_a = after.split("## Milestones\n")
        self.assertEqual(pre_a, pre_b)
        self.assertEqual(rest_a[rest_a.index("## Workstreams"):rest_a.index("## Program Intake")],
                         rest_b[rest_b.index("## Workstreams"):rest_b.index("## Related Notes")])
        self.assertTrue(rest_a.endswith("## Related Notes" + chr(10) * 2 + "- x" + chr(10)))

    def test_no_adopt_leaves_hand_kept_section_alone(self):
        before = self.idx_bytes()
        out = self.ok(OB, "render", "obj")
        self.assertIn("milestones: skipped", out)
        self.assertEqual(self.idx_bytes(), before)

    def test_idempotent_rerender_changes_no_bytes(self):
        self.adopt()
        first = self.idx_bytes()
        self.ok(OB, "render", "obj")
        self.assertEqual(self.idx_bytes(), first)
        self.ok(OB, "render", "obj", "--check")

    def test_record_edit_commands_rerender(self):
        self.adopt()
        self.ok(OB, "add-milestone", "obj", "--title", "third")
        self.assertIn("#3 third", self.idx())
        self.ok(OB, "check-milestone", "obj", "3")
        self.assertIn("- [x] #3 third", self.idx())
        self.ok(OB, "set-milestone", "obj", "3", "--unit", "workstream:w")
        self.assertIn("#3 third (unit: workstream:w)", self.idx())
        self.ok(OB, "drop-milestone", "obj", "2", "--reason", "nope")
        self.assertIn("~~#2 m2~~ (dropped)", self.idx())

    def test_hand_edit_refused_unless_force(self):
        self.adopt()
        p = self.root / OBJ_IDX
        p.write_bytes(self.idx_bytes().replace(b"- [ ] #1 m1", b"- [ ] #1 HAND EDITED"))
        before = self.idx_bytes()
        self.milestone(1, title="renamed")
        code, out, err = self.run_(OB, "render", "obj")
        self.assertEqual(code, 1, out + err)
        self.assertIn("hand-edited", err)
        self.assertEqual(self.idx_bytes(), before)
        self.ok(OB, "render", "obj", "--force")
        self.assertNotIn("HAND EDITED", self.idx())
        self.ok(OB, "render", "obj", "--check")

    def test_hand_edit_does_not_fail_a_record_edit_command(self):
        self.adopt()
        (self.root / OBJ_IDX).write_bytes(self.idx_bytes().replace(b"- [ ] #1 m1", b"- [ ] #1 HAND"))
        code, out, err = self.run_(OB, "add-milestone", "obj", "--title", "later")
        self.assertEqual(code, 0, out + err)
        self.assertIn("warning", err)

    def test_check_exits_1_on_stale_region(self):
        self.adopt()
        code, _, _ = self.run_(OB, "render", "obj", "--check")
        self.assertEqual(code, 0)
        self.milestone(1, status="done")
        code, out, err = self.run_(OB, "render", "obj", "--check")
        self.assertEqual(code, 1, out + err)
        self.assertIn("stale", out)
        self.assertNotIn("[x] #1", self.idx())     # --check never writes

    def test_crlf_file_stays_crlf(self):
        (self.root / OBJ_IDX).write_bytes(BASE_INDEX.replace("\n", "\r\n").encode())
        self.adopt()
        self.milestone(1, status="done")
        self.ok(OB, "render", "obj")
        b = self.idx_bytes()
        self.assertEqual(b.count(b"\n"), b.count(b"\r\n"), "a bare LF crept into a CRLF file")
        self.assertIn(b"- [x] #1 m1\r\n", b)

    def test_mixed_file_untouched_lines_keep_their_eol(self):
        lines = BASE_INDEX.split("\n")
        raw = "\n".join(lines[:8]) + "\n" + "\r\n".join(lines[8:])
        (self.root / OBJ_IDX).write_bytes(raw.encode())
        self.adopt()
        tail = b"## Related Notes\r\n\r\n- x\r\n"
        self.assertTrue(self.idx_bytes().endswith(tail))
        self.assertTrue(self.idx_bytes().startswith("\n".join(lines[:8]).encode() + b"\n"))

    def test_render_all_skips_unmigrated(self):
        self.write("control-plane/objectives/old/index.md", "# old\n\n## Milestones\n\n- [ ] x\n")
        self.adopt()
        out = self.ok(OB, "render", "--all", "--check")
        self.assertIn("obj: milestones: ok", out)
        self.assertNotIn("old:", out)

    def test_unmigrated_single_render_exits_1(self):
        self.write("control-plane/objectives/old/index.md", "# old\n")
        code, _, err = self.run_(OB, "render", "old")
        self.assertEqual(code, 1)
        self.assertIn("not migrated", err)

    def test_create_scaffold_matches_render(self):
        self.ok(OB, "create", "fresh")
        self.ok(OB, "render", "fresh", "--check")           # scaffolded region already carries its sha
        text = (self.root / "control-plane/objectives/fresh/index.md").read_text(encoding="utf-8")
        body, sha = region_of(text, "milestones")
        self.assertEqual(body, "*(none yet)*\n")
        self.assertEqual(sha, H._sha8(body))


class TestOtherViews(ViewBase):
    def test_gates_section_inserted_after_milestones_with_adopt(self):
        self.gate("g1")
        self.milestone(2, depends_on=["gate:g1"])
        self.adopt()
        text = self.idx()
        self.assertLess(text.index("## Milestones"), text.index("## Open Gates"))
        self.assertLess(text.index("## Open Gates"), text.index("## Workstreams"))
        body, _ = region_of(text, "gates")
        self.assertIn("gate:g1 (human, operator)", body)

    def test_carried_inputs_and_program_intake(self):
        self.write("outputs/prod/gaps.md", BACKLOG3)
        self.raw_intake("live", inputs=["outputs/prod/gaps.md"], route="workstream:w")
        self.raw_intake("done", status="consumed", inputs=["outputs/prod/gaps.md"])
        self.milestone(2, inputs=["outputs/prod/gaps.md"], unit="assignment:a")
        self.adopt()
        text = self.idx()
        ci, _ = region_of(text, "carried-inputs")
        self.assertIn("`outputs/prod/gaps.md` — intake:live (until: workstream:w); obj#2 (until: assignment:a)", ci)
        self.assertNotIn("intake:done", ci)
        pi, _ = region_of(text, "program-intake")
        self.assertIn("- intake:live · triaged · workstream:w", pi)
        self.assertIn("## Program Intake", text)

    def test_archived_consumed_recent_shown_old_hidden(self):
        for slug, when in (("recent", "2026-11-10"), ("old", "2026-06-01")):
            self.raw_intake(slug, status="consumed", consumed_by=["workstream:w"], consumed=when)
            self.ok(IN, "check")    # warm path; also proves live-terminal is only a warning
            src = self.cp / "intake" / f"{slug}.md"
            dst = self.cp / "intake" / "_archive" / f"{slug}.md"
            dst.parent.mkdir(exist_ok=True)
            src.replace(dst)
            os.utime(dst, (1, 1))      # R4: the window follows the `consumed:` date, never file mtime
        self.adopt()
        pi, _ = region_of(self.idx(), "program-intake")
        self.assertIn("intake:recent", pi)
        self.assertNotIn("intake:old", pi)


class TestIntakeQueueView(WSBase):
    def setUp(self):
        super().setUp()
        self.write(INTAKE_IDX, "# Intake\n\nconventions\n\n## Live Queue\n\n- hand kept\n")
        self.raw_intake("a", route="tools")
        self.raw_intake("b", route="workstream:w", depends_on=["intake:a"])

    def test_adopt_render_idempotent_and_check(self):
        self.ok(IN, "render", "--adopt")
        text = (self.root / INTAKE_IDX).read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Intake\n\nconventions\n\n## Live Queue\n"))
        body, _ = region_of(text, "intake-queue")
        self.assertIn("### obj", body)
        self.assertIn("- intake:a · triaged · tools · next: ready", body)
        self.assertIn("- intake:b · triaged · workstream:w · next: waits on intake:a", body)
        first = (self.root / INTAKE_IDX).read_bytes()
        self.ok(IN, "render")
        self.assertEqual((self.root / INTAKE_IDX).read_bytes(), first)
        self.ok(IN, "render", "--check")

    def test_check_stale_exits_1_and_hand_edit_refused(self):
        self.ok(IN, "render", "--adopt")
        self.raw_intake("c", route="tools")
        code, out, _ = self.run_(IN, "render", "--check")
        self.assertEqual(code, 1, out)
        p = self.root / INTAKE_IDX
        p.write_bytes(p.read_bytes().replace(b"intake:a", b"intake:HAND", 1))
        before = p.read_bytes()
        code, out, err = self.run_(IN, "render")
        self.assertEqual(code, 1, out + err)
        self.assertEqual(p.read_bytes(), before)
        self.ok(IN, "render", "--force")
        self.assertNotIn("HAND", p.read_text(encoding="utf-8"))

    def test_crlf_preserved(self):
        p = self.root / INTAKE_IDX
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        self.ok(IN, "render", "--adopt")
        b = p.read_bytes()
        self.assertEqual(b.count(b"\n"), b.count(b"\r\n"))


class TestInputsCheck(WSBase):
    def setUp(self):
        super().setUp()
        for d in ("live_a", "ref_tool", "ref_claude", "ref_vault", "keep_tool", "keep_perm", "idle", "norow",
                  "stale_pre", "unit_in", "consumed_only", "log_only"):
            self.write(f"outputs/{d}/f.md", "x")
        self.write("outputs/_archive/old_one/f.md", "x")
        self.write("outputs/index.md",
                   "# Outputs\n\n| Folder | Purpose | Keep |\n|---|---|---|\n"
                   + "".join(f"| `{d}` | x | {k} |\n" for d, k in (
                       ("live_a", ""), ("ref_tool", ""), ("ref_claude", ""), ("ref_vault", ""),
                       ("keep_tool", "tool"), ("keep_perm", "permanent"), ("idle", ""),
                       ("stale_pre", ""), ("unit_in", ""), ("consumed_only", ""), ("log_only", ""),
                       ("old_one", ""), ("phantom", ""))))
        self.raw_intake("src", status="active", inputs=["outputs/live_a/f.md"])
        self.raw_intake("gone", status="consumed", inputs=["outputs/consumed_only/f.md"])
        self.write("control-plane/workstreams/w/index.md",
                   "---\nworkstream: w\nstatus: active\ninputs: [outputs/unit_in]\n---\n\n# w\n")
        self.write("tools/helper.py", 'p = join(HERE, "../../outputs/ref_tool")\nq = "outputs\\\\ref_tool\\\\x"\n')
        self.write("tools/tests/fixture.py", "outputs/idle/f.md\n")
        self.write(".claude/skills/s.md", "see `outputs/ref_claude/f.md` and `outputs/old_one/f.md`\n")
        self.write("knowledge/vault/n.md", "see ../../outputs/ref_vault/f.md and outputs/ghost/x\n")
        self.write("control-plane/rules.md", "legacy `control-plane/outputs/stale_pre/f.md`\n")
        self.write("control-plane/workstreams/_log/2026-01-01-w.md", "outputs/log_only/f.md\n")

    def check(self, no_rg=False, args=("check", "--inputs", "--json")):
        env_old = os.environ.get("HARNESS_NO_RG")
        if no_rg:
            os.environ["HARNESS_NO_RG"] = "1"
        try:
            code, out, err = self.run_(IN, *args)
        finally:
            if env_old is None:
                os.environ.pop("HARNESS_NO_RG", None)
            else:
                os.environ["HARNESS_NO_RG"] = env_old
        return code, json.loads(out), err

    def live(self, env):
        return {x["folder"]: x["reasons"] for x in env["live"]}

    def defects(self, env):
        return {(d["code"], d["folder"]) for d in env["defects"]}

    def test_reason_a_record_and_unit_inputs(self):
        code, env, _ = self.check()
        live = self.live(env)
        self.assertEqual(env["schema"], "harness-records/1")
        self.assertEqual(env["kind"], "inputs")
        self.assertEqual(live["outputs/live_a"], ["intake:src"])
        self.assertIn("workstream:w", live["outputs/unit_in"])
        self.assertNotIn("outputs/consumed_only", live)       # terminal record: not live

    def test_reason_b_references_in_tools_claude_vault(self):
        _, env, _ = self.check()
        live = self.live(env)
        self.assertEqual(live["outputs/ref_tool"], ["ref:tools/helper.py"])
        self.assertEqual(live["outputs/ref_claude"], ["ref:.claude/skills/s.md"])
        self.assertEqual(live["outputs/ref_vault"], ["ref:knowledge/vault/n.md"])
        self.assertNotIn("outputs/idle", live)                # tools/tests and idle: not live
        self.assertNotIn("outputs/log_only", live)            # historical _log: ignored

    def test_reason_c_keep_column(self):
        _, env, _ = self.check()
        live = self.live(env)
        self.assertEqual(live["outputs/keep_tool"], ["keep:tool"])
        self.assertEqual(live["outputs/keep_perm"], ["keep:permanent"])

    def test_missing_keep_column_means_no_keeps(self):
        self.write("outputs/index.md", "# Outputs\n\n| Folder | Purpose |\n|---|---|\n| keep_tool | tool |\n")
        _, env, _ = self.check()
        self.assertNotIn("outputs/keep_tool", self.live(env))

    def test_defect_classes(self):
        code, env, _ = self.check()
        self.assertEqual(code, 1)
        d = self.defects(env)
        self.assertIn(("stale-prefix", "stale_pre"), d)
        self.assertIn(("archived-live", "old_one"), d)
        self.assertIn(("absent", "ghost"), d)
        self.assertIn(("missing-row", "norow"), d)
        self.assertIn(("extra-row", "phantom"), d)
        self.assertEqual(self.live(env)["outputs/stale_pre"], ["ref:control-plane/rules.md"])

    def test_explicit_archive_link_is_not_a_defect(self):
        # A pre-move live path to an archived folder is a defect; an explicit outputs/_archive/<f> link is history.
        self.write(".claude/skills/s.md", "see `outputs/ref_claude/f.md` and `outputs/_archive/old_one/f.md`\n")
        _, env, _ = self.check()
        self.assertNotIn(("archived-live", "old_one"), self.defects(env))
        self.assertNotIn("outputs/old_one", self.live(env))

    def test_unit_planning_prose_is_not_a_referrer(self):
        # Inside a unit folder only index.md counts; research/blueprint/_working quote paths without consuming them.
        for rel in ("control-plane/workstreams/w/research.md", "control-plane/workstreams/w/blueprint.md",
                    "control-plane/assignments/a/notes.md", "control-plane/cadences/c/design.md"):
            self.write(rel, "example `outputs/idle/f.md`, stale `control-plane/outputs/stale_pre/x`, absent `outputs/nope/x`\n")
        self.write("control-plane/assignments/a/index.md", "---\nassignment: a\nstatus: active\n---\n\nreads `outputs/ref_tool/x`\n")
        _, env, _ = self.check()
        live, d = self.live(env), self.defects(env)
        self.assertNotIn("outputs/idle", live)
        self.assertNotIn(("absent", "nope"), d)
        self.assertEqual(live["outputs/stale_pre"], ["ref:control-plane/rules.md"])   # only the non-unit referrer
        self.assertIn("ref:control-plane/assignments/a/index.md", live["outputs/ref_tool"])   # unit index.md still counts

    def test_clean_tree_exits_0(self):
        for rel in ("control-plane/rules.md", "knowledge/vault/n.md", ".claude/skills/s.md"):
            (self.root / rel).unlink()
        self.write("outputs/index.md", "# Outputs\n\n| Folder | Keep |\n|---|---|\n"
                   + "".join(f"| {d} | |\n" for d in sorted(p.name for p in (self.root / "outputs").iterdir()
                                                            if p.is_dir() and p.name != "_archive"))
                   + "| old_one | |\n")
        code, env, err = self.check()
        self.assertEqual(code, 0, err + json.dumps(env))

    def test_os_walk_fallback_matches_ripgrep(self):
        _, with_rg, _ = self.check()
        _, without, _ = self.check(no_rg=True)
        self.assertEqual(with_rg["live"], without["live"])
        self.assertEqual(self.defects(with_rg), self.defects(without))
        self.assertEqual(self.live(without)["outputs/ref_tool"], ["ref:tools/helper.py"])

    def test_walk_path_used_directly(self):
        import intake
        hits = intake.scan_refs(self.root, use_rg=False)
        self.assertTrue(any(p == "tools/helper.py" and "ref_tool" in t for p, t in hits))
        self.assertFalse(any(p.startswith("tools/tests/") for p, _ in hits))

    def test_text_output(self):
        code, out, err = self.run_(IN, "check", "--inputs")
        self.assertEqual(code, 1)
        self.assertIn("live  outputs/live_a: intake:src", out)
        self.assertIn("DEFECT absent ghost", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
