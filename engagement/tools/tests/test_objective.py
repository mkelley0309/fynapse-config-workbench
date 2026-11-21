#!/usr/bin/env python3
"""Tests for objective.py — the defects found during the objective-progress-backfill
workstream, plus regression cover for the helpers they touch.

Run:  python -B tools/tests/test_objective.py
Stdlib only (unittest) — no pytest dependency.
"""

import argparse
import io
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import objective  # noqa: E402


FRONTMATTER_FIXTURE = """---
objective: role-evolution
status: active
created: 2026-03-01
tags: [objective, role, strategy, personal]
---
# Role Evolution — Objective Context

Body text that happens to contain a --- horizontal rule below.

---

More body.
"""


class TestFmSet(unittest.TestCase):
    """fm_set inserted absent fields ABOVE the opening --- fence, destroying frontmatter."""

    def test_absent_field_inserted_inside_frontmatter(self):
        out = objective.fm_set(FRONTMATTER_FIXTURE, "health", "on-track")
        self.assertTrue(
            out.startswith("---\n"),
            "file must still open with the frontmatter fence",
        )
        lines = out.splitlines()
        closing = lines.index("---", 1)
        self.assertIn(
            "health: on-track",
            lines[1:closing],
            "new field must land between the opening and closing fences",
        )

    def test_absent_field_does_not_duplicate_fence(self):
        out = objective.fm_set(FRONTMATTER_FIXTURE, "cadence", "monthly")
        self.assertEqual(
            out.count("---"), FRONTMATTER_FIXTURE.count("---"),
            "no fence may be added or removed",
        )

    def test_existing_field_replaced_in_place(self):
        out = objective.fm_set(FRONTMATTER_FIXTURE, "status", "complete")
        self.assertIn("status: complete", out)
        self.assertNotIn("status: active", out)

    def test_body_horizontal_rule_untouched(self):
        out = objective.fm_set(FRONTMATTER_FIXTURE, "health", "at-risk")
        self.assertIn("Body text that happens to contain a --- horizontal rule below.", out)
        self.assertIn("More body.", out)

    def test_sequential_inserts_both_land_inside(self):
        out = objective.fm_set(FRONTMATTER_FIXTURE, "health", "on-track")
        out = objective.fm_set(out, "cadence", "monthly")
        lines = out.splitlines()
        closing = lines.index("---", 1)
        head = lines[1:closing]
        self.assertIn("health: on-track", head)
        self.assertIn("cadence: monthly", head)


SECTION_FIXTURE = """---
objective: demo
---
# Demo

## Objective

Some text.

## Success Criteria

- one

## Dependencies

- dep

## Key Decisions Log

| Decision | Rationale | Date |
|---|---|---|
| First | Because | 2026-01-01 |
| Second | Also | 2026-02-01 |

## Related Notes

- [[somewhere]]
"""


class TestReplaceSection(unittest.TestCase):
    """replace_section appended absent sections AFTER ## Related Notes."""

    NEW = "## Key Results\n\n| Result | Current | Target | Updated |\n|---|---|---|---|\n\n"

    def test_absent_section_inserted_before_related_notes(self):
        out = objective.replace_section(SECTION_FIXTURE, "## Key Results", self.NEW)
        self.assertLess(
            out.index("## Key Results"), out.index("## Related Notes"),
            "a new managed section must not be stranded after Related Notes",
        )

    def test_absent_section_appends_when_no_related_notes(self):
        trimmed = SECTION_FIXTURE.split("## Related Notes")[0]
        out = objective.replace_section(trimmed, "## Key Results", self.NEW)
        self.assertIn("## Key Results", out)
        self.assertGreater(out.index("## Key Results"), out.index("## Key Decisions Log"))

    def test_existing_section_replaced_in_place(self):
        seeded = objective.replace_section(SECTION_FIXTURE, "## Key Results", self.NEW)
        replacement = "## Key Results\n\nREPLACED\n\n"
        out = objective.replace_section(seeded, "## Key Results", replacement)
        self.assertIn("REPLACED", out)
        self.assertEqual(out.count("## Key Results"), 1, "must not duplicate the section")
        self.assertLess(out.index("## Key Results"), out.index("## Related Notes"))

    def test_decisions_log_survives_byte_identical(self):
        """The append-only constraint: no managed-section write may perturb the log."""
        before = objective.section_text(SECTION_FIXTURE, "## Key Decisions Log")
        out = SECTION_FIXTURE
        for header, body in [
            ("## Key Results", self.NEW),
            ("## Milestones", "## Milestones\n\n*(none yet)*\n\n"),
            ("## Workstreams", "## Workstreams\n\n| Workstream | Status | Linked |\n|---|---|---|\n\n"),
        ]:
            out = objective.replace_section(out, header, body)
        after = objective.section_text(out, "## Key Decisions Log")
        self.assertEqual(before, after, "Key Decisions Log must round-trip byte-identical")

    def test_all_three_managed_sections_precede_related_notes(self):
        out = SECTION_FIXTURE
        for header, body in [
            ("## Key Results", self.NEW),
            ("## Milestones", "## Milestones\n\n*(none yet)*\n\n"),
            ("## Workstreams", "## Workstreams\n\n| Workstream | Status | Linked |\n|---|---|---|\n\n"),
        ]:
            out = objective.replace_section(out, header, body)
        rn = out.index("## Related Notes")
        for header in ["## Key Results", "## Milestones", "## Workstreams"]:
            self.assertLess(out.index(header), rn, f"{header} stranded after Related Notes")


GROUPED_INDEX = """# Objectives

## Active

### Anchor

| Objective | Description | Status |
|---|---|---|
| [role-evolution](role-evolution/index.md) | Anchor | Active |

### Infrastructure Builds

| Objective | Description | Status |
|---|---|---|
| [responsive-content-library](responsive-content-library/index.md) | Build | Active |
| [navattic-demo-library](navattic-demo-library/index.md) | Build | Active |

### Enablement Programs

| Objective | Description | Status |
|---|---|---|
| [field-enablement](field-enablement/index.md) | Program | Active |

## Complete

| Objective | Description | Completed | Key Outcome |
|---|---|---|---|
| *(none yet)* | | | |
"""


class TestGroupedIndexParsing(unittest.TestCase):
    """cmd_list leaked each ### subgroup's header row as a data row."""

    def test_no_header_rows_in_output(self):
        rows = objective.parse_index_rows(GROUPED_INDEX)
        for r in rows:
            self.assertNotIn("| Objective | Description | Status |", r)

    def test_all_data_rows_returned(self):
        rows = objective.parse_index_rows(GROUPED_INDEX)
        self.assertEqual(len(rows), 4, f"expected 4 objective rows, got {len(rows)}: {rows}")

    def test_complete_section_excluded(self):
        rows = objective.parse_index_rows(GROUPED_INDEX)
        self.assertFalse(any("none yet" in r for r in rows))

    def test_ungrouped_index_still_parses(self):
        flat = (
            "# Objectives\n\n## Active\n\n"
            "| Objective | Description | Status |\n|---|---|---|\n"
            "| [a](a/index.md) | One | Active |\n"
            "| [b](b/index.md) | Two | Active |\n\n"
            "## Complete\n"
        )
        rows = objective.parse_index_rows(flat)
        self.assertEqual(len(rows), 2)

    def test_subgroup_lookup_finds_correct_group(self):
        """cmd_create must insert into the right ### subgroup, not always the first."""
        idx = objective.index_insert_point(GROUPED_INDEX, "Enablement Programs")
        anchor_idx = objective.index_insert_point(GROUPED_INDEX, "Anchor")
        self.assertIsNotNone(idx)
        self.assertNotEqual(
            idx, anchor_idx,
            "Enablement Programs must not resolve to the Anchor subgroup",
        )


class TestLinkWorkstreamValidation(unittest.TestCase):
    """link-workstream hardcoded status=active and validated nothing."""

    def test_normalize_bare_name(self):
        self.assertEqual(
            objective.normalize_workstream_ref("my-thing"), "workstreams/my-thing"
        )

    def test_normalize_preserves_explicit_path(self):
        self.assertEqual(
            objective.normalize_workstream_ref("workstreams/my-thing"),
            "workstreams/my-thing",
        )

    def test_normalize_recognizes_log_entry(self):
        ref = "workstreams/_log/2026-05-22-fynapse-buy-v-build-insurance"
        self.assertEqual(objective.normalize_workstream_ref(ref), ref)


REVIEWABLE = """---
objective: demo
status: active
health: at-risk
cadence: monthly
---
# Demo

## Key Results

| Result | Current | Target | Updated |
|---|---|---|---|
| Gates cleared | 1 | 4 | 2026-07-30 |

## Workstreams

| Workstream | Status | Linked |
|---|---|---|
| workstreams/live-one | active | 2026-07-30 |
| workstreams/_log/2026-05-22-done-one | complete | 2026-07-30 |

## Related Notes

- [[somewhere]]
"""


MS_VIEW = [
    {"n": 1, "title": "First thing", "status": "done"},
    {"n": 2, "title": "Second thing", "status": "open"},
    {"n": 3, "title": "Third thing", "status": "dropped"},
]


class TestCheckpointRendering(unittest.TestCase):
    """checkpoint must snapshot tracked state without touching the anchor."""

    def setUp(self):
        self.out = objective.render_checkpoint("demo", REVIEWABLE, "2026-07-30", MS_VIEW)

    def test_carries_health_and_cadence_into_frontmatter(self):
        self.assertIn("health: at-risk", self.out)
        self.assertIn("cadence: monthly", self.out)
        self.assertIn("checkpoint_date: 2026-07-30", self.out)

    def test_snapshots_kr_values(self):
        self.assertIn("| Gates cleared | 1 | 4 | 2026-07-30 |", self.out)

    def test_counts_milestones(self):
        self.assertIn("## Milestones — 1/3 done", self.out)
        self.assertIn("- [x] #1 First thing", self.out)
        self.assertIn("- [ ] #2 Second thing", self.out)
        self.assertIn("- [x] ~~#3 Third thing~~ (dropped)", self.out)

    def test_carries_workstream_status(self):
        self.assertIn("`workstreams/live-one` — active", self.out)
        self.assertIn("`workstreams/_log/2026-05-22-done-one` — complete", self.out)

    def test_empty_kr_set_is_framed_as_a_finding(self):
        bare = REVIEWABLE.replace("| Gates cleared | 1 | 4 | 2026-07-30 |", "")
        out = objective.render_checkpoint("demo", bare, "2026-07-30")
        self.assertIn("No Key Results set", out)
        self.assertIn("finding, not an omission", out)

    def test_health_section_demands_evidence(self):
        self.assertIn("A health value without evidence is an assertion", self.out)

    def test_missing_health_and_cadence_do_not_crash(self):
        minimal = "---\nobjective: demo\n---\n# Demo\n\n## Related Notes\n"
        out = objective.render_checkpoint("demo", minimal, "2026-07-30")
        self.assertIn("health: —", out)
        self.assertIn("## Milestones — 0/0 done", out)

    def test_render_is_pure(self):
        """Rendering must not mutate the source text — the anchor is read-only here."""
        before = REVIEWABLE
        objective.render_checkpoint("demo", REVIEWABLE, "2026-07-30")
        self.assertEqual(before, REVIEWABLE)

    def test_carries_a_harness_friction_section(self):
        """The objective tier's feedback loop — how the machinery performed this cycle."""
        self.assertIn("## Harness Friction", self.out)

    def test_friction_section_scopes_itself_to_the_harness(self):
        """Without the scoping cue this section becomes a second progress log."""
        i = self.out.index("## Harness Friction")
        section = self.out[i:self.out.index("## Next Checkpoint", i)]
        self.assertIn("unrelated objective", section)
        self.assertIn("_harness/friction.md", section)


DECOY = """---
objective: demo
status: active
health: on-track
---
# Demo

A prose line describing the schema, which happens to start like a field:

status: this is body text, not frontmatter
health: blocked
cadence: annual

## Related Notes
"""


class TestFrontmatterScoping(unittest.TestCase):
    """The fm_* helpers matched any `field:`-shaped line anywhere in the document.

    A read could return body text; a write could rewrite it. All three helpers
    shared the defect — fm_get on the read path, fm_set and fm_add_field_after on
    the write path.
    """

    def test_get_ignores_body_line_when_field_absent_from_frontmatter(self):
        self.assertIsNone(
            objective.fm_get(DECOY, "cadence"),
            "cadence exists only in the body — must not be read as frontmatter",
        )

    def test_get_prefers_frontmatter_over_later_body_line(self):
        self.assertEqual(objective.fm_get(DECOY, "health"), "on-track")
        self.assertEqual(objective.fm_get(DECOY, "status"), "active")

    def test_set_rewrites_frontmatter_not_body(self):
        out = objective.fm_set(DECOY, "health", "stale")
        lines = out.splitlines()
        closing = lines.index("---", 1)
        self.assertIn("health: stale", lines[1:closing])
        self.assertIn(
            "health: blocked", lines[closing:],
            "the body line must survive untouched",
        )
        self.assertEqual(
            out.count("health: stale"), 1,
            "exactly one line may change",
        )

    def test_set_absent_field_inserts_into_frontmatter_despite_body_decoy(self):
        out = objective.fm_set(DECOY, "cadence", "monthly")
        lines = out.splitlines()
        closing = lines.index("---", 1)
        self.assertIn("cadence: monthly", lines[1:closing])
        self.assertIn(
            "cadence: annual", lines[closing:],
            "the decoy body line must remain in the body",
        )

    def test_set_preserves_crlf_terminators(self):
        crlf = DECOY.replace("\n", "\r\n")
        out = objective.fm_set(crlf, "cadence", "monthly")
        self.assertIn("cadence: monthly\r\n", out)
        self.assertNotIn("cadence: monthly\n\r", out)
        self.assertEqual(out.count("\r\n"), crlf.count("\r\n") + 1)

    def test_set_dies_without_terminated_fence(self):
        with self.assertRaises(SystemExit):
            objective.fm_set("no frontmatter here\n", "health", "stale")

    def test_add_field_after_ignores_body_decoy(self):
        out = objective.fm_add_field_after(DECOY, "status", "cadence", "monthly")
        lines = out.splitlines()
        closing = lines.index("---", 1)
        self.assertIn("cadence: monthly", lines[1:closing])

    def test_add_field_after_is_noop_when_present_in_frontmatter(self):
        self.assertEqual(
            objective.fm_add_field_after(DECOY, "objective", "health", "stale"),
            DECOY,
        )


class TestEnumValidation(unittest.TestCase):
    """health enforced its enum inline; cadence was unvalidated free text."""

    def test_cadence_values_in_use_are_all_valid(self):
        for value in ("monthly", "bi-weekly", "quarterly"):
            self.assertIn(value, objective.VALID_CADENCE)

    def test_scaffold_defaults_are_valid(self):
        self.assertIn("on-track", objective.VALID_HEALTH)
        self.assertIn("quarterly", objective.VALID_CADENCE)

    def test_enums_are_ordered_not_sets(self):
        """Error messages must list values in a stable order, not set order."""
        self.assertIsInstance(objective.VALID_HEALTH, tuple)
        self.assertIsInstance(objective.VALID_CADENCE, tuple)



class MilestoneBase(unittest.TestCase):
    """Temp workspace; objective.py module globals are repointed at it."""

    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name).resolve()
        self._saved = (objective.WORKSPACE, objective.OBJECTIVES_DIR,
                       objective.PORTFOLIO_INDEX, objective.ARCHIVE_DIR)
        objective.WORKSPACE = self.root
        objective.OBJECTIVES_DIR = self.root / "control-plane" / "objectives"
        objective.PORTFOLIO_INDEX = objective.OBJECTIVES_DIR / "index.md"
        objective.ARCHIVE_DIR = objective.OBJECTIVES_DIR / "_archive"
        self._out = io.StringIO()
        self._so = sys.stdout
        sys.stdout = self._out
        self.run_cmd(objective.cmd_create, name="demo", title=None, origin=None, group=None)

    def tearDown(self):
        sys.stdout = self._so
        (objective.WORKSPACE, objective.OBJECTIVES_DIR,
         objective.PORTFOLIO_INDEX, objective.ARCHIVE_DIR) = self._saved
        self._td.cleanup()

    def run_cmd(self, fn, **kw):
        return fn(argparse.Namespace(**kw))

    def add_kw(self, title, **kw):
        base = dict(name="demo", title=title, depends_on=None, locks=None, fed_by=None,
                    related=None, ref=None, order=None, conditional=False)
        base.update(kw)
        return base

    def add(self, title, **kw):
        return self.run_cmd(objective.cmd_add_milestone, **self.add_kw(title, **kw))

    def set_kw(self, key, **kw):
        base = dict(name="demo", key=key, title=None, order=None, conditional=None, ref=None,
                    unit=None, depends_on=None, locks=None, fed_by=None, related=None,
                    inputs=None, backlog=None)
        base.update(kw)
        return base

    def fails(self, fn, **kw):
        err = io.StringIO()
        se, sys.stderr = sys.stderr, err
        try:
            with self.assertRaises(SystemExit) as cm:
                self.run_cmd(fn, **kw)
        finally:
            sys.stderr = se
        self.assertEqual(cm.exception.code, 1)
        return err.getvalue()

    def ms_dir(self):
        return objective.OBJECTIVES_DIR / "demo" / "milestones"

    def fm(self, n):
        return objective.harnesslib.fm_read(next(self.ms_dir().glob(f"{n:02d}-*.md")))[0]


class TestMilestoneRecords(MilestoneBase):
    def test_create_scaffolds_milestones_dir(self):
        self.assertTrue(self.ms_dir().is_dir())

    def test_add_writes_record_with_sequential_ids(self):
        self.add("First thing")
        self.add("Second: thing", conditional=True, ref="07 order 6")
        a, b = self.fm(1), self.fm(2)
        self.assertEqual((a["id"], a["status"], a["note_type"]), ("demo#1", "open", "milestone"))
        self.assertEqual((b["id"], b["title"], b["conditional"], b["ref"]),
                         ("demo#2", "Second: thing", "true", "07 order 6"))
        self.assertEqual(b["order"], "2")

    def test_add_duplicate_title_refused(self):
        self.add("Same")
        self.assertIn("already exists", self.fails(objective.cmd_add_milestone, **self.add_kw("Same")))

    def test_add_unresolved_dependency_refused(self):
        self.assertIn("unresolved", self.fails(objective.cmd_add_milestone,
                                               **self.add_kw("X", depends_on=["demo#9"])))
        self.assertEqual(list(self.ms_dir().glob("*.md")), [])

    def test_add_with_dependency_and_unknown_lock(self):
        self.add("A")
        self.add("B", depends_on=["demo#1"])
        self.assertEqual(self.fm(2)["depends_on"], ["demo#1"])
        self.assertIn("unknown lock", self.fails(objective.cmd_add_milestone,
                                                 **self.add_kw("C", locks=["nope"])))

    def test_set_cycle_refused(self):
        self.add("A")
        self.add("B", depends_on=["demo#1"])
        self.assertIn("cycle", self.fails(objective.cmd_set_milestone,
                                          **self.set_kw("1", depends_on=["demo#2"])))
        self.assertEqual(self.fm(1)["depends_on"], [])

    def test_check_by_number_and_by_title_and_legacy(self):
        self.add("A")
        self.add("B")
        self.add("C")
        objective.harnesslib.fm_write(next(self.ms_dir().glob("03-*.md")),
                                      {"legacy": "- [ ] Old checklist line"})
        self.run_cmd(objective.cmd_check_milestone, name="demo", text="1")
        self.run_cmd(objective.cmd_check_milestone, name="demo", text="B")
        self.run_cmd(objective.cmd_check_milestone, name="demo", text="Old checklist line")
        for n in (1, 2, 3):
            self.assertEqual(self.fm(n)["status"], "done")
            self.assertEqual(self.fm(n)["done"], objective.today())

    def test_check_twice_and_missing_refused(self):
        self.add("A")
        self.run_cmd(objective.cmd_check_milestone, name="demo", text="1")
        self.assertIn("already done", self.fails(objective.cmd_check_milestone, name="demo", text="1"))
        self.assertIn("not found", self.fails(objective.cmd_check_milestone, name="demo", text="zzz"))

    def test_check_refused_with_open_backlog_rows(self):
        self.add("A")
        bl = self.root / "outputs" / "p" / "b.md"
        bl.parent.mkdir(parents=True)
        bl.write_text("| id | item | status | route |\n|---|---|---|---|\n| r1 | x | open | |\n")
        self.run_cmd(objective.cmd_set_milestone,
                     **self.set_kw("1", inputs=["outputs/p/b.md"], backlog=["outputs/p/b.md"]))
        self.assertIn("open backlog", self.fails(objective.cmd_check_milestone, name="demo", text="1"))

    def test_set_updates_only_named_fields(self):
        self.add("A")
        self.run_cmd(objective.cmd_set_milestone, **self.set_kw("1", title="A2", order=7, conditional="true"))
        f = self.fm(1)
        self.assertEqual((f["title"], f["order"], f["conditional"], f["id"]), ("A2", "7", "true", "demo#1"))

    def test_drop_logs_decision_and_refuses_repeat(self):
        self.add("A")
        self.run_cmd(objective.cmd_drop_milestone, name="demo", key="1", reason="superseded")
        self.assertEqual(self.fm(1)["status"], "dropped")
        idx = (objective.OBJECTIVES_DIR / "demo" / "index.md").read_text(encoding="utf-8")
        self.assertIn("| Milestone demo#1 dropped | superseded |", idx)
        self.assertIn("already dropped", self.fails(objective.cmd_drop_milestone, name="demo", key="1", reason="x"))

    def test_drop_blank_reason_refused(self):
        self.add("A")
        self.assertIn("reason", self.fails(objective.cmd_drop_milestone, name="demo", key="1", reason="  "))
        self.assertEqual(self.fm(1)["status"], "open")

    def test_checkpoint_snapshots_records(self):
        self.add("A")
        self.add("B")
        self.run_cmd(objective.cmd_check_milestone, name="demo", text="1")
        self.run_cmd(objective.cmd_checkpoint, name="demo", date="2026-07-30", force=False)
        cp = (objective.OBJECTIVES_DIR / "demo" / "checkpoints" / "2026-07-30.md").read_text(encoding="utf-8")
        self.assertIn("## Milestones — 1/2 done", cp)
        self.assertIn("- [x] #1 A", cp)
        self.assertIn("- [ ] #2 B", cp)


class TestUnmigrated(MilestoneBase):
    def setUp(self):
        super().setUp()
        (self.ms_dir() / ".gitkeep").unlink()
        self.ms_dir().rmdir()

    def test_every_milestone_command_exits_1_with_message(self):
        msg = "not migrated: run M2 (harness-intake-dependency-model)"
        self.assertIn(msg, self.fails(objective.cmd_add_milestone, **self.add_kw("x")))
        self.assertIn(msg, self.fails(objective.cmd_check_milestone, name="demo", text="1"))
        self.assertIn(msg, self.fails(objective.cmd_drop_milestone, name="demo", key="1", reason="r"))
        self.assertIn(msg, self.fails(objective.cmd_set_milestone, **self.set_kw("1", title="t")))
        self.assertIn(msg, self.fails(objective.cmd_checkpoint, name="demo", date=None, force=False))

    def test_no_legacy_parser_remains(self):
        for sym in ("_parse_milestones", "_render_milestone_section", "MS_HEADER"):
            self.assertFalse(hasattr(objective, sym), sym)


class TestD17Fixes(MilestoneBase):
    """R13 defect fixes: each has a regression test."""

    def idx(self):
        return (objective.OBJECTIVES_DIR / "demo" / "index.md").read_text(encoding="utf-8")

    def portfolio(self):
        return objective.PORTFOLIO_INDEX.read_text(encoding="utf-8")

    def link(self, ref, status="active"):
        self.run_cmd(objective.cmd_link_workstream, objective="demo", workstream=ref, status=status)

    def ws_rows(self):
        return objective._parse_workstreams(self.idx())

    def mkws(self, name, log=False):
        cp = self.root / "control-plane" / "workstreams"
        if log:
            (cp / "_log").mkdir(parents=True, exist_ok=True)
            (cp / "_log" / f"2026-11-01-{name}.md").write_text("log\n", encoding="utf-8")
        else:
            (cp / name).mkdir(parents=True, exist_ok=True)
            (cp / name / "index.md").write_text("---\nstatus: active\n---\n", encoding="utf-8")

    def test_link_log_form_normalises_to_bare_name(self):
        self.mkws("thing", log=True)
        self.link("workstreams/_log/2026-11-01-thing", "complete")
        rows = self.ws_rows()
        self.assertEqual([(r["workstream"], r["status"]) for r in rows], [("workstreams/thing", "complete")])

    def test_link_never_duplicates_and_updates_status_in_place(self):
        self.mkws("thing")
        self.link("thing")
        self.link("thing")
        self.assertEqual(len(self.ws_rows()), 1)
        self.mkws("thing", log=True)
        self.link("workstreams/_log/2026-11-01-thing", "complete")
        rows = self.ws_rows()
        self.assertEqual([(r["workstream"], r["status"]) for r in rows], [("workstreams/thing", "complete")])

    def test_link_updates_legacy_log_row_instead_of_adding(self):
        self.mkws("thing", log=True)
        p = objective.OBJECTIVES_DIR / "demo" / "index.md"
        t = p.read_text(encoding="utf-8").replace(
            "| *(none yet)* | | |\n\n## Dependencies",
            "| workstreams/_log/2026-11-01-thing | active | 2026-11-01 |\n\n## Dependencies")
        p.write_text(t, encoding="utf-8")
        self.assertEqual(len(self.ws_rows()), 1)
        self.link("thing", "complete")
        rows = self.ws_rows()
        self.assertEqual([(r["workstream"], r["status"]) for r in rows], [("workstreams/thing", "complete")])

    def test_abandon_creates_abandoned_section_when_absent(self):
        self.assertNotIn("## Abandoned", self.portfolio())
        self.run_cmd(objective.cmd_abandon, name="demo", reason="no longer needed", disposition=None)
        p = self.portfolio()
        self.assertIn("## Abandoned", p)
        tail = p.split("## Abandoned", 1)[1]
        self.assertIn("[demo](_archive/abandoned/demo/index.md)", tail)
        self.assertIn("no longer needed", tail)
        self.assertNotIn("[demo]", p.split("## Abandoned", 1)[0])

    def test_complete_moves_row_to_complete_table(self):
        self.run_cmd(objective.cmd_complete, name="demo", reason="all done")
        p = self.portfolio()
        active = p.split("## Active", 1)[1].split("## Complete", 1)[0]
        done = p.split("## Complete", 1)[1]
        self.assertNotIn("[demo]", active)
        self.assertIn("[demo](_archive/closed/demo/index.md)", done)
        self.assertIn("all done", done)

    def test_complete_creates_complete_section_when_absent(self):
        objective.PORTFOLIO_INDEX.write_text(
            "# Objectives\n\n## Active\n\n| Objective | Description | Status |\n|---|---|---|\n"
            "| [demo](demo/index.md) | d | Active |\n", encoding="utf-8")
        self.run_cmd(objective.cmd_complete, name="demo", reason="done")
        p = self.portfolio()
        self.assertIn("## Complete", p)
        self.assertIn("[demo](_archive/closed/demo/index.md)", p.split("## Complete", 1)[1])

    def _no_active_row(self):
        objective.PORTFOLIO_INDEX.write_text(
            "# Objectives\n\n## Active\n\n| Objective | Description | Status |\n|---|---|---|\n",
            encoding="utf-8")

    def test_complete_refused_without_active_row_leaves_index_untouched(self):
        self._no_active_row()
        p = objective.OBJECTIVES_DIR / "demo" / "index.md"
        before = p.read_bytes()
        err = self.fails(objective.cmd_complete, name="demo", reason="x")
        self.assertIn("not found in the Active table", err)
        self.assertEqual(p.read_bytes(), before)
        self.assertTrue(p.exists())

    def test_abandon_refused_without_active_row_leaves_index_untouched(self):
        self._no_active_row()
        p = objective.OBJECTIVES_DIR / "demo" / "index.md"
        before = p.read_bytes()
        err = self.fails(objective.cmd_abandon, name="demo", reason="x", disposition=None)
        self.assertIn("not found in the Active table", err)
        self.assertEqual(p.read_bytes(), before)

    def test_section_bounds_ignore_deeper_headings(self):
        text = "## A\n\nbody\n\n### Sub\n\nmore\n\n#### Deep\n\nx\n\n## B\n\ny\n"
        s, e = objective._section_bounds(text, "## A")
        sec = "".join(text.splitlines(keepends=True)[s:e])
        self.assertIn("### Sub", sec)
        self.assertIn("#### Deep", sec)
        self.assertNotIn("## B", sec)
        # a single-# heading still ends the section
        s, e = objective._section_bounds("## A\n\nx\n\n# Top\n\ny\n", "## A")
        self.assertEqual(e, 4)

    def test_log_decision_literal_backslashes_and_single_row(self):
        text = ("## Key Decisions Log\n\n| Decision | Rationale | Date |\n|---|---|---|\n| a | b | c |\n\n"
                "## Other\n\n## Key Decisions Log\n\n| Decision | Rationale | Date |\n|---|---|---|\n")
        out = objective.log_decision_text(text, r"use \1 and \g<1>", r"path C:\new\dir")
        self.assertIn(r"| use \1 and \g<1> | path C:\new\dir |", out)
        self.assertEqual(out.count(r"\g<1>"), 1)   # count=1: only the first log gets the row


if __name__ == "__main__":
    os.environ.setdefault("WORKSPACE_ROOT", str(Path(__file__).resolve().parent.parent))
    unittest.main(verbosity=2)
