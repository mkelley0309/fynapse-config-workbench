#!/usr/bin/env python3
"""harnesslib - shared control-plane primitives (stdlib only, Python 3.12).

Areas: root discovery, frontmatter read/write, EOL-preserving splice writes,
records graph, generated regions, outputs path normalisation, small helpers.

Import from sibling tools:
    sys.path.insert(0, str(Path(__file__).resolve().parent)); import harnesslib

Write rule: nothing here ever normalises a whole file's line endings. Untouched
lines keep their own bytes; a new line takes the EOL of the line above it (or the
one below, at the top); a new file is LF.
"""

import datetime
import difflib
import hashlib
import json
import os
import re
import sys
from pathlib import Path


class HarnessError(Exception):
    pass


class RegionEdited(HarnessError):
    """A generated region's content no longer matches its recorded sha."""


class RegionMissing(HarnessError):
    pass


# --------------------------------------------------------------------------- helpers

def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def today():
    return datetime.date.today().isoformat()


def kebab_ok(name):
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name or ""))


# --------------------------------------------------------------------------- root

def _walk_up(start):
    start = Path(start).resolve()
    for cand in (start, *start.parents):
        if (cand / "control-plane").is_dir():
            return cand
    return None


def find_root():
    """Walk up from cwd to a directory containing control-plane/ (R1).

    WORKSPACE_ROOT, when set, must agree with that walk-up (R2): a different root dies naming
    both, because an env var silently overriding cwd wrote into the wrong workspace. When cwd has
    no control-plane/ ancestor the env root wins."""
    cwd = Path(os.getcwd()).resolve()
    cwd_root = _walk_up(cwd)
    env = os.environ.get("WORKSPACE_ROOT")
    if env:
        env_root = _walk_up(env)
        if env_root is None:
            die(f"no workspace root found (no control-plane/ at or above WORKSPACE_ROOT={Path(env).resolve()})")
        if cwd_root is not None and os.path.normcase(str(cwd_root)) != os.path.normcase(str(env_root)):
            die(f"WORKSPACE_ROOT={env_root} disagrees with the workspace found from the current directory "
                f"({cwd_root}); unset WORKSPACE_ROOT or run from inside {env_root}")
        return env_root
    if cwd_root is None:
        die(f"no workspace root found (no control-plane/ at or above {cwd})")
    return cwd_root


def git_user(root=None):
    """`git config user.name` of the root repo, else 'operator'."""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(root or find_root()), "config", "user.name"],
                           capture_output=True, text=True, encoding="utf-8")
        name = r.stdout.strip()
    except OSError:
        name = ""
    return name or "operator"


def rel_cmd(script, root=None):
    """Build a `python -B <relpath>` hint string for a tools script."""
    here = Path(__file__).resolve().parent
    base = Path(root).resolve() if root else here.parent
    try:
        rel = (here / script).relative_to(base)
    except ValueError:
        rel = Path("tools") / script
    return f"python -B {rel.as_posix()}"


# --------------------------------------------------------------------------- splice write

def _split_lines(raw):
    """bytes -> list of [content_bytes, eol_bytes]; each line keeps its own EOL."""
    parts = raw.split(b"\n")
    lines = []
    for p in parts[:-1]:
        if p.endswith(b"\r"):
            lines.append([p[:-1], b"\r\n"])
        else:
            lines.append([p, b"\n"])
    if parts[-1]:
        lines.append([parts[-1], b""])
    return lines


def _join_lines(lines):
    return b"".join(c + e for c, e in lines)


def _neighbor_eol(lines, i):
    """EOL for a line inserted at index i: the line above, else the one below, else LF."""
    for j in range(min(i, len(lines)) - 1, -1, -1):
        if lines[j][1]:
            return lines[j][1]
    for j in range(max(i, 0), len(lines)):
        if lines[j][1]:
            return lines[j][1]
    return b"\n"


def splice_lines(raw, edits, final_newline=None):
    """Apply line edits to raw bytes. edits: [(start, end, [str, ...])] over original
    line indexes, end exclusive, non-overlapping. Returns new bytes."""
    lines = _split_lines(raw)
    for start, end, new in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        old = lines[start:end]
        out = []
        for k, text in enumerate(new):
            if k < len(old) and old[k][1]:
                eol = old[k][1]
            elif out:
                eol = out[-1][1] or b"\n"
            else:
                eol = _neighbor_eol(lines, start)
            out.append([text.encode("utf-8"), eol])
        lines[start:end] = out
    for i, ln in enumerate(lines[:-1]):
        if not ln[1]:
            ln[1] = _neighbor_eol(lines, i)
    if lines:
        if final_newline is True and not lines[-1][1]:
            lines[-1][1] = _neighbor_eol(lines, len(lines) - 1)
        elif final_newline is False:
            lines[-1][1] = b""
    return _join_lines(lines)


def _eol_guard(path, raw, new):
    """R11: refuse a write that turns an all-CRLF file into one holding LF-only lines."""
    nl, crlf = raw.count(b"\n"), raw.count(b"\r\n")
    if nl and nl == crlf and new.count(b"\n") != new.count(b"\r\n"):
        raise HarnessError(f"{path}: refusing write: an all-CRLF file would gain LF-only lines")


def splice_write(path, edits, final_newline=None):
    """Splice line edits into a file in place, byte-preserving elsewhere.
    A missing file is created (LF) from the edits applied to nothing."""
    path = Path(path)
    if path.exists():
        raw = path.read_bytes()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = b""
    new = splice_lines(raw, edits, final_newline)
    _eol_guard(path, raw, new)
    if new != raw:
        path.write_bytes(new)
    return new != raw


def write_text(path, text):
    """Write full text by diffing it against the file and splicing only changed lines.

    The drop-in replacement for Path.write_text in tools that rebuild a whole text:
    a one-line change touches one line, whatever EOL the file uses. New files are LF.
    """
    path = Path(path)
    text = text.replace("\r\n", "\n")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return True
    raw = path.read_bytes()
    old_lines = [c.decode("utf-8") for c, _ in _split_lines(raw)]
    new_lines = text.split("\n")
    ends_nl = text.endswith("\n")
    if new_lines and new_lines[-1] == "":
        new_lines.pop()
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    edits = [(i1, i2, new_lines[j1:j2]) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]
    old_ends_nl = raw.endswith(b"\n")
    final = None
    if new_lines and ends_nl != old_ends_nl:
        final = ends_nl
    if not edits and final is None:
        return False
    return splice_write(path, edits, final)


# --------------------------------------------------------------------------- frontmatter

def _decode_lines(path):
    return [c.decode("utf-8") for c, _ in _split_lines(Path(path).read_bytes())]


def _fm_bounds(lines):
    """(start, end) line indexes of the frontmatter body, exclusive of fences, or None."""
    if not lines or lines[0].rstrip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return 1, i
    return None


def _split_flow(inner):
    items, cur, q = [], "", None
    for ch in inner:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            cur += ch
        elif ch == ",":
            items.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip() or items:
        items.append(cur)
    return [parse_scalar(i.strip()) for i in items if i.strip()]


def parse_scalar(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        try:
            return json.loads(s)
        except ValueError:
            return s[1:-1]
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    return s


def parse_value(raw):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return _split_flow(raw[1:-1])
    return parse_scalar(raw)


class Raw(str):
    """A frontmatter value written verbatim (already quoted by the caller)."""


def render_value(v):
    if isinstance(v, Raw):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_render_item(i) for i in v) + "]"
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return _render_item(v)


def _render_item(v):
    s = str(v)
    if s == "":
        return ""
    if (s != s.strip() or ": " in s or " #" in s or s[0] in "[{\"'>|*&!%@`#,"
            or s.endswith(":") or "," in s and False):
        return json.dumps(s, ensure_ascii=False)
    return s


def fm_parse(text):
    """Parse frontmatter from text -> (dict, body_start_line). ({}, 0) when absent."""
    lines = text.replace("\r\n", "\n").split("\n")
    return _fm_from_lines(lines)


def _fm_from_lines(lines):
    b = _fm_bounds(lines)
    if not b:
        return {}, 0
    out = {}
    for ln in lines[b[0]:b[1]]:
        m = re.match(r"^([A-Za-z_][\w-]*):(.*)$", ln.rstrip("\r"))
        if m:
            out[m.group(1)] = parse_value(m.group(2))
    return out, b[1] + 1


def fm_read(path):
    """-> (dict, body_span). body_span = (first_body_line, line_count) over file lines."""
    lines = _decode_lines(path)
    fm, body = _fm_from_lines(lines)
    return fm, (body, len(lines))


def fm_write(path, updates):
    """Set frontmatter keys in place. Existing keys change only their own line; new
    keys append before the closing fence; key order and unknown keys are kept."""
    lines = _decode_lines(path)
    b = _fm_bounds(lines)
    if not b:
        raise HarnessError(f"{path}: no terminated frontmatter fence")
    start, end = b
    edits = []
    pending = dict(updates)
    for i in range(start, end):
        m = re.match(r"^([A-Za-z_][\w-]*):", lines[i])
        if m and m.group(1) in pending:
            key = m.group(1)
            val = render_value(pending.pop(key))
            edits.append((i, i + 1, [f"{key}: {val}" if val != "" else f"{key}:"]))
    if pending:
        add = []
        for key, v in pending.items():
            val = render_value(v)
            add.append(f"{key}: {val}" if val != "" else f"{key}:")
        edits.append((end, end, add))
    return splice_write(path, edits)


def fm_delete(path, keys):
    """Remove frontmatter keys (and nothing else). -> True when a line was removed."""
    lines = _decode_lines(path)
    b = _fm_bounds(lines)
    if not b:
        raise HarnessError(f"{path}: no terminated frontmatter fence")
    keys = set(keys)
    edits = []
    for i in range(b[0], b[1]):
        m = re.match(r"^([A-Za-z_][\w-]*):", lines[i])
        if m and m.group(1) in keys:
            edits.append((i, i + 1, []))
    return splice_write(path, edits) if edits else False


# --------------------------------------------------------------------------- regions

def _sha8(text):
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()[:8]


def _region_find(lines, view):
    open_re = re.compile(rf"^\s*<!-- generated:{re.escape(view)} -->\s*$")
    close_re = re.compile(rf"^\s*<!-- /generated:{re.escape(view)}(?: sha=([0-9a-f]{{8}}))? -->\s*$")
    o = None
    for i, ln in enumerate(lines):
        if o is None and open_re.match(ln):
            o = i
        elif o is not None:
            m = close_re.match(ln)
            if m:
                return o, i, m.group(1)
    raise RegionMissing(f"region '{view}' not found")


def _norm_region_text(text):
    text = text.replace("\r\n", "\n")
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def region_stale(path, view, text):
    lines = _decode_lines(path)
    o, c, sha = _region_find(lines, view)
    cur = "".join(l + "\n" for l in lines[o + 1:c])
    want = _norm_region_text(text)
    return cur != want or sha != _sha8(want)


def render_region(path, view, text, force=False):
    """Replace the generated region body and refresh its sha. Refuses (RegionEdited)
    when the existing body no longer matches its recorded sha, unless force."""
    lines = _decode_lines(path)
    o, c, sha = _region_find(lines, view)
    cur = "".join(l + "\n" for l in lines[o + 1:c])
    if sha is not None and sha != _sha8(cur) and not force:
        raise RegionEdited(f"region '{view}' was hand-edited; use --force")
    want = _norm_region_text(text)
    body = want.split("\n")[:-1] if want else []
    close_old = lines[c]
    indent = re.match(r"^\s*", close_old).group(0)
    edits = [(o + 1, c, body), (c, c + 1, [f"{indent}<!-- /generated:{view} sha={_sha8(want)} -->"])]
    # merge into one edit to keep indices valid
    edits = [(o + 1, c + 1, body + [edits[1][2][0]])]
    return splice_write(path, edits)


def region_exists(path, view):
    try:
        _region_find(_decode_lines(path), view)
        return True
    except RegionMissing:
        return False


def region_block(view, text):
    """Marked region lines (open marker, body, close marker with sha) for a view text."""
    want = _norm_region_text(text)
    body = want.split("\n")[:-1] if want else []
    return [f"<!-- generated:{view} -->"] + body + [f"<!-- /generated:{view} sha={_sha8(want)} -->"]


def _section_span(lines, heading):
    s = next((i for i, ln in enumerate(lines) if ln.rstrip() == heading), None)
    if s is None:
        return None, None
    e = len(lines)
    for i in range(s + 1, len(lines)):
        if re.match(r"^#{1,2} ", lines[i]):
            e = i
            break
    return s, e


def adopt_region(path, heading, view, text, after=None, before="## Related Notes"):
    """First render of a view into a file that has no region yet. Replaces only the body of
    the `heading` section with a marked region (heading line kept). When the section is absent
    it is inserted after the `after` section, else before `before`, else at end of file."""
    lines = _decode_lines(path)
    block = region_block(view, text)
    s, e = _section_span(lines, heading)
    if s is not None:
        tail = [""] if e < len(lines) else []
        return splice_write(path, [(s + 1, e, [""] + block + tail)])
    sect = [heading, ""] + block + [""]
    if after:
        a_s, a_e = _section_span(lines, after)
        if a_s is not None:
            return splice_write(path, [(a_e, a_e, sect)])
    b_s, _ = _section_span(lines, before) if before else (None, None)
    if b_s is not None:
        return splice_write(path, [(b_s, b_s, sect)])
    pre = [""] if lines and lines[-1].strip() else []
    return splice_write(path, [(len(lines), len(lines), pre + sect[:-1])])


def render_view(path, view, text, heading, force=False, adopt=False, check=False, after=None):
    """Render one generated view. -> 'ok' | 'rendered' | 'adopted' | 'stale' | 'skipped'.
    'skipped' = no region and no --adopt. Raises RegionEdited on a hand-edited region (no force)."""
    if not region_exists(path, view):
        if not adopt:
            return "skipped"
        if check:
            return "stale"
        adopt_region(path, heading, view, text, after=after)
        return "adopted"
    stale = region_stale(path, view, text)
    if check:
        return "stale" if stale else "ok"
    if not stale:
        return "ok"
    render_region(path, view, text, force=force)
    return "rendered"


# --------------------------------------------------------------------------- outputs refs

_OUT_RE = re.compile(r"(?:^|[^A-Za-z0-9_-])outputs/")


def norm_outputs_ref(s):
    """Normalise a reference to an outputs folder -> (folder|None, archived, defect|None).

    Handles backticked paths, paths with files, ../ forms, code-relative joins,
    outputs/_archive/<f>, the stale control-plane/outputs prefix (defect
    'stale-prefix') and backslash separators. Exclusions return (None, False, None).
    """
    t = s.strip().strip("`").replace("\\", "/")
    m = _OUT_RE.search(t)
    if not m:
        return None, False, None
    before = t[: m.end() - len("outputs/")]
    defect = "stale-prefix" if re.search(r"control-plane/$", before) else None
    rest = t[m.end():]
    rest = re.split(r"[\"'`)\s]", rest, maxsplit=1)[0]
    parts = [p for p in rest.split("/") if p and p != "."]
    archived = False
    if parts and parts[0] == "_archive":
        archived = True
        parts = parts[1:]
    if not parts:
        return None, False, None
    folder = parts[0]
    if folder in ("index", "index.md"):
        return None, False, None
    return folder, archived, defect


# --------------------------------------------------------------------------- records

_TERMINAL = {"consumed", "dropped", "done"}


def _cp(root):
    return Path(root) / "control-plane"


def _record(kind, rid, path, archived=False):
    fm, span = fm_read(path)
    return {"id": rid, "kind": kind, "path": Path(path), "fm": fm,
            "body_span": span, "archived": archived}


def record_title(rec):
    """Display title: frontmatter `title` (milestones, gates), else the first `# ` heading in the body
    (intake records keep their title there), else the id."""
    t = rec["fm"].get("title")
    if t:
        return str(t)
    try:
        for ln in Path(rec["path"]).read_text(encoding="utf-8").splitlines()[rec["body_span"][0] if rec.get("body_span") else 0:]:
            if ln.startswith("# "):
                return ln[2:].strip()
    except (OSError, TypeError, IndexError):
        pass
    return rec["id"]


def load_records(root=None, dups=None):
    """Scan intake, intake/_archive, milestones and gates -> {id: record}.

    Last record wins on a repeated id. Pass a list as `dups` to collect (id, kept_path, lost_path)
    for every repeat (R3: `intake.py check` reports them)."""
    root = Path(root) if root else find_root()
    cp = _cp(root)
    recs = {}

    def put(r):
        if r["id"] in recs and dups is not None:
            dups.append((r["id"], recs[r["id"]]["path"], r["path"]))
        recs[r["id"]] = r

    for sub, archived in (("intake", False), ("intake/_archive", True)):
        d = cp / sub
        if d.is_dir():
            for p in sorted(d.glob("*.md")):
                if p.name == "index.md":
                    continue
                r = _record("intake", f"intake:{p.stem}", p, archived)
                if r["fm"].get("note_type") == "intake":
                    put(r)
    objs = cp / "objectives"
    if objs.is_dir():
        for p in sorted(objs.glob("*/milestones/*.md")):
            fm, _ = fm_read(p)
            if fm.get("note_type") == "milestone" and fm.get("id"):
                put(_record("milestone", fm["id"], p))
    g = cp / "gates"
    if g.is_dir():
        for p in sorted(g.glob("*.md")):
            r = _record("gate", f"gate:{p.stem}", p)
            if r["fm"].get("note_type") == "gate":
                put(r)
    return recs


def _unit_kind(rid):
    m = re.match(r"^(workstream|assignment|cadence):(.+)$", rid)
    return (m.group(1), m.group(2)) if m else (None, None)


def resolve(rid, records=None, root=None):
    """Return the record for an ID; unit IDs resolve to a pseudo-record; else None."""
    records = records if records is not None else load_records(root)
    if rid in records:
        return records[rid]
    kind, name = _unit_kind(rid)
    if kind:
        return {"id": rid, "kind": "unit", "unit_kind": kind, "name": name, "fm": {}}
    return None


def build_graph(records=None, root=None):
    """{id: [depends_on ids]} over records."""
    records = records if records is not None else load_records(root)
    out = {}
    for rid, r in records.items():
        dep = r["fm"].get("depends_on") or []
        out[rid] = list(dep) if isinstance(dep, list) else [dep]
    return out


def find_cycle(graph=None, records=None, root=None):
    """Return a cycle as [a, b, ..., a], or None."""
    graph = graph if graph is not None else build_graph(records, root)
    state = {}
    stack = []

    def visit(n):
        state[n] = 1
        stack.append(n)
        for m in graph.get(n, []):
            if state.get(m) == 1:
                return stack[stack.index(m):] + [m]
            if state.get(m) is None and m in graph:
                c = visit(m)
                if c:
                    return c
        stack.pop()
        state[n] = 2
        return None

    for n in list(graph):
        if state.get(n) is None:
            c = visit(n)
            if c:
                return c
    return None


def unit_state(unit_id, root=None):
    """-> 'closed' | 'open' | 'absent' for workstream:/assignment:/cadence: IDs (R1)."""
    root = Path(root) if root else find_root()
    cp = _cp(root)
    kind, name = _unit_kind(unit_id)
    if not kind:
        raise HarnessError(f"not a unit id: {unit_id}")
    if kind == "workstream":
        log = cp / "workstreams" / "_log"
        if log.is_dir() and any(log.glob(f"*-{name}.md")):
            return "closed"
        idx = cp / "workstreams" / "index.md"
        if idx.exists():
            txt = idx.read_text(encoding="utf-8")
            m = re.search(r"^##\s+Recently Completed\s*$(.*?)(?=^##\s|\Z)", txt, re.M | re.S)
            if m and re.search(rf"\[{re.escape(name)}\]", m.group(1)):
                return "closed"
        folder = cp / "workstreams" / name / "index.md"
    elif kind == "assignment":
        log = cp / "assignments" / "_log.md"
        if log.exists() and re.search(rf"^##\s+\d{{4}}-\d{{2}}-\d{{2}}\s+·\s+{re.escape(name)}\s*$",
                                      log.read_text(encoding="utf-8"), re.M):
            return "closed"
        folder = cp / "assignments" / name / "index.md"
    else:
        folder = cp / "cadences" / name / "index.md"
        if folder.exists():
            st = fm_read(folder)[0].get("status")
            if st in ("retired", "abandoned"):
                return "closed"
        log = cp / "cadences" / "_log.md"
        if log.exists() and re.search(rf"\b{re.escape(name)}\b", log.read_text(encoding="utf-8")):
            return "closed"
    if folder.exists():
        st = fm_read(folder)[0].get("status", "active")
        return "open" if st in ("active", "paused") else "closed"
    return "absent"


def satisfied(rid, records=None, root=None):
    """R5 satisfaction of one target."""
    records = records if records is not None else load_records(root)
    r = resolve(rid, records, root)
    if r is None:
        return False
    st = r["fm"].get("status")
    k = r["kind"]
    if k == "milestone":
        return st == "done" or (st == "dropped" and str(r["fm"].get("conditional")).lower() == "true")
    if k == "gate":
        return st == "done"
    if k == "intake":
        return st == "consumed"
    if k == "unit":
        return unit_state(rid, root) == "closed"
    return False


# --------------------------------------------------------------------------- JSON envelope

SCHEMA = "harness-records/1"


def envelope(kind, **payload):
    """R9 JSON object for any --json output."""
    out = {"schema": SCHEMA, "kind": kind, "generated": today()}
    out.update(payload)
    return out


# --------------------------------------------------------------------------- locks (R6)

def load_locks(root=None):
    """control-plane/locks.md table -> {lock: {probe, meaning}}."""
    root = Path(root) if root else find_root()
    p = _cp(root) / "locks.md"
    out = {}
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8").splitlines():
        cells = _cells(ln)
        if len(cells) >= 3 and cells[0] not in ("lock", "") and not set(cells[0]) <= set("-: "):
            out[cells[0]] = {"probe": cells[1], "meaning": cells[2]}
    return out


def probe_fires(root, probe):
    """True when a lock probe fires. Only `git-dirty:<path>` is known (R6).

    Runs git from inside <root>/<path> so the probe sees whichever repo owns that path
    (a nested repo, or the root repo for a plain subdirectory). A missing path raises
    HarnessError; callers treat that as not fired."""
    import subprocess
    kind, _, arg = probe.partition(":")
    if kind != "git-dirty" or not arg:
        raise HarnessError(f"unknown probe kind: {probe}")
    target = Path(root) / arg
    if not target.is_dir():
        raise HarnessError(f"probe path missing or not a directory: {target}")
    r = subprocess.run(["git", "-C", str(target), "status", "--porcelain", "--", "."],
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


# --------------------------------------------------------------------------- backlog tables (R8)

BACKLOG_STATUS = ("open", "done", "dropped", "moved")


def _cells(line):
    s = line.strip()
    if not s.startswith("|"):
        return []
    s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def _render_row(cells):
    return "| " + " | ".join(cells) + " |"


def backlog_parse(path):
    """Parse the backlog table -> {header, hdr, rows:[{line, cells, id, item, status, route, note}]}."""
    lines = _decode_lines(path)
    for i in range(len(lines) - 1):
        head = _cells(lines[i])
        sep = _cells(lines[i + 1])
        if head and sep and all(re.fullmatch(r":?-{1,}:?", c) for c in sep if c != "") \
                and "id" in [h.lower() for h in head] and "status" in [h.lower() for h in head]:
            hl = [h.lower() for h in head]
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                c = _cells(lines[j])
                c += [""] * (len(hl) - len(c))
                d = {k: c[hl.index(k)] if k in hl else "" for k in ("id", "item", "status", "route", "note")}
                d.update(line=j, cells=c)
                rows.append(d)
                j += 1
            return {"header": hl, "hdr": i, "rows": rows}
    raise HarnessError(f"{path}: no backlog table (needs id and status columns)")


def backlog_counts(rows):
    c = {s: 0 for s in BACKLOG_STATUS}
    for r in rows:
        if r["status"] in c:
            c[r["status"]] += 1
    return c


def backlog_progress(path):
    """-> (done, total) where total excludes moved rows."""
    c = backlog_counts(backlog_parse(path)["rows"])
    return c["done"], c["open"] + c["done"] + c["dropped"]


def backlog_tick(path, row_id, status, route=None, note=None):
    """Set one row's status (open rows only); only that row's line changes, except that
    a `note` column is appended to the whole table if it is missing."""
    if status not in BACKLOG_STATUS or status == "open":
        raise HarnessError(f"bad backlog status: {status}")
    bl = backlog_parse(path)
    hl, rows = bl["header"], bl["rows"]
    row = next((r for r in rows if r["id"] == row_id), None)
    if row is None:
        raise HarnessError(f"{path}: no row with id {row_id}")
    if row["status"] != "open":
        raise HarnessError(f"{path}: row {row_id} is {row['status']}, not open")
    lines = _decode_lines(path)
    edits = []
    if note is not None and "note" not in hl:
        hl = hl + ["note"]
        h = _cells(lines[bl["hdr"]]) + ["note"]
        s = _cells(lines[bl["hdr"] + 1]) + ["---"]
        edits.append((bl["hdr"], bl["hdr"] + 1, [_render_row(h)]))
        edits.append((bl["hdr"] + 1, bl["hdr"] + 2, [_render_row(s)]))
        for r in rows:
            r["cells"] = r["cells"] + [""]
    cells = list(row["cells"])
    cells[hl.index("status")] = status
    if route is not None:
        if "route" not in hl:
            raise HarnessError(f"{path}: no route column")
        cells[hl.index("route")] = route
    if note is not None:
        cells[hl.index("note")] = note
    for r in rows:
        if r is row:
            edits.append((r["line"], r["line"] + 1, [_render_row(cells)]))
        elif len(r["cells"]) != len(_cells(lines[r["line"]])):
            edits.append((r["line"], r["line"] + 1, [_render_row(r["cells"])]))
    edits.sort(key=lambda e: e[0])
    splice_write(path, edits)


# --------------------------------------------------------------------------- handover writer (R7 step 3)

def _union(a, b):
    out = list(a or [])
    for x in b or []:
        if x not in out:
            out.append(x)
    return out


def write_handover(root, producer, target, purpose, inputs=(), backlog=(), objective="none"):
    """R7 step 3. Target exists (milestone record, or unit folder active/paused) ->
    union inputs/backlog into its frontmatter; else write intake/<producer>-handover-<n>.md.
    Returns {"appended": path} or {"created": path}."""
    root = Path(root)
    cp = _cp(root)
    inputs, backlog = list(inputs or []), list(backlog or [])
    tid = target[len("milestone:"):] if target.startswith("milestone:") else target
    path = None
    recs = load_records(root)
    if tid in recs and recs[tid]["kind"] == "milestone":
        path = recs[tid]["path"]
    else:
        kind, name = _unit_kind(tid)
        if kind:
            idx = cp / {"workstream": "workstreams", "assignment": "assignments",
                        "cadence": "cadences"}[kind] / name / "index.md"
            if idx.exists() and fm_read(idx)[0].get("status", "active") in ("active", "paused"):
                path = idx
    if path:
        fm = fm_read(path)[0]
        upd = {}
        for key, new in (("inputs", inputs), ("backlog", backlog)):
            if new:
                upd[key] = _union(fm.get(key), new)
        if upd:
            fm_write(path, upd)
        return {"appended": path}
    pname = producer.split(":", 1)[-1]
    d = cp / "intake"
    n = 1
    while (d / f"{pname}-handover-{n}.md").exists() or (d / "_archive" / f"{pname}-handover-{n}.md").exists():
        n += 1
    p = d / f"{pname}-handover-{n}.md"
    fm = ["---", "note_type: intake", "kind: handover", "status: triaged", f"captured: {today()}",
          f"source: {render_value(producer)}", f"objective: {objective or 'none'}",
          f"route: {render_value(target)}", f"inputs: {render_value(inputs)}",
          f"backlog: {render_value(backlog)}", "depends_on: []", "related: []", "locks: []",
          "---", "", purpose, ""]
    write_text(p, "\n".join(fm))
    return {"created": p}



# --------------------------------------------------------------------------- unit create/close checks (R7)

UNIT_DIRS = {"workstream": "workstreams", "assignment": "assignments", "cadence": "cadences"}
_UNIT_ID_RE = re.compile(r"^(workstream|assignment|cadence):[a-z0-9-]+$")
_MS_ID_RE = re.compile(r"^[a-z0-9-]+#\d+$")
_DEC_RE = re.compile(r"\(decision\s+([a-z0-9-]+)\s+(\d{4}-\d{2}-\d{2})\)")
_HANDOVER_RE = re.compile(
    r"^handover:\s*(\S+)\s+(?:—|--|-)\s+(.*?)(?:;\s*inputs:\s*(.*?))?(?:;\s*backlog:\s*(.*?))?\s*$", re.S)

RESIDUALS_COMMENT = (
    "<!-- One bullet per line. Allowed forms:\n"
    "- none\n"
    "- intake:<slug>, <note>\n"
    "- milestone:<obj>#N, <note>\n"
    "- spawned:<unit id>\n"
    "- dropped: <text> (decision <obj> YYYY-MM-DD)\n"
    "- handover: <target> — <purpose>; inputs: <path>[, <path>]; backlog: <path>\n"
    "-->")


def residuals_lines(text):
    """Bullets under `## Residuals` (HTML comments stripped) -> list, or None when the section is absent."""
    t = text.replace("\r\n", "\n")
    m = re.search(r"^##[ \t]+Residuals[ \t]*$(.*?)(?=^## |\Z)", t, re.M | re.S)
    if not m:
        return None
    body = re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S)
    return [ln.strip()[2:].strip() for ln in body.split("\n") if ln.strip().startswith("- ")]


def _csv(s):
    return [x.strip().strip("`") for x in (s or "").split(",") if x.strip()]


def listflag(vals):
    """Repeatable list flags: `--x a --x b` or `--x a,b` -> [a, b].

    The one parsing helper for every list flag in every CLI. A plain string (a flag declared
    without action="append") is one value; iterating it would yield characters."""
    if vals is None:
        return []
    if isinstance(vals, str):
        vals = [vals]
    out = []
    for v in vals:
        out += [x.strip() for x in str(v).split(",") if x.strip()]
    return out


def open_backlog_rows(root, paths):
    """[(path, row id)] of rows still `open` in the given backlog files."""
    out = []
    for p in paths or []:
        f = Path(root) / p
        if f.exists():
            try:
                for row in backlog_parse(f)["rows"]:
                    if row["status"] == "open":
                        out.append((p, row["id"]))
            except HarnessError:
                pass
    return out


def _decision_exists(root, obj, date):
    base = _cp(root) / "objectives"
    for d in (base / obj, base / "_archive" / "closed" / obj, base / "_archive" / "abandoned" / obj):
        f = d / "index.md"
        if f.exists():
            t = f.read_text(encoding="utf-8").replace("\r\n", "\n")
            m = re.search(r"^##\s+Key Decisions Log\s*$(.*?)(?=^##\s|\Z)", t, re.M | re.S)
            if m and any(ln.lstrip().startswith("|") and date in ln for ln in m.group(1).split("\n")):
                return True
    return False


def unit_index_path(root, unit_id):
    kind, name = _unit_kind(unit_id)
    return _cp(root) / UNIT_DIRS[kind] / name / "index.md"


def _parent_objective(fm):
    p = str(fm.get("parent") or "")
    return p[len("objectives/"):] if p.startswith("objectives/") else "none"


def stamp_archive_date(path, when=None):
    """R4: give a consumed/dropped intake record its `consumed:` / `dropped:` date (kept when present)."""
    fm = fm_read(path)[0]
    key = fm.get("status")
    if key in ("consumed", "dropped") and not fm.get(key):
        fm_write(path, {key: when or today()})


def move_archive(root, slug):
    """Move a live intake record to intake/_archive (git mv when tracked)."""
    import subprocess
    src = _cp(root) / "intake" / f"{slug}.md"
    dst = _cp(root) / "intake" / "_archive" / f"{slug}.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    stamp_archive_date(src)
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", str(src)],
                             capture_output=True).returncode == 0
    if tracked:
        res = subprocess.run(["git", "-C", str(root), "mv", str(src), str(dst)], capture_output=True, text=True)
        if res.returncode != 0:
            raise HarnessError(f"git mv failed: {res.stderr.strip()}")
    else:
        src.replace(dst)


def _unit_listing_source(root, rid, exclude):
    """True when another open unit lists intake record `rid` in its intake_source."""
    for kind, d in UNIT_DIRS.items():
        base = _cp(root) / d
        if not base.is_dir():
            continue
        for idx in base.glob("*/index.md"):
            uid = f"{kind}:{idx.parent.name}"
            if uid == exclude:
                continue
            fm = fm_read(idx)[0]
            if fm.get("status", "active") in ("active", "paused") and rid in (fm.get("intake_source") or []):
                return True
    return False


def create_plan(root, sources, milestone, locks, unit_id=None):
    """Validate the create-side flags before anything is written (R7). -> {inputs, backlog, sources}.
    `unit_id` is the binding unit: a milestone whose `unit` already names it is accepted (idempotent bind)."""
    root = Path(root)
    recs = load_records(root)
    errs, inputs, backlog = [], [], []
    for sid in sources or []:
        r = recs.get(sid)
        if r is None or r["kind"] != "intake" or r["archived"]:
            errs.append(f"intake_source not a live intake record: {sid}")
            continue
        if r["fm"].get("status") in ("consumed", "dropped"):
            errs.append(f"intake_source is {r['fm'].get('status')}: {sid}")
            continue
        inputs = _union(inputs, r["fm"].get("inputs"))
        backlog = _union(backlog, r["fm"].get("backlog"))
    if milestone:
        m = recs.get(milestone)
        if m is None or m["kind"] != "milestone":
            errs.append(f"unresolved milestone: {milestone}")
        elif m["fm"].get("status") not in ("open", "active"):
            errs.append(f"milestone {milestone} is {m['fm'].get('status')}, not open")
        elif m["fm"].get("unit") and str(m["fm"].get("unit")) != str(unit_id or ""):
            errs.append(f"milestone {milestone} already has unit {m['fm'].get('unit')}")
    if locks:
        reg = load_locks(root)
        for n in locks:
            if n not in reg:
                errs.append(f"unknown lock '{n}' (registry: control-plane/locks.md)")
    if errs:
        raise HarnessError("; ".join(errs))
    return {"inputs": inputs, "backlog": backlog, "sources": list(sources or []), "milestone": milestone}


def create_apply(root, unit_id, plan):
    """R7 create-side effects: sources -> active, milestone -> active with unit set."""
    recs = load_records(root)
    for sid in plan["sources"]:
        if recs[sid]["fm"].get("status") != "active":
            fm_write(recs[sid]["path"], {"status": "active"})
    if plan["milestone"]:
        fm_write(recs[plan["milestone"]]["path"], {"status": "active", "unit": unit_id})


SET_UNIT_FLAGS = (("intake-source", "intake:<slug>", "intake record the unit consumes; copies its inputs/backlog, sets it active"),
                  ("locks", "LOCK", "lock names from locks.md"),
                  ("inputs", "PATH", "workspace-relative input paths"),
                  ("backlog", "PATH", "backlog paths (subset of inputs)"))


def add_set_unit_args(parser):
    """Flags of the `set-unit` subcommand, shared by workstream.py, assignment.py and cadence.py."""
    parser.add_argument("name")
    for flag, meta, hlp in SET_UNIT_FLAGS:
        parser.add_argument(f"--{flag}", action="append", metavar=meta, help=hlp + " (repeatable or comma-separated)")
    parser.add_argument("--milestone", metavar="<obj>#N", help="milestone the unit delivers; sets it active with unit filled")


def unit_set_plan(root, unit_id, sources=(), milestone="", locks=(), inputs=(), backlog=()):
    """Validate a set-unit request without writing. Raises HarnessError listing every refusal.
    -> {idx, upd, create} where `upd` is the frontmatter update and `create` the create_apply plan."""
    root = Path(root)
    idx = unit_index_path(root, unit_id)
    if not idx.exists():
        raise HarnessError(f"no such unit: {unit_id}")
    fm = fm_read(idx)[0]
    if fm.get("status", "active") not in ("active", "paused"):
        raise HarnessError(f"{unit_id} is {fm.get('status')}, not open")
    sources, locks, inputs, backlog = list(sources or []), list(locks or []), list(inputs or []), list(backlog or [])
    milestone = milestone or ""
    if not (sources or milestone or locks or inputs or backlog):
        raise HarnessError("nothing to set")
    errs = []
    cur_ms = str(fm.get("milestone") or "")
    if milestone and cur_ms and milestone != cur_ms:
        errs.append(f"{unit_id} already delivers milestone {cur_ms}")
    new_ms = "" if (not milestone or milestone == cur_ms) else milestone
    cur_src = list(fm.get("intake_source") or [])
    new_src = [s for s in sources if s not in cur_src]
    plan = {"inputs": [], "backlog": [], "sources": [], "milestone": ""}
    try:
        plan = create_plan(root, new_src, new_ms, locks, unit_id)
    except HarnessError as e:
        errs.append(str(e))
    for p in inputs + backlog:
        if not (root / p).exists():
            errs.append(f"path does not exist: {p}")
    fin_inputs = _union(_union(fm.get("inputs"), plan["inputs"]), inputs)
    fin_backlog = _union(_union(fm.get("backlog"), plan["backlog"]), backlog)
    if not set(fin_backlog) <= set(fin_inputs):
        errs.append("backlog must be a subset of inputs")
    if errs:
        raise HarnessError("; ".join(errs))
    upd = {}
    if sources:
        upd["intake_source"] = _union(cur_src, sources)
    if new_ms:
        upd["milestone"] = new_ms
    if locks:
        upd["locks"] = _union(fm.get("locks"), locks)
    if inputs or plan["inputs"]:
        upd["inputs"] = fin_inputs
    if backlog or plan["backlog"]:
        upd["backlog"] = fin_backlog
    return {"idx": idx, "upd": upd, "create": plan}


def unit_set_apply(root, unit_id, plan):
    """Write what unit_set_plan validated: frontmatter, then create_apply side effects."""
    if plan["upd"]:
        fm_write(plan["idx"], plan["upd"])
    create_apply(root, unit_id, plan["create"])


def run_set_unit(root, unit_id, args):
    """Shared body of every tool's `set-unit`: validate everything, then write, then report."""
    plan = unit_set_plan(root, unit_id, listflag(getattr(args, "intake_source", None)),
                         getattr(args, "milestone", None) or "", listflag(getattr(args, "locks", None)),
                         listflag(getattr(args, "inputs", None)), listflag(getattr(args, "backlog", None)))
    unit_set_apply(root, unit_id, plan)
    print(f"set-unit {unit_id}: {', '.join(plan['upd']) or 'no change'}")
    for sid in plan["create"]["sources"]:
        print(f"active: {sid}")
    if plan["create"]["milestone"]:
        print(f"active: {plan['create']['milestone']} (unit {unit_id})")


def close_plan(root, unit_id, idx):
    """R7 steps 1-2 plus target resolution. Reads only; raises HarnessError listing every refusal."""
    root, idx = Path(root), Path(idx)
    text = idx.read_text(encoding="utf-8")
    fm = fm_parse(text)[0]
    bullets = residuals_lines(text)
    if bullets is None:
        raise HarnessError("no '## Residuals' section; add one (use '- none' if nothing remains)")
    if not bullets:
        raise HarnessError("'## Residuals' is empty; add one bullet per line (use '- none' if nothing remains)")
    recs = load_records(root)
    errs, handovers, objs = [], [], set()
    pobj = _parent_objective(fm)
    if pobj != "none":
        objs.add(pobj)
    for b in bullets:
        if b == "none" or b.startswith("none"):
            continue
        if b.startswith("intake:"):
            rid = re.split(r"[,\s]", b, maxsplit=1)[0]
            if rid not in recs or recs[rid]["kind"] != "intake":
                errs.append(f"unresolved id: {rid}")
        elif b.startswith("milestone:"):
            rid = re.split(r"[,\s]", b[len("milestone:"):], maxsplit=1)[0]
            if rid not in recs or recs[rid]["kind"] != "milestone":
                errs.append(f"unresolved id: milestone:{rid}")
            else:
                objs.add(rid.split("#")[0])
        elif b.startswith("spawned:"):
            uid = re.split(r"[,\s]", b[len("spawned:"):].strip(), maxsplit=1)[0]
            if not _UNIT_ID_RE.match(uid) or unit_state(uid, root) == "absent":
                errs.append(f"unresolved id: spawned:{uid}")
        elif b.startswith("dropped:"):
            m = _DEC_RE.search(b)
            if not m:
                errs.append(f"dropped residual lacks '(decision <obj> YYYY-MM-DD)': {b}")
            elif not _decision_exists(root, m.group(1), m.group(2)):
                errs.append(f"unresolved id: no decision row {m.group(1)} {m.group(2)}")
        elif b.startswith("handover:"):
            m = _HANDOVER_RE.match(b)
            if not m:
                errs.append(f"malformed handover residual: {b}")
                continue
            tgt, purpose = m.group(1), m.group(2).strip()
            ins, bl = _csv(m.group(3)), _csv(m.group(4))
            if tgt.startswith("milestone:"):
                mid = tgt[len("milestone:"):]
                if mid not in recs or recs[mid]["kind"] != "milestone":
                    errs.append(f"unresolved id: {tgt}")
                else:
                    objs.add(mid.split("#")[0])
            elif not (_UNIT_ID_RE.match(tgt) or tgt in ("candidate:workstream", "candidate:assignment")):
                errs.append(f"bad handover target: {tgt}")
            for p in ins + bl:
                if not (root / p).exists():
                    errs.append(f"handover path does not exist: {p}")
            if not set(bl) <= set(ins):
                errs.append(f"handover backlog must be a subset of inputs: {b}")
            handovers.append((tgt, purpose, ins, bl))
        else:
            errs.append(f"unrecognised residual form: {b}")
    sources = [s for s in (fm.get("intake_source") or [])]
    open_rows = open_backlog_rows(root, fm.get("backlog"))
    for sid in sources:
        r = recs.get(sid)
        if r is None or r["kind"] != "intake":
            errs.append(f"unresolved id: intake_source {sid}")
            continue
        o = r["fm"].get("objective")
        if o and o != "none":
            objs.add(o)
        open_rows += open_backlog_rows(root, r["fm"].get("backlog"))
    ms = fm.get("milestone") or ""
    if ms:
        m = recs.get(ms)
        if m is None or m["kind"] != "milestone":
            errs.append(f"unresolved id: milestone {ms}")
        else:
            objs.add(ms.split("#")[0])
            open_rows += open_backlog_rows(root, m["fm"].get("backlog"))
    for p, i in open_rows:
        errs.append(f"open backlog row {i} in {p}")
    if errs:
        raise HarnessError("close refused: " + "; ".join(errs))
    return {"unit_id": unit_id, "idx": idx, "fm": fm, "bullets": bullets, "handovers": handovers,
            "sources": sources, "milestone": ms, "objectives": objs, "parent_objective": pobj}


def close_apply(root, plan):
    """R7 steps 3-5. Call only after close_plan succeeded. -> list of action lines."""
    root = Path(root)
    uid, actions = plan["unit_id"], []
    for tgt, purpose, ins, bl in plan["handovers"]:
        res = write_handover(root, uid, tgt, purpose, ins, bl, objective=plan["parent_objective"])
        if "created" in res:
            actions.append(f"handover {tgt}: created {Path(res['created']).relative_to(root).as_posix()}")
        else:
            actions.append(f"handover {tgt}: appended inputs/backlog to {Path(res['appended']).relative_to(root).as_posix()}")
    for sid in plan["sources"]:
        recs = load_records(root)
        r = recs.get(sid)
        if r is None or r["archived"] or r["fm"].get("status") not in ("captured", "triaged", "active"):
            continue
        ku = r["fm"].get("keep_until")
        ku_met = bool(ku) and (ku == plan["milestone"] or satisfied(ku, recs, root))
        if (ku and not ku_met) or _unit_listing_source(root, sid, uid):
            if r["fm"].get("status") != "active":
                fm_write(r["path"], {"status": "active"})
            actions.append(f"{sid}: kept active")
        else:
            fm_write(r["path"], {"status": "consumed", "consumed_by": _union(r["fm"].get("consumed_by"), [uid]),
                                 "consumed": today()})
            move_archive(root, sid.split(":", 1)[1])
            actions.append(f"{sid}: consumed and archived")
    if plan["milestone"]:
        recs = load_records(root)
        fm_write(recs[plan["milestone"]]["path"], {"status": "done", "done": today()})
        actions.append(f"{plan['milestone']}: done")
    return actions


def render_views(root, objs):
    """R7 step 6: re-render milestone views for each touched, migrated objective."""
    out = []
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    for o in sorted(objs):
        if not (_cp(root) / "objectives" / o / "milestones").is_dir():
            continue
        try:
            import objective
            objective.render_milestones(o)
            out.append(f"rendered {o}")
        except (Exception, SystemExit) as e:  # a failed render must not undo the close
            out.append(f"render skipped for {o}: {e}")
    return out


def close_report(plan, actions):
    """R7 step 7: the block the skill pastes into the log entry's `### Residuals`."""
    lines = ["Residuals (paste into the log entry's ### Residuals):"]
    lines += [f"- {b}" for b in plan["bullets"]]
    lines += [f"  ({a})" for a in actions]
    return lines


# --------------------------------------------------------------------------- conflicted regions (R5)

_CONFLICT_OPEN, _CONFLICT_MID, _CONFLICT_CLOSE = "<<<<<<<", "=======", ">>>>>>>"


def _is_marker(line):
    return line.startswith((_CONFLICT_OPEN + " ", _CONFLICT_OPEN)) or line.rstrip() == _CONFLICT_MID \
        or line.startswith(_CONFLICT_CLOSE)


def _conflict_blocks(lines):
    """[(start, end)] line spans (inclusive) of git conflict blocks."""
    out, start = [], None
    for i, ln in enumerate(lines):
        if ln.startswith(_CONFLICT_OPEN) and start is None:
            start = i
        elif ln.startswith(_CONFLICT_CLOSE) and start is not None:
            out.append((start, i))
            start = None
    return out


def resolve_conflicted_regions(path):
    """R5: in each generated region holding git conflict markers, drop both sides (and any doubled
    footer) leaving an empty region for the caller to re-render. Lines outside regions are untouched.
    -> (views_reset, outside_marker_lines[1-based])."""
    lines = _decode_lines(path)
    blocks = _conflict_blocks(lines)
    open_re = re.compile(r"^\s*<!-- generated:([A-Za-z0-9_-]+) -->\s*$")
    edits, views, covered, i = [], [], set(), 0
    while i < len(lines):
        m = open_re.match(lines[i])
        if not m:
            i += 1
            continue
        view = m.group(1)
        close_re = re.compile(r"^\s*<!-- /generated:" + re.escape(view) + r"(?: sha=[0-9a-f]{8})? -->\s*$")
        end = None
        for j in range(i + 1, len(lines)):
            blk = next((b for b in blocks if b[0] <= j <= b[1]), None)
            if close_re.match(lines[j]):
                end = blk[1] if blk else j
                break
        if end is None:
            i += 1
            continue
        if any(i <= b[0] <= end for b in blocks):
            indent = re.match(r"^\s*", lines[i]).group(0)
            edits.append((i, end + 1, [lines[i], indent + "<!-- /generated:" + view + " -->"]))
            views.append(view)
            covered.update(range(i, end + 1))
        i = end + 1
    outside = [n + 1 for n, ln in enumerate(lines) if n not in covered and _is_marker(ln)
               and any(b[0] <= n <= b[1] for b in blocks)]
    if edits:
        splice_write(path, edits)
    return views, outside


# --------------------------------------------------------------------------- claims (R7)

def unit_claim(root, unit_id):
    """claimed_by of an open unit's index.md, or None."""
    idx = unit_index_path(root, unit_id)
    if not idx.exists():
        return None
    return fm_read(idx)[0].get("claimed_by") or None


def claim_unit(root, unit_id, release=False, user=None):
    """R7: write (or clear) claimed_by / claimed in a unit's index.md frontmatter. -> message."""
    root = Path(root)
    idx = unit_index_path(root, unit_id)
    if not idx.exists():
        raise HarnessError(f"no such unit: {unit_id}")
    fm = fm_read(idx)[0]
    holder = fm.get("claimed_by") or None
    if release:
        if not holder:
            return f"{unit_id}: not claimed"
        fm_delete(idx, ("claimed_by", "claimed"))
        return f"released {unit_id} (was claimed by {holder})"
    if fm.get("status", "active") not in ("active", "paused"):
        raise HarnessError(f"{unit_id} is {fm.get('status')}, not open")
    user = user or git_user(root)
    if holder and holder != user:
        raise HarnessError(f"{unit_id} is already claimed by {holder}; they must release it first")
    fm_write(idx, {"claimed_by": Raw(json.dumps(user, ensure_ascii=False)), "claimed": today()})
    return f"claimed {unit_id} for {user}"


def run_claim(root, unit_id, release=False):
    """Shared body of `claim` / `release` in workstream.py and assignment.py."""
    try:
        print(claim_unit(root, unit_id, release=release))
    except HarnessError as e:
        die(str(e))
