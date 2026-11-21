#!/usr/bin/env python3
"""Tests for assignment.py — first coverage for this module (was zero before Phase 9.1).

Covers the pure frontmatter/table helpers plus the file-touching commands (create,
status, validate, complete, delete) against a temp portfolio, exercising the
presence-vs-value and row-rebuild behavior the source comments call out as
previously-fixed defects.

Run:  python -B tools/tests/test_assignment.py
Stdlib only (unittest) — no pytest dependency.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import assignment  # noqa: E402


class TestKebabOk(unittest.TestCase):
    def test_accepts_simple_name(self):
        self.assertTrue(assignment.kebab_ok("refresh-docs"))

    def test_accepts_digits(self):
        self.assertTrue(assignment.kebab_ok("q3-2026-review"))

    def test_rejects_path_separator(self):
        self.assertFalse(assignment.kebab_ok("workstreams/foo"))

    def test_rejects_uppercase(self):
        self.assertFalse(assignment.kebab_ok("Refresh-Docs"))

    def test_rejects_double_hyphen_edges(self):
        self.assertFalse(assignment.kebab_ok("-leading"))
        self.assertFalse(assignment.kebab_ok("trailing-"))

    def test_rejects_empty(self):
        self.assertFalse(assignment.kebab_ok(""))


FM_FIXTURE = """---
assignment: refresh-docs
status: active
parent: null
started: 2026-08-01
completed:
validated:
tags: [assignment/refresh-docs]
---

# Refresh Docs
"""


class TestFmGetSet(unittest.TestCase):
    def test_get_existing_field(self):
        self.assertEqual(assignment.fm_get(FM_FIXTURE, "status"), "active")

    def test_get_empty_field_returns_none(self):
        self.assertIsNone(assignment.fm_get(FM_FIXTURE, "completed"))

    def test_get_missing_field_returns_none(self):
        self.assertIsNone(assignment.fm_get(FM_FIXTURE, "nonexistent"))

    def test_set_replaces_value_in_place(self):
        out = assignment.fm_set(FM_FIXTURE, "status", "complete")
        self.assertIn("status: complete", out)
        self.assertNotIn("status: active", out)

    def test_set_fills_empty_field_without_eating_next_line(self):
        """`\\s*` would cross the newline and swallow the line after an empty field."""
        out = assignment.fm_set(FM_FIXTURE, "completed", "2026-08-10")
        self.assertIn("completed: 2026-08-10", out)
        self.assertIn("validated:\n", out, "the following empty field must survive untouched")

    def test_set_is_noop_when_field_absent(self):
        """assignment.fm_set only rewrites an existing `field:` line; it does not insert one."""
        out = assignment.fm_set(FM_FIXTURE, "nonexistent", "value")
        self.assertEqual(out, FM_FIXTURE)

    def test_set_only_touches_one_line(self):
        out = assignment.fm_set(FM_FIXTURE, "status", "complete")
        self.assertEqual(out.count("\n"), FM_FIXTURE.count("\n"))


GROUPED_PORTFOLIO = """# Assignments

## Active

### Anchor

| Assignment | Description | Parent | Started |
|---|---|---|---|
| [refresh-docs](refresh-docs/index.md) | Docs | — | 2026-08-01 |

### Infra

| Assignment | Description | Parent | Started |
|---|---|---|---|
| [lint-vault](lint-vault/index.md) | Lint | — | 2026-08-02 |
| [placeholder](placeholder/index.md) | *(none yet)* | — | — |

## Complete

| Assignment | Description | Completed |
|---|---|---|
| *(none yet)* | | |
"""


class TestParseIndexRows(unittest.TestCase):
    def test_rows_across_subgroups_all_returned(self):
        rows = assignment.parse_index_rows(GROUPED_PORTFOLIO)
        self.assertEqual(len(rows), 2, f"got: {rows}")

    def test_subgroup_header_rows_not_leaked_as_data(self):
        rows = assignment.parse_index_rows(GROUPED_PORTFOLIO)
        for r in rows:
            self.assertNotIn("| Assignment | Description | Parent | Started |", r)

    def test_none_yet_placeholder_excluded(self):
        rows = assignment.parse_index_rows(GROUPED_PORTFOLIO)
        self.assertFalse(any("none yet" in r for r in rows))

    def test_complete_section_excluded(self):
        rows = assignment.parse_index_rows(GROUPED_PORTFOLIO)
        self.assertTrue(all("refresh-docs" in r or "lint-vault" in r for r in rows))


class AssignmentFileTestCase(unittest.TestCase):
    """Redirect the module's path constants at a temp portfolio for each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self._orig_dir = assignment.ASSIGNMENTS_DIR
        self._orig_idx = assignment.PORTFOLIO_INDEX
        assignment.ASSIGNMENTS_DIR = root / "control-plane" / "assignments"
        assignment.PORTFOLIO_INDEX = assignment.ASSIGNMENTS_DIR / "index.md"
        self.addCleanup(self._restore)

    def _restore(self):
        assignment.ASSIGNMENTS_DIR = self._orig_dir
        assignment.PORTFOLIO_INDEX = self._orig_idx

    def make_args(self, **kw):
        ns = type("Args", (), {})()
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns


class TestCmdCreate(AssignmentFileTestCase):
    def test_creates_index_and_portfolio_row(self):
        assignment.cmd_create(self.make_args(name="refresh-docs", parent=None, title=None))
        idx = assignment.ASSIGNMENTS_DIR / "refresh-docs" / "index.md"
        self.assertTrue(idx.exists())
        portfolio = assignment.PORTFOLIO_INDEX.read_text(encoding="utf-8")
        self.assertIn("[refresh-docs](refresh-docs/index.md)", portfolio)

    def test_rejects_duplicate_name(self):
        assignment.cmd_create(self.make_args(name="dup", parent=None, title=None))
        with self.assertRaises(SystemExit):
            assignment.cmd_create(self.make_args(name="dup", parent=None, title=None))

    def test_rejects_invalid_name(self):
        with self.assertRaises(SystemExit):
            assignment.cmd_create(self.make_args(name="Not_Kebab", parent=None, title=None))

    def test_parent_link_rendered_when_given(self):
        assignment.cmd_create(self.make_args(name="child", parent="my-workstream", title=None))
        idx = (assignment.ASSIGNMENTS_DIR / "child" / "index.md").read_text(encoding="utf-8")
        self.assertIn("workstreams/my-workstream", idx)


class TestCmdValidateComplete(AssignmentFileTestCase):
    def setUp(self):
        super().setUp()
        assignment.cmd_create(self.make_args(name="w", parent=None, title=None))
        idx = assignment.ASSIGNMENTS_DIR / "w" / "index.md"
        idx.write_text(idx.read_text(encoding="utf-8").replace("-->\n\n## Cross-links", "-->\n\n- none\n\n## Cross-links"),
                       encoding="utf-8")

    def test_validate_fills_empty_field_in_place(self):
        """The template ships `validated:` empty — a presence check must fire, not a value check."""
        assignment.cmd_validate(self.make_args(name="w"))
        _, text = assignment.read_index("w")
        self.assertRegex(text, r"(?m)^validated: \d{4}-\d{2}-\d{2}$")
        self.assertEqual(text.count("validated:"), 1, "must not duplicate the field")

    def test_complete_sets_status_and_date(self):
        assignment.cmd_complete(self.make_args(name="w"))
        _, text = assignment.read_index("w")
        self.assertIn("status: complete", text)
        self.assertRegex(text, r"completed: \d{4}-\d{2}-\d{2}")
        self.assertEqual(text.count("completed:"), 1)

    def test_complete_moves_row_from_active_to_complete(self):
        assignment.cmd_complete(self.make_args(name="w"))
        portfolio = assignment.PORTFOLIO_INDEX.read_text(encoding="utf-8")
        active, complete = portfolio.split("## Complete")
        self.assertNotIn("[w]", active)
        self.assertIn("[w](_log.md)", complete, "completed row must repoint off the deleted folder")

    def test_complete_row_has_correct_cell_count(self):
        """Active has 4 cells (name/desc/parent/started); Complete has 3 — must rebuild, not patch."""
        assignment.cmd_complete(self.make_args(name="w"))
        portfolio = assignment.PORTFOLIO_INDEX.read_text(encoding="utf-8")
        complete_section = portfolio.split("## Complete")[1]
        row = [l for l in complete_section.splitlines() if l.startswith("| [w]")][0]
        cells = [c for c in row.strip().strip("|").split("|")]
        self.assertEqual(len(cells), 3, f"row: {row}")


class TestCmdDelete(AssignmentFileTestCase):
    def test_delete_removes_folder(self):
        assignment.cmd_create(self.make_args(name="throwaway", parent=None, title=None))
        path = assignment.ASSIGNMENTS_DIR / "throwaway"
        self.assertTrue(path.exists())
        assignment.cmd_delete(self.make_args(name="throwaway"))
        self.assertFalse(path.exists())


if __name__ == "__main__":
    os.environ.setdefault("WORKSPACE_ROOT", str(Path(__file__).resolve().parent.parent))
    unittest.main(verbosity=2)
