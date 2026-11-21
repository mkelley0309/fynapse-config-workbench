#!/usr/bin/env python3
"""disclosure_scan - deterministic pre-push disclosure scanner (no network, no LLM).

Usage (run from the workspace root):
    python -B tools/disclosure-scan/disclosure_scan.py tree [PATH ...]
    python -B tools/disclosure-scan/disclosure_scan.py tree --git-set DIR
    python -B tools/disclosure-scan/disclosure_scan.py diff (--staged | --range A..B) [--cwd DIR]

Findings cite category and term id, never matched values (console only with
--show-values). Reported paths are workspace-relative in every mode (a path
outside the workspace stays relative to its scan target). Exit 0 clean, 1 unwaived findings (or stale waivers with
--strict), 2 usage/config/git error. Stdlib only.
"""

import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TERMS = SCRIPT_DIR / "terms.local.json"
DEFAULT_WAIVERS = SCRIPT_DIR / "waivers.json"
DEFAULT_MAX_BYTES = 5242880
PRIORITY = {"local-path": 0, "email": 1, "client-path": 2, "hostname": 3,
            "customer": 4, "identity": 5, "private-path": 6}
CATEGORIES = list(PRIORITY)

SEP = "[\\s._\\-'’]{0,3}"
DOT = r"(?:\.|\[dot\]|\(dot\)|\s+dot\s+)"
AT = r"(?:[ \t]*(?:@|\[at\]|\(at\)|%40)[ \t]*|\s+at\s+)"


class ConfigError(Exception):
    pass


def find_root():
    """WORKSPACE_ROOT env -> script dir -> walk up to a directory containing control-plane/."""
    env = os.environ.get("WORKSPACE_ROOT")
    start = Path(env).resolve() if env else SCRIPT_DIR
    for cand in (start, *start.parents):
        if (cand / "control-plane").is_dir():
            return cand
    raise ConfigError(f"no workspace root found (no control-plane/ at or above {start})")


def git(args, cwd=None):
    try:
        r = subprocess.run(["git", *args], capture_output=True, cwd=cwd)
    except OSError as e:
        raise ConfigError(f"git failed: {e}")
    if r.returncode != 0:
        raise ConfigError(r.stderr.decode("utf-8", "replace").strip() or "git error")
    return r.stdout


# ---------------------------------------------------------------- term compiler

def term_tokens(text):
    out = []
    for part in re.split("[\\s._\\-/'’]+", text):
        part = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])|(?<=[a-z])(?=[A-Z])", " ", part)
        out.extend(part.split())
    return out


def term_regex(text, bounds=True):
    toks = term_tokens(text)
    if not toks:
        raise ConfigError("empty term")
    body = SEP.join(re.escape(t) for t in toks)
    if bounds:
        return f"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"
    return body


def domain_regex(domain):
    labels = [x for x in domain.strip(".").split(".") if x]
    if not labels:
        raise ConfigError("empty domain")
    return DOT.join(re.escape(x) for x in labels)


def sep_literal_regex(text):
    parts = [re.escape(p) for p in re.split(r"[\\/]+", text) if p]
    if not parts:
        raise ConfigError("empty literal")
    tail = r"[\\/]+" if text[-1:] in ("/", "\\") else ""
    return r"(?<![A-Za-z0-9])" + r"[\\/]+".join(parts) + tail


# ---------------------------------------------------------------- terms loading

def strip_notes(o):
    if isinstance(o, dict):
        return {k: strip_notes(v) for k, v in o.items() if k != "_note"}
    if isinstance(o, list):
        return [strip_notes(v) for v in o]
    return o


def _rx(pattern, flags=0):
    try:
        return re.compile(pattern, flags)
    except re.error as e:
        raise ConfigError(f"regex does not compile: {e}")


def load_terms(path):
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"terms file not found: {p}")
    raw = p.read_bytes()
    try:
        data = strip_notes(json.loads(raw.decode("utf-8")))
    except (ValueError, UnicodeDecodeError) as e:
        raise ConfigError(f"terms file is not valid JSON: {e}")
    if not isinstance(data, dict) or data.get("schema") != "disclosure-terms/1":
        raise ConfigError("terms file schema must be disclosure-terms/1")

    ids, count = set(), 0
    rules, partner_rx, client_roots = [], [], []
    cust_names, partner_names = {}, {}

    def entries(key):
        v = data.get(key) or []
        if not isinstance(v, list) or not all(isinstance(e, dict) for e in v):
            raise ConfigError(f"{key} must be a list of objects")
        for e in v:
            i = e.get("id")
            if not isinstance(i, str) or not i:
                raise ConfigError(f"{key}: entry missing id")
            if i in ids:
                raise ConfigError(f"duplicate id: {i}")
            ids.add(i)
        return v

    def strs(e, key):
        v = e.get(key) or []
        if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
            raise ConfigError(f"{e['id']}: {key} must be a list of non-empty strings")
        return v

    def one(e, key):
        v = e.get(key)
        if not isinstance(v, str) or not v.strip():
            raise ConfigError(f"{e['id']}: {key} must be a non-empty string")
        return v

    def norm(s):
        return " ".join(term_tokens(s)).lower()

    for e in entries("internal_domains"):
        count += 1
        rules.append(("hostname", e["id"], _rx(
            f"(?<![A-Za-z0-9-]){domain_regex(one(e, 'domain'))}(?![A-Za-z0-9-])", re.I), None))
    for e in entries("host_patterns"):
        count += 1
        rules.append(("hostname", e["id"], _rx(one(e, "regex")), None))
    for e in entries("email_domains"):
        count += 1
        allow = strs(e, "allow_local_parts")
        skip = ("(?!(?:" + "|".join(term_regex(a, False) for a in allow) + ")" + AT + ")") if allow else ""
        rules.append(("email", e["id"], _rx(
            "(?<![A-Za-z0-9._%+\\-])" + skip + "[A-Za-z0-9._%+\\-]+" + AT
            + "(?:[A-Za-z0-9-]+" + DOT + ")*" + domain_regex(one(e, "domain")) + "(?![A-Za-z0-9-])",
            re.I), None))
    for e in entries("identities"):
        names, lps, users = strs(e, "names"), strs(e, "local_parts"), strs(e, "usernames")
        count += len(names) + len(lps) + len(users)
        for t in names + lps:
            rules.append(("identity", e["id"], _rx(term_regex(t), re.I), "identity"))
        for t in lps:
            rules.append(("email", e["id"], _rx(
                "(?<![A-Za-z0-9])" + term_regex(t, False) + AT
                + "[A-Za-z0-9-]+(?:" + DOT + "[A-Za-z0-9-]+)*", re.I), None))
        for u in users:
            rules.append(("local-path", e["id"], _rx(
                r"(?:[A-Za-z]:[\\/]+|[\\/]+)(?:Users|home)[\\/]+" + re.escape(u) + "(?![A-Za-z0-9_])",
                re.I), None))
    cdoms = data.get("citation_domains") or []
    if not isinstance(cdoms, list) or not all(isinstance(d, str) and d.strip() for d in cdoms):
        raise ConfigError("citation_domains must be a list of non-empty strings")
    cit_rx = re.compile(r"https://(?:[A-Za-z0-9-]+\.)*(?:" + "|".join(re.escape(d.strip().lower()) for d in cdoms)
                        + r")(?:[/?#]|$)", re.I) if cdoms else None
    for e in entries("customers"):
        count += 1
        names = [one(e, "name")] + strs(e, "variants")
        for n in names:
            cust_names.setdefault(norm(n), e["id"])
        cit = e.get("public_citation")
        if cit is not None and not (isinstance(cit, str) and cit.strip()):
            raise ConfigError(f"{e['id']}: public_citation must be a string or null")
        if cit is not None and cit_rx is None:
            raise ConfigError(f"{e['id']}: public_citation set but citation_domains is empty; "
                              "a cited customer is never scanned, so citations must be checkable")
        if cit is not None and not cit_rx.match(cit.strip()):
            raise ConfigError(f"{e['id']}: public_citation is not a URL on an allowed citation_domains site")
        if cit is None:
            names.sort(key=len, reverse=True)
            rules.append(("customer", e["id"],
                          _rx("|".join(term_regex(n) for n in names), re.I), "customer"))
    for e in entries("partners"):
        count += 1
        names = [one(e, "name")] + strs(e, "variants")
        for n in names:
            partner_names[norm(n)] = e["id"]
        names.sort(key=len, reverse=True)
        partner_rx.append(_rx("|".join(term_regex(n) for n in names), re.I))
    clash = set(cust_names) & set(partner_names)
    if clash:
        a = sorted(f"{cust_names[k]}/{partner_names[k]}" for k in clash)
        raise ConfigError(f"partner name/variant equals customer name/variant: {', '.join(a)}")
    for e in entries("client_paths"):
        count += 1
        root = one(e, "root").replace("\\", "/").strip("/") + "/"
        refs = strs(e, "reference_terms")
        client_roots.append((e["id"], root))
        for r in refs:
            rules.append(("client-path", e["id"], _rx(sep_literal_regex(r), re.I), None))
    for e in entries("private_terms"):
        count += 1
        kind = e.get("kind")
        if kind == "literal":
            rules.append(("private-path", e["id"], _rx(sep_literal_regex(one(e, "term")), re.I), None))
        elif kind == "regex":
            rules.append(("private-path", e["id"], _rx(one(e, "term")), None))
        else:
            raise ConfigError(f"{e['id']}: kind must be literal or regex")
    globs = data.get("exclude_globs") or []
    if not isinstance(globs, list) or not all(isinstance(g, str) for g in globs):
        raise ConfigError("exclude_globs must be a list of strings")
    mb = data.get("max_bytes", DEFAULT_MAX_BYTES)
    if not isinstance(mb, int) or isinstance(mb, bool) or mb <= 0:
        raise ConfigError("max_bytes must be a positive integer")
    if count == 0:
        raise ConfigError("terms file defines zero terms; refusing to report clean")
    return {"rules": rules, "partners": partner_rx, "roots": client_roots, "globs": globs,
            "max_bytes": mb, "digest": hashlib.sha256(raw).hexdigest(), "path": p.resolve()}


def load_waivers(path):
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"waivers file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ConfigError(f"waivers file is not valid JSON: {e}")
    if not isinstance(data, dict) or data.get("schema") != "disclosure-waivers/1" \
            or not isinstance(data.get("waivers"), list):
        raise ConfigError("waivers file schema must be disclosure-waivers/1 with a waivers list")
    out = []
    for i, w in enumerate(data["waivers"]):
        if not isinstance(w, dict):
            raise ConfigError(f"waiver #{i}: must be an object")
        for k in ("path", "category", "term_id", "reason"):
            if not isinstance(w.get(k), str) or not w[k].strip():
                raise ConfigError(f"waiver #{i}: missing or empty field {k}")
        out.append({k: w[k] for k in ("path", "category", "term_id", "reason")})
    return out


# ---------------------------------------------------------------- matching

def scan_line(terms, line):
    """-> [(category, term_id, start, end, text)] with overlaps resolved by priority."""
    cands = []
    for cat, tid, rx, special in terms["rules"]:
        for m in rx.finditer(line):
            if m.end() == m.start():
                continue
            if special == "identity":
                before = line[max(0, m.start() - 3):m.start()].lower()
                after = line[m.end():m.end() + 5].lower()
                if before.endswith("@") or before.endswith("%40") \
                        or re.match(r"(?:@|\[at\]|\(at\)|%40)", after):
                    continue
            cands.append((PRIORITY[cat], m.start(), m.end(), cat, tid, special))
    if not cands:
        return []
    if any(c[5] == "customer" for c in cands):
        pspans = [(m.start(), m.end()) for rx in terms["partners"] for m in rx.finditer(line)]
        cands = [c for c in cands if c[5] != "customer"
                 or not any(c[1] < pe and ps < c[2] for ps, pe in pspans)]
    cands.sort(key=lambda c: (c[0], c[1], -(c[2] - c[1]), c[4]))
    taken, out = [], []
    for _, s, e, cat, tid, _sp in cands:
        if any(s < te and ts < e for ts, te in taken):
            continue
        taken.append((s, e))
        out.append((cat, tid, s, e, line[s:e]))
    return out


def root_of(terms, rel):
    for cid, root in terms["roots"]:
        if rel.startswith(root):
            return cid, root
    return None


def excluded(terms, rel, is_dir=False):
    cand = rel + "/" if is_dir else rel
    for g in terms["globs"]:
        for pat in {g, g[3:] if g.startswith("**/") else g}:
            if fnmatch.fnmatchcase(cand, pat):
                return True
    return False


class Collector:
    def __init__(self, terms):
        self.terms = terms
        self.findings, self.skipped, self.presence = [], [], {}
        self.scanned = set()  # repo-relative paths this run covered (for stale-waiver scoping)

    def line(self, rel, ln, text):
        for cat, tid, s, _e, val in scan_line(self.terms, text):
            self.findings.append({"category": cat, "term_id": tid, "path": rel, "line": ln,
                                  "col": s + 1, "_value": val})

    def path(self, rel):
        self.line(rel, 0, rel)

    def text(self, rel, text):
        self.path(rel)
        for i, ln in enumerate(text.split("\n"), 1):
            self.line(rel, i, ln.rstrip("\r"))

    def count_root(self, cid, root):
        self.presence[(cid, root)] = self.presence.get((cid, root), 0) + 1

    def finish(self):
        for (cid, root), n in self.presence.items():
            self.scanned.add(root.rstrip("/"))
            self.findings.append({"category": "client-path", "term_id": cid, "path": root.rstrip("/"),
                                  "line": 0, "col": 1, "count": n, "_value": f"{n} files"})


def read_text(path, max_bytes):
    """-> (text|None, skip_reason|None)."""
    try:
        if path.stat().st_size > max_bytes:
            return None, "too-large"
        data = path.read_bytes()
    except OSError:
        return None, "unreadable"
    if b"\0" in data[:8192]:
        return None, "binary"
    return data.decode("utf-8", errors="replace"), None


def ws_prefix(d, root):
    """Path of directory d relative to the workspace root as a 'x/y/' prefix ('' at or outside root)."""
    try:
        rel = Path(d).resolve().relative_to(root).as_posix()
    except ValueError:
        return ""
    return "" if rel == "." else rel + "/"


def scan_git_set(terms, d, root):
    """Scan exactly what `git -C d ls-files -co --exclude-standard` lists (tracked + untracked,
    not ignored); paths re-prefixed workspace-relative. Nested repos it lists as a directory
    are skipped with reason nested-repo."""
    dp = Path(d).resolve()
    if not dp.is_dir():
        raise ConfigError(f"path not found: {d}")
    pre = ws_prefix(dp, root)
    out = git(["ls-files", "-z", "-co", "--exclude-standard"], str(dp)).decode("utf-8", "replace")
    col = Collector(terms)
    for name in sorted(set(x for x in out.split("\x00") if x)):
        fp = dp / name
        rel = pre + name.rstrip("/")
        if excluded(terms, rel) or (fp.exists() and fp.resolve() == terms["path"]):
            continue
        if name.endswith("/") or fp.is_dir():
            col.skipped.append({"path": rel, "reason": "nested-repo"})
            continue
        if not fp.exists():
            continue  # tracked but deleted in the working tree
        col.scanned.add(rel)
        hit = root_of(terms, rel)
        if hit:
            col.count_root(*hit)
            continue
        text, why = read_text(fp, terms["max_bytes"])
        if why:
            col.skipped.append({"path": rel, "reason": why})
            col.path(rel)
        else:
            col.text(rel, text)
    col.finish()
    return col, [pre.rstrip("/") or "."]


def scan_tree(terms, targets, root):
    col = Collector(terms)
    seen = set()
    shown = []
    for t in targets:
        tp = Path(t).resolve()
        if not tp.exists():
            raise ConfigError(f"path not found: {t}")
        try:
            tp.relative_to(root)
            base = root
        except ValueError:
            base = tp if tp.is_dir() else tp.parent
        shown.append(tp.relative_to(base).as_posix() if tp != base else ".")
        files = []
        if tp.is_file():
            files.append(tp)
        else:
            for dp, dns, fns in os.walk(tp):
                rd = Path(dp).relative_to(base).as_posix()
                dns[:] = sorted(d for d in dns if not excluded(
                    terms, d if rd == "." else f"{rd}/{d}", True))
                files.extend(Path(dp) / f for f in sorted(fns))
        for fp in files:
            rel = fp.relative_to(base).as_posix()
            if fp.resolve() == terms["path"] or excluded(terms, rel) or (base, rel) in seen:
                continue
            seen.add((base, rel))
            col.scanned.add(rel)
            hit = root_of(terms, rel)
            if hit:
                col.count_root(*hit)
                continue
            text, why = read_text(fp, terms["max_bytes"])
            if why:
                col.skipped.append({"path": rel, "reason": why})
                col.path(rel)
            else:
                col.text(rel, text)
    col.finish()
    return col, shown


def scan_diff(terms, staged, rng, cwd):
    if staged:
        dargs, target = ["--cached"], "--staged"
    else:
        a, _, b = rng.partition("..")
        if not a or not b:
            raise ConfigError("--range needs <a>..<b>")
        dargs, target = [a, b], rng
    top = Path(git(["rev-parse", "--show-toplevel"], cwd).decode("utf-8", "replace").strip()).resolve()
    pre = ws_prefix(top, find_root())
    out = git(["-c", "core.quotepath=off", "diff", "-U0", "--no-renames", "--no-color",
               "--no-ext-diff", *dargs], cwd).decode("utf-8", "replace")
    col = Collector(terms)
    cur, active, ro, rn, ln = None, False, 0, 0, 0
    for row in out.split("\n"):
        if ro > 0 or rn > 0:
            if row.startswith("\\"):
                continue
            c = row[:1]
            if c == "+":
                if active:
                    col.line(cur, ln, row[1:].rstrip("\r"))
                ln += 1
                rn -= 1
            elif c == "-":
                ro -= 1
            else:
                ro -= 1
                rn -= 1
                ln += 1
            continue
        if row.startswith("diff --git "):
            rest = row[len("diff --git "):]
            n = (len(rest) - 5) // 2
            raw = rest[2:2 + n] if rest.startswith("a/") and n > 0 else rest
            cur = pre + raw
            active = not excluded(terms, cur) and (top / raw).resolve() != terms["path"]
            if active:
                col.scanned.add(cur)
            hit = root_of(terms, cur) if active else None
            if hit:
                col.count_root(*hit)
                active = False
        elif row.startswith("new file mode"):
            if active:
                col.path(cur)
        elif row.startswith("Binary files ") or row.startswith("GIT binary patch"):
            if active:
                col.skipped.append({"path": cur, "reason": "binary"})
        elif row.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", row)
            if m:
                ro = int(m.group(1)) if m.group(1) is not None else 1
                ln = int(m.group(2))
                rn = int(m.group(3)) if m.group(3) is not None else 1
    col.finish()
    return col, [target]


# ---------------------------------------------------------------- report

def apply_waivers(findings, waivers, scanned=None):
    """Mark waived findings. Return stale waivers: unused AND covering at least one path this
    run scanned (a waiver for paths outside a partial scan is not stale)."""
    used = set()
    for f in findings:
        f["waived"], f["waiver_reason"] = False, None
        for i, w in enumerate(waivers):
            if w["category"] == f["category"] and w["term_id"] == f["term_id"] \
                    and fnmatch.fnmatchcase(f["path"], w["path"]):
                used.add(i)
                if not f["waived"]:
                    f["waived"], f["waiver_reason"] = True, w["reason"]
    return [{"path": w["path"], "category": w["category"], "term_id": w["term_id"]}
            for i, w in enumerate(waivers) if i not in used
            and (scanned is None or any(fnmatch.fnmatchcase(p, w["path"]) for p in scanned))]


def build_report(mode, targets, terms, col, stale):
    fs = sorted(col.findings, key=lambda f: (f["path"], f["line"], f["col"], f["category"], f["term_id"]))
    counts = {c: {"total": 0, "waived": 0} for c in CATEGORIES}
    for f in fs:
        counts[f["category"]]["total"] += 1
        counts[f["category"]]["waived"] += 1 if f["waived"] else 0
    pub = []
    for f in fs:
        d = {k: f[k] for k in ("category", "term_id", "path", "line", "col", "waived", "waiver_reason")}
        if "count" in f:
            d["count"] = f["count"]
        pub.append(d)
    return fs, {"schema": "harness-records/1", "kind": "disclosure-scan",
                "generated": datetime.date.today().isoformat(), "mode": mode,
                "targets": targets, "terms_digest": terms["digest"], "counts": counts,
                "findings": pub,
                "skipped": sorted(col.skipped, key=lambda s: (s["path"], s["reason"])),
                "stale_waivers": stale}


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--terms", default=str(DEFAULT_TERMS))
    common.add_argument("--waivers", default=str(DEFAULT_WAIVERS))
    common.add_argument("--json", action="store_true", help="print the JSON report to stdout")
    common.add_argument("--out", help="write the JSON report to FILE")
    common.add_argument("--show-values", action="store_true", help="append matched text (console only)")
    common.add_argument("--strict", action="store_true", help="stale waivers exit 1")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    pt = sub.add_parser("tree", parents=[common], help="scan a directory tree")
    pt.add_argument("paths", nargs="*")
    pt.add_argument("--git-set", metavar="DIR",
                    help="scan the files `git -C DIR ls-files -co --exclude-standard` lists (no PATHs)")
    pd = sub.add_parser("diff", parents=[common], help="scan added lines of a git diff")
    g = pd.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true")
    g.add_argument("--range", dest="rng")
    pd.add_argument("--cwd", help="git repo directory (default: workspace root)")
    a = ap.parse_args(argv)
    try:
        root = find_root()
        terms = load_terms(a.terms)
        waivers = load_waivers(a.waivers)
        if a.mode == "tree" and a.git_set:
            if a.paths:
                raise ConfigError("--git-set takes no PATH arguments")
            col, targets = scan_git_set(terms, a.git_set, root)
        elif a.mode == "tree":
            col, targets = scan_tree(terms, a.paths or [str(root / "knowledge")], root)
        else:
            col, targets = scan_diff(terms, a.staged, a.rng, a.cwd or str(root))
    except ConfigError as e:
        sys.stderr.write(f"disclosure-scan: {e}\n")
        return 2
    stale = apply_waivers(col.findings, waivers, col.scanned)
    if a.mode == "diff":
        stale = []  # a diff sees only added lines; an unused waiver there says nothing about staleness
    fs, report = build_report(a.mode, targets, terms, col, stale)
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    unwaived = sum(1 for f in fs if not f["waived"])
    if a.json:
        print(json.dumps(report, indent=2))
    else:
        for f in fs:
            row = f"{f['path']}:{f['line']}:{f['col']} {f['category']} {f['term_id']}"
            if "count" in f:
                row += f" files={f['count']}"
            if f["waived"]:
                row += " (waived)"
            if a.show_values:
                row += f"  {f['_value']!r}"
            print(row)
        for s in report["skipped"]:
            print(f"skipped {s['path']} ({s['reason']})")
        print(f"{len(fs)} findings, {unwaived} unwaived, {len(report['skipped'])} skipped")
    for w in stale:
        sys.stderr.write(f"warning: stale waiver {w['category']} {w['term_id']} {w['path']}\n")
    return 1 if unwaived or (a.strict and stale) else 0


if __name__ == "__main__":
    sys.exit(main())
