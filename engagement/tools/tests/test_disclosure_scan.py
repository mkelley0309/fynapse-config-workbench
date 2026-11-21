#!/usr/bin/env python3
"""Tests for disclosure_scan.py with obviously fake terms. Stdlib only."""

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("disclosure_scan", HERE / "disclosure-scan" / "disclosure_scan.py")
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)

BASE = {
    "schema": "disclosure-terms/1",
    "_note": "ignored",
    "internal_domains": [{"id": "dom-01", "domain": "corp.example.invalid"}],
    "host_patterns": [{"id": "hp-01", "regex": r"\bbuild-\d+\.example\b"}],
    "email_domains": [{"id": "ed-01", "domain": "example.invalid"}],
    "identities": [{"id": "id-01", "names": ["Jane Q Doe"], "local_parts": ["jane.doe"],
                    "usernames": ["jane.doe"]}],
    "citation_domains": ["example.invalid"],
    "customers": [
        {"id": "cust-01", "name": "Acme Mutual", "variants": ["AcmeMutual", "Acme Mut."], "public_citation": None},
        {"id": "cust-02", "name": "Cited Corp", "variants": [], "public_citation": "https://example.invalid/c"},
        {"id": "cust-03", "name": "Phase 0", "variants": [], "public_citation": None},
    ],
    "partners": [{"id": "ptr-01", "name": "Acme Mutual Partners LLP", "variants": []}],
    "client_paths": [{"id": "cp-01", "root": "knowledge/sources/example-intel/held-docs/",
                      "reference_terms": ["example-intel/held-docs", "held-docs"]}],
    "private_terms": [{"id": "pt-01", "term": "outputs/", "kind": "literal"},
                      {"id": "pt-02", "term": r"SECRET-\d{3}", "kind": "regex"}],
    "exclude_globs": [".git/**", "**/node_modules/**"],
}


def git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false",
                    *args], cwd=repo, check=True, capture_output=True)


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.scan_dir = self.tmp / "tree"
        self.scan_dir.mkdir()
        self.terms = self.tmp / "terms.json"
        self.waivers = self.tmp / "waivers.json"
        self.write_terms({})
        self.write_waivers([])

    def write_terms(self, over):
        d = dict(BASE)
        d.update(over)
        self.terms.write_text(json.dumps(d), encoding="utf-8")

    def write_waivers(self, ws):
        self.waivers.write_text(json.dumps({"schema": "disclosure-waivers/1", "waivers": ws}), encoding="utf-8")

    def put(self, rel, text, root=None):
        p = (root or self.scan_dir) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
        return p

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = ds.main([*args])
        return rc, out.getvalue(), err.getvalue()

    def tree(self, *extra, paths=None):
        rc, out, err = self.run_main("tree", *(paths or [str(self.scan_dir)]), "--terms", str(self.terms),
                                     "--waivers", str(self.waivers), "--json", *extra)
        return rc, (json.loads(out) if out.strip() else None), err

    def hits(self, text, name="a.txt"):
        self.put(name, text)
        rc, rep, _ = self.tree()
        return {(f["category"], f["term_id"]) for f in rep["findings"] if f["line"] > 0}

    def one(self, text, cat, tid=None):
        h = self.hits(text)
        return any(c == cat and (tid is None or t == tid) for c, t in h)


class TestCompiler(unittest.TestCase):
    def rx(self, t):
        return re.compile(ds.term_regex(t), re.I)

    def test_phase_zero_regression(self):
        r = self.rx("Phase 0")
        for s in ["Phase 0", "Phase-0", "phase_0", "Phase0", "PHASE.0", "phase - 0"]:
            self.assertTrue(r.search(s), s)
        for s in ["Phase 01", "xPhase0", "Phase 1"]:
            self.assertFalse(r.search(s), s)

    def test_separator_variants_and_case(self):
        r = self.rx("jane.doe")
        for s in ["jane.doe", "Jane Doe", "JANE_DOE", "jane-doe", "janedoe"]:
            self.assertTrue(r.search(s), s)

    def test_camel_and_boundaries(self):
        r = self.rx("AcmeMutual")
        self.assertTrue(r.search("acme mutual"))
        self.assertTrue(r.search("(Acme-Mutual)"))
        self.assertFalse(r.search("Acme Mutually"))
        self.assertFalse(r.search("xAcmeMutual"))


class TestEmail(Base):
    def test_at_variants(self):
        for s in ["bob@example.invalid", "bob[at]example.invalid", "bob(at)example.invalid",
                  "bob at example.invalid", "bob%40example.invalid", "bob@example[dot]invalid",
                  "BOB@EXAMPLE.INVALID", "bob@mail.example.invalid"]:
            self.assertTrue(self.one(s, "email", "ed-01"), s)

    def test_spaced_at_variants(self):
        for s in ["bob @ example.invalid", "bob [at] example.invalid", "bob (at) example.invalid",
                  "bob	@	example.invalid"]:
            self.assertTrue(self.one(s, "email", "ed-01"), s)

    def test_local_part_foreign_domain(self):
        self.assertTrue(self.one("write jane.doe@mail.example.test now", "email", "id-01"))
        self.assertTrue(self.one("jane.doe[at]foo[dot]example", "email", "id-01"))

    def test_allow_local_parts(self):
        self.write_terms({"email_domains": [{"id": "ed-01", "domain": "example.invalid",
                                             "allow_local_parts": ["owner.one"]}]})
        for s in ["owner.one@example.invalid", "Owner_One[at]example[dot]invalid"]:
            self.assertFalse(self.one(s, "email", "ed-01"), s)
        for s in ["bob@example.invalid", "xowner.one@example.invalid", "owner.one2@example.invalid"]:
            self.assertTrue(self.one(s, "email", "ed-01"), s)

    def test_bare_identity(self):
        self.assertEqual(self.hits("Contact Jane Q Doe today"), {("identity", "id-01")})
        self.assertFalse(self.one("someone else", "identity"))


class TestHostname(Base):
    def test_subdomain_and_dots(self):
        for s in ["a.corp.example.invalid", "a.corp[dot]example(dot)invalid", "corp dot example dot invalid"]:
            self.assertTrue(self.one(s, "hostname", "dom-01"), s)

    def test_public_negative(self):
        self.assertFalse(self.one("see corp.example.com and notcorp.example.invalid", "hostname"))

    def test_host_pattern(self):
        self.assertTrue(self.one("ssh build-42.example", "hostname", "hp-01"))
        self.assertFalse(self.one("build-x.example", "hostname"))


class TestCustomer(Base):
    def test_uncited_hits(self):
        for s in ["Acme Mutual", "acme-mutual", "AcmeMutual", "Acme Mut."]:
            self.assertTrue(self.one(s, "customer", "cust-01"), s)

    def test_cited_passes(self):
        self.assertFalse(self.one("Cited Corp is public", "customer"))

    def test_citation_domains_enforced(self):
        def cust(url):
            return {"citation_domains": ["example.com"],
                    "customers": [{"id": "cust-01", "name": "Acme Mutual", "variants": [],
                                   "public_citation": url}]}
        for ok in ["https://example.com/case-studies/acme", "https://www.example.com/", "https://example.com"]:
            self.write_terms(cust(ok))
            self.assertNotEqual(self.tree()[0], 2, ok)
        for bad in ["https://news.example.org/acme", "https://example.com.evil.test/x",
                    "http://example.com/x", "knowledge/vault/x.md"]:
            self.write_terms(cust(bad))
            self.assertEqual(self.tree()[0], 2, bad)

    def test_citation_without_domains_exit_2(self):
        self.write_terms({"citation_domains": []})
        self.assertEqual(self.tree()[0], 2)

    def test_partner_not_flagged(self):
        self.assertFalse(self.one("Acme Mutual Partners LLP signed", "customer", "cust-01"))
        self.assertTrue(self.one("Acme Mutual Partners LLP and Acme Mutual", "customer", "cust-01"))

    def test_partner_customer_name_clash_exit_2(self):
        self.write_terms({"partners": [{"id": "ptr-01", "name": "acme-mutual", "variants": []}]})
        rc, _, err = self.tree()
        self.assertEqual(rc, 2)
        self.assertNotIn("Acme", err)


class TestClientPath(Base):
    def setUp(self):
        super().setUp()
        self.root = "knowledge/sources/example-intel/held-docs"

    def test_presence_count_not_content(self):
        self.put(f"{self.root}/a.md", "Acme Mutual\n")
        self.put(f"{self.root}/sub/b.md", "Acme Mutual\n")
        rc, rep, _ = self.tree()
        self.assertEqual(rc, 1)
        self.assertEqual([(f["category"], f["path"], f.get("count")) for f in rep["findings"]],
                         [("client-path", self.root, 2)])

    def test_references(self):
        for s in ["see example-intel/held-docs/x", r"see example-intel\held-docs\x",
                  "the held-docs folder", "knowledge/sources/example-intel/held-docs"]:
            self.assertTrue(self.one(s, "client-path", "cp-01"), s)

    def test_reference_in_path(self):
        self.put("notes/held-docs-index.md", "clean\n")
        _, rep, _ = self.tree()
        self.assertEqual([(f["category"], f["line"]) for f in rep["findings"]], [("client-path", 0)])


class TestLocalPath(Base):
    def test_forms(self):
        for s in [r"C:\Users\jane.doe\x", "C:/Users/jane.doe/x", r"C:\\Users\\jane.doe\\x",
                  "/Users/jane.doe/x", "/home/jane.doe/x", r"d:\users\JANE.DOE"]:
            self.assertTrue(self.one(s, "local-path", "id-01"), s)

    def test_negative(self):
        self.assertFalse(self.one(r"C:\Users\jane.doex\x", "local-path"))
        self.assertFalse(self.one("/home/other", "local-path"))


class TestPrivatePath(Base):
    def test_literal_slashes(self):
        self.assertTrue(self.one("see outputs/foo", "private-path", "pt-01"))
        self.assertTrue(self.one(r"see outputs\foo", "private-path", "pt-01"))
        self.assertFalse(self.one("myoutputs/foo", "private-path"))

    def test_regex(self):
        self.assertTrue(self.one("token SECRET-123", "private-path", "pt-02"))
        self.assertFalse(self.one("SECRET-12", "private-path"))


class TestPathScan(Base):
    def test_filename_line_zero(self):
        self.put("Acme-Mutual-notes.md", "clean\n")
        _, rep, _ = self.tree()
        self.assertEqual([(f["category"], f["path"], f["line"]) for f in rep["findings"]],
                         [("customer", "Acme-Mutual-notes.md", 0)])


class TestWaivers(Base):
    def setUp(self):
        super().setUp()
        self.put("x/a.md", "Acme Mutual\n")

    def waive(self, **kw):
        w = {"path": "x/**", "category": "customer", "term_id": "cust-01", "reason": "public case study"}
        w.update(kw)
        self.write_waivers([w])

    def test_suppression_keeps_finding(self):
        self.waive()
        rc, rep, _ = self.tree()
        self.assertEqual(rc, 0)
        f = rep["findings"][0]
        self.assertTrue(f["waived"])
        self.assertEqual(f["waiver_reason"], "public case study")
        self.assertEqual(rep["counts"]["customer"], {"total": 1, "waived": 1})

    def test_stale_and_strict(self):
        self.waive(path="nomatch/**")
        rc, rep, err = self.tree()
        self.assertEqual(rc, 1)  # finding unwaived
        self.assertEqual(rep["stale_waivers"], [])  # waiver covers no scanned path: not stale
        self.waive(term_id="cust-01")
        self.put("x/a.md", "clean\n")
        rc, rep, err = self.tree()
        self.assertEqual(rc, 0)
        self.assertEqual(len(rep["stale_waivers"]), 1)
        self.assertIn("stale", err)
        rc, rep, _ = self.tree("--strict")
        self.assertEqual(rc, 1)

    def test_partial_scan_not_stale_under_strict(self):
        self.waive()  # covers x/**
        self.put("y/b.md", "clean\n")
        rc, rep, _ = self.tree("--strict", paths=[str(self.scan_dir / "y")])
        self.assertEqual(rep["stale_waivers"], [])
        self.assertEqual(rc, 0)

    def test_missing_reason_exit_2(self):
        self.write_waivers([{"path": "x/**", "category": "customer", "term_id": "cust-01"}])
        rc, _, _ = self.tree()
        self.assertEqual(rc, 2)


class TestRedaction(Base):
    def test_value_never_leaks(self):
        self.put("a.md", "met Acme Mutual yesterday\n")
        outf = self.tmp / "report.json"
        rc, rep, _ = self.tree("--out", str(outf))
        self.assertEqual(rc, 1)
        self.assertNotIn("Acme", json.dumps(rep))
        self.assertNotIn("Acme", outf.read_text(encoding="utf-8"))
        args = ["tree", str(self.scan_dir), "--terms", str(self.terms), "--waivers", str(self.waivers)]
        rc, out, _ = self.run_main(*args)
        self.assertNotIn("Acme", out)
        self.assertIn("a.md:1:5 customer cust-01", out)
        rc, out, _ = self.run_main(*args, "--show-values")
        self.assertIn("Acme Mutual", out)
        rc, out, _ = self.run_main(*args, "--show-values", "--json")
        self.assertNotIn("Acme", out)


class TestSkips(Base):
    def test_binary_and_large(self):
        self.put("b.bin", b"\0Acme Mutual")
        self.put("big.txt", "Acme Mutual\n" * 10)
        self.write_terms({"max_bytes": 50})
        rc, rep, _ = self.tree()
        self.assertEqual(rc, 0)
        self.assertEqual({(s["path"], s["reason"]) for s in rep["skipped"]},
                         {("b.bin", "binary"), ("big.txt", "too-large")})


class TestDiff(Base):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        self.put("a.md", "one\nAcme Mutual old\nthree\n", self.repo)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "base")

    def diff(self, *args):
        rc, out, err = self.run_main("diff", *args, "--cwd", str(self.repo), "--terms", str(self.terms),
                                     "--waivers", str(self.waivers), "--json")
        return rc, (json.loads(out) if out.strip() else None), err

    def test_removed_not_flagged_added_flagged(self):
        self.put("a.md", "one\nclean\nthree\nfour\nAcme Mutual new\n", self.repo)
        git(self.repo, "add", "-A")
        rc, rep, _ = self.diff("--staged")
        self.assertEqual(rc, 1)
        self.assertEqual([(f["path"], f["line"], f["category"]) for f in rep["findings"]],
                         [("a.md", 5, "customer")])

    def test_diff_never_reports_stale(self):
        self.write_waivers([{"path": "*.md", "category": "customer", "term_id": "cust-01", "reason": "r"}])
        self.put("a.md", "one\nAcme Mutual old\nthree\nclean add\n", self.repo)
        git(self.repo, "add", "-A")
        rc, rep, _ = self.run_main("diff", "--staged", "--strict", "--cwd", str(self.repo), "--terms",
                                   str(self.terms), "--waivers", str(self.waivers), "--json")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(rep)["stale_waivers"], [])

    def test_removed_only_clean(self):
        self.put("a.md", "one\nthree\n", self.repo)
        git(self.repo, "add", "-A")
        rc, rep, _ = self.diff("--staged")
        self.assertEqual(rc, 0)
        self.assertEqual(rep["findings"], [])

    def test_range_new_file_and_binary(self):
        self.put("Acme-Mutual.md", "clean\n", self.repo)
        self.put("img.bin", b"\0\1\2Acme Mutual", self.repo)
        self.put("b.md", "x\nmail bob@example.invalid\n", self.repo)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "two")
        rc, rep, _ = self.diff("--range", "HEAD~1..HEAD")
        self.assertEqual(rc, 1)
        got = [(f["path"], f["line"], f["category"]) for f in rep["findings"]]
        self.assertEqual(got, [("Acme-Mutual.md", 0, "customer"), ("b.md", 2, "email")])
        self.assertEqual(rep["skipped"], [{"path": "img.bin", "reason": "binary"}])
        self.assertEqual(rep["targets"], ["HEAD~1..HEAD"])

    def test_client_root_presence(self):
        self.put("knowledge/sources/example-intel/held-docs/x.md", "Acme Mutual\n", self.repo)
        git(self.repo, "add", "-A")
        rc, rep, _ = self.diff("--staged")
        self.assertEqual([(f["category"], f.get("count")) for f in rep["findings"]], [("client-path", 1)])

    def test_bad_range_and_not_repo(self):
        rc, _, _ = self.diff("--range", "nope")
        self.assertEqual(rc, 2)
        rc, _, _ = self.run_main("diff", "--staged", "--cwd", str(self.tmp / "tree"), "--terms",
                                 str(self.terms), "--waivers", str(self.waivers))
        self.assertEqual(rc, 2)


class TestNestedRepo(Base):
    """Workspace root repo ignoring knowledge/, nested repo at knowledge/ ignoring restricted/."""

    def setUp(self):
        super().setUp()
        self.ws = self.tmp / "ws"
        (self.ws / "control-plane").mkdir(parents=True)
        git(self.ws, "init", "-q")
        self.put(".gitignore", "knowledge/\n", self.ws)
        self.kn = self.ws / "knowledge"
        self.kn.mkdir()
        git(self.kn, "init", "-q")
        self.put(".gitignore", "restricted/\n", self.kn)
        self.put("vault/n.md", "Acme Mutual\n", self.kn)
        self.put("restricted/r.md", "Acme Mutual\n", self.kn)
        env = mock.patch.dict(os.environ, {"WORKSPACE_ROOT": str(self.ws)})
        env.start()
        self.addCleanup(env.stop)

    def gset(self, d, *extra):
        rc, out, err = self.run_main("tree", "--git-set", str(d), "--terms", str(self.terms),
                                     "--waivers", str(self.waivers), "--json", *extra)
        return rc, (json.loads(out) if out.strip() else None), err

    def test_git_set_excludes_ignored_restricted(self):
        self.put("vault/untracked.md", "bob@example.invalid\n", self.kn)
        rc, rep, _ = self.gset(self.kn)
        self.assertEqual(rc, 1)
        got = {(f["path"], f["category"]) for f in rep["findings"]}
        self.assertEqual(got, {("knowledge/vault/n.md", "customer"),
                               ("knowledge/vault/untracked.md", "email")})
        self.assertEqual(rep["targets"], ["knowledge"])
        # waivers keep their workspace-relative knowledge/... form
        self.write_waivers([{"path": "knowledge/vault/*", "category": "customer", "term_id": "cust-01",
                             "reason": "r"}, {"path": "knowledge/vault/*", "category": "email",
                                              "term_id": "ed-01", "reason": "r"}])
        rc, rep, _ = self.gset(self.kn, "--strict")
        self.assertEqual(rc, 0)

    def test_git_set_rejects_paths(self):
        rc, _, _ = self.tree("--git-set", str(self.kn), paths=[str(self.kn)])
        self.assertEqual(rc, 2)

    def test_git_set_root_skips_ignored_nested_repo(self):
        rc, rep, _ = self.gset(self.ws)
        self.assertEqual(rc, 0)
        self.assertFalse(any(f["path"].startswith("knowledge/") for f in rep["findings"]))

    def test_diff_paths_prefixed_workspace_relative(self):
        git(self.kn, "add", "-A")
        rc, out, _ = self.run_main("diff", "--staged", "--cwd", str(self.kn), "--terms", str(self.terms),
                                   "--waivers", str(self.waivers), "--json")
        self.assertEqual(rc, 1)
        rep = json.loads(out)
        self.assertEqual([(f["path"], f["line"]) for f in rep["findings"]], [("knowledge/vault/n.md", 1)])


class TestExitConfig(Base):
    def test_clean_0_and_dirty_1(self):
        self.put("a.md", "nothing here\n")
        self.assertEqual(self.tree()[0], 0)
        self.put("b.md", "Acme Mutual\n")
        self.assertEqual(self.tree()[0], 1)

    def test_missing_terms(self):
        self.terms.unlink()
        self.assertEqual(self.tree()[0], 2)

    def test_empty_term_set(self):
        self.terms.write_text(json.dumps({"schema": "disclosure-terms/1", "internal_domains": [],
                                          "customers": []}), encoding="utf-8")
        self.put("a.md", "clean\n")
        self.assertEqual(self.tree()[0], 2)

    def test_bad_regex_and_duplicate_id(self):
        self.write_terms({"host_patterns": [{"id": "hp-01", "regex": "(unclosed"}]})
        self.assertEqual(self.tree()[0], 2)
        self.write_terms({"host_patterns": [{"id": "dom-01", "regex": "x"}]})
        self.assertEqual(self.tree()[0], 2)

    def test_terms_file_excluded_from_own_dir(self):
        self.put("a.md", "clean\n")
        inside = self.scan_dir / "terms.json"
        inside.write_text(self.terms.read_text(encoding="utf-8"), encoding="utf-8")
        self.terms = inside
        rc, rep, _ = self.tree()
        self.assertEqual(rc, 0)
        self.assertEqual(rep["findings"], [])

    def test_exclude_globs(self):
        self.put("node_modules/x/a.md", "Acme Mutual\n")
        self.put(".git/config", "Acme Mutual\n")
        self.assertEqual(self.tree()[0], 0)


class TestDeterminism(Base):
    def test_identical_findings(self):
        for i in range(5):
            self.put(f"d{i}/f.md", "Acme Mutual jane.doe@x.test\nbuild-1.example\n")
        a = self.tree()[1]
        b = self.tree()[1]
        self.assertEqual(a["findings"], b["findings"])
        self.assertEqual(a["terms_digest"], b["terms_digest"])
        self.assertEqual(a["findings"], sorted(a["findings"], key=lambda f: (
            f["path"], f["line"], f["col"], f["category"], f["term_id"])))


if __name__ == "__main__":
    unittest.main()
