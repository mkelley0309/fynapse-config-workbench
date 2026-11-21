#!/usr/bin/env python3
"""cli-record-field-coverage: every record field settable through a CLI, list-flag parsing, set-unit.

Temp workspaces only (WORKSPACE_ROOT); every command runs as a subprocess through the real argparse CLI.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wsfix import BACKLOG3, WSBase  # noqa: E402

import harnesslib as H  # noqa: E402
import intake  # noqa: E402

OB, IN, WS, AS, CA = "objective.py", "intake.py", "workstream.py", "assignment.py", "cadence.py"
MSDIR = "control-plane/objectives/obj/milestones"


class FieldBase(WSBase):
    def ms_file(self, n):
        return next((self.root / MSDIR).glob(f"{n:02d}-*.md"))

    def msfm(self, n):
        return H.fm_read(self.ms_file(n))[0]


class TestAddMilestone(FieldBase):
    def test_explicit_id_zero_and_all_fields(self):
        self.write("outputs/p/in.md", "x")
        self.write("outputs/p/bl.md", BACKLOG3)
        self.ok(OB, "add-milestone", "obj", "--title", "Zero", "--id", "0", "--unit", "workstream:w",
                "--inputs", "outputs/p/in.md,outputs/p/bl.md", "--backlog", "outputs/p/bl.md",
                "--legacy", "- [x] original: line", "--substep", "one, with comma", "--substep", "two")
        fm = self.msfm(0)
        self.assertEqual(fm["id"], "obj#0")
        self.assertEqual(fm["order"], "0")
        self.assertEqual(fm["unit"], "workstream:w")
        self.assertEqual(fm["inputs"], ["outputs/p/in.md", "outputs/p/bl.md"])
        self.assertEqual(fm["backlog"], ["outputs/p/bl.md"])
        self.assertEqual(fm["legacy"], "- [x] original: line")
        body = self.ms_file(0).read_text(encoding="utf-8")
        self.assertIn("- [ ] one, with comma\n- [ ] two\n", body)

    def test_duplicate_id_refused(self):
        self.refused(OB, "add-milestone", "obj", "--title", "Dup", "--id", "1", text="already exists")

    def test_bad_paths_and_unit_refused(self):
        self.refused(OB, "add-milestone", "obj", "--title", "X", "--inputs", "no/such.md", text="does not exist")
        self.write("outputs/p/in.md", "x")
        self.refused(OB, "add-milestone", "obj", "--title", "X", "--inputs", "outputs/p/in.md",
                     "--backlog", "outputs/p/other.md", text="does not exist")
        self.refused(OB, "add-milestone", "obj", "--title", "X", "--unit", "bogus", text="bad --unit")

    def test_default_numbering_unchanged(self):
        self.ok(OB, "add-milestone", "obj", "--title", "Next")
        self.assertEqual(self.msfm(3)["id"], "obj#3")


class TestMilestoneSetters(FieldBase):
    def test_set_legacy_and_done(self):
        self.ok(OB, "set-milestone", "obj", "1", "--legacy", "- [ ] old line", "--done", "2026-10-01")
        fm = self.msfm(1)
        self.assertEqual(fm["legacy"], "- [ ] old line")
        self.assertEqual(fm["done"], "2026-10-01")
        self.assertEqual(fm["status"], "open")

    def test_set_done_bad_date_refused(self):
        self.refused(OB, "set-milestone", "obj", "1", "--done", "2026-13-40", text="--done")

    def test_check_milestone_date(self):
        self.ok(OB, "check-milestone", "obj", "1", "--date", "2026-09-30")
        fm = self.msfm(1)
        self.assertEqual((fm["status"], fm["done"]), ("done", "2026-09-30"))

    def test_check_milestone_default_today_and_bad_date(self):
        self.refused(OB, "check-milestone", "obj", "2", "--date", "yesterday", text="--date")
        self.ok(OB, "check-milestone", "obj", "2")
        self.assertEqual(self.msfm(2)["done"], H.today())


class TestIntakeSet(FieldBase):
    def setUp(self):
        super().setUp()
        self.raw_intake("a")
        self.raw_intake("b")
        self.write("outputs/p/in.md", "x")
        self.write("outputs/p/bl.md", BACKLOG3)
        self.gate("g")

    def test_sets_every_field(self):
        self.ok(IN, "set", "a", "--kind", "handover", "--captured", "2026-10-02", "--source", "new src",
                "--objective", "other", "--route", "workstream:foo", "--depends-on", "intake:b,gate:g",
                "--related", "intake:b", "--locks", "vault-edit", "--inputs", "outputs/p/in.md,outputs/p/bl.md",
                "--backlog", "outputs/p/bl.md", "--consumed-by", "workstream:w", "--keep-until", "gate:g",
                "--dropped-reason", "why")
        fm = self.ifm("a")
        self.assertEqual((fm["kind"], fm["captured"], fm["source"], fm["objective"], fm["route"]),
                         ("handover", "2026-10-02", "new src", "other", "workstream:foo"))
        self.assertEqual(fm["depends_on"], ["intake:b", "gate:g"])
        self.assertEqual(fm["locks"], ["vault-edit"])
        self.assertEqual(fm["backlog"], ["outputs/p/bl.md"])
        self.assertEqual(fm["consumed_by"], ["workstream:w"])
        self.assertEqual((fm["keep_until"], fm["dropped_reason"], fm["status"]), ("gate:g", "why", "triaged"))

    def test_status_is_not_settable(self):
        code, out, err = self.run_(IN, "set", "a", "--status", "consumed")
        self.assertEqual(code, 2)
        self.assertEqual(self.ifm("a")["status"], "triaged")

    def test_refusals_leave_bytes_unchanged(self):
        self.ok(IN, "set", "b", "--depends-on", "intake:a")
        for args, text in ((("--kind", "bogus"), "bad kind"),
                           (("--captured", "2026-02-31"), "--captured"),
                           (("--route", "nonsense"), "bad route"),
                           (("--depends-on", "intake:ghost"), "unresolved"),
                           (("--depends-on", "intake:b"), "cycle"),
                           (("--locks", "nope"), "unknown lock"),
                           (("--consumed-by", "intake:b"), "unit ids"),
                           (("--backlog", "outputs/p/bl.md"), "subset"),
                           (("--inputs", "no/such.md"), "does not exist"),
                           (("--source", " "), "cannot be empty")):
            self.refused(IN, "set", "a", *args, text=text)
        self.refused(IN, "set", "a", text="nothing to set")
        self.refused(IN, "set", "ghost", "--source", "x", text="no live intake")

    def test_clear_with_empty_values(self):
        self.ok(IN, "set", "a", "--keep-until", "gate:g", "--related", "intake:b")
        self.ok(IN, "set", "a", "--keep-until", "", "--related", "")
        fm = self.ifm("a")
        self.assertEqual(fm["keep_until"], "")
        self.assertEqual(fm["related"], [])

    def test_gate_set(self):
        self.ok(IN, "gate", "set", "g", "--title", "New", "--type", "decision", "--who", "me",
                "--criteria", "c2", "--objective", "other", "--evidence", "sha1")
        fm = H.fm_read(self.cp / "gates" / "g.md")[0]
        self.assertEqual((fm["title"], fm["gate_type"], fm["who"], fm["criteria"], fm["objective"], fm["evidence"]),
                         ("New", "decision", "me", "c2", "other", "sha1"))
        self.assertEqual(fm["status"], "open")
        self.refused(IN, "gate", "set", "g", "--type", "bogus", text="bad gate type")
        self.refused(IN, "gate", "set", "g", text="nothing to set")
        self.refused(IN, "gate", "set", "ghost", "--title", "x", text="no gate")


class TestListFlagParsing(FieldBase):
    """Regression: a list flag given a plain string iterated characters ("bad slug: -")."""

    def test_listflag_accepts_plain_string(self):
        self.assertEqual(H.listflag("a,b"), ["a", "b"])
        self.assertEqual(H.listflag(["a", "b,c"]), ["a", "b", "c"])
        self.assertEqual(H.listflag(None), [])
        self.assertEqual(H.listflag([""]), [])

    def test_split_into_comma_separated_through_cli(self):
        self.raw_intake("big")
        self.ok(IN, "split", "big", "--into", "a,b")
        self.assertTrue((self.cp / "intake" / "big-a.md").exists())
        self.assertTrue((self.cp / "intake" / "big-b.md").exists())
        self.assertTrue((self.cp / "intake" / "_archive" / "big.md").exists())

    def test_split_into_repeated_through_cli(self):
        self.raw_intake("big")
        self.ok(IN, "split", "big", "--into", "a", "--into", "b,c", "--route", "a=tools", "--route", "b=none")
        for n in "abc":
            self.assertTrue((self.cp / "intake" / f"big-{n}.md").exists())
        self.assertEqual(self.ifm("big-a")["route"], "tools")

    def test_every_list_flag_takes_both_forms(self):
        """intake triage, objective milestone flags and the unit tools accept repeated and comma forms."""
        self.raw_intake("o1")
        self.raw_intake("o2")
        self.raw_intake("t", status="captured")
        self.ok(IN, "triage", "t", "--objective", "obj", "--route", "tools", "--depends-on", "intake:o1,intake:o2")
        self.assertEqual(self.ifm("t")["depends_on"], ["intake:o1", "intake:o2"])
        self.ok(IN, "triage", "t", "--objective", "obj", "--route", "tools", "--depends-on", "intake:o1",
                "--depends-on", "intake:o2")
        self.assertEqual(self.ifm("t")["depends_on"], ["intake:o1", "intake:o2"])
        self.ok(OB, "set-milestone", "obj", "1", "--depends-on", "obj#2,intake:o1")
        self.assertEqual(self.msfm(1)["depends_on"], ["obj#2", "intake:o1"])
        self.ok(OB, "set-milestone", "obj", "1", "--depends-on", "obj#2", "--depends-on", "intake:o1")
        self.assertEqual(self.msfm(1)["depends_on"], ["obj#2", "intake:o1"])
        for script in (WS, AS, CA):
            self.ok(script, "create", "u1", "--locks", "vault-edit,vault-edit")
            self.assertEqual(self.ufm(script, "u1")["locks"], ["vault-edit", "vault-edit"])
            self.cp_rm(script, "u1")

    def cp_rm(self, script, name):
        import shutil
        shutil.rmtree(self.unit_index(script, name).parent)


class TestSetUnit(FieldBase):
    def test_bind_accepted_when_milestone_already_names_this_unit(self):
        # add-milestone --unit followed by set-unit --milestone is idempotent; another unit is still refused.
        self.ok(WS, "create", "u1")
        self.milestone(4, status="open", unit="workstream:u1")
        self.ok(WS, "set-unit", "u1", "--milestone", "obj#4")
        self.assertEqual(self.ufm(WS, "u1")["milestone"], "obj#4")
        self.assertEqual(self.mfm(4)["status"], "active")
        self.milestone(5, status="open", unit="workstream:other")
        self.refused(WS, "set-unit", "u1", "--intake-source", "intake:nope", "--milestone", "obj#5", text="already")

    def test_binds_everything_on_each_unit_tool(self):
        for n, script in enumerate((WS, AS, CA), start=1):
            self.backlog_file()
            self.raw_intake(f"src{n}", inputs=["outputs/prod/gaps.md"], backlog=["outputs/prod/gaps.md"])
            self.ok(script, "create", f"u{n}")
            self.assertEqual(self.ufm(script, f"u{n}")["milestone"], "")
            kind = script.split(".")[0]
            args = [script, "set-unit", f"u{n}", "--intake-source", f"intake:src{n}", "--locks", "vault-edit",
                    "--milestone", f"obj#{n}" if n < 3 else "obj#1"]
            if n == 3:
                args = args[:-2] + ["--inputs", "outputs/prod/gaps.md"]
            self.ok(*args)
            fm = self.ufm(script, f"u{n}")
            self.assertEqual(fm["intake_source"], [f"intake:src{n}"])
            self.assertEqual(fm["locks"], ["vault-edit"])
            self.assertEqual(fm["inputs"], ["outputs/prod/gaps.md"])
            self.assertEqual(fm["backlog"], ["outputs/prod/gaps.md"])
            self.assertEqual(self.ifm(f"src{n}")["status"], "active")
            if n < 3:
                self.assertEqual(fm["milestone"], f"obj#{n}")
                self.assertEqual(self.mfm(n)["status"], "active")
                self.assertEqual(self.mfm(n)["unit"], f"{kind}:u{n}")

    def test_set_unit_is_additive_and_idempotent(self):
        self.write("outputs/p/a.md", "x")
        self.write("outputs/p/b.md", "x")
        self.ok(AS, "create", "a1", "--locks", "vault-edit")
        self.ok(AS, "set-unit", "a1", "--inputs", "outputs/p/a.md")
        self.ok(AS, "set-unit", "a1", "--inputs", "outputs/p/a.md,outputs/p/b.md", "--backlog", "outputs/p/b.md",
                "--locks", "vault-edit")
        fm = self.ufm(AS, "a1")
        self.assertEqual(fm["inputs"], ["outputs/p/a.md", "outputs/p/b.md"])
        self.assertEqual(fm["backlog"], ["outputs/p/b.md"])
        self.assertEqual(fm["locks"], ["vault-edit"])

    def test_refusals_are_atomic(self):
        self.raw_intake("src")
        self.raw_intake("gone", status="consumed")
        self.milestone(3, status="active", unit="assignment:other")
        for script in (WS, AS, CA):
            self.ok(script, "create", "u1")
            before = self.snap()
            for args, text in ((("--intake-source", "intake:ghost"), "intake_source"),
                               (("--intake-source", "intake:src", "--locks", "nope"), "unknown lock"),
                               (("--intake-source", "intake:src", "--milestone", "obj#3"), "already has unit"),
                               (("--intake-source", "intake:gone"), "consumed"),
                               (("--milestone", "obj#9"), "milestone"),
                               (("--inputs", "no/such.md"), "does not exist"),
                               (("--backlog", "outputs/prod/gaps.md"), "does not exist"),
                               ((), "nothing to set")):
                code, out, err = self.run_(script, "set-unit", "u1", *args)
                self.assertEqual(code, 1, out + err)
                self.assertIn(text, err)
                self.assertEqual(self.snap(), before)
            self.refused(script, "set-unit", "ghost", "--locks", "vault-edit")
            import shutil
            shutil.rmtree(self.unit_index(script, "u1").parent)
            self.snap()

    def test_second_milestone_refused(self):
        self.ok(WS, "create", "w1", "--milestone", "obj#1")
        self.refused(WS, "set-unit", "w1", "--milestone", "obj#2", text="already delivers")
        self.ok(WS, "set-unit", "w1", "--milestone", "obj#1")      # same milestone: no-op, no error

    def test_closed_unit_refused(self):
        self.ok(CA, "create", "c1")
        self.residuals(CA, "c1", "- none")
        self.ok(CA, "retire", "c1", "--reason", "done")
        self.refused(CA, "set-unit", "c1", "--locks", "vault-edit")


# R3 keys -> the command and flag that sets each one. `status` and `resolved` are lifecycle-only.
LIFECYCLE_ONLY = {"intake": {"status", "consumed", "dropped"}, "milestone": {"status"}, "gate": {"status", "resolved"}}
CONSTANT = {"note_type"}
SETTERS = {
    "intake": {
        "kind": (IN, ["set"], "--kind"), "captured": (IN, ["set"], "--captured"),
        "source": (IN, ["set"], "--source"), "objective": (IN, ["set"], "--objective"),
        "route": (IN, ["set"], "--route"), "depends_on": (IN, ["set"], "--depends-on"),
        "related": (IN, ["set"], "--related"), "locks": (IN, ["set"], "--locks"),
        "inputs": (IN, ["set"], "--inputs"), "backlog": (IN, ["set"], "--backlog"),
        "consumed_by": (IN, ["set"], "--consumed-by"), "keep_until": (IN, ["set"], "--keep-until"),
        "dropped_reason": (IN, ["set"], "--dropped-reason"),
    },
    "milestone": {
        "id": (OB, ["add-milestone"], "--id"), "title": (OB, ["set-milestone"], "--title"),
        "order": (OB, ["set-milestone"], "--order"), "conditional": (OB, ["set-milestone"], "--conditional"),
        "depends_on": (OB, ["set-milestone"], "--depends-on"), "related": (OB, ["set-milestone"], "--related"),
        "locks": (OB, ["set-milestone"], "--locks"), "fed_by": (OB, ["set-milestone"], "--fed-by"),
        "inputs": (OB, ["set-milestone"], "--inputs"), "backlog": (OB, ["set-milestone"], "--backlog"),
        "unit": (OB, ["set-milestone"], "--unit"), "ref": (OB, ["set-milestone"], "--ref"),
        "done": (OB, ["set-milestone"], "--done"), "legacy": (OB, ["set-milestone"], "--legacy"),
    },
    "gate": {
        "title": (IN, ["gate", "set"], "--title"), "gate_type": (IN, ["gate", "set"], "--type"),
        "who": (IN, ["gate", "set"], "--who"), "criteria": (IN, ["gate", "set"], "--criteria"),
        "evidence": (IN, ["gate", "set"], "--evidence"), "objective": (IN, ["gate", "set"], "--objective"),
    },
}
# Unit keys (workstream, assignment, cadence index.md): set-unit on each tool.
UNIT_SETTERS = {"intake_source": "--intake-source", "milestone": "--milestone", "locks": "--locks",
                "inputs": "--inputs", "backlog": "--backlog"}
# Extra milestone flags that must exist on add-milestone (seed fields at creation).
ADD_MILESTONE_FLAGS = ("--id", "--unit", "--inputs", "--backlog", "--legacy", "--substep", "--title", "--ref",
                       "--order", "--conditional", "--depends-on", "--related", "--locks", "--fed-by")


class TestSchemaCoverage(FieldBase):
    def help_of(self, script, sub):
        code, out, err = self.run_(script, *sub, "--help")
        self.assertEqual(code, 0, err)
        return out

    def test_every_schema_key_is_mapped(self):
        """The mapping covers exactly the keys intake.py declares, minus lifecycle-only and constants."""
        for kind, keys in intake.KEYS.items():
            want = keys - LIFECYCLE_ONLY[kind] - CONSTANT
            self.assertEqual(want, set(SETTERS[kind]), f"{kind}: schema keys and setter map differ")

    def test_every_schema_key_has_a_cli_flag(self):
        for kind, mapping in SETTERS.items():
            for key, (script, sub, flag) in mapping.items():
                self.assertIn(flag, self.help_of(script, sub), f"{kind}.{key}: {script} {' '.join(sub)} lacks {flag}")

    def test_unit_keys_have_set_unit_flags(self):
        for script in (WS, AS, CA):
            text = self.help_of(script, ["set-unit"])
            for key, flag in UNIT_SETTERS.items():
                self.assertIn(flag, text, f"unit key {key}: {script} set-unit lacks {flag}")

    def test_add_milestone_seed_flags(self):
        text = self.help_of(OB, ["add-milestone"])
        for flag in ADD_MILESTONE_FLAGS:
            self.assertIn(flag, text)
        self.assertIn("--date", self.help_of(OB, ["check-milestone"]))

    def test_status_has_no_setter(self):
        for sub in (["set"], ["gate", "set"]):
            self.assertNotIn("--status", self.help_of(IN, sub))
        self.assertNotIn("--status", self.help_of(OB, ["set-milestone"]))
        self.assertNotIn("--resolved", self.help_of(IN, ["gate", "set"]))


if __name__ == "__main__":
    unittest.main()
