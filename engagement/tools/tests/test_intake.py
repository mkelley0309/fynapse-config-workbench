#!/usr/bin/env python3
"""Tests for tools/intake.py (harness-records/1). Temp workspaces only (WORKSPACE_ROOT)."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import harnesslib as H  # noqa: E402
import intake  # noqa: E402

R9_ROW_KEYS = {"id", "kind", "status", "title", "objective", "route", "depends_on", "related", "locks",
               "inputs", "backlog", "path"}
BACKLOG = ("| id | item | status | route |\n|---|---|---|---|\n"
           "| 1 | first | open | |\n| 2 | second | open | |\n| 3 | third | open | |\n")
LOCKS = "| lock | probe | meaning |\n|---|---|---|\n| vault | git-dirty:knowledge/vault | vault busy |\n"


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name).resolve()
        (self.root / "control-plane" / "intake").mkdir(parents=True)
        self._old = os.environ.get("WORKSPACE_ROOT")
        os.environ["WORKSPACE_ROOT"] = str(self.root)
        self._cwd = os.getcwd()
        os.chdir(self.root)          # R2: env and cwd must name the same root

    def tearDown(self):
        os.chdir(self._cwd)
        if self._old is None:
            os.environ.pop("WORKSPACE_ROOT", None)
        else:
            os.environ["WORKSPACE_ROOT"] = self._old
        self._td.cleanup()

    # -- helpers
    def run_(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                intake.main(list(argv))
            except SystemExit as e:
                code = e.code or 0
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv):
        code, out, err = self.run_(*argv)
        self.assertEqual(code, 0, err)
        return out

    def refuses(self, *argv, text=None):
        code, out, err = self.run_(*argv)
        self.assertEqual(code, 1, out + err)
        if text:
            self.assertIn(text, err)
        return err

    def p(self, rel):
        return self.root / rel

    def write(self, rel, text):
        f = self.p(rel)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8", newline="\n")
        return f

    def ipath(self, slug, archived=False):
        return self.p(f"control-plane/intake/{'_archive/' if archived else ''}{slug}.md")

    def fm(self, slug, archived=False):
        return H.fm_read(self.ipath(slug, archived))[0]

    def raw_intake(self, slug, archived=False, **over):
        fm = {"note_type": "intake", "kind": "item", "status": "triaged", "captured": "2026-11-01",
              "source": "s", "objective": "demo", "route": "tools", "depends_on": [], "related": [],
              "locks": [], "inputs": [], "backlog": []}
        fm.update(over)
        lines = ["---"] + [f"{k}: {H.render_value(v)}" for k, v in fm.items() if v is not Ellipsis] + \
                ["---", "", f"# {slug}", ""]
        self.write(f"control-plane/intake/{'_archive/' if archived else ''}{slug}.md", "\n".join(lines))

    def milestone(self, n=1, status="open", **extra):
        fm = {"note_type": "milestone", "id": f"demo#{n}", "title": f"m{n}", "status": status}
        fm.update(extra)
        lines = ["---"] + [f"{k}: {H.render_value(v)}" for k, v in fm.items()] + ["---", "", "x", ""]
        self.write(f"control-plane/objectives/demo/milestones/{n:02d}-m.md", "\n".join(lines))

    def capture(self, slug, **kw):
        self.ok("capture", slug, "--title", "T", "--source", "S")

    def triage(self, slug, *extra):
        return self.ok("triage", slug, "--objective", "demo", "--route", "tools", *extra)

    def check(self, *flags):
        code, out, err = self.run_("check", "--json", *flags)
        env = json.loads(out)
        return code, env, [e["code"] for e in env["errors"]], [w["code"] for w in env["warnings"]]


class TestCapture(Base):
    def test_happy(self):
        self.capture("my-item")
        fm = self.fm("my-item")
        self.assertEqual((fm["note_type"], fm["status"], fm["route"], fm["objective"]),
                         ("intake", "captured", "none", "none"))
        self.assertEqual(fm["source"], "S")

    def test_bad_slug(self):
        self.refuses("capture", "Bad_Slug", "--title", "T", "--source", "S", text="bad slug")

    def test_duplicate_live_and_archived(self):
        self.capture("dup")
        self.refuses("capture", "dup", "--title", "T", "--source", "S", text="already exists")
        self.raw_intake("old", archived=True, status="consumed")
        self.refuses("capture", "old", "--title", "T", "--source", "S", text="already exists")

    def test_bad_route_and_unresolved_milestone(self):
        self.refuses("capture", "x", "--title", "T", "--source", "S", "--route", "bogus", text="bad route")
        self.refuses("capture", "x", "--title", "T", "--source", "S", "--route", "milestone:demo#9",
                     text="unresolved route")
        self.assertFalse(self.ipath("x").exists())

    def test_milestone_route_resolves(self):
        self.milestone(1)
        self.ok("capture", "x", "--title", "T", "--source", "S", "--route", "milestone:demo#1")
        self.assertEqual(self.fm("x")["route"], "milestone:demo#1")


class TestTriage(Base):
    def test_happy_with_all_fields(self):
        self.capture("other")
        self.write("control-plane/locks.md", LOCKS)
        self.write("data/in.md", "x")
        self.write("data/bl.md", BACKLOG)
        self.capture("a")
        self.ok("gate", "add", "g", "--title", "G", "--type", "human", "--who", "me", "--criteria", "c")
        self.triage("a", "--depends-on", "intake:other", "--related", "gate:g", "--locks", "vault",
                    "--inputs", "data/in.md,data/bl.md", "--backlog", "data/bl.md", "--keep-until", "gate:g")
        fm = self.fm("a")
        self.assertEqual(fm["status"], "triaged")
        self.assertEqual(fm["depends_on"], ["intake:other"])
        self.assertEqual(fm["related"], ["gate:g"])
        self.assertEqual(fm["locks"], ["vault"])
        self.assertEqual(fm["inputs"], ["data/in.md", "data/bl.md"])
        self.assertEqual(fm["backlog"], ["data/bl.md"])
        self.assertEqual(fm["keep_until"], "gate:g")
        self.assertEqual(fm["route"], "tools")

    def test_repeatable_flags(self):
        self.capture("o1")
        self.capture("o2")
        self.capture("a")
        self.triage("a", "--depends-on", "intake:o1", "--depends-on", "intake:o2")
        self.assertEqual(self.fm("a")["depends_on"], ["intake:o1", "intake:o2"])

    def test_refusals(self):
        self.capture("a")
        self.refuses("triage", "a", "--objective", "d", "--route", "tools", "--locks", "nope",
                     text="unknown lock")
        self.refuses("triage", "a", "--objective", "d", "--route", "tools", "--depends-on", "intake:ghost",
                     text="unresolved id")
        self.refuses("triage", "a", "--objective", "d", "--route", "tools", "--backlog", "x.md",
                     text="subset")
        self.refuses("triage", "a", "--objective", "d", "--route", "tools", "--inputs", "no/such.md",
                     text="does not exist")
        self.refuses("triage", "a", "--objective", "d", "--route", "bogus", text="bad route")
        self.refuses("triage", "ghost", "--objective", "d", "--route", "tools", text="no live intake")
        self.assertEqual(self.fm("a")["status"], "captured")

    def test_cycle_refused(self):
        self.capture("a")
        self.capture("b")
        self.triage("a", "--depends-on", "intake:b")
        self.refuses("triage", "b", "--objective", "demo", "--route", "tools", "--depends-on", "intake:a",
                     text="cycle")

    def test_terminal_refused(self):
        self.capture("a")
        self.ok("drop", "a", "--reason", "nah")
        self.refuses("triage", "a", "--objective", "d", "--route", "tools", text="cannot triage")


class TestConsumeDrop(Base):
    def test_consume_happy(self):
        self.capture("a")
        self.ok("consume", "a", "--by", "assignment:foo")
        fm = self.fm("a")
        self.assertEqual((fm["status"], fm["consumed_by"]), ("consumed", ["assignment:foo"]))

    def test_consume_needs_unit_id_and_not_terminal(self):
        self.capture("a")
        self.refuses("consume", "a", "--by", "foo", text="unit id")
        self.refuses("consume", "a", "--by", "intake:x", text="unit id")
        self.ok("consume", "a", "--by", "assignment:foo")
        self.refuses("consume", "a", "--by", "assignment:bar", text="already consumed")

    def test_drop_needs_reason(self):
        self.capture("a")
        self.refuses("drop", "a", "--reason", "  ", text="--reason required")
        self.ok("drop", "a", "--reason", "not needed")
        fm = self.fm("a")
        self.assertEqual((fm["status"], fm["dropped_reason"]), ("dropped", "not needed"))
        self.refuses("drop", "a", "--reason", "again", text="already dropped")

    def test_unknown_slug(self):
        self.refuses("drop", "ghost", "--reason", "r", text="no live intake")
        self.refuses("consume", "ghost", "--by", "assignment:x", text="no live intake")


class TestArchive(Base):
    def test_refuses_non_terminal(self):
        self.capture("a")
        self.refuses("archive", "a", text="not consumed/dropped")
        self.assertTrue(self.ipath("a").exists())

    def test_refuses_unknown(self):
        self.refuses("archive", "ghost", text="no live intake")

    def test_refuses_open_consumer_then_allows_after_close(self):
        self.capture("a")
        self.ok("consume", "a", "--by", "assignment:foo")
        self.write("control-plane/assignments/foo/index.md", "---\nstatus: active\n---\n")
        self.refuses("archive", "a", text="consumer still open")
        self.write("control-plane/assignments/foo/index.md", "---\nstatus: complete\n---\n")
        self.ok("archive", "a")
        self.assertTrue(self.ipath("a", True).exists())
        self.assertFalse(self.ipath("a").exists())

    def test_keep_until_unmet_then_met(self):
        self.ok("gate", "add", "g", "--title", "G", "--type", "human", "--who", "me", "--criteria", "c")
        self.capture("a")
        self.triage("a", "--keep-until", "gate:g")
        self.ok("drop", "a", "--reason", "r")
        self.refuses("archive", "a", text="keep_until unmet")
        self.ok("gate", "resolve", "g", "--evidence", "done")
        self.ok("archive", "a")
        self.assertTrue(self.ipath("a", True).exists())

    def test_open_backlog_row_blocks_then_done_allows(self):
        self.write("data/bl.md", BACKLOG)
        self.capture("a")
        self.triage("a", "--inputs", "data/bl.md", "--backlog", "data/bl.md")
        self.ok("drop", "a", "--reason", "r")
        self.refuses("archive", "a", text="open backlog row 1")
        for i in ("1", "2", "3"):
            self.ok("backlog", "data/bl.md", "--done", i)
        self.ok("archive", "a")

    def test_git_tracked_uses_git_mv(self):
        def git(*a):
            return subprocess.run(["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t",
                                   *a], capture_output=True, text=True)
        git("init", "-q")
        self.capture("a")
        self.ok("drop", "a", "--reason", "r")
        git("add", "-A")
        git("commit", "-q", "-m", "x")
        self.ok("archive", "a")
        st = git("status", "--porcelain").stdout
        self.assertTrue(st.startswith("R"), st)   # staged rename = git mv was used
        self.assertTrue(self.ipath("a", True).exists())


class TestSplit(Base):
    def test_happy(self):
        self.capture("p")
        self.triage("p")
        self.ok("split", "p", "--into", "a,b", "--route", "a=assignment:x", "--objective", "b=other")
        a, b = self.fm("p-a"), self.fm("p-b")
        self.assertEqual((a["route"], a["objective"], a["status"]), ("assignment:x", "demo", "triaged"))
        self.assertEqual((b["route"], b["objective"]), ("tools", "other"))
        self.assertEqual(a["captured"], self.fm("p", True)["captured"])
        par = self.fm("p", True)
        self.assertEqual(par["status"], "consumed")
        self.assertEqual(par["consumed_by"], ["intake:p-a", "intake:p-b"])
        self.assertFalse(self.ipath("p").exists())

    def test_captured_parent_children_captured(self):
        self.capture("p")
        self.ok("split", "p", "--into", "a,b")
        self.assertEqual(self.fm("p-a")["status"], "captured")

    def test_refusals(self):
        self.capture("p")
        self.refuses("split", "p", "--into", "a", text="at least two")
        self.refuses("split", "p", "--into", "a,B_", text="bad slug")
        self.refuses("split", "p", "--into", "a,b", "--route", "z=tools", text="unknown slice")
        self.refuses("split", "p", "--into", "a,b", "--route", "a=bogus", text="bad route")
        self.capture("p-a")
        self.refuses("split", "p", "--into", "a,b", text="child exists")
        self.ok("drop", "p", "--reason", "r")
        self.refuses("split", "p", "--into", "c,d", text="terminal")
        self.assertTrue(self.ipath("p").exists())


class TestGate(Base):
    def add(self, slug="g", type_="human"):
        return self.ok("gate", "add", slug, "--title", "G", "--type", type_, "--who", "me", "--criteria", "c")

    def test_add_resolve(self):
        self.add()
        fm = H.fm_read(self.p("control-plane/gates/g.md"))[0]
        self.assertEqual((fm["note_type"], fm["status"], fm["gate_type"], fm["objective"]),
                         ("gate", "open", "human", "none"))
        self.ok("gate", "resolve", "g", "--evidence", "proof")
        fm = H.fm_read(self.p("control-plane/gates/g.md"))[0]
        self.assertEqual((fm["status"], fm["evidence"]), ("done", "proof"))
        self.refuses("gate", "resolve", "g", "--evidence", "again", text="not open")

    def test_add_refusals(self):
        self.refuses("gate", "add", "g", "--title", "G", "--type", "bogus", "--who", "m", "--criteria", "c",
                     text="bad gate type")
        self.add()
        self.refuses("gate", "add", "g", "--title", "G", "--type", "human", "--who", "m", "--criteria", "c",
                     text="gate exists")
        self.refuses("gate", "add", "Bad_X", "--title", "G", "--type", "human", "--who", "m",
                     "--criteria", "c", text="bad slug")

    def test_drop_and_refusals(self):
        self.add()
        self.refuses("gate", "drop", "g", "--reason", " ", text="--reason required")
        self.refuses("gate", "resolve", "g", "--evidence", " ", text="--evidence required")
        self.ok("gate", "drop", "g", "--reason", "moot")
        fm = H.fm_read(self.p("control-plane/gates/g.md"))[0]
        self.assertEqual(fm["status"], "dropped")
        self.refuses("gate", "drop", "g", "--reason", "x", text="not open")
        self.refuses("gate", "resolve", "ghost", "--evidence", "e", text="no gate")


class TestBacklog(Base):
    def setUp(self):
        super().setUp()
        self.write("outputs/prod/backlog.md", BACKLOG)
        self.bl = "outputs/prod/backlog.md"

    def rows(self):
        return {r["id"]: r for r in H.backlog_parse(self.p(self.bl))["rows"]}

    def test_counts(self):
        self.assertEqual(self.ok("backlog", self.bl).strip(), "open=3 done=0 dropped=0 moved=0")

    def test_done(self):
        out = self.ok("backlog", self.bl, "--done", "2")
        self.assertIn("open=2 done=1", out)
        self.assertEqual(self.rows()["2"]["status"], "done")
        self.assertEqual(self.rows()["1"]["status"], "open")
        self.refuses("backlog", self.bl, "--done", "2", text="not open")
        self.refuses("backlog", self.bl, "--done", "9", text="no row")

    def test_drop_needs_reason_and_adds_note(self):
        self.refuses("backlog", self.bl, "--drop", "1", text="--reason")
        self.ok("backlog", self.bl, "--drop", "1", "--reason", "stale")
        r = self.rows()["1"]
        self.assertEqual((r["status"], r["note"]), ("dropped", "stale"))
        self.assertIn("note", H.backlog_parse(self.p(self.bl))["header"])

    def test_move_unit_target_writes_handover_keeps_id_sets_route(self):
        self.ok("backlog", self.bl, "--move", "2", "--to", "assignment:foo")
        r = self.rows()
        self.assertEqual(set(r), {"1", "2", "3"})                    # row ID unchanged
        self.assertEqual(r["2"]["status"], "moved")
        self.assertEqual(r["2"]["route"], "assignment:foo")          # route recorded on the moved row
        self.assertEqual((r["1"]["route"], r["1"]["status"]), ("", "open"))
        ho = self.fm("prod-handover-1")
        self.assertEqual((ho["kind"], ho["status"], ho["route"], ho["inputs"]),
                         ("handover", "triaged", "assignment:foo", [self.bl]))

    def test_move_to_milestone_appends_inputs(self):
        self.milestone(1)
        self.ok("backlog", self.bl, "--move", "1", "--to", "milestone:demo#1")
        fm = H.fm_read(self.p("control-plane/objectives/demo/milestones/01-m.md"))[0]
        self.assertEqual(fm["inputs"], [self.bl])
        self.assertFalse(self.ipath("prod-handover-1").exists())
        self.assertEqual(self.rows()["1"]["route"], "milestone:demo#1")

    def test_move_refusals(self):
        self.refuses("backlog", self.bl, "--move", "1", text="--to")
        self.refuses("backlog", self.bl, "--move", "1", "--to", "bogus", text="bad --to")
        self.refuses("backlog", self.bl, "--move", "1", "--to", "none", text="bad --to")
        self.refuses("backlog", self.bl, "--move", "1", "--to", "milestone:demo#9", text="unresolved")
        self.refuses("backlog", self.bl, "--move", "9", "--to", "assignment:x", text="no row")
        self.ok("backlog", self.bl, "--move", "1", "--to", "assignment:x")
        self.refuses("backlog", self.bl, "--move", "1", "--to", "assignment:y", text="not open")

    def test_missing_file(self):
        self.refuses("backlog", "nope.md", text="no such file")

    def test_json_envelope(self):
        env = json.loads(self.ok("backlog", self.bl, "--json"))
        self.assertEqual(env["schema"], "harness-records/1")
        self.assertEqual(env["kind"], "backlog")
        self.assertIn("generated", env)
        self.assertEqual(env["path"], self.bl)
        self.assertEqual(env["counts"], {"open": 3, "done": 0, "dropped": 0, "moved": 0})
        self.assertEqual(set(env["rows"][0]), {"id", "item", "status", "route"})


class TestList(Base):
    def setUp(self):
        super().setUp()
        self.raw_intake("a", objective="demo", status="triaged")
        self.raw_intake("b", objective="other", status="captured")
        self.milestone(1)
        self.ok("gate", "add", "g", "--title", "G", "--type", "human", "--who", "m", "--criteria", "c")

    def ids(self, *flags):
        return [r["id"] for r in json.loads(self.ok("list", "--json", *flags))["records"]]

    def test_filters(self):
        self.assertEqual(self.ids(), ["demo#1", "gate:g", "intake:a", "intake:b"])
        self.assertEqual(self.ids("--kind", "intake"), ["intake:a", "intake:b"])
        self.assertEqual(self.ids("--status", "captured"), ["intake:b"])
        self.assertEqual(self.ids("--objective", "demo"), ["demo#1", "intake:a"])
        self.assertEqual(self.ids("--objective", "demo", "--kind", "intake", "--status", "triaged"),
                         ["intake:a"])

    def test_r9_envelope(self):
        env = json.loads(self.ok("list", "--json"))
        self.assertEqual((env["schema"], env["kind"]), ("harness-records/1", "list"))
        self.assertIn("generated", env)
        for row in env["records"]:
            self.assertEqual(set(row), R9_ROW_KEYS)
        ms = next(r for r in env["records"] if r["id"] == "demo#1")
        self.assertEqual(ms["objective"], "demo")
        self.assertEqual(ms["path"], "control-plane/objectives/demo/milestones/01-m.md")

    def test_text_output(self):
        out = self.ok("list", "--kind", "intake")
        self.assertIn("intake:a · triaged · tools", out)


class TestCheck(Base):
    def codes(self, *flags):
        return self.check(*flags)[2]

    def test_clean(self):
        self.raw_intake("a")
        code, out, _ = self.run_("check")
        self.assertEqual((code, out.strip()), (0, "ok"))
        code, env, errs, warns = self.check()
        self.assertEqual((code, errs, warns), (0, [], []))
        self.assertEqual((env["schema"], env["kind"]), ("harness-records/1", "check"))
        self.assertIn("generated", env)

    def test_missing_key(self):
        self.raw_intake("a", source=Ellipsis)
        self.assertIn("missing-key", self.codes())

    def test_bad_status(self):
        self.raw_intake("a", status="weird")
        self.assertIn("bad-status", self.codes())

    def test_bad_route(self):
        self.raw_intake("a", route="nonsense")
        self.assertIn("bad-route", self.codes())

    def test_unresolved_route_milestone(self):
        self.raw_intake("a", route="milestone:demo#9")
        self.assertIn("unresolved-id", self.codes())

    def test_unresolved_id(self):
        self.raw_intake("a", depends_on=["intake:ghost"])
        self.assertIn("unresolved-id", self.codes())

    def test_dropped_dependency(self):
        self.raw_intake("a", status="dropped", dropped_reason="r")
        self.raw_intake("b", depends_on=["intake:a"])
        self.assertIn("dropped-dependency", self.codes())

    def test_unknown_lock(self):
        self.raw_intake("a", locks=["nope"])
        self.assertIn("unknown-lock", self.codes())

    def test_unknown_probe(self):
        self.write("control-plane/locks.md", "| lock | probe | meaning |\n|---|---|---|\n| x | weird:y | m |\n")
        self.assertIn("unknown-probe", self.codes())

    def test_missing_input(self):
        self.raw_intake("a", inputs=["no/such.md"])
        self.assertIn("missing-input", self.codes())

    def test_missing_input_archived_ok(self):
        self.raw_intake("a", archived=True, status="consumed", inputs=["no/such.md"])
        self.assertNotIn("missing-input", self.codes())

    def test_backlog_not_in_inputs(self):
        self.write("data/bl.md", BACKLOG)
        self.raw_intake("a", backlog=["data/bl.md"], inputs=[])
        self.assertIn("backlog-not-in-inputs", self.codes())

    def test_open_backlog(self):
        self.write("data/bl.md", BACKLOG)
        self.raw_intake("a", status="consumed", inputs=["data/bl.md"], backlog=["data/bl.md"])
        self.assertIn("open-backlog", self.codes())

    def test_archived_nonterminal(self):
        self.raw_intake("a", archived=True, status="triaged")
        self.assertIn("archived-nonterminal", self.codes())

    def test_dropped_no_reason(self):
        self.raw_intake("a", status="dropped")
        self.assertIn("dropped-no-reason", self.codes())

    def test_cycle(self):
        self.raw_intake("a", depends_on=["intake:b"])
        self.raw_intake("b", depends_on=["intake:a"])
        code, env, errs, _ = self.check()
        self.assertEqual(code, 1)
        self.assertIn("cycle", errs)

    def test_bad_gate_type(self):
        self.write("control-plane/gates/g.md",
                   "---\nnote_type: gate\ntitle: G\ngate_type: weird\nwho: m\ncriteria: c\nstatus: open\n---\n")
        self.assertIn("bad-gate-type", self.codes())

    def test_error_exit_and_error_shape(self):
        self.raw_intake("a", status="weird")
        code, env, _, _ = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(set(env["errors"][0]), {"code", "id", "path", "message"})
        code, out, _ = self.run_("check")
        self.assertEqual(code, 1)
        self.assertIn("ERROR bad-status intake:a", out)

    def test_warnings_unknown_key_and_live_terminal(self):
        self.raw_intake("a", foo="1")
        self.raw_intake("b", status="consumed")
        code, env, errs, warns = self.check()
        self.assertEqual((code, errs), (0, []))
        self.assertEqual(sorted(warns), ["live-terminal", "unknown-key"])

    def test_strict_promotes_warnings(self):
        self.raw_intake("b", status="consumed")
        self.assertEqual(self.run_("check")[0], 0)
        code, env, errs, warns = self.check("--strict")
        self.assertEqual(code, 1)
        self.assertEqual((errs, warns), (["live-terminal"], []))
        code, out, _ = self.run_("check", "--strict")
        self.assertEqual(code, 1)
        self.assertIn("ERROR live-terminal", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
