#!/usr/bin/env python3
"""Phase 3 tests: create flags (3.1) and R7 close checks (3.2) for workstream, assignment, cadence.

Temp workspaces only (WORKSPACE_ROOT). Every refusal test also asserts the workspace is
byte-identical afterwards (atomicity).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wsfix import BACKLOG3, WSBase  # noqa: E402

WS, AS, CA = "workstream.py", "assignment.py", "cadence.py"
UNITS = (WS, AS, CA)


class TestCreateFlags(WSBase):
    def test_workstream_create_flags_write_r3_keys(self):
        self.backlog_file()
        self.raw_intake("src", inputs=["outputs/prod/gaps.md"], backlog=["outputs/prod/gaps.md"])
        self.ok(WS, "create", "w1", "--intake-source", "intake:src", "--milestone", "obj#1",
                "--locks", "vault-edit")
        fm = self.ufm(WS, "w1")
        self.assertEqual(fm["intake_source"], ["intake:src"])
        self.assertEqual(fm["milestone"], "obj#1")
        self.assertEqual(fm["locks"], ["vault-edit"])
        self.assertEqual(fm["inputs"], ["outputs/prod/gaps.md"])
        self.assertEqual(fm["backlog"], ["outputs/prod/gaps.md"])
        self.assertEqual(self.ifm("src")["status"], "active")
        self.assertEqual(self.mfm(1)["status"], "active")
        self.assertEqual(self.mfm(1)["unit"], "workstream:w1")

    def test_assignment_create_flags_write_r3_keys(self):
        self.backlog_file()
        self.raw_intake("src", inputs=["outputs/prod/gaps.md"], backlog=["outputs/prod/gaps.md"])
        self.ok(AS, "create", "a1", "--intake-source", "intake:src", "--milestone", "obj#2",
                "--locks", "vault-edit")
        fm = self.ufm(AS, "a1")
        self.assertEqual(fm["intake_source"], ["intake:src"])
        self.assertEqual(fm["milestone"], "obj#2")
        self.assertEqual(fm["inputs"], ["outputs/prod/gaps.md"])
        self.assertEqual(fm["backlog"], ["outputs/prod/gaps.md"])
        self.assertEqual(self.ifm("src")["status"], "active")
        self.assertEqual(self.mfm(2)["unit"], "assignment:a1")

    def test_repeatable_intake_source_unions_inputs(self):
        self.write("outputs/p/a.md", "x")
        self.write("outputs/p/b.md", "x")
        self.raw_intake("s1", inputs=["outputs/p/a.md"])
        self.raw_intake("s2", inputs=["outputs/p/a.md", "outputs/p/b.md"])
        self.ok(AS, "create", "a1", "--intake-source", "intake:s1", "--intake-source", "intake:s2")
        self.assertEqual(self.ufm(AS, "a1")["inputs"], ["outputs/p/a.md", "outputs/p/b.md"])

    def test_new_index_has_residuals_section_with_allowed_forms(self):
        for script in UNITS:
            self.ok(script, "create", "u1")
            text = self.unit_index(script, "u1").read_text(encoding="utf-8")
            self.assertIn("## Residuals", text)
            self.assertIn("- handover: <target>", text)
            self.assertIn("- dropped: <text> (decision <obj> YYYY-MM-DD)", text)

    def test_create_without_flags_writes_empty_keys(self):
        self.ok(WS, "create", "plain")
        fm = self.ufm(WS, "plain")
        self.assertEqual(fm["intake_source"], [])
        self.assertEqual(fm["locks"], [])
        self.assertEqual(fm["inputs"], [])
        self.assertEqual(fm["backlog"], [])

    def test_unresolved_intake_source_refused_atomically(self):
        for script in (WS, AS):
            self.refused(script, "create", "w1", "--intake-source", "intake:ghost", text="intake_source")

    def test_terminal_or_archived_intake_source_refused(self):
        self.raw_intake("done", status="consumed")
        self.refused(AS, "create", "a1", "--intake-source", "intake:done", text="consumed")

    def test_unresolved_milestone_refused_atomically(self):
        for script in (WS, AS):
            self.refused(script, "create", "w1", "--milestone", "obj#9", text="milestone")

    def test_milestone_already_owned_refused(self):
        self.milestone(1, status="active", unit="assignment:other")
        self.refused(WS, "create", "w1", "--milestone", "obj#1", text="already has unit")

    def test_unknown_lock_refused_atomically(self):
        for script in UNITS:
            self.refused(script, "create", "u1", "--locks", "nope", text="unknown lock")

    def test_cadence_create_locks(self):
        self.ok(CA, "create", "c1", "--locks", "vault-edit")
        self.assertEqual(self.ufm(CA, "c1")["locks"], ["vault-edit"])

    def test_cadence_run_spawned_must_exist(self):
        self.ok(CA, "create", "c1")
        self.refused(CA, "run", "c1", "--note", "n", "--spawned", "assignments/ghost", text="does not exist")
        self.ok(AS, "create", "kid")
        self.ok(CA, "run", "c1", "--note", "n", "--spawned", "assignments/kid")

    def test_cadence_run_spawned_bad_form_refused(self):
        self.ok(CA, "create", "c1")
        self.refused(CA, "run", "c1", "--note", "n", "--spawned", "kid", text="--spawned must be")

    def test_link_accepts_both_child_headings(self):
        for heading, head_row in (("Child Tasks", "| Task | Linked |"),
                                  ("Child Assignments", "| Assignment | Spawned |")):
            name = heading.split()[1].lower()
            self.ok(WS, "create", name)
            p = self.unit_index(WS, name)
            t = p.read_text(encoding="utf-8")
            t = t.replace("## Child Tasks\n\n| Task | Linked |", f"## {heading}\n\n{head_row}")
            p.write_text(t, encoding="utf-8", newline="\n")
            self.ok(WS, "link", name, "kid-a")
            self.assertIn("| kid-a |", p.read_text(encoding="utf-8"))
            self.assertIn(f"## {heading}", p.read_text(encoding="utf-8"))


class TestCloseRefusals(WSBase):
    """R7 steps 1-2: each refusal leaves every file byte-identical."""

    def make(self, script, name="u1", *flags):
        self.ok(script, "create", name, *flags)

    def test_residuals_section_missing_refused(self):
        for script in UNITS:
            self.make(script)
            p = self.unit_index(script, "u1")
            t = p.read_text(encoding="utf-8")
            start = t.index("## Residuals")
            p.write_text(t[:start] + t[t.index("## Cross-links"):], encoding="utf-8", newline="\n")
            self.refused(script, *self.close_args(script, "u1"), text="no '## Residuals' section")

    def test_residuals_empty_refused(self):
        for script in UNITS:
            self.make(script)
            self.refused(script, *self.close_args(script, "u1"), text="'## Residuals' is empty")

    def test_residuals_comment_alone_counts_as_empty(self):
        self.make(AS)
        text = self.unit_index(AS, "u1").read_text(encoding="utf-8")
        self.assertIn("- none\n", text)          # the allowed-forms comment lists it
        self.refused(AS, "complete", "u1", text="is empty")

    def test_unresolved_ids_refused(self):
        for si, script in enumerate(UNITS):
            for bi, bullet in enumerate(("- intake:ghost, note", "- milestone:obj#9, note",
                                         "- spawned:assignment:ghost")):
                name = f"u{si}{bi}"
                self.make(script, name)
                self.residuals(script, name, bullet)
                self.refused(script, *self.close_args(script, name), text="unresolved id")

    def test_unrecognised_form_refused(self):
        self.make(AS)
        self.residuals(AS, "u1", "- whatever")
        self.refused(AS, "complete", "u1", text="unrecognised residual form")

    def test_dropped_needs_existing_decision_row(self):
        self.make(AS)
        self.residuals(AS, "u1", "- dropped: scope cut (decision obj 2026-01-01)")
        self.refused(AS, "complete", "u1", text="no decision row obj 2026-01-01")
        self.residuals(AS, "u1", "- dropped: no cite")
        self.refused(AS, "complete", "u1", text="lacks '(decision")

    def test_dropped_with_existing_decision_accepted(self):
        self.make(AS)
        self.residuals(AS, "u1", "- dropped: scope cut (decision obj 2026-11-09)")
        self.ok(AS, "complete", "u1")

    def test_handover_missing_input_path_refused(self):
        self.make(WS)
        self.residuals(WS, "u1", "- handover: assignment:recv — do it; inputs: outputs/nope.md")
        self.refused(WS, "complete", "u1", text="does not exist")

    def test_handover_unresolved_milestone_refused(self):
        self.make(WS)
        self.residuals(WS, "u1", "- handover: milestone:obj#9 — do it")
        self.refused(WS, "complete", "u1", text="unresolved id")

    def test_open_backlog_rows_on_unit_refused(self):
        self.backlog_file()
        self.raw_intake("src", inputs=["outputs/prod/gaps.md"], backlog=["outputs/prod/gaps.md"])
        for script in (WS, AS):
            name = "u" + script[0]
            self.make(script, name, "--intake-source", "intake:src")
            self.residuals(script, name, "- none")
            self.refused(script, *self.close_args(script, name), text="open backlog row r1")

    def test_open_backlog_rows_via_intake_source_only(self):
        # The unit frontmatter carries no backlog, but its source record does.
        self.backlog_file()
        self.raw_intake("src", inputs=["outputs/prod/gaps.md"], backlog=["outputs/prod/gaps.md"])
        self.make(AS, "u1", "--intake-source", "intake:src")
        from harnesslib import fm_write
        fm_write(self.unit_index(AS, "u1"), {"backlog": [], "inputs": []})
        self.residuals(AS, "u1", "- none")
        self.refused(AS, "complete", "u1", text="open backlog row r1")

    def test_cadence_open_backlog_refused(self):
        self.backlog_file()
        self.make(CA, "c1")
        from harnesslib import fm_write
        fm_write(self.unit_index(CA, "c1"), {"inputs": ["outputs/prod/gaps.md"], "backlog": ["outputs/prod/gaps.md"]})
        self.residuals(CA, "c1", "- none")
        self.refused(CA, "retire", "c1", "--reason", "x", text="open backlog row")
        self.refused(CA, "abandon", "c1", "--reason", "x", text="open backlog row")

    def test_milestone_with_open_backlog_refused(self):
        self.backlog_file()
        self.milestone(1, backlog=["outputs/prod/gaps.md"], inputs=["outputs/prod/gaps.md"])
        self.make(AS, "u1", "--milestone", "obj#1")
        self.residuals(AS, "u1", "- none")
        self.refused(AS, "complete", "u1", text="open backlog row r1")

    def test_all_refusals_reported_together(self):
        self.make(AS)
        self.residuals(AS, "u1", "- intake:ghost", "- spawned:assignment:ghost")
        err = self.refused(AS, "complete", "u1")
        self.assertIn("intake:ghost", err)
        self.assertIn("assignment:ghost", err)


class TestCloseEffects(WSBase):
    def make(self, script, name="u1", *flags):
        self.ok(script, "create", name, *flags)

    def test_none_residual_closes_each_unit(self):
        for script in UNITS:
            self.make(script)
            self.residuals(script, "u1", "- none")
            out = self.ok(script, *self.close_args(script, "u1"))
            self.assertIn("Residuals (paste into the log entry's ### Residuals):", out)
            self.assertIn("- none", out)

    def test_cadence_abandon_accepted(self):
        self.make(CA, "c1")
        self.residuals(CA, "c1", "- none")
        self.ok(CA, "abandon", "c1", "--reason", "x")
        self.assertEqual(self.ufm(CA, "c1")["status"], "abandoned")

    def test_resolved_ids_accepted(self):
        self.raw_intake("known")
        self.ok(AS, "create", "kid")
        self.make(AS, "u1")
        self.residuals(AS, "u1", "- intake:known, still open", "- milestone:obj#2, later",
                       "- spawned:assignment:kid")
        out = self.ok(AS, "complete", "u1")
        self.assertIn("- spawned:assignment:kid", out)

    def test_handover_to_existing_unit_appends_and_creates_no_intake(self):
        self.backlog_file()
        self.make(AS, "recv")
        self.make(WS, "prod")
        self.residuals(WS, "prod", "- handover: assignment:recv — work the gaps; "
                                   "inputs: outputs/prod/gaps.md; backlog: outputs/prod/gaps.md")
        before = {p.name for p in (self.cp / "intake").glob("*.md")}
        self.ok(WS, "complete", "prod")
        self.assertEqual({p.name for p in (self.cp / "intake").glob("*.md")}, before)
        fm = self.ufm(AS, "recv")
        self.assertEqual(fm["inputs"], ["outputs/prod/gaps.md"])
        self.assertEqual(fm["backlog"], ["outputs/prod/gaps.md"])

    def test_handover_to_existing_milestone_appends(self):
        self.backlog_file()
        self.make(WS, "prod")
        self.residuals(WS, "prod", "- handover: milestone:obj#2 — take it; inputs: outputs/prod/gaps.md")
        self.ok(WS, "complete", "prod")
        self.assertEqual(self.mfm(2)["inputs"], ["outputs/prod/gaps.md"])

    def test_handover_to_missing_target_generates_intake(self):
        self.backlog_file()
        self.ok(WS, "create", "prod", "--parent", "objectives/obj")
        self.residuals(WS, "prod", "- handover: assignment:recv — work the gaps; "
                                   "inputs: outputs/prod/gaps.md; backlog: outputs/prod/gaps.md")
        self.ok(WS, "complete", "prod")
        fm = self.ifm("prod-handover-1")
        self.assertEqual(fm["kind"], "handover")
        self.assertEqual(fm["status"], "triaged")
        self.assertEqual(fm["route"], "assignment:recv")
        self.assertEqual(fm["inputs"], ["outputs/prod/gaps.md"])
        self.assertEqual(fm["backlog"], ["outputs/prod/gaps.md"])
        self.assertEqual(fm["source"], "workstream:prod")
        self.assertEqual(fm["objective"], "obj")
        body = (self.cp / "intake" / "prod-handover-1.md").read_text(encoding="utf-8")
        self.assertIn("work the gaps", body)

    def test_handover_numbering_skips_existing(self):
        self.make(WS, "prod")
        self.raw_intake("prod-handover-1", kind="handover")
        self.residuals(WS, "prod", "- handover: candidate:workstream — big follow-up")
        self.ok(WS, "complete", "prod")
        self.assertTrue((self.cp / "intake" / "prod-handover-2.md").exists())
        self.assertEqual(self.ifm("prod-handover-2")["route"], "candidate:workstream")

    def test_intake_source_consumed_and_archived(self):
        self.raw_intake("src")
        self.make(AS, "u1", "--intake-source", "intake:src")
        self.residuals(AS, "u1", "- none")
        self.ok(AS, "complete", "u1")
        self.assertFalse((self.cp / "intake" / "src.md").exists())
        fm = self.ifm("src", archived=True)
        self.assertEqual(fm["status"], "consumed")
        self.assertEqual(fm["consumed_by"], ["assignment:u1"])

    def test_intake_source_kept_active_when_keep_until_unmet(self):
        self.gate("g")
        self.raw_intake("src", keep_until="gate:g")
        self.make(AS, "u1", "--intake-source", "intake:src")
        self.residuals(AS, "u1", "- none")
        self.ok(AS, "complete", "u1")
        self.assertEqual(self.ifm("src")["status"], "active")
        self.assertFalse((self.cp / "intake" / "_archive" / "src.md").exists())

    def test_keep_until_own_milestone_counts_as_met_at_close(self):
        self.raw_intake("src", keep_until="obj#1")
        self.make(AS, "u1", "--intake-source", "intake:src", "--milestone", "obj#1")
        self.residuals(AS, "u1", "- none")
        self.ok(AS, "complete", "u1")
        self.assertFalse((self.cp / "intake" / "src.md").exists())
        fm = self.ifm("src", archived=True)
        self.assertEqual(fm["status"], "consumed")
        self.assertEqual(self.mfm(1)["status"], "done")

    def test_keep_until_other_milestone_still_keeps_active(self):
        self.raw_intake("src", keep_until="obj#2")
        self.make(AS, "u1", "--intake-source", "intake:src", "--milestone", "obj#1")
        self.residuals(AS, "u1", "- none")
        self.ok(AS, "complete", "u1")
        self.assertEqual(self.ifm("src")["status"], "active")

    def test_intake_source_kept_active_when_another_open_unit_lists_it(self):
        self.raw_intake("src")
        self.make(AS, "u1", "--intake-source", "intake:src")
        self.make(WS, "other", "--intake-source", "intake:src")
        self.residuals(AS, "u1", "- none")
        self.ok(AS, "complete", "u1")
        self.assertEqual(self.ifm("src")["status"], "active")
        self.assertTrue((self.cp / "intake" / "src.md").exists())

    def test_milestone_set_done_with_date(self):
        self.make(AS, "u1", "--milestone", "obj#1")
        self.residuals(AS, "u1", "- none")
        self.ok(AS, "complete", "u1")
        fm = self.mfm(1)
        self.assertEqual(fm["status"], "done")
        self.assertRegex(fm["done"], r"^\d{4}-\d{2}-\d{2}$")

    def test_report_names_actions(self):
        self.raw_intake("src")
        self.make(AS, "u1", "--intake-source", "intake:src", "--milestone", "obj#1")
        self.residuals(AS, "u1", "- none")
        out = self.ok(AS, "complete", "u1")
        self.assertIn("intake:src: consumed and archived", out)
        self.assertIn("obj#1: done", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
