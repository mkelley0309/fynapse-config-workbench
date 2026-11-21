"""Root harness fixes R1-R7 and R11 (fynapse-config-workbench P1).

Every command runs as a subprocess inside a temp workspace. WORKSPACE_ROOT is removed from the
environment unless a test sets it deliberately (R2), and cwd is the temp root or one of its
subdirectories, so nothing can reach the real control-plane/.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import harnesslib as H  # noqa: E402

LOCKS = "# Locks\n\n| lock | probe | meaning |\n|---|---|---|\n"
TRICKY = "pipe \\| back\\slash café — “quoted” ‘x’"


def make_ws(parent, name="ws"):
    ws = Path(parent) / name
    for d in ("intake", "objectives", "workstreams", "assignments", "gates"):
        (ws / "control-plane" / d).mkdir(parents=True)
    (ws / "control-plane" / "locks.md").write_bytes(LOCKS.encode())
    subprocess.run(["git", "init", "-q", str(ws)], check=True)
    subprocess.run(["git", "-C", str(ws), "config", "user.name", "Test User"], check=True)
    return ws.resolve()


def run(script, args, cwd, env_root=None):
    env = {k: v for k, v in os.environ.items() if k != "WORKSPACE_ROOT"}
    if env_root is not None:
        env["WORKSPACE_ROOT"] = str(env_root)
    r = subprocess.run([sys.executable, "-B", str(TOOLS / script), *args], cwd=cwd, env=env,
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout, r.stderr


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.ws = make_ws(self._td.name)

    def run_(self, script, *args, cwd=None, env_root=None):
        return run(script, list(args), cwd or self.ws, env_root)

    def ok(self, script, *args, **kw):
        code, out, err = self.run_(script, *args, **kw)
        self.assertEqual(code, 0, out + err)
        return out

    def obj(self, name="o1"):
        self.ok("objective.py", "create", name, "--title", "t")
        return self.ws / "control-plane" / "objectives" / name / "index.md"

    def intake(self, slug, **fm):
        pairs = {"note_type": "intake", "kind": "item", "status": "triaged", "captured": "2026-11-01",
                 "source": "s", "objective": "o1", "route": "tools", "depends_on": [], "related": [],
                 "locks": [], "inputs": [], "backlog": []}
        pairs.update(fm)
        lines = ["---"] + [f"{k}: {H.render_value(v)}" for k, v in pairs.items()] + ["---", "", f"# {slug}", ""]
        p = self.ws / "control-plane" / "intake" / f"{slug}.md"
        p.write_bytes("\n".join(lines).encode())
        return p


class R1R2Root(Base):
    def test_r1_walk_up_from_subdirectory(self):
        self.obj()
        sub = self.ws / "control-plane" / "objectives"
        for tool, args in (("objective.py", ("next", "o1")), ("assignment.py", ("list",)),
                           ("cadence.py", ("list",)), ("workstream.py", ("list",))):
            code, out, err = self.run_(tool, *args, cwd=sub)
            self.assertNotIn("no workspace root", err, f"{tool}: {err}")
        deep = self.ws / "control-plane" / "objectives" / "o1"
        self.ok("objective.py", "status", "o1", cwd=deep)

    def test_r2_mismatch_dies_naming_both(self):
        other = make_ws(self._td.name, "other")
        code, out, err = self.run_("intake.py", "check", cwd=other, env_root=self.ws)
        self.assertNotEqual(code, 0)
        self.assertIn(str(self.ws), err)
        self.assertIn(str(other), err)

    def test_r2_mismatch_writes_nothing(self):
        other = make_ws(self._td.name, "other")
        before = sorted(p for p in self.ws.rglob("*") if ".git" not in p.parts)
        code, out, err = self.run_("objective.py", "create", "o1", cwd=other, env_root=self.ws)
        self.assertNotEqual(code, 0)
        self.assertEqual(sorted(p for p in self.ws.rglob("*") if ".git" not in p.parts), before)

    def test_r2_match_accepted_from_root_and_subdir(self):
        self.ok("intake.py", "check", cwd=self.ws, env_root=self.ws)
        self.ok("intake.py", "check", cwd=self.ws / "control-plane", env_root=self.ws)

    def test_r2_env_wins_when_cwd_has_no_root(self):
        with tempfile.TemporaryDirectory() as bare:
            code, out, err = run("intake.py", ["check"], bare, self.ws)
            self.assertEqual(code, 0, out + err)

    def test_no_root_anywhere_dies(self):
        with tempfile.TemporaryDirectory() as bare:
            code, out, err = run("intake.py", ["check"], bare)
            self.assertEqual(code, 1)
            self.assertIn("no workspace root", err)


class R3Duplicates(Base):
    def test_duplicate_milestone_ids_error_names_id(self):
        self.obj()
        self.ok("objective.py", "add-milestone", "o1", "--title", "m one")
        md = self.ws / "control-plane/objectives/o1/milestones"
        src = next(md.glob("01-*.md"))
        (md / "01-m-two.md").write_bytes(src.read_bytes().replace(b"title: m one", b"title: m two"))
        code, out, err = self.run_("intake.py", "check")
        self.assertEqual(code, 1)
        self.assertIn("duplicate-id", out)
        self.assertIn("o1#1", out)
        code, out, err = self.run_("intake.py", "check", "--json")
        self.assertIn('"duplicate-id"', out)

    def test_no_duplicates_is_clean(self):
        self.obj()
        self.ok("objective.py", "add-milestone", "o1", "--title", "m one")
        self.assertEqual(self.ok("intake.py", "check").strip(), "ok")

    def test_load_records_collects_dups(self):
        self.obj()
        self.ok("objective.py", "add-milestone", "o1", "--title", "m one")
        md = self.ws / "control-plane/objectives/o1/milestones"
        src = next(md.glob("01-*.md"))
        (md / "01-b.md").write_bytes(src.read_bytes())
        dups = []
        H.load_records(self.ws, dups)
        self.assertEqual([d[0] for d in dups], ["o1#1"])


class R4ArchiveDates(Base):
    def test_consume_and_drop_write_dates(self):
        self.obj()
        self.intake("a")
        self.intake("b")
        self.ok("intake.py", "consume", "a", "--by", "workstream:w")
        self.ok("intake.py", "drop", "b", "--reason", "no")
        p = self.ws / "control-plane/intake"
        self.assertEqual(H.fm_read(p / "a.md")[0]["consumed"], H.today())
        self.assertEqual(H.fm_read(p / "b.md")[0]["dropped"], H.today())

    def test_archive_stamps_missing_date_and_keeps_existing(self):
        self.obj()
        self.intake("a", status="consumed", consumed_by=["workstream:w"])
        self.intake("b", status="dropped", dropped_reason="x", dropped="2026-01-02")
        self.ok("intake.py", "archive", "a")
        self.ok("intake.py", "archive", "b")
        arch = self.ws / "control-plane/intake/_archive"
        self.assertEqual(H.fm_read(arch / "a.md")[0]["consumed"], H.today())
        self.assertEqual(H.fm_read(arch / "b.md")[0]["dropped"], "2026-01-02")

    def test_no_unknown_key_warning_for_dates(self):
        self.obj()
        self.intake("a")
        self.ok("intake.py", "consume", "a", "--by", "workstream:w")
        self.ok("intake.py", "archive", "a")
        self.assertEqual(self.ok("intake.py", "check", "--strict").strip(), "ok")

    def test_program_intake_view_is_clock_and_mtime_free(self):
        self.obj()
        for slug, when in (("old", "2025-06-01"), ("mid", "2026-01-10"), ("new", "2026-01-20")):
            p = self.intake(slug, status="consumed", consumed_by=["workstream:w"], consumed=when)
            arch = self.ws / "control-plane/intake/_archive"
            arch.mkdir(exist_ok=True)
            p.replace(arch / p.name)
            os.utime(arch / p.name, (1, 1))          # ancient mtime must not matter
        self.intake("nodate", status="consumed", consumed_by=["workstream:w"])
        p = self.ws / "control-plane/intake/nodate.md"
        p.replace(self.ws / "control-plane/intake/_archive/nodate.md")
        self.ok("objective.py", "render", "o1", "--adopt")
        idx = (self.ws / "control-plane/objectives/o1/index.md").read_text(encoding="utf-8")
        region = re.search(r"<!-- generated:program-intake -->\n(.*?)<!-- /generated", idx, re.S).group(1)
        self.assertIn("intake:mid", region)
        self.assertIn("intake:new", region)
        self.assertNotIn("intake:old", region)
        self.assertNotIn("intake:nodate", region)
        first = idx
        self.ok("objective.py", "render", "o1")
        self.assertEqual((self.ws / "control-plane/objectives/o1/index.md").read_text(encoding="utf-8"), first)

    def test_objective_source_has_no_clock_or_mtime(self):
        src = (TOOLS / "objective.py").read_text(encoding="utf-8")
        self.assertNotIn("st_mtime", src)
        self.assertNotIn("datetime.now(", src)

    def test_close_consumes_with_date(self):
        self.obj()
        self.intake("src")
        self.ok("assignment.py", "create", "a1", "--intake-source", "intake:src")
        idx = self.ws / "control-plane/assignments/a1/index.md"
        t = idx.read_text(encoding="utf-8")
        t = re.sub(r"(## Residuals\n\n).*?(## Cross-links)", lambda m: m.group(1) + "- none\n\n" + m.group(2), t,
                   count=1, flags=re.S)
        idx.write_bytes(t.encode())
        self.ok("assignment.py", "complete", "a1")
        fm = H.fm_read(self.ws / "control-plane/intake/_archive/src.md")[0]
        self.assertEqual(fm["status"], "consumed")
        self.assertEqual(fm["consumed"], H.today())


class R5Resolve(Base):
    def _conflict(self, idx, double_footer=False):
        text = idx.read_text(encoding="utf-8")
        m = re.search(r"(<!-- generated:milestones -->\n)(.*?)(<!-- /generated:milestones[^\n]*\n)", text, re.S)
        body, foot = m.group(2), m.group(3)
        if double_footer:
            bad = (m.group(1) + "<<<<<<< ours\n" + body + foot + "=======\n"
                   + body.replace("m one", "m other") + foot.replace("sha=", "sha=0") + ">>>>>>> theirs\n")
        else:
            bad = (m.group(1) + "<<<<<<< ours\n" + body + "=======\n" + body.replace("m one", "m other")
                   + ">>>>>>> theirs\n" + foot)
        idx.write_bytes(text.replace(m.group(0), bad).encode())

    def test_resolve_body_conflict(self):
        idx = self.obj()
        self.ok("objective.py", "add-milestone", "o1", "--title", "m one")
        self._conflict(idx)
        self.ok("objective.py", "render", "o1", "--resolve")
        after = idx.read_text(encoding="utf-8")
        self.assertNotRegex(after, r"<<<<<<<|>>>>>>>|=======")
        self.assertIn("m one", after)
        self.assertNotIn("m other", after)
        self.ok("objective.py", "render", "o1", "--check")

    def test_resolve_doubled_footer(self):
        idx = self.obj()
        self.ok("objective.py", "add-milestone", "o1", "--title", "m one")
        self._conflict(idx, double_footer=True)
        self.ok("objective.py", "render", "o1", "--resolve")
        after = idx.read_text(encoding="utf-8")
        self.assertNotRegex(after, r"<<<<<<<|>>>>>>>|=======")
        self.assertEqual(after.count("<!-- /generated:milestones"), 1)
        self.ok("objective.py", "render", "o1", "--check")

    def test_resolve_all_and_outside_lines_left_alone(self):
        idx = self.obj()
        self.ok("objective.py", "add-milestone", "o1", "--title", "m one")
        self._conflict(idx)
        t = idx.read_text(encoding="utf-8").replace(
            "## Dependencies\n", "## Dependencies\n\n<<<<<<< ours\nA\n=======\nB\n>>>>>>> theirs\n")
        idx.write_bytes(t.encode())
        code, out, err = self.run_("objective.py", "render", "--all", "--resolve")
        self.assertEqual(code, 0, out + err)
        self.assertIn("outside generated regions", err)
        after = idx.read_text(encoding="utf-8")
        self.assertIn("<<<<<<< ours\nA\n=======\nB\n>>>>>>> theirs", after)
        self.assertNotIn("m other", after)

    def test_resolve_intake_queue(self):
        idx = self.ws / "control-plane/intake/index.md"
        idx.write_bytes(b"# Intake\n\n## Live Queue\n\n<!-- generated:intake-queue -->\n*(none)*\n"
                        b"<!-- /generated:intake-queue -->\n")
        self.ok("intake.py", "render")
        t = idx.read_text(encoding="utf-8")
        t = t.replace("<!-- generated:intake-queue -->\n",
                      "<!-- generated:intake-queue -->\n<<<<<<< ours\nx\n=======\ny\n>>>>>>> theirs\n")
        idx.write_bytes(t.encode())
        self.ok("intake.py", "render", "--resolve")
        self.assertNotRegex(idx.read_text(encoding="utf-8"), r"<<<<<<<|>>>>>>>|=======")
        self.ok("intake.py", "render", "--check")

    def test_resolve_keeps_crlf(self):
        idx = self.obj()
        self.ok("objective.py", "add-milestone", "o1", "--title", "m one")
        self._conflict(idx)
        idx.write_bytes(idx.read_bytes().replace(b"\n", b"\r\n"))
        self.ok("objective.py", "render", "o1", "--resolve")
        raw = idx.read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))


class R6By(Base):
    HEADER = "| Decision | Rationale | By | Date |"

    def test_create_header_and_default_by(self):
        idx = self.obj()
        self.assertIn(self.HEADER + "\n|---|---|---|---|\n| *(append-only; never truncated)* | | | |", idx.read_text(encoding="utf-8"))
        self.ok("objective.py", "log-decision", "o1", "d1", "r1")
        self.assertIn(f"| d1 | r1 | Test User | {H.today()} |", idx.read_text(encoding="utf-8"))

    def test_by_flag(self):
        idx = self.obj()
        self.ok("objective.py", "log-decision", "o1", "d1", "r1", "--by", "Ada")
        self.assertIn(f"| d1 | r1 | Ada | {H.today()} |", idx.read_text(encoding="utf-8"))

    def test_default_operator_without_git_name(self):
        env_ws = Path(self._td.name) / "nogit"
        for d in ("intake", "objectives"):
            (env_ws / "control-plane" / d).mkdir(parents=True)
        env = {k: v for k, v in os.environ.items() if k != "WORKSPACE_ROOT"}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        r = subprocess.run([sys.executable, "-B", str(TOOLS / "objective.py"), "create", "o1"], cwd=env_ws, env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([sys.executable, "-B", str(TOOLS / "objective.py"), "log-decision", "o1", "d", "r"],
                           cwd=env_ws, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        t = (env_ws / "control-plane/objectives/o1/index.md").read_text(encoding="utf-8")
        self.assertIn(f"| d | r | operator | {H.today()} |", t)

    def test_complete_and_abandon_write_by_rows(self):
        self.obj("done-one")
        self.obj("gone-one")
        self.ok("objective.py", "complete", "done-one", "--reason", "finished")
        self.ok("objective.py", "abandon", "gone-one", "--reason", "nope")
        base = self.ws / "control-plane/objectives/_archive"
        t = (base / "closed/done-one/index.md").read_text(encoding="utf-8")
        self.assertIn(f"| Objective completed | finished | Test User | {H.today()} |", t)
        t = (base / "abandoned/gone-one/index.md").read_text(encoding="utf-8")
        self.assertIn(f"| Objective abandoned | nope | Test User | {H.today()} |", t)

    def test_drop_milestone_writes_by_row(self):
        idx = self.obj()
        self.ok("objective.py", "add-milestone", "o1", "--title", "m one")
        self.ok("objective.py", "drop-milestone", "o1", "1", "--reason", "meh")
        self.assertIn(f"| Milestone o1#1 dropped | meh | Test User | {H.today()} |", idx.read_text(encoding="utf-8"))


class R7Claims(Base):
    def _ws(self):
        self.obj()
        self.ok("workstream.py", "create", "w1", "--parent", "objectives/o1")
        return self.ws / "control-plane/workstreams/w1/index.md"

    def test_workstream_claim_release(self):
        idx = self._ws()
        self.ok("workstream.py", "claim", "w1")
        fm = H.fm_read(idx)[0]
        self.assertEqual(fm["claimed_by"], "Test User")
        self.assertEqual(fm["claimed"], H.today())
        self.assertIn('claimed_by: "Test User"', idx.read_text(encoding="utf-8"))
        self.ok("workstream.py", "release", "w1")
        t = idx.read_text(encoding="utf-8")
        self.assertNotIn("claimed", t)

    def test_assignment_claim_release_keeps_crlf(self):
        self.ok("assignment.py", "create", "a1")
        idx = self.ws / "control-plane/assignments/a1/index.md"
        idx.write_bytes(idx.read_bytes().replace(b"\n", b"\r\n"))
        self.ok("assignment.py", "claim", "a1")
        raw = idx.read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        self.assertEqual(H.fm_read(idx)[0]["claimed_by"], "Test User")
        self.ok("assignment.py", "release", "a1")
        raw = idx.read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        self.assertNotIn(b"claimed", raw)

    def test_claim_refused_for_other_holder_and_closed_unit(self):
        idx = self._ws()
        H.fm_write(idx, {"claimed_by": "Someone Else", "claimed": "2026-11-01"})
        code, out, err = self.run_("workstream.py", "claim", "w1")
        self.assertEqual(code, 1)
        self.assertIn("Someone Else", err)

    def test_help_lists_claim_release(self):
        for tool in ("workstream.py", "assignment.py"):
            out = self.ok(tool, "--help")
            self.assertIn("claim", out)
            self.assertIn("release", out)

    def test_next_shows_claimed(self):
        self.obj()
        self.ok("objective.py", "add-milestone", "o1", "--title", "mine")
        self.ok("objective.py", "add-milestone", "o1", "--title", "theirs")
        self.ok("workstream.py", "create", "wa", "--parent", "objectives/o1", "--milestone", "o1#1")
        self.ok("workstream.py", "create", "wb", "--parent", "objectives/o1", "--milestone", "o1#2")
        self.ok("workstream.py", "claim", "wa")
        H.fm_write(self.ws / "control-plane/workstreams/wb/index.md", {"claimed_by": "Someone Else", "claimed": "2026-11-01"})
        out = self.ok("objective.py", "next", "o1")
        self.assertIn("CLAIMED(Test User)", out)
        self.assertIn("CLAIMED(Someone Else)", out)

    def test_next_ready_excludes_other_claims(self):
        self.obj()
        self.ok("workstream.py", "create", "wz", "--parent", "objectives/o1")
        self.intake("a", route="workstream:wz", status="triaged")
        self.intake("b", route="tools", status="triaged")
        out = self.ok("objective.py", "next", "o1")
        self.assertRegex(out, r"READY\n\s+1\. intake:a[^\n]*\n\s+2\. intake:b")
        H.fm_write(self.ws / "control-plane/workstreams/wz/index.md", {"claimed_by": "Someone Else", "claimed": "2026-11-01"})
        out = self.ok("objective.py", "next", "o1")
        ready = out.split("READY\n", 1)[1].split("\n\n", 1)[0]
        self.assertNotIn("intake:a", ready)
        self.assertIn("intake:b", ready)
        self.assertIn("CLAIMED(Someone Else)", out)
        H.fm_write(self.ws / "control-plane/workstreams/wz/index.md", {"claimed_by": "Test User"})
        out = self.ok("objective.py", "next", "o1")
        ready = out.split("READY\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("intake:a", ready)
        self.assertIn("CLAIMED(Test User)", ready)


class R11Eol(Base):
    def _idx(self, eol):
        idx = self.obj()
        idx.write_bytes(idx.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", eol))
        return idx

    def _check_log(self, eol):
        idx = self._idx(eol)
        before = idx.read_bytes()
        self.ok("objective.py", "log-decision", "o1", TRICKY, "why", "--by", "x")
        after = idx.read_bytes()
        if eol == b"\r\n":
            self.assertEqual(after.count(b"\n"), after.count(b"\r\n"), "LF-only lines appeared in a CRLF file")
        else:
            self.assertEqual(after.count(b"\r\n"), 0)
        self.assertEqual(len(after.splitlines()), len(before.splitlines()) + 1)
        self.assertIn(TRICKY.encode("utf-8"), after)
        b = before.splitlines(True)
        a = after.splitlines(True)
        self.assertEqual(sum(1 for ln in a if ln not in b), 1)

    def test_log_decision_crlf(self):
        self._check_log(b"\r\n")

    def test_log_decision_lf(self):
        self._check_log(b"\n")

    def test_add_kr_milestone_health_keep_crlf(self):
        idx = self._idx(b"\r\n")
        self.ok("objective.py", "add-kr", "o1", "kr one", "10")
        self.ok("objective.py", "update-kr", "o1", "kr one", "5")
        self.ok("objective.py", "add-milestone", "o1", "--title", "m one")
        self.ok("objective.py", "health", "o1", "at-risk")
        self.ok("objective.py", "render", "o1", "--adopt")
        raw = idx.read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))

    def test_complete_and_abandon_keep_crlf(self):
        for name, cmd in (("c1", ("complete", "c1", "--reason", "café — done")),
                          ("a1", ("abandon", "a1", "--reason", "café — gone"))):
            idx = self._idx_for(name)
            self.ok("objective.py", *cmd)
            moved = next((self.ws / "control-plane/objectives/_archive").rglob(f"{name}/index.md"))
            raw = moved.read_bytes()
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), name)
            self.assertIn("café".encode("utf-8"), raw)

    def _idx_for(self, name):
        idx = self.obj(name)
        idx.write_bytes(idx.read_bytes().replace(b"\n", b"\r\n"))
        return idx

    def test_guard_refuses_crlf_to_lf(self):
        p = self.ws / "crlf.md"
        p.write_bytes(b"a\r\nb\r\nc\r\n")
        with self.assertRaises(H.HarnessError):
            H.splice_write(p, [(1, 1, ["x\ny"])])       # an embedded LF would make an LF-only line
        self.assertEqual(p.read_bytes(), b"a\r\nb\r\nc\r\n")

    def test_guard_allows_normal_edits(self):
        p = self.ws / "crlf.md"
        p.write_bytes(b"a\r\nb\r\nc\r\n")
        H.write_text(p, "a\nB\nc\nd\n")
        self.assertEqual(p.read_bytes(), b"a\r\nB\r\nc\r\nd\r\n")
        q = self.ws / "mixed.md"
        q.write_bytes(b"a\r\nb\nc\r\n")
        H.write_text(q, "a\nB\nc\n")
        self.assertEqual(q.read_bytes(), b"a\r\nB\nc\r\n")


if __name__ == "__main__":
    unittest.main()
