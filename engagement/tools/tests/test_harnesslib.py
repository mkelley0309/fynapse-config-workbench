#!/usr/bin/env python3
"""Tests for harnesslib.py. Run: python -B -m unittest tools.tests.test_harnesslib
Stdlib only."""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import harnesslib  # noqa: E402


def tmp():
    d = tempfile.TemporaryDirectory()
    return d, Path(d.name)


class TestFrontmatter(unittest.TestCase):
    def setUp(self):
        self.d, self.p = tmp()
        self.f = self.p / "a.md"

    def tearDown(self):
        self.d.cleanup()

    def test_read_types(self):
        self.f.write_bytes(b'---\nk: v\nq: "a: b"\nl: [x, y, "z, w"]\ne: []\ndone:\n---\nbody\n')
        fm, span = harnesslib.fm_read(self.f)
        self.assertEqual(fm["k"], "v")
        self.assertEqual(fm["q"], "a: b")
        self.assertEqual(fm["l"], ["x", "y", "z, w"])
        self.assertEqual(fm["e"], [])
        self.assertEqual(fm["done"], "")
        self.assertEqual(span[0], 7)

    def test_write_round_trip_keeps_order_and_unknown(self):
        raw = b'---\nb: 1\nunknown_key: keep me\na: [p, q]\n---\nbody\n'
        self.f.write_bytes(raw)
        harnesslib.fm_write(self.f, {"a": ["p", "q", "r"], "new": "x: y"})
        out = self.f.read_bytes()
        self.assertEqual(out, b'---\nb: 1\nunknown_key: keep me\na: [p, q, r]\nnew: "x: y"\n---\nbody\n')
        fm, _ = harnesslib.fm_read(self.f)
        self.assertEqual(fm["new"], "x: y")
        self.assertEqual(fm["a"], ["p", "q", "r"])

    def test_noop_write_leaves_bytes(self):
        raw = b'---\r\nk: v\r\n---\r\nbody\r\n'
        self.f.write_bytes(raw)
        self.assertFalse(harnesslib.fm_write(self.f, {"k": "v"}))
        self.assertEqual(self.f.read_bytes(), raw)

    def test_body_key_not_touched(self):
        self.f.write_bytes(b'---\nk: v\n---\nk: body\n')
        harnesslib.fm_write(self.f, {"k": "w"})
        self.assertEqual(self.f.read_bytes(), b'---\nk: w\n---\nk: body\n')

    def test_missing_fence_raises(self):
        self.f.write_bytes(b'no fm\n')
        with self.assertRaises(harnesslib.HarnessError):
            harnesslib.fm_write(self.f, {"k": "v"})


class TestSplice(unittest.TestCase):
    def setUp(self):
        self.d, self.p = tmp()
        self.f = self.p / "a.txt"

    def tearDown(self):
        self.d.cleanup()

    def test_lf(self):
        self.f.write_bytes(b"a\nb\nc\n")
        harnesslib.splice_write(self.f, [(1, 2, ["B"])])
        self.assertEqual(self.f.read_bytes(), b"a\nB\nc\n")

    def test_crlf(self):
        self.f.write_bytes(b"a\r\nb\r\nc\r\n")
        harnesslib.splice_write(self.f, [(1, 2, ["B", "B2"])])
        self.assertEqual(self.f.read_bytes(), b"a\r\nB\r\nB2\r\nc\r\n")

    def test_mixed_untouched_lines_keep_bytes(self):
        self.f.write_bytes(b"a\r\nb\nc\r\nd\n")
        harnesslib.splice_write(self.f, [(2, 3, ["C"])])
        self.assertEqual(self.f.read_bytes(), b"a\r\nb\nC\r\nd\n")
        harnesslib.splice_write(self.f, [(1, 1, ["ins"])])  # takes EOL of line above (CRLF)
        self.assertEqual(self.f.read_bytes(), b"a\r\nins\r\nb\nC\r\nd\n")

    def test_insert_at_top_uses_line_below(self):
        self.f.write_bytes(b"x\r\ny\r\n")
        harnesslib.splice_write(self.f, [(0, 0, ["top"])])
        self.assertEqual(self.f.read_bytes(), b"top\r\nx\r\ny\r\n")

    def test_new_file_is_lf(self):
        n = self.p / "sub" / "n.txt"
        harnesslib.splice_write(n, [(0, 0, ["one", "two"])])
        self.assertEqual(n.read_bytes(), b"one\ntwo\n")

    def test_append_after_unterminated_last_line(self):
        self.f.write_bytes(b"a\r\nb")
        harnesslib.splice_write(self.f, [(2, 2, ["c"])])
        self.assertEqual(self.f.read_bytes(), b"a\r\nb\r\nc\r\n")

    def test_write_text_diff_mixed(self):
        self.f.write_bytes(b"a\r\nb\nc\r\nd\n")
        harnesslib.write_text(self.f, "a\nB\nc\nd\ne\n")
        self.assertEqual(self.f.read_bytes(), b"a\r\nB\nc\r\nd\ne\n")

    def test_write_text_no_change_keeps_bytes(self):
        raw = b"a\r\nb\nc\r\n"
        self.f.write_bytes(raw)
        self.assertFalse(harnesslib.write_text(self.f, "a\nb\nc\n"))
        self.assertEqual(self.f.read_bytes(), raw)

    def test_write_text_new_file_lf(self):
        n = self.p / "x" / "n.md"
        harnesslib.write_text(n, "a\nb\n")
        self.assertEqual(n.read_bytes(), b"a\nb\n")

    def test_write_text_trailing_newline_change(self):
        self.f.write_bytes(b"a\r\nb")
        harnesslib.write_text(self.f, "a\nb\n")
        self.assertEqual(self.f.read_bytes(), b"a\r\nb\r\n")


class TestRoot(unittest.TestCase):
    def setUp(self):
        self.d, self.p = tmp()
        self.old_env = os.environ.pop("WORKSPACE_ROOT", None)
        self.old_cwd = os.getcwd()
        (self.p / "control-plane" / "x").mkdir(parents=True)
        (self.p / "plain").mkdir()

    def tearDown(self):
        os.chdir(self.old_cwd)
        os.environ.pop("WORKSPACE_ROOT", None)
        if self.old_env is not None:
            os.environ["WORKSPACE_ROOT"] = self.old_env
        self.d.cleanup()

    def test_env(self):
        os.environ["WORKSPACE_ROOT"] = str(self.p)
        os.chdir(self.p / "plain")       # inside the same root: env and cwd agree (R2)
        self.assertEqual(harnesslib.find_root(), self.p.resolve())

    def test_env_without_cwd_root(self):
        bare = tempfile.TemporaryDirectory()
        self.addCleanup(bare.cleanup)
        os.chdir(bare.name)              # no control-plane/ above cwd: the env root wins
        os.environ["WORKSPACE_ROOT"] = str(self.p)
        self.assertEqual(harnesslib.find_root(), self.p.resolve())

    def test_env_cwd_mismatch_dies_naming_both(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        (Path(other.name) / "control-plane").mkdir()
        os.chdir(other.name)
        os.environ["WORKSPACE_ROOT"] = str(self.p)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            harnesslib.find_root()
        self.assertIn(str(self.p.resolve()), err.getvalue())
        self.assertIn(str(Path(other.name).resolve()), err.getvalue())

    def test_cwd(self):
        os.chdir(self.p)
        self.assertEqual(harnesslib.find_root(), self.p.resolve())

    def test_walk_up(self):
        os.chdir(self.p / "control-plane" / "x")
        self.assertEqual(harnesslib.find_root(), self.p.resolve())

    def test_failure(self):
        # a temp dir with no control-plane/ anywhere above
        os.environ["WORKSPACE_ROOT"] = str(Path(self.p.anchor))
        with self.assertRaises(SystemExit):
            harnesslib.find_root()

    def test_rel_cmd(self):
        self.assertTrue(harnesslib.rel_cmd("objective.py").startswith("python -B "))
        self.assertTrue(harnesslib.rel_cmd("objective.py").endswith("objective.py"))


class TestRegions(unittest.TestCase):
    def setUp(self):
        self.d, self.p = tmp()
        self.f = self.p / "r.md"
        self.f.write_bytes(b"head\r\n<!-- generated:v -->\r\nold\r\n<!-- /generated:v -->\r\ntail\r\n")

    def tearDown(self):
        self.d.cleanup()

    def test_render_keeps_eol_and_sets_sha(self):
        harnesslib.render_region(self.f, "v", "line1\nline2")
        out = self.f.read_bytes()
        sha = harnesslib._sha8("line1\nline2\n")
        self.assertEqual(out, (b"head\r\n<!-- generated:v -->\r\nline1\r\nline2\r\n"
                               b"<!-- /generated:v sha=" + sha.encode() + b" -->\r\ntail\r\n"))
        self.assertFalse(harnesslib.region_stale(self.f, "v", "line1\nline2"))
        self.assertTrue(harnesslib.region_stale(self.f, "v", "other"))

    def test_unmarked_sha_is_stale_but_renders(self):
        self.assertTrue(harnesslib.region_stale(self.f, "v", "old"))
        harnesslib.render_region(self.f, "v", "old")
        self.assertFalse(harnesslib.region_stale(self.f, "v", "old"))

    def test_hand_edit_refused_unless_force(self):
        harnesslib.render_region(self.f, "v", "a")
        raw = self.f.read_bytes().replace(b"\r\na\r\n", b"\r\nhand\r\n")
        self.f.write_bytes(raw)
        with self.assertRaises(harnesslib.RegionEdited):
            harnesslib.render_region(self.f, "v", "a")
        harnesslib.render_region(self.f, "v", "a", force=True)
        self.assertFalse(harnesslib.region_stale(self.f, "v", "a"))

    def test_missing_region(self):
        with self.assertRaises(harnesslib.RegionMissing):
            harnesslib.render_region(self.f, "nope", "x")

    def test_only_region_changes(self):
        harnesslib.render_region(self.f, "v", "z")
        out = self.f.read_bytes()
        self.assertTrue(out.startswith(b"head\r\n<!-- generated:v -->\r\n"))
        self.assertTrue(out.endswith(b"-->\r\ntail\r\n"))


class TestOutputsRef(unittest.TestCase):
    def check(self, s, want):
        self.assertEqual(harnesslib.norm_outputs_ref(s), want, s)

    def test_forms(self):
        self.check("`outputs/foo`", ("foo", False, None))
        self.check("`outputs/foo/report.md`", ("foo", False, None))
        self.check("../outputs/foo/x", ("foo", False, None))
        self.check("../../outputs/foo", ("foo", False, None))
        self.check('join(HERE, "../../outputs/foo")', ("foo", False, None))
        self.check("outputs/_archive/foo", ("foo", True, None))
        self.check("outputs/_archive/foo/a.md", ("foo", True, None))
        self.check("control-plane/outputs/foo", ("foo", False, "stale-prefix"))
        self.check("outputs\\foo\\a.md", ("foo", False, None))
        self.check("..\\..\\outputs\\_archive\\foo", ("foo", True, None))

    def test_exclusions(self):
        self.check("outputs/index", (None, False, None))
        self.check("outputs/index.md", (None, False, None))
        self.check("outputs/", (None, False, None))
        self.check("`outputs/`", (None, False, None))
        self.check("outputs/_archive", (None, False, None))
        self.check("outputs/_archive/", (None, False, None))
        self.check("no reference here", (None, False, None))

    def test_not_a_suffix_match(self):
        self.check("myoutputs/foo", (None, False, None))


class TestRecords(unittest.TestCase):
    def setUp(self):
        self.d, self.p = tmp()
        cp = self.p / "control-plane"
        (cp / "intake" / "_archive").mkdir(parents=True)
        (cp / "objectives" / "o" / "milestones").mkdir(parents=True)
        (cp / "gates").mkdir()
        (cp / "workstreams" / "_log").mkdir(parents=True)
        (cp / "assignments").mkdir()
        (cp / "intake" / "a.md").write_text("---\nnote_type: intake\nstatus: triaged\ndepends_on: [o#1, gate:g]\n---\n", encoding="utf-8")
        (cp / "intake" / "_archive" / "b.md").write_text("---\nnote_type: intake\nstatus: consumed\n---\n", encoding="utf-8")
        (cp / "intake" / "index.md").write_text("# idx\n", encoding="utf-8")
        (cp / "objectives" / "o" / "milestones" / "01-x.md").write_text("---\nnote_type: milestone\nid: o#1\nstatus: dropped\nconditional: true\ndepends_on: [o#2]\n---\n", encoding="utf-8")
        (cp / "objectives" / "o" / "milestones" / "02-y.md").write_text("---\nnote_type: milestone\nid: o#2\nstatus: open\ndepends_on: [o#1]\n---\n", encoding="utf-8")
        (cp / "gates" / "g.md").write_text("---\nnote_type: gate\nstatus: open\n---\n", encoding="utf-8")
        (cp / "workstreams" / "_log" / "2026-01-01-done-ws.md").write_text("x", encoding="utf-8")
        (cp / "assignments" / "_log.md").write_text("## 2026-01-02 · done-a\ntext\n", encoding="utf-8")
        (cp / "assignments" / "live-a").mkdir()
        (cp / "assignments" / "live-a" / "index.md").write_text("---\nstatus: active\n---\n", encoding="utf-8")
        self.recs = harnesslib.load_records(self.p)

    def tearDown(self):
        self.d.cleanup()

    def test_load(self):
        self.assertEqual(set(self.recs), {"intake:a", "intake:b", "o#1", "o#2", "gate:g"})
        self.assertTrue(self.recs["intake:b"]["archived"])

    def test_resolve(self):
        self.assertEqual(harnesslib.resolve("o#1", self.recs)["kind"], "milestone")
        self.assertEqual(harnesslib.resolve("workstream:w", self.recs)["kind"], "unit")
        self.assertIsNone(harnesslib.resolve("nope", self.recs))

    def test_cycle(self):
        cyc = harnesslib.find_cycle(records=self.recs)
        self.assertIsNotNone(cyc)
        self.assertEqual(cyc[0], cyc[-1])
        self.assertIn("o#1", cyc)

    def test_no_cycle(self):
        g = {"a": ["b"], "b": ["c"], "c": []}
        self.assertIsNone(harnesslib.find_cycle(graph=g))

    def test_satisfied(self):
        self.assertTrue(harnesslib.satisfied("o#1", self.recs, self.p))   # dropped + conditional
        self.assertFalse(harnesslib.satisfied("o#2", self.recs, self.p))
        self.assertFalse(harnesslib.satisfied("gate:g", self.recs, self.p))
        self.assertTrue(harnesslib.satisfied("intake:b", self.recs, self.p))
        self.assertTrue(harnesslib.satisfied("workstream:done-ws", self.recs, self.p))
        self.assertTrue(harnesslib.satisfied("assignment:done-a", self.recs, self.p))
        self.assertFalse(harnesslib.satisfied("assignment:live-a", self.recs, self.p))

    def test_unit_state(self):
        self.assertEqual(harnesslib.unit_state("assignment:live-a", self.p), "open")
        self.assertEqual(harnesslib.unit_state("assignment:ghost", self.p), "absent")
        self.assertEqual(harnesslib.unit_state("workstream:done-ws", self.p), "closed")


class TestHelpers(unittest.TestCase):
    def test_kebab(self):
        self.assertTrue(harnesslib.kebab_ok("a-b1"))
        self.assertFalse(harnesslib.kebab_ok("A"))
        self.assertFalse(harnesslib.kebab_ok("a--b"))

    def test_today(self):
        self.assertRegex(harnesslib.today(), r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
