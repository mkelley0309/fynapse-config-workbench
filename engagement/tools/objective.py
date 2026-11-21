#!/usr/bin/env python3
"""Objective state management — deterministic bookkeeping, no LLM."""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesslib  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

WORKSPACE = harnesslib.find_root()
OBJECTIVES_DIR = WORKSPACE / "control-plane" / "objectives"
PORTFOLIO_INDEX = OBJECTIVES_DIR / "index.md"
ARCHIVE_DIR = OBJECTIVES_DIR / "_archive"

# Ordered enums, mirroring workstream.py's VALID_PHASES. Kept as module constants
# so the CLI, its error messages, and any caller read from one definition.
VALID_HEALTH = ("on-track", "at-risk", "blocked", "stale")
VALID_CADENCE = ("weekly", "bi-weekly", "monthly", "quarterly", "semi-annual", "annual")
VALID_STATUS = ("active", "complete", "abandoned")

def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)

def ensure_portfolio_index():
    """Create the objectives portfolio index if it's missing (header-agnostic insert anchors on the separator)."""
    if not PORTFOLIO_INDEX.exists():
        OBJECTIVES_DIR.mkdir(parents=True, exist_ok=True)
        harnesslib.write_text(PORTFOLIO_INDEX, "# Objectives\n\n"
            "## Active\n\n"
            "| Objective | Description | Status |\n"
            "|---|---|---|\n\n"
            "## Complete\n\n"
            "| Objective | Description | Completed | Key Outcome |\n"
            "|---|---|---|---|\n")

def set_status(idx_text, value):
    """Set frontmatter status, validated against VALID_STATUS (status was previously unvalidated)."""
    if value not in VALID_STATUS:
        die(f"status must be one of: {', '.join(VALID_STATUS)}")
    return fm_set(idx_text, "status", value)

def archive_path(name, disposition):
    """Resolve the archive destination for a closing objective's folder.

    'complete' dispositions land under _archive/closed/, everything else
    (abandoned, merged, etc.) under _archive/abandoned/.
    """
    bucket = "closed" if disposition == "complete" else "abandoned"
    return ARCHIVE_DIR / bucket / name

def today():
    return date.today().strftime("%Y-%m-%d")

def kebab_ok(name):
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name))

def obj_dir(name):
    if not kebab_ok(name):
        die(f"invalid objective name '{name}' — must be kebab-case (a-z, 0-9, hyphens); no path separators")
    p = OBJECTIVES_DIR / name
    if not p.exists():
        die(f"objective '{name}' not found at {p}")
    return p

def read_index(name):
    p = obj_dir(name) / "index.md"
    if not p.exists():
        die(f"index.md not found for '{name}'")
    return p, p.read_text(encoding="utf-8")

def _fm_bounds(text):
    """Line indices [start, end) of the frontmatter body, exclusive of both fences.

    Returns None when the file has no terminated frontmatter block. Every helper
    below scopes itself to this range: an unscoped `^field:` regex also matches a
    same-named line in the document body, so a read can return body text and a
    write can silently rewrite it.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return 1, i
    return None

def _line_parts(raw):
    """Split a raw line into (content, terminator), preserving CRLF vs LF."""
    content = raw.rstrip("\r\n")
    return content, raw[len(content):]

def fm_get(text, field):
    bounds = _fm_bounds(text)
    if not bounds:
        return None
    start, end = bounds
    lines = text.splitlines(keepends=True)
    pat = re.compile(rf"^{re.escape(field)}:\s*(.+)$")
    for i in range(start, end):
        m = pat.match(_line_parts(lines[i])[0])
        if m:
            return m.group(1).strip().strip('"')
    return None

def fm_set(text, field, value):
    """Set a frontmatter field, inserting before the closing --- when absent."""
    bounds = _fm_bounds(text)
    if not bounds:
        die("cannot set frontmatter field: file does not open with a terminated '---' fence")
    start, end = bounds
    lines = text.splitlines(keepends=True)
    pat = re.compile(rf"^({re.escape(field)}:\s*).*$")
    for i in range(start, end):
        content, term = _line_parts(lines[i])
        m = pat.match(content)
        if m:
            lines[i] = f"{m.group(1)}{value}{term}"
            return "".join(lines)
    term = _line_parts(lines[end - 1])[1] or "\n" if end > start else "\n"
    lines.insert(end, f"{field}: {value}{term}")
    return "".join(lines)

def fm_add_field_after(text, after_field, new_field, value):
    """Insert a new frontmatter field after another field (no-op if already present)."""
    bounds = _fm_bounds(text)
    if not bounds:
        return text
    start, end = bounds
    lines = text.splitlines(keepends=True)
    present = re.compile(rf"^{re.escape(new_field)}:")
    anchor = re.compile(rf"^{re.escape(after_field)}:")
    for i in range(start, end):
        if present.match(_line_parts(lines[i])[0]):
            return text  # already present
    for i in range(start, end):
        content, term = _line_parts(lines[i])
        if anchor.match(content):
            lines.insert(i + 1, f"{new_field}: {value}{term or chr(10)}")
            return "".join(lines)
    return text  # anchor field absent — leave unchanged

# ---------------------------------------------------------------------------
# Portfolio-index helpers (grouping-aware)
#
# The Active table may be split across ### subgroup headings, each with its own
# header + separator row. Anything that walks the table must reset per subgroup,
# or every subgroup's header row after the first is mistaken for a data row.
# ---------------------------------------------------------------------------

SEPARATOR_RE = re.compile(r"^\|[\s\-|]+\|$")

def parse_index_rows(text):
    """Return the data rows of the Active table, across all ### subgroups."""
    rows, in_active, after_sep = [], False, False
    for line in text.splitlines():
        if line.startswith("## Active"):
            in_active, after_sep = True, False
            continue
        if line.startswith("## "):
            in_active = False
            continue
        if not in_active:
            continue
        if line.startswith("### "):
            after_sep = False          # new subgroup — its header row follows
            continue
        if SEPARATOR_RE.match(line):
            after_sep = True
            continue
        if after_sep and line.startswith("|") and "*(none yet)*" not in line:
            rows.append(line)
    return rows

def index_insert_point(text, subgroup=None):
    """Line index just after the separator row of the Active table.

    With `subgroup`, targets that ### subgroup's separator; without, the first
    separator in Active. Returns None if no matching separator is found.
    """
    in_active, current = False, None
    for i, line in enumerate(text.splitlines()):
        if line.startswith("## Active"):
            in_active, current = True, None
            continue
        if line.startswith("## "):
            in_active = False
            continue
        if not in_active:
            continue
        if line.startswith("### "):
            current = line[4:].strip()
            continue
        if SEPARATOR_RE.match(line):
            if subgroup is None or (current and current.startswith(subgroup)):
                return i + 1
    return None

def table_insert_point(text, header):
    """Line index just after the separator row of the table under `header`.

    None when the heading is absent or has no separator row yet.
    """
    in_section = False
    for i, line in enumerate(text.splitlines()):
        if line.startswith(header):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            return None
        if in_section and SEPARATOR_RE.match(line):
            return i + 1
    return None

def abandoned_insert_point(text):
    return table_insert_point(text, "## Abandoned")

PORTFOLIO_TABLES = {
    "## Complete": ["| Objective | Description | Completed | Key Outcome |", "|---|---|---|---|"],
    "## Abandoned": ["| Objective | Description | Abandoned | Reason |", "|---|---|---|---|"],
}

def ensure_table_section(text, header):
    """D17: make sure `header` has a table to insert into, creating the section if absent."""
    if table_insert_point(text, header) is not None:
        return text
    lines = text.splitlines()
    head = PORTFOLIO_TABLES[header]
    for i, ln in enumerate(lines):
        if ln.startswith(header):
            lines[i + 1:i + 1] = ["", *head]
            return "\n".join(lines) + "\n"
    return text.rstrip("\n") + f"\n\n{header}\n\n" + "\n".join(head) + "\n"

def move_portfolio_row(portfolio, name, header, link, third, fourth):
    """Remove `name`'s Active row and insert it in the `header` table; returns new text."""
    row_re = re.compile(
        rf"^\|\s*\[{re.escape(name)}\]\([^)]+\)\s*\|([^|]*)\|([^|]*)\|[ \t]*\n?", re.MULTILINE)
    m = row_re.search(portfolio)
    if not m:
        die(f"objective '{name}' not found in the Active table of {PORTFOLIO_INDEX}")
    description = m.group(1).strip()
    portfolio = portfolio[:m.start()] + portfolio[m.end():]
    portfolio = ensure_table_section(portfolio, header)
    at = table_insert_point(portfolio, header)
    lines = portfolio.splitlines(keepends=True)
    lines.insert(at, f"| [{name}]({link}) | {description} | {third} | {fourth} |\n")
    return "".join(lines)

def normalize_workstream_ref(ref):
    """Bare name → workstreams/<name>; explicit paths (incl. _log/ entries) pass through."""
    return ref if "/" in ref else f"workstreams/{ref}"

def canon_workstream(ref):
    """`workstreams/_log/2026-11-01-name`, `workstreams/name`, `name` -> `name`."""
    t = ref.strip().strip("`")
    t = re.sub(r"\.md$", "", t)
    t = t.rsplit("/", 1)[-1]
    return re.sub(r"^\d{4}-\d{2}-\d{2}-", "", t)

def workstream_ref_exists(ref):
    """True if the reference resolves on disk, as a folder index or a _log/ entry."""
    base = WORKSPACE / "control-plane" / ref
    if (base / "index.md").exists() or base.exists() or base.with_suffix(".md").exists():
        return True
    # D17: a closed workstream's folder is gone; its _log entry is the record
    log = WORKSPACE / "control-plane" / "workstreams" / "_log"
    return log.is_dir() and any(log.glob(f"*-{canon_workstream(ref)}.md"))

# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------

def _section_bounds(text, header):
    """Return (start_line_idx, end_line_idx_exclusive) of a markdown section."""
    lines = text.splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        if re.match(rf"^{re.escape(header)}\s*$", ln.rstrip()):
            start = i
            break
    if start is None:
        return None, None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^#{1,2} ", lines[i]):   # D17: ### subheadings stay inside the section
            end = i
            break
    return start, end

def section_text(text, header):
    s, e = _section_bounds(text, header)
    if s is None:
        return None
    return "".join(text.splitlines(keepends=True)[s:e])

TRAILING_SECTION = "## Related Notes"

def replace_section(text, header, new_section_text):
    """Replace an existing section (header through next header) with new_section_text.

    When the section is absent it is inserted immediately before ## Related Notes,
    which is canonically last. Appending to end of file would strand managed
    sections (Key Results, Milestones, Workstreams) below it.
    """
    lines = text.splitlines(keepends=True)
    s, e = _section_bounds(text, header)
    if s is None:
        anchor, _ = _section_bounds(text, TRAILING_SECTION)
        if anchor is None:
            return text + "\n" + new_section_text
        return "".join(lines[:anchor]) + new_section_text + "".join(lines[anchor:])
    return "".join(lines[:s]) + new_section_text + "".join(lines[e:])

# ---------------------------------------------------------------------------
# Key-Results helpers
# ---------------------------------------------------------------------------
KR_HEADER = "## Key Results"
KR_SEP    = "|---|---|---|---|"

def _parse_kr_table(text):
    """Return list of (result, current, target, updated) dicts."""
    sec = section_text(text, KR_HEADER)
    if not sec:
        return []
    rows = []
    in_table = False
    for ln in sec.splitlines():
        if re.match(r"^\|[\s\-|]+\|$", ln):
            in_table = True
            continue
        if in_table and ln.startswith("|"):
            parts = [c.strip() for c in ln.strip("|").split("|")]
            if len(parts) >= 4 and "*(none yet)*" not in parts[0]:
                rows.append({"result": parts[0], "current": parts[1],
                             "target": parts[2], "updated": parts[3]})
    return rows

def _render_kr_section(rows):
    lines = [f"{KR_HEADER}\n", "\n",
             "| Result | Current | Target | Updated |\n",
             "|---|---|---|---|\n"]
    if not rows:
        lines.append("| *(none yet)* | | | |\n")
    else:
        for r in rows:
            lines.append(f"| {r['result']} | {r['current']} | {r['target']} | {r['updated']} |\n")
    lines.append("\n")
    return "".join(lines)

# ---------------------------------------------------------------------------
# Milestone helpers
# ---------------------------------------------------------------------------
#
# Milestones are records: objectives/<obj>/milestones/<NN>-<slug>.md (R1/R3).
# There is no checklist-parsing path; an objective without milestones/ is unmigrated.
NOT_MIGRATED = "not migrated: run M2 (harness-intake-dependency-model)"
MS_LIST_FIELDS = ("depends_on", "related", "locks", "fed_by")

def require_migrated(name):
    d = obj_dir(name) / "milestones"
    if not d.is_dir():
        die(NOT_MIGRATED)
    return d

VIEW_HEADINGS = {"milestones": "## Milestones", "program-intake": "## Program Intake",
                 "carried-inputs": "## Carried Inputs", "gates": "## Open Gates"}
VIEWS = tuple(VIEW_HEADINGS)
TERMINAL_STATUS = ("consumed", "dropped", "done")


def _short(rid, name):
    return rid[len(name):] if rid.startswith(f"{name}#") else rid


def _backlog_progress(fm):
    done = total = 0
    for b in fm.get("backlog") or []:
        p = WORKSPACE / b
        if p.exists():
            try:
                d, t = harnesslib.backlog_progress(p)
            except harnesslib.HarnessError:
                continue
            done, total = done + d, total + t
    return (done, total) if total else None


def milestone_line(name, m):
    fm = m["fm"]
    st = fm.get("status", "open")
    if st == "dropped":
        return f"- [x] ~~#{m['n']} {fm.get('title', '')}~~ (dropped)"
    deps = [d for d in fm.get("depends_on") or [] if not str(d).startswith("gate:")]
    gates = [d for d in fm.get("depends_on") or [] if str(d).startswith("gate:")]
    parts = []
    if deps:
        parts.append("deps: " + ", ".join(_short(d, name) for d in deps))
    if gates:
        parts.append("gates: " + ", ".join(gates))
    if fm.get("unit"):
        parts.append(f"unit: {fm['unit']}")
    bp = _backlog_progress(fm)
    if bp:
        parts.append(f"backlog: {bp[0]}/{bp[1]}")
    box = "x" if st == "done" else " "
    return f"- [{box}] #{m['n']} {fm.get('title', '')}" + (f" ({'; '.join(parts)})" if parts else "")


def view_milestones(name, recs):
    ms = list_milestones(name)
    return "\n".join(milestone_line(name, m) for m in ms) + "\n" if ms else "*(none yet)*\n"


def _mine(name, recs):
    return {rid: r for rid, r in recs.items()
            if (r["kind"] == "milestone" and rid.startswith(f"{name}#"))
            or (r["kind"] != "milestone" and r["fm"].get("objective") == name)}


PROGRAM_INTAKE_WINDOW_DAYS = 30


def _fm_date(fm, key):
    try:
        return date.fromisoformat(str(fm.get(key) or ""))
    except ValueError:
        return None


def view_program_intake(name, recs):
    """Live intake plus archived-consumed intake whose `consumed:` date falls within
    PROGRAM_INTAKE_WINDOW_DAYS of the latest archive date on record (a deterministic reference:
    no file mtime, no clock). Archived records without a date are left out."""
    stamps = [d for r in recs.values() if r["kind"] == "intake" and r["archived"]
              for d in (_fm_date(r["fm"], "consumed"), _fm_date(r["fm"], "dropped")) if d]
    cutoff = max(stamps) - timedelta(days=PROGRAM_INTAKE_WINDOW_DAYS) if stamps else None
    lines = []
    for rid, r in sorted(recs.items()):
        if r["kind"] != "intake" or r["fm"].get("objective") != name:
            continue
        st = r["fm"].get("status")
        if r["archived"]:
            when = _fm_date(r["fm"], "consumed")
            if st != "consumed" or when is None or when < cutoff:
                continue
            lines.append(f"- {rid} · consumed (archived) · by {', '.join(r['fm'].get('consumed_by') or []) or '-'}")
        else:
            lines.append(f"- {rid} · {st} · {r['fm'].get('route', '')}")
    return "\n".join(lines) + "\n" if lines else "*(none)*\n"


def view_carried_inputs(name, recs):
    by = {}
    for rid, r in sorted(_mine(name, recs).items()):
        if r["kind"] not in ("intake", "milestone") or r["archived"] or r["fm"].get("status") in TERMINAL_STATUS:
            continue
        fm = r["fm"]
        until = fm.get("unit") or (fm.get("route") if str(fm.get("route", "")).startswith(("workstream:", "assignment:", "cadence:", "milestone:")) else "") or rid
        for p in fm.get("inputs") or []:
            by.setdefault(p, []).append(f"{rid} (until: {until})")
    lines = [f"- `{p}` — " + "; ".join(v) for p, v in sorted(by.items())]
    return "\n".join(lines) + "\n" if lines else "*(none)*\n"


def view_gates(name, recs):
    mine = _mine(name, recs)
    refd = set()
    for r in mine.values():
        if r["kind"] in ("intake", "milestone"):
            refd.update(str(d) for d in (r["fm"].get("depends_on") or []) + (r["fm"].get("fed_by") or []))
    lines = []
    for rid, r in sorted(recs.items()):
        if r["kind"] == "gate" and r["fm"].get("status") == "open" and (rid in mine or rid in refd):
            fm = r["fm"]
            lines.append(f"- {rid} ({fm.get('gate_type')}, {fm.get('who')}): {fm.get('title')} — {fm.get('criteria')}")
    return "\n".join(lines) + "\n" if lines else "*(none open)*\n"


VIEW_FUNCS = {"milestones": view_milestones, "program-intake": view_program_intake,
              "carried-inputs": view_carried_inputs, "gates": view_gates}


def render_milestones(name):
    """Re-render the `milestones` view after a record edit. Never fatal: a missing region is
    skipped, a hand-edited one is left alone with a warning (run `render --force`)."""
    path = obj_dir(name) / "index.md"
    try:
        harnesslib.render_view(path, "milestones", view_milestones(name, None), VIEW_HEADINGS["milestones"])
    except harnesslib.RegionEdited as e:
        print(f"warning: milestones view not refreshed: {e}", file=sys.stderr)


def render_objective(name, check=False, force=False, adopt=False):
    """-> [(view, status)]; status per harnesslib.render_view, or 'refused' on a hand edit."""
    path = obj_dir(name) / "index.md"
    recs = harnesslib.load_records(WORKSPACE)
    out = []
    for view in VIEWS:
        text = VIEW_FUNCS[view](name, recs)
        try:
            st = harnesslib.render_view(path, view, text, VIEW_HEADINGS[view], force=force, adopt=adopt,
                                        check=check, after="## Milestones" if view == "gates" else None)
        except harnesslib.RegionEdited as e:
            st = "refused"
        out.append((view, st))
    return out


def cmd_render(args):
    if args.all:
        names = sorted(p.name for p in OBJECTIVES_DIR.iterdir()
                       if p.is_dir() and not p.name.startswith("_") and (p / "index.md").exists())
        names = [n for n in names if (OBJECTIVES_DIR / n / "milestones").is_dir()]
    elif args.name:
        read_index(args.name)
        require_migrated(args.name)
        names = [args.name]
    else:
        die("render needs an objective name or --all")
    bad = False
    for n in names:
        if args.resolve:
            ipath = obj_dir(n) / "index.md"
            views, outside = harnesslib.resolve_conflicted_regions(ipath)
            for v in views:
                print(f"{n}: {v}: conflict dropped, re-rendering")
            if outside:
                print(f"warning: {n}: conflict markers outside generated regions left alone "
                      f"(lines {', '.join(map(str, outside))})", file=sys.stderr)
        for view, st in render_objective(n, check=args.check, force=args.force, adopt=args.adopt):
            print(f"{n}: {view}: {st}")
            if st == "refused":
                bad = True
            elif args.check and st == "stale":
                bad = True
    if bad:
        if not args.check:
            print("error: a generated region was hand-edited; re-run with --force", file=sys.stderr)
        sys.exit(1)

def list_milestones(name):
    """Milestone records of an objective, sorted by N: [{n, id, path, fm}]."""
    out = []
    for rid, r in harnesslib.load_records(WORKSPACE).items():
        if r["kind"] == "milestone" and rid.startswith(f"{name}#"):
            try:
                n = int(rid.split("#", 1)[1])
            except ValueError:
                continue
            out.append({"n": n, "id": rid, "path": r["path"], "fm": r["fm"]})
    return sorted(out, key=lambda m: m["n"])

def find_milestone(name, key):
    """Match by N (or #N), else by exact `title` or `legacy` line."""
    ms = list_milestones(name)
    k = key.strip()
    if k.lstrip("#").isdigit():
        hit = [m for m in ms if m["n"] == int(k.lstrip("#"))]
    else:
        def legacy_ok(m):
            lg = str(m["fm"].get("legacy") or "")
            return bool(lg) and (lg == k or re.sub(r"^- \[[x ]\] ", "", lg) == k)
        hit = [m for m in ms if m["fm"].get("title") == k or legacy_ok(m)]
    if not hit:
        die(f"milestone not found: {key}")
    return hit[0]

def flat_list(vals):
    """Repeatable list flags accept `--x a --x b` or `--x a,b` (one helper: harnesslib.listflag)."""
    return harnesslib.listflag(vals)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def need_date(val, flag):
    try:
        if not DATE_RE.match(val or ""):
            raise ValueError
        date.fromisoformat(val)
    except ValueError:
        die(f"{flag} must be a real date YYYY-MM-DD, got '{val}'")
    return val


def need_paths(inputs, backlog):
    for p in inputs + backlog:
        if not (WORKSPACE / p).exists():
            die(f"path does not exist: {p}")
    if not set(backlog) <= set(inputs):
        die("backlog must be a subset of inputs")

def validate_links(rid, deps, locks, fed_by=()):
    recs = harnesslib.load_records(WORKSPACE)
    for d in list(deps) + list(fed_by):
        if harnesslib.resolve(d, recs) is None:
            die(f"unresolved id: {d}")
    reg = harnesslib.load_locks(WORKSPACE)
    for lk in locks:
        if lk not in reg:
            die(f"unknown lock: {lk}")
    g = harnesslib.build_graph(recs)
    g[rid] = list(deps)
    cyc = harnesslib.find_cycle(g)
    if cyc:
        die("dependency cycle: " + " -> ".join(cyc))

def milestone_view(name):
    return [{"n": m["n"], "title": m["fm"].get("title", ""), "status": m["fm"].get("status", "open")}
            for m in list_milestones(name)]

# ---------------------------------------------------------------------------
# Workstreams helpers
# ---------------------------------------------------------------------------
WORKSTREAMS_HEADER = "## Workstreams"
WORKSTREAMS_SEP    = "|---|---|---|"

def _parse_workstreams(text):
    sec = section_text(text, WORKSTREAMS_HEADER)
    if not sec:
        return []
    rows = []
    in_table = False
    for ln in sec.splitlines():
        if re.match(r"^\|[\s\-|]+\|$", ln):
            in_table = True
            continue
        if in_table and ln.startswith("|"):
            parts = [c.strip() for c in ln.strip("|").split("|")]
            if len(parts) >= 3 and "*(none yet)*" not in parts[0]:
                rows.append({"workstream": parts[0], "status": parts[1], "linked": parts[2]})
    return rows

def _render_workstreams_section(rows):
    lines = [f"{WORKSTREAMS_HEADER}\n", "\n",
             "| Workstream | Status | Linked |\n",
             "|---|---|---|\n"]
    if not rows:
        lines.append("| *(none yet)* | | |\n")
    else:
        for r in rows:
            lines.append(f"| {r['workstream']} | {r['status']} | {r['linked']} |\n")
    lines.append("\n")
    return "".join(lines)

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(_args):
    if not PORTFOLIO_INDEX.exists():
        die(f"portfolio index not found: {PORTFOLIO_INDEX}")
    for row in parse_index_rows(PORTFOLIO_INDEX.read_text(encoding="utf-8")):
        print(row)


def cmd_status(args):
    _, text = read_index(args.name)
    for field, key in [
        ("objective", "objective"), ("status", "status"), ("health", "health"),
        ("cadence", "cadence"), ("created", "created"), ("completed", "completed"),
    ]:
        val = fm_get(text, key)
        if val:
            print(f"{field:<12} {val}")

    # Key Results
    krs = _parse_kr_table(text)
    if krs:
        print(f"\nkey results ({len(krs)}):")
        for r in krs:
            print(f"  {r['result']:<40} {r['current']:>12} / {r['target']:<12} (updated {r['updated']})")
    else:
        print("\nkey results: (none)")

    # Milestones
    if (obj_dir(args.name) / "milestones").is_dir():
        ms = milestone_view(args.name)
        done = sum(1 for m in ms if m["status"] == "done")
        print(f"\nmilestones:  {done}/{len(ms)} done")
        for m in ms:
            mark = "x" if m["status"] in ("done", "dropped") else " "
            tail = " (dropped)" if m["status"] == "dropped" else ""
            print(f"  [{mark}] #{m['n']} {m['title']}{tail}")
    else:
        print(f"\nmilestones:  {NOT_MIGRATED}")

    # Workstreams
    workstreams = _parse_workstreams(text)
    if workstreams:
        active = sum(1 for m in workstreams if m["status"] == "active")
        summary = f"{len(workstreams)}" + (f", {active} active" if active else "")
        print(f"\nworkstreams ({summary}):")
        for m in workstreams:
            print(f"  {m['workstream']:<58} {m['status']}")
    else:
        print("\nworkstreams:    (none)")

    # Recent decisions
    dec_m = re.search(r"## Key Decisions Log\n\n[^\n]+\n[^\n]+\n((?:\|[^\n]+\n)*)", text)
    if dec_m:
        rows = [r for r in dec_m.group(1).strip().splitlines() if "append-only" not in r]
        if rows:
            print(f"\nrecent decisions ({len(rows)} total):")
            for row in rows[-3:]:
                print(f"  {row.strip()}")


def cmd_create(args):
    name = args.name
    if not kebab_ok(name):
        die(f"invalid objective name '{name}' — must be kebab-case (a-z, 0-9, hyphens); no path separators")
    dest = OBJECTIVES_DIR / name
    if dest.exists():
        die(f"'{name}' already exists")

    title   = args.title or name.replace("-", " ").title()
    today_s = today()
    origin  = getattr(args, "origin", None) or ""
    origin_line = ""
    if origin:
        origin_line = (
            f"*Promoted from* [{origin}](../../{origin}/index.md)*, which outgrew its tier. "
            "That work keeps its original scope and closes itself out under this objective "
            "rather than being rewritten — the promotion gives it a parent, it does not "
            "change what it was for.*\n\n")

    index_md = f"""---
objective: {name}
status: active
health: on-track
cadence: quarterly
created: {today_s}
promoted_from: "{origin}"
tags: [objective]
---

# {title} — Objective Context

## Objective

{origin_line}*What this is and why it matters. Tie to strategy where relevant.*

## Success Criteria

- *concrete, verifiable criterion*

## Key Results

| Result | Current | Target | Updated |
|---|---|---|---|
| *(none yet)* | | | |

## Milestones

<!-- generated:milestones -->
*(none yet)*
<!-- /generated:milestones sha={harnesslib._sha8("*(none yet)*" + chr(10))} -->

## Workstreams

| Workstream | Status | Linked |
|---|---|---|
| *(none yet)* | | |

## Dependencies

- *dependency name — what's needed, from whom, why*

## Key Decisions Log

| Decision | Rationale | By | Date |
|---|---|---|---|
| *(append-only; never truncated)* | | | |

## Definition of Done

*Specific conditions under which this objective closes.*

## Related Notes

- *links to child workstreams, parent strategy, dependent objectives*
"""

    dest.mkdir(parents=True)
    harnesslib.write_text((dest / "index.md"), index_md)
    harnesslib.write_text(dest / "milestones" / ".gitkeep", "")
    print(f"created: {dest / 'index.md'}")

    ensure_portfolio_index()
    portfolio = PORTFOLIO_INDEX.read_text(encoding="utf-8")
    new_row = f"| [{name}]({name}/index.md) | *add description* | Active |"
    at = index_insert_point(portfolio, getattr(args, "group", None))
    if at is None:
        die(
            f"could not find an Active table separator in {PORTFOLIO_INDEX}"
            + (f" for subgroup '{args.group}'" if getattr(args, "group", None) else "")
        )
    lines = [ln for ln in portfolio.splitlines()
             if "*(none yet)*" not in ln or not ln.startswith("|")]
    # Re-resolve against the filtered list so the insert point stays correct.
    at = index_insert_point("\n".join(lines), getattr(args, "group", None))
    lines.insert(at, new_row)
    portfolio = "\n".join(lines) + "\n"
    harnesslib.write_text(PORTFOLIO_INDEX, portfolio)
    print(f"updated: {PORTFOLIO_INDEX}")


def checkpoint_dir(name):
    return obj_dir(name) / "checkpoints"

def render_checkpoint(name, text, when, milestones=()):
    """Build a checkpoint entry from the objective's current tracked state.

    Read-only with respect to index.md — the checkpoint is a point-in-time snapshot,
    written alongside the anchor rather than appended to it. This is what gives
    KRs a history: `update-kr` overwrites `current` in place, so without a dated
    snapshot the trajectory is lost on every update.
    """
    krs = _parse_kr_table(text)
    workstreams = _parse_workstreams(text)
    health = fm_get(text, "health") or "—"
    cadence = fm_get(text, "cadence") or "—"
    done = sum(1 for m in milestones if m["status"] == "done")

    out = [
        "---",
        "note_type: objective-checkpoint",
        f"objective: {name}",
        f"checkpoint_date: {when}",
        f"health: {health}",
        f"cadence: {cadence}",
        f"tags: [objective/{name}, checkpoint]",
        "---",
        f"# {name} — Checkpoint {when}",
        "",
        f"Point-in-time snapshot. Health **{health}**, cadence **{cadence}**.",
        "",
        "## Key Results at Checkpoint",
        "",
    ]
    if krs:
        out += ["| Result | Current | Target | Last Updated |", "|---|---|---|---|"]
        out += [f"| {r['result']} | {r['current']} | {r['target']} | {r['updated']} |"
                for r in krs]
    else:
        out.append("*No Key Results set.* Record here why — a deliberately empty KR set "
                   "is a finding, not an omission.")
    out += ["", f"## Milestones — {done}/{len(milestones)} done", ""]
    def _ms_line(m):
        if m["status"] == "dropped":
            return f"- [x] ~~#{m['n']} {m['title']}~~ (dropped)"
        return f"- [{'x' if m['status'] == 'done' else ' '}] #{m['n']} {m['title']}"
    out += [_ms_line(m) for m in milestones] or ["*(none)*"]
    out += ["", "## Workstreams", ""]
    out += ([f"- `{w['workstream']}` — {w['status']}" for w in workstreams]
            or ["*(none linked)*"])
    out += [
        "", "## Health Assessment", "",
        f"**{health}** — *state the evidence for this call; cite lines in `index.md` "
        "or a linked workstream. A health value without evidence is an assertion.*",
        "", "## Movement Since Last Checkpoint", "",
        "*What changed, what did not, and why. Compare against the previous entry in "
        "this folder.*",
        "", "## Decisions Taken", "",
        "*Anything decided at this checkpoint. Material decisions also belong in the "
        "objective's append-only `## Key Decisions Log`.*",
        "", "## Harness Friction", "",
        "*Only how the objective machinery performed this cycle — a command that "
        "misbehaved, an instruction that was wrong, a checkpoint step that could not be "
        "carried out. Not progress, not blockers on the work itself. Would it still "
        "be true for an unrelated objective? If not, it belongs above. Usually empty; "
        "carry anything unresolved to `_harness/friction.md`.*",
        "", "## Next Checkpoint", "",
        f"*Per cadence `{cadence}`.*", "",
    ]
    return "\n".join(out)

def cmd_checkpoint(args):
    _, text = read_index(args.name)
    require_migrated(args.name)
    when = args.date or today()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", when):
        die(f"invalid date '{when}' — expected YYYY-MM-DD")
    cdir = checkpoint_dir(args.name)
    cdir.mkdir(parents=True, exist_ok=True)
    dest = cdir / f"{when}.md"
    if dest.exists() and not args.force:
        die(f"checkpoint already exists: {dest} — pass --force to overwrite")
    harnesslib.write_text(dest, render_checkpoint(args.name, text, when, milestone_view(args.name)))
    print(f"checkpoint written: {dest}")


def cmd_log_decision(args):
    idx_path, idx_text = read_index(args.name)
    idx_text = log_decision_text(idx_text, args.decision, args.rationale, args.by)
    harnesslib.write_text(idx_path, idx_text)
    print(f"logged: {args.decision}")


def log_decision_text(idx_text, decision, rationale, by=None):
    """Append a row to '## Key Decisions Log' in already-loaded index text.

    Shared by cmd_log_decision and the closure commands (complete/abandon), which
    need to log a decision as part of a larger edit before writing index.md once.
    """
    new_row = f"| {decision} | {rationale} | {by or harnesslib.git_user(WORKSPACE)} | {today()} |"
    # D17: function replacement (decision text may hold backslashes / group refs), count=1.
    return re.sub(
        r"(## Key Decisions Log\n\n\|[^\n]+\n\|[-|]+\n(?:\|[^\n]+\n)*)",
        lambda m: m.group(1) + new_row + "\n",
        idx_text,
        count=1,
    )


def cmd_complete(args):
    idx_path, idx_text = read_index(args.name)
    today_s = today()

    if "completed:" in idx_text:
        idx_text = fm_set(idx_text, "completed", today_s)
    else:
        idx_text = idx_text.replace("status: active", f"status: complete\ncompleted: {today_s}", 1)
    idx_text = set_status(idx_text, "complete")

    reason = getattr(args, "reason", None) or "Reached its Definition of Done"
    idx_text = log_decision_text(idx_text, "Objective completed", reason)

    portfolio = PORTFOLIO_INDEX.read_text(encoding="utf-8")
    dest = archive_path(args.name, "complete")
    link = f"{dest.relative_to(OBJECTIVES_DIR).as_posix()}/index.md"
    # D17: the row moves from Active to the Complete table (it used to stay in Active).
    # Validate (may die) before any write so a refusal leaves index.md untouched.
    portfolio = move_portfolio_row(portfolio, args.name, "## Complete", link, today_s, reason)
    harnesslib.write_text(idx_path, idx_text)
    harnesslib.write_text(PORTFOLIO_INDEX, portfolio)

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(OBJECTIVES_DIR / args.name), str(dest))

    print(f"logged decision and completed: {args.name}")
    print(f"moved to: {dest}")


def cmd_abandon(args):
    idx_path, idx_text = read_index(args.name)
    today_s = today()
    disposition = args.disposition or "abandoned"

    if "completed:" in idx_text:
        idx_text = fm_set(idx_text, "completed", today_s)
    else:
        idx_text = idx_text.replace("status: active", f"status: abandoned\ncompleted: {today_s}", 1)
    idx_text = set_status(idx_text, "abandoned")

    decision_text = ("Objective abandoned" if disposition == "abandoned"
                      else f"Objective abandoned — {disposition}")
    idx_text = log_decision_text(idx_text, decision_text, args.reason)

    portfolio = PORTFOLIO_INDEX.read_text(encoding="utf-8")
    dest = archive_path(args.name, disposition)
    link = f"{dest.relative_to(OBJECTIVES_DIR).as_posix()}/index.md"
    # D17: creates `## Abandoned` when absent instead of dropping the row.
    # Validate before any write (see cmd_complete).
    portfolio = move_portfolio_row(portfolio, args.name, "## Abandoned", link, today_s, args.reason)
    harnesslib.write_text(idx_path, idx_text)
    harnesslib.write_text(PORTFOLIO_INDEX, portfolio)

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(OBJECTIVES_DIR / args.name), str(dest))

    print(f"logged decision and abandoned: {args.name}")
    print(f"moved to: {dest}")


def cmd_health(args):
    if args.value not in VALID_HEALTH:
        die(f"health must be one of: {', '.join(VALID_HEALTH)}")
    idx_path, idx_text = read_index(args.name)
    idx_text = fm_set(idx_text, "health", args.value)
    harnesslib.write_text(idx_path, idx_text)
    print(f"health set: {args.value}")


def cmd_set_cadence(args):
    if args.cadence not in VALID_CADENCE:
        die(f"cadence must be one of: {', '.join(VALID_CADENCE)}")
    idx_path, idx_text = read_index(args.name)
    idx_text = fm_set(idx_text, "cadence", args.cadence)
    harnesslib.write_text(idx_path, idx_text)
    print(f"cadence set: {args.cadence}")


def cmd_add_kr(args):
    idx_path, idx_text = read_index(args.name)
    rows = _parse_kr_table(idx_text)
    # Idempotent by result label
    if any(r["result"] == args.result for r in rows):
        die(f"KR already exists: {args.result}")
    rows.append({"result": args.result, "current": "—", "target": args.target,
                 "updated": today()})
    idx_text = replace_section(idx_text, KR_HEADER, _render_kr_section(rows))
    harnesslib.write_text(idx_path, idx_text)
    print(f"added KR: {args.result}")


def cmd_update_kr(args):
    idx_path, idx_text = read_index(args.name)
    rows = _parse_kr_table(idx_text)
    found = False
    for r in rows:
        if r["result"] == args.result:
            r["current"] = args.current
            r["updated"] = today()
            found = True
            break
    if not found:
        die(f"KR not found: {args.result}")
    idx_text = replace_section(idx_text, KR_HEADER, _render_kr_section(rows))
    harnesslib.write_text(idx_path, idx_text)
    print(f"updated KR: {args.result} → {args.current}")


def cmd_add_milestone(args):
    read_index(args.name)
    d = require_migrated(args.name)
    title = (args.title or "").strip()
    if not title:
        die("--title is required")
    ms = list_milestones(args.name)
    if any(m["fm"].get("title") == title for m in ms):
        die(f"milestone already exists: {title}")
    if getattr(args, "id", None) is not None:
        if args.id < 0:
            die("--id must be 0 or greater")
        n = args.id
        if any(m["n"] == n for m in ms):
            die(f"milestone already exists: {args.name}#{n}")
    else:
        n = max([m["n"] for m in ms], default=0) + 1
    rid = f"{args.name}#{n}"
    deps, locks = flat_list(args.depends_on), flat_list(args.locks)
    related, fed_by = flat_list(args.related), flat_list(args.fed_by)
    inputs, backlog = flat_list(getattr(args, "inputs", None)), flat_list(getattr(args, "backlog", None))
    unit = (getattr(args, "unit", None) or "").strip()
    if unit and not re.fullmatch(r"(workstream|assignment|cadence):[a-z0-9-]+", unit):
        die(f"bad --unit '{unit}' (expected workstream:|assignment:|cadence:<name>)")
    validate_links(rid, deps, locks, fed_by)
    need_paths(inputs, backlog)
    R = harnesslib.render_value
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "milestone"
    lines = ["---", "note_type: milestone", f"id: {rid}", f"title: {R(title)}", "status: open",
             f"order: {args.order if args.order is not None else n}",
             f"conditional: {'true' if args.conditional else 'false'}",
             f"depends_on: {R(deps)}", f"related: {R(related)}", f"locks: {R(locks)}",
             f"fed_by: {R(fed_by)}", f"inputs: {R(inputs)}", f"backlog: {R(backlog)}",
             f"unit: {unit}" if unit else "unit:"]
    if args.ref:
        lines.append(f"ref: {R(args.ref)}")
    if getattr(args, "legacy", None):
        lines.append(f"legacy: {R(args.legacy)}")
    lines += ["---", "", "## Sub-steps", ""]
    lines += [f"- [ ] {s}" for s in (getattr(args, "substep", None) or [])]
    harnesslib.write_text(d / f"{n:02d}-{slug}.md", "\n".join(lines) + "\n")
    render_milestones(args.name)
    print(f"added milestone: {rid} {title}")


def _open_backlog_rows(fm):
    for b in fm.get("backlog") or []:
        p = WORKSPACE / b
        if p.exists():
            try:
                c = harnesslib.backlog_counts(harnesslib.backlog_parse(p)["rows"])
            except harnesslib.HarnessError:
                continue
            if c["open"]:
                return b, c["open"]
    return None


def cmd_check_milestone(args):
    read_index(args.name)
    require_migrated(args.name)
    m = find_milestone(args.name, args.text)
    st = m["fm"].get("status")
    if st in ("done", "dropped"):
        die(f"milestone {m['id']} is already {st}")
    ob = _open_backlog_rows(m["fm"])
    if ob:
        die(f"milestone {m['id']} has {ob[1]} open backlog row(s) in {ob[0]}")
    when = need_date(args.date, "--date") if getattr(args, "date", None) else today()
    harnesslib.fm_write(m["path"], {"status": "done", "done": when})
    render_milestones(args.name)
    print(f"checked milestone: {m['id']} {m['fm'].get('title', '')}")


def cmd_set_milestone(args):
    read_index(args.name)
    require_migrated(args.name)
    m = find_milestone(args.name, args.key)
    upd = {}
    if args.title is not None:
        upd["title"] = args.title
    if args.order is not None:
        upd["order"] = args.order
    if args.conditional is not None:
        upd["conditional"] = args.conditional
    if args.ref is not None:
        upd["ref"] = args.ref
    if args.unit is not None:
        upd["unit"] = args.unit
    if getattr(args, "legacy", None) is not None:
        upd["legacy"] = args.legacy
    if getattr(args, "done", None) is not None:
        upd["done"] = need_date(args.done, "--done")
    for f in MS_LIST_FIELDS + ("inputs", "backlog"):
        v = getattr(args, f)
        if v is not None:
            upd[f] = flat_list(v)
    if not upd:
        die("nothing to set")
    fm = dict(m["fm"])
    fm.update(upd)
    validate_links(m["id"], fm.get("depends_on") or [], fm.get("locks") or [], fm.get("fed_by") or [])
    harnesslib.fm_write(m["path"], upd)
    render_milestones(args.name)
    print(f"set milestone: {m['id']} {', '.join(upd)}")


def cmd_drop_milestone(args):
    idx_path, idx_text = read_index(args.name)
    require_migrated(args.name)
    if not (args.reason or "").strip():
        die("--reason is required")
    m = find_milestone(args.name, args.key)
    st = m["fm"].get("status")
    if st in ("done", "dropped"):
        die(f"milestone {m['id']} is already {st}")
    harnesslib.fm_write(m["path"], {"status": "dropped"})
    idx_text = log_decision_text(idx_text, f"Milestone {m['id']} dropped", args.reason)
    harnesslib.write_text(idx_path, idx_text)
    render_milestones(args.name)
    print(f"dropped milestone: {m['id']} (decision logged {today()})")


VALID_LINK_STATUSES = ("active", "complete", "paused", "abandoned")

def cmd_link_workstream(args):
    idx_path, idx_text = read_index(args.objective)
    rows = _parse_workstreams(idx_text)
    ref = normalize_workstream_ref(args.workstream)
    status = getattr(args, "status", None) or "active"
    if status not in VALID_LINK_STATUSES:
        die(f"invalid status '{status}' — must be one of: {', '.join(VALID_LINK_STATUSES)}")
    if not workstream_ref_exists(ref):
        die(f"workstream not found on disk: control-plane/{ref} — "
            "check the name, or pass an explicit path such as "
            "workstreams/_log/YYYY-MM-DD-name")
    # D17: a `_log/DATE-name` link is the same workstream as `name`; update in place, never duplicate.
    canon = canon_workstream(ref)
    ref = f"workstreams/{canon}"
    match = next((r for r in rows if canon_workstream(r["workstream"]) == canon), None)
    if match:
        if match["status"] == status and match["workstream"] == ref:
            print(f"already linked: {ref}")
            return
        match["workstream"], match["status"] = ref, status
    else:
        rows.append({"workstream": ref, "status": status, "linked": today()})
    idx_text = replace_section(idx_text, WORKSTREAMS_HEADER, _render_workstreams_section(rows))
    harnesslib.write_text(idx_path, idx_text)
    print(f"linked workstream: {ref}")


# ---------------------------------------------------------------------------
# next (R5 + R6): computed "what next for objective X"
# ---------------------------------------------------------------------------

TERMINAL_STATUS = {"done", "dropped", "consumed"}
NEXT_ROUTES = ("candidate:", "assignment:", "workstream:")
NO_ORDER = 10 ** 6


class NextCycle(Exception):
    def __init__(self, cycle):
        super().__init__(" -> ".join(cycle))
        self.cycle = cycle


def _order_of(fm):
    try:
        return int(str(fm.get("order")))
    except (TypeError, ValueError):
        return NO_ORDER


def lock_holders(recs):
    """{lock: holder} for every held lock (R6).

    Held when (a) an `active` record, or an open workstream/assignment, declares it, or
    (b) the registry probe fires (holder `uncommitted changes`). Cadences hold a lock
    only through the probe: a cadence is `active` between runs.
    """
    held = {}
    for rid, r in sorted(recs.items()):
        if r["fm"].get("status") == "active":
            for lk in r["fm"].get("locks") or []:
                held.setdefault(lk, rid)
    cpdir = WORKSPACE / "control-plane"
    for kind, folder in (("workstream", "workstreams"), ("assignment", "assignments")):
        base = cpdir / folder
        if not base.is_dir():
            continue
        for idx in sorted(base.glob("*/index.md")):
            if idx.parent.name.startswith("_"):
                continue
            uid = f"{kind}:{idx.parent.name}"
            if harnesslib.unit_state(uid, WORKSPACE) != "open":
                continue
            for lk in harnesslib.fm_read(idx)[0].get("locks") or []:
                held.setdefault(lk, uid)
    for lk, info in harnesslib.load_locks(WORKSPACE).items():
        if lk in held:
            continue
        try:
            fires = harnesslib.probe_fires(WORKSPACE, info["probe"])
        except harnesslib.HarnessError:
            fires = False
        if fires:
            held[lk] = "uncommitted changes"
    return held


def classify_deps(rid, recs):
    """Walk unsatisfied depends_on transitively -> (root_blockers, open_gates, has_nongate)."""
    roots, gates, seen, flag = [], [], set(), [False]

    def deps_of(i):
        r = harnesslib.resolve(i, recs, WORKSPACE)
        d = (r["fm"].get("depends_on") if r else None) or []
        return d if isinstance(d, list) else [d]

    def unsat(i):
        return not harnesslib.satisfied(i, recs, WORKSPACE)

    def walk(i):
        for d in deps_of(i):
            if d in seen or not unsat(d):
                continue
            seen.add(d)
            r = harnesslib.resolve(d, recs, WORKSPACE)
            if r is not None and r["kind"] == "gate" and r["fm"].get("status") == "open":
                gates.append(d)
                roots.append(d)
                continue
            flag[0] = True
            kids = [x for x in deps_of(d) if unsat(x)]
            if r is None or r["kind"] == "gate" or not kids:
                roots.append(d)
            else:
                walk(d)

    walk(rid)
    return roots, gates, flag[0]


def count_unblocks(rid, rev, recs):
    seen, stack = set(), [rid]
    while stack:
        for c in rev.get(stack.pop(), ()):
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return sum(1 for c in seen if c != rid and c in recs
               and recs[c]["fm"].get("status") not in TERMINAL_STATUS)


def backlog_label(fm):
    done = total = 0
    seen = False
    for b in fm.get("backlog") or []:
        p = WORKSPACE / b
        if p.exists():
            try:
                d, t = harnesslib.backlog_progress(p)
            except harnesslib.HarnessError:
                continue
            done, total, seen = done + d, total + t, True
    return f"{done}/{total}" if seen else None


def _claim_of(fm):
    """claimed_by of the unit an item is bound to (its `unit`, else a unit `route`), or None."""
    for key in ("unit", "route"):
        u = str(fm.get(key) or "")
        if harnesslib._unit_kind(u)[0]:
            return harnesslib.unit_claim(WORKSPACE, u)
    return None


def compute_next(name):
    """R5 classification for an objective -> R9 `next` payload (dict). Raises NextCycle."""
    recs = harnesslib.load_records(WORKSPACE)
    graph = harnesslib.build_graph(recs)
    cyc = harnesslib.find_cycle(graph)
    if cyc:
        raise NextCycle(cyc)
    rev = {}
    for rid, deps in graph.items():
        for d in deps:
            rev.setdefault(d, []).append(rid)
    fed = {i for r in recs.values() if r["kind"] == "milestone" for i in r["fm"].get("fed_by") or []}
    cands, active = [], []
    for rid, r in recs.items():
        fm, st = r["fm"], r["fm"].get("status")
        if r["kind"] == "milestone" and rid.startswith(f"{name}#"):
            (cands if st == "open" else active if st == "active" else []).append(rid)
        elif r["kind"] == "intake" and not r["archived"] and fm.get("objective") == name:
            route = str(fm.get("route", ""))
            if st == "triaged" and rid not in fed and (route.startswith(NEXT_ROUTES) or route == "tools"):
                cands.append(rid)
            elif st == "active":
                active.append(rid)
    held = lock_holders(recs)
    ready, blocked, human, lock, claimed = [], [], [], [], []
    ready_locks = {}
    me = None
    for rid in cands:
        fm = recs[rid]["fm"]
        base = {"id": rid, "title": harnesslib.record_title(recs[rid]), "order": _order_of(fm),
                "backlog": backlog_label(fm)}
        holder = _claim_of(fm)
        if holder:
            base["claimed_by"] = holder
            me = me or harnesslib.git_user(WORKSPACE)
            if holder != me:
                claimed.append(base)
                continue
        roots, gates, nongate = classify_deps(rid, recs)
        if nongate:
            blocked.append(dict(base, root_blockers=roots))
        elif gates:
            human.append(dict(base, gates=[
                {"id": g, "who": recs[g]["fm"].get("who", ""), "criteria": recs[g]["fm"].get("criteria", "")}
                for g in gates]))
        else:
            mine = [lk for lk in fm.get("locks") or []]
            busy = [lk for lk in mine if lk in held and held[lk] != rid]
            if busy:
                lock.append(dict(base, lock=busy[0], holder=held[busy[0]]))
            else:
                ready.append(dict(base, unblocks=count_unblocks(rid, rev, recs)))
                ready_locks[rid] = mine
    ready.sort(key=lambda x: (-x["unblocks"], x["order"], x["id"]))
    for lst in (blocked, human, lock):
        lst.sort(key=lambda x: (x["order"], x["id"]))
    notes = []
    for lk in sorted({lk for v in ready_locks.values() for lk in v}):
        ids = [x["id"] for x in ready if lk in ready_locks[x["id"]]]
        if len(ids) > 1:
            notes.append(f"{lk}: only one of these can open: {', '.join(ids)}; top-ranked: {ids[0]}")
    claimed.sort(key=lambda x: (x["order"], x["id"]))
    act = []
    for i in sorted(active):
        item = {"id": i, "title": harnesslib.record_title(recs[i]), "backlog": backlog_label(recs[i]["fm"])}
        if _claim_of(recs[i]["fm"]):
            item["claimed_by"] = _claim_of(recs[i]["fm"])
        act.append(item)
    return {"objective": name, "ready": ready, "blocked": blocked, "human": human, "lock": lock,
            "claimed": claimed, "active": act, "notes": notes}


def render_next(res):
    def bl(x):
        return ((f" — backlog {x['backlog']} done" if x.get("backlog") else "")
                + (f" CLAIMED({x['claimed_by']})" if x.get("claimed_by") else ""))
    out = [f"next: {res['objective']}", ""]
    out.append("READY")
    for n, x in enumerate(res["ready"], 1):
        out.append(f"  {n}. {x['id']} {x['title']} (unblocks {x['unblocks']}" + (f", order {x['order']}" if x['order'] != NO_ORDER else "") + f"){bl(x)}")
    if not res["ready"]:
        out.append("  (none)")
    for label, key in (("BLOCKED", "blocked"), ("HUMAN", "human"), ("LOCK", "lock"), ("CLAIMED", "claimed")):
        if res[key]:
            out += ["", label]
            for x in res[key]:
                if key == "blocked":
                    out.append(f"  {x['id']} {x['title']} <- {', '.join(x['root_blockers'])}{bl(x)}")
                elif key == "human":
                    gs = "; ".join(f"{g['id']} (who: {g['who']}; {g['criteria']})" for g in x["gates"])
                    out.append(f"  {x['id']} {x['title']} <- {gs}{bl(x)}")
                elif key == "claimed":
                    out.append(f"  {x['id']} {x['title']}{bl(x)}")
                else:
                    out.append(f"  {x['id']} {x['title']} <- lock {x['lock']} held by {x['holder']}{bl(x)}")
    if res["active"]:
        out += ["", "ACTIVE"] + [f"  {x['id']} {x['title']}{bl(x)}" for x in res["active"]]
    if res["notes"]:
        out += [""] + [f"note: {n}" for n in res["notes"]]
    return "\n".join(out)


def cmd_next(args):
    read_index(args.name)
    require_migrated(args.name)
    try:
        res = compute_next(args.name)
    except NextCycle as e:
        print("error: dependency cycle: " + " -> ".join(e.cycle), file=sys.stderr)
        sys.exit(2)
    if args.json:
        print(json.dumps(harnesslib.envelope("next", **res), indent=2))
    else:
        print(render_next(res))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Objective state management")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")

    sub.add_parser("status").add_argument("name")

    s = sub.add_parser("complete")
    s.add_argument("name")
    s.add_argument("--reason", help="rationale recorded in the Key Decisions Log "
                                     "(default: 'Reached its Definition of Done')")

    s = sub.add_parser("abandon")
    s.add_argument("name")
    s.add_argument("--reason", required=True)
    s.add_argument("--disposition", default="abandoned",
                   help="free-text disposition recorded in the objective's own Key Decisions "
                        "Log and used to pick the archive bucket, e.g. "
                        "'merged into gtm-enablement' (default: abandoned)")

    from_example = ""
    s = sub.add_parser("create")
    s.add_argument("name")
    s.add_argument("--title")
    s.add_argument("--from", dest="origin", metavar="PATH",
                   help="the workstream or cadence that outgrew its tier" + from_example +
                        ". Records the promotion.")
    s.add_argument("--group",
                   help="### subgroup of the Active table to insert into "
                        "(e.g. 'Infrastructure Builds'); defaults to the first")

    s = sub.add_parser("checkpoint",
                       help="scaffold a dated checkpoint entry in objectives/<name>/checkpoints/")
    s.add_argument("name")
    s.add_argument("--date", help="checkpoint date (YYYY-MM-DD); defaults to today")
    s.add_argument("--force", action="store_true",
                   help="overwrite an existing entry for that date")

    s = sub.add_parser("log-decision")
    s.add_argument("name")
    s.add_argument("decision")
    s.add_argument("rationale")
    s.add_argument("--by", metavar="NAME", help="who decided (default: git config user.name, else 'operator')")

    s = sub.add_parser("health")
    s.add_argument("name")
    s.add_argument("value")

    s = sub.add_parser("set-cadence")
    s.add_argument("name")
    s.add_argument("cadence")

    s = sub.add_parser("add-kr")
    s.add_argument("name")
    s.add_argument("result")
    s.add_argument("target")

    s = sub.add_parser("update-kr")
    s.add_argument("name")
    s.add_argument("result")
    s.add_argument("current")

    s = sub.add_parser("add-milestone")
    s.add_argument("name")
    s.add_argument("--title", required=True)
    for f in ("depends-on", "locks", "fed-by", "related"):
        s.add_argument(f"--{f}", action="append")
    s.add_argument("--ref")
    s.add_argument("--order", type=int)
    s.add_argument("--conditional", action="store_true")
    s.add_argument("--id", type=int, metavar="N", help="explicit milestone number, including 0 (default: max+1)")
    s.add_argument("--unit", metavar="workstream:|assignment:|cadence:<name>")
    for f in ("inputs", "backlog"):
        s.add_argument(f"--{f}", action="append")
    s.add_argument("--legacy", help="original checklist line, verbatim")
    s.add_argument("--substep", action="append", help="body checklist item (repeatable; commas kept)")

    s = sub.add_parser("check-milestone")
    s.add_argument("name")
    s.add_argument("text", help="N, #N, or exact title/legacy line")
    s.add_argument("--date", metavar="YYYY-MM-DD", help="completion date (default: today)")

    s = sub.add_parser("set-milestone")
    s.add_argument("name")
    s.add_argument("key", help="N, #N, or exact title")
    s.add_argument("--title")
    s.add_argument("--order", type=int)
    s.add_argument("--conditional", choices=("true", "false"))
    s.add_argument("--ref")
    s.add_argument("--unit")
    s.add_argument("--legacy", help="original checklist line, verbatim")
    s.add_argument("--done", metavar="YYYY-MM-DD", help="completion date field (status stays command-driven)")
    for f in ("depends-on", "locks", "fed-by", "related", "inputs", "backlog"):
        s.add_argument(f"--{f}", action="append")

    s = sub.add_parser("drop-milestone")
    s.add_argument("name")
    s.add_argument("key", help="N, #N, or exact title")
    s.add_argument("--reason", required=True)

    s = sub.add_parser("next", help="compute READY/BLOCKED/HUMAN/LOCK for an objective's open work")
    s.add_argument("name")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("render", help="re-render generated views in an objective's index.md")
    s.add_argument("name", nargs="?")
    s.add_argument("--all", action="store_true")
    s.add_argument("--check", action="store_true", help="exit 1 if any region is stale")
    s.add_argument("--force", action="store_true", help="overwrite a hand-edited region")
    s.add_argument("--adopt", action="store_true",
                   help="first render: replace the hand-kept section body with a marked region")
    s.add_argument("--resolve", action="store_true",
                   help="drop both sides of a git conflict inside a generated region, then re-render it")

    s = sub.add_parser("link-workstream")
    s.add_argument("objective")
    s.add_argument("workstream",
                   help="bare name, workstreams/<name>, or workstreams/_log/<entry>")
    s.add_argument("--status", choices=VALID_LINK_STATUSES, default="active",
                   help="link status (default: active)")

    args = p.parse_args()
    {
        "list":            cmd_list,
        "status":          cmd_status,
        "create":          cmd_create,
        "log-decision":    cmd_log_decision,
        "complete":        cmd_complete,
        "abandon":         cmd_abandon,
        "health":          cmd_health,
        "set-cadence":     cmd_set_cadence,
        "add-kr":          cmd_add_kr,
        "update-kr":       cmd_update_kr,
        "add-milestone":   cmd_add_milestone,
        "check-milestone": cmd_check_milestone,
        "set-milestone":   cmd_set_milestone,
        "drop-milestone":  cmd_drop_milestone,
        "next":            cmd_next,
        "render":          cmd_render,
        "link-workstream":    cmd_link_workstream,
        "checkpoint":         cmd_checkpoint,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
