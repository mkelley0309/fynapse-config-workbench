#!/usr/bin/env python3
"""template_sync - generic, stdlib-only template sync from a git commit.

Reads files from a pinned commit of a source repo (never the working tree),
copies them per a manifest into a destination, and pins the result in a lock.

  template_sync.py pull  --manifest M --dest D [--source [id=]PATH] [--commit [id=]REF] ...
  template_sync.py check --manifest M --dest D [--lock L]
  template_sync.py init  --manifest M --dest NEW ...
  template_sync.py strip --edition engagement|workspace PATH

Exit codes: 0 ok/clean, 1 drift or refused (conflicts), 2 error (bad input, git, markers).
See README.md.
"""

import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MANIFEST_SCHEMA = "template-sync-manifest/1"
LOCK_SCHEMA = "template-sync-lock/1"
CLASSES = ("managed", "seeded")
EDITIONS = ("engagement", "workspace")
PENDING = "pending"
DEFAULT_LOCK_NAME = "template-sync.lock.json"


class SyncError(Exception):
    pass


# -- edition marker stripping (ported from friendly-neighborhood strip_markers) --

# Line markers. Markdown: <!-- EDITION:workspace:start -->; code: # EDITION:workspace:start.
# Indentation allowed. One marker kind only (workspace).
_MARK_MD = re.compile(r"^[ \t]*<!--[ \t]*EDITION:workspace:(start|end)[ \t]*-->[ \t]*$")
_MARK_SH = re.compile(r"^[ \t]*#[ \t]*EDITION:workspace:(start|end)[ \t]*$")


def _marker(line: bytes):
    """Return (kind, which) for a marker line, else None."""
    text = line.decode("latin-1").rstrip("\r\n")
    for kind, rx in (("md", _MARK_MD), ("sh", _MARK_SH)):
        m = rx.match(text)
        if m:
            return kind, m.group(1)
    return None


def strip_workspace_spans(data: bytes, label: str = "<input>") -> bytes:
    """Drop workspace marker spans (marker lines inclusive); keep other lines' EOL bytes.

    Raises SyncError on unbalanced, nested, or kind-mismatched markers.
    """
    out = []
    open_kind = None
    open_line = 0
    for n, line in enumerate(data.splitlines(keepends=True), 1):
        mk = _marker(line)
        if mk is None:
            if open_kind is None:
                out.append(line)
            continue
        kind, which = mk
        if which == "start":
            if open_kind is not None:
                raise SyncError(f"{label}:{n}: nested EDITION:workspace:start (open since line {open_line})")
            open_kind, open_line = kind, n
        else:
            if open_kind is None:
                raise SyncError(f"{label}:{n}: EDITION:workspace:end without start")
            if kind != open_kind:
                raise SyncError(f"{label}:{n}: end marker kind '{kind}' does not match start '{open_kind}' (line {open_line})")
            open_kind = None
    if open_kind is not None:
        raise SyncError(f"{label}:{open_line}: EDITION:workspace:start never closed")
    return b"".join(out)


def apply_edition(data: bytes, edition: str, label: str = "<input>") -> bytes:
    """engagement: strip workspace spans. workspace: file unchanged (markers kept)."""
    if edition == "engagement":
        return strip_workspace_spans(data, label)
    return data


# -- git access (commit objects only) --

def git(repo, *args, input=None, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], input=input, capture_output=True)
    if check and r.returncode:
        raise SyncError(f"git {' '.join(args)} failed in {repo}: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r


def resolve_commit(repo, ref):
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").stdout.decode().strip()


def commit_meta(repo, sha):
    date = git(repo, "show", "-s", "--format=%cI", sha).stdout.decode().strip()
    meta = {"repo_id": Path(os.path.abspath(repo)).name, "commit": sha, "commit_date": date}
    r = git(repo, "describe", "--tags", "--exact-match", sha, check=False)
    if r.returncode == 0 and r.stdout.strip():
        meta["tag"] = r.stdout.decode().strip()
    return meta


def list_tree(repo, sha):
    """{path: blob sha} for regular files at the commit."""
    raw = git(repo, "ls-tree", "-r", "-z", "--full-name", sha).stdout
    tree = {}
    for rec in raw.split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        mode, typ, oid = meta.decode().split()
        if typ != "blob" or mode == "120000":
            continue
        tree[path.decode("utf-8")] = oid
    return tree


def read_blobs(repo, oids):
    oids = sorted(set(oids))
    if not oids:
        return {}
    buf = git(repo, "cat-file", "--batch", input=("\n".join(oids) + "\n").encode()).stdout
    out, pos = {}, 0
    for oid in oids:
        nl = buf.index(b"\n", pos)
        head = buf[pos:nl].split()
        if len(head) < 3 or head[1] == b"missing":
            raise SyncError(f"blob {oid} missing in {repo}")
        size = int(head[2])
        out[oid] = buf[nl + 1:nl + 1 + size]
        pos = nl + 1 + size + 1
    return out


# -- manifest / lock --

def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_manifest(path):
    raw = Path(path).read_bytes()
    try:
        m = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        raise SyncError(f"manifest {path}: invalid JSON: {e}")
    if m.get("schema") != MANIFEST_SCHEMA:
        raise SyncError(f"manifest {path}: schema must be {MANIFEST_SCHEMA}")
    if not isinstance(m.get("sources"), dict) or not m["sources"]:
        raise SyncError("manifest: 'sources' must be a non-empty object")
    for i, e in enumerate(m.get("entries", [])):
        for k in ("source", "path", "dest", "class"):
            if k not in e:
                raise SyncError(f"manifest entry {i}: missing '{k}'")
        if e["source"] not in m["sources"]:
            raise SyncError(f"manifest entry {i}: unknown source '{e['source']}'")
        if e["class"] not in CLASSES:
            raise SyncError(f"manifest entry {i}: class must be one of {CLASSES}")
        d = e["dest"].replace("\\", "/")
        if d.startswith("/") or ".." in d.split("/") or re.match(r"^[A-Za-z]:", d):
            raise SyncError(f"manifest entry {i}: dest must be relative without '..'")
    return m, sha256(raw)


def load_lock(path):
    p = Path(path)
    if not p.exists():
        return None
    lock = json.loads(p.read_bytes().decode("utf-8"))
    if lock.get("schema") != LOCK_SCHEMA:
        raise SyncError(f"lock {path}: schema must be {LOCK_SCHEMA}")
    return lock


def write_lock(path, lock):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes((json.dumps(lock, sort_keys=True, indent=2) + "\n").encode("utf-8"))


# -- selection --

def _glob_re(pat):
    out, i = [], 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _has_glob(p):
    return any(c in p for c in "*?[")


def select(entry, tree):
    """Return [(source path, relative path)] for an entry; '' relative = single file."""
    p = entry["path"].replace("\\", "/").strip("/")
    if p == ".":
        p = ""
    if p and p in tree:
        return [(p, "")]
    if _has_glob(p):
        rx = _glob_re(p)
        base_parts = []
        for part in p.split("/")[:-1]:
            if _has_glob(part):
                break
            base_parts.append(part)
        base = "/".join(base_parts)
        found = [(t, t[len(base) + 1:] if base else t) for t in tree if rx.match(t)]
    else:
        prefix = p + "/" if p else ""
        found = [(t, t[len(prefix):]) for t in tree if t.startswith(prefix)]
    ex = [_glob_re(g) for g in entry.get("exclude", [])]
    ex += [_glob_re("**/" + g) for g in entry.get("exclude", [])]
    return sorted((t, r) for t, r in found if not any(x.match(r) for x in ex))


def build_plan(manifest, repos, commits, edition):
    """-> (plan {dest: dict}, skipped [source ids pending])."""
    trees, plan, skipped = {}, {}, []
    pending = {sid for sid, c in commits.items() if c == PENDING}
    wanted = []
    for e in manifest.get("entries", []):
        sid = e["source"]
        if sid in pending:
            if sid not in skipped:
                skipped.append(sid)
            continue
        if sid not in trees:
            trees[sid] = list_tree(repos[sid], commits[sid])
        sel = select(e, trees[sid])
        if not sel:
            raise SyncError(f"manifest entry path '{e['path']}' (source {sid}) matched no files")
        for src, rel in sel:
            d = e["dest"].replace("\\", "/")
            if rel == "":
                dest = d + os.path.basename(src) if d.endswith("/") else d
            else:
                dest = rel if d in ("", ".") else d.rstrip("/") + "/" + rel
            if dest in plan:
                raise SyncError(f"two entries write the same dest '{dest}'")
            plan[dest] = {"source": sid, "class": e["class"], "src": src,
                          "strip": bool(e.get("edition_strip")), "oid": trees[sid][src]}
            wanted.append((sid, plan[dest]))
    blobs = {}
    for sid in trees:
        blobs[sid] = read_blobs(repos[sid], [it["oid"] for s, it in wanted if s == sid])
    for sid, it in wanted:
        data = blobs[sid][it["oid"]]
        if it["strip"]:
            data = apply_edition(data, edition, f"{sid}:{it['src']}")
        it["data"] = data
        it["sha256"] = sha256(data)
    return plan, skipped


# -- shared command plumbing --

def _split_kv(values, ids, what):
    """Parse repeated '[id=]value' into {id: value}; bare form needs a sole source."""
    out = {}
    for v in values or []:
        k, sep, rest = v.partition("=")
        if sep and k in ids:
            out[k] = rest
        elif len(ids) == 1:
            out[next(iter(ids))] = v
        else:
            raise SyncError(f"--{what} '{v}': manifest has several sources; use id=value")
    return out


def _is_within(child, parent):
    c, p = os.path.normcase(os.path.realpath(child)), os.path.normcase(os.path.realpath(parent))
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def _owning_repo(path):
    """git toplevel of the repo that would hold `path` (its nearest existing ancestor), or None."""
    p = Path(os.path.realpath(path))
    while not p.exists() and p != p.parent:
        p = p.parent
    r = git(p if p.is_dir() else p.parent, "rev-parse", "--show-toplevel", check=False)
    return r.stdout.decode().strip() if r.returncode == 0 else None


def _guard_dest(dest, repos, used):
    """Refuse a dest that the source repo itself would own. A dest inside a separate (nested,
    e.g. gitignored) repo that merely sits under the source directory is allowed: hop 1 pulls
    from a workspace root into a nested template repo."""
    for sid in used:
        top = git(repos[sid], "rev-parse", "--show-toplevel").stdout.decode().strip()
        owner = _owning_repo(dest)
        same = owner is not None and _is_within(owner, top) and _is_within(top, owner)
        loose = owner is None and (_is_within(dest, top) or _is_within(dest, repos[sid]))
        if same or loose:
            raise SyncError(f"dest {dest} is the source repo or inside it ({repos[sid]})")


def _diff_summary(old: bytes, new: bytes):
    a = old.decode("utf-8", "replace").splitlines()
    b = new.decode("utf-8", "replace").splitlines()
    add = rem = 0
    for ln in difflib.unified_diff(a, b, lineterm="", n=0):
        if ln.startswith("+") and not ln.startswith("+++"):
            add += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            rem += 1
    return {"added": add, "removed": rem}


def _read(p):
    return p.read_bytes() if p.is_file() else None


def _setup(args):
    manifest, msha = load_manifest(args.manifest)
    mdir = Path(args.manifest).resolve().parent
    ids = set(manifest["sources"])
    overrides = _split_kv(args.source, ids, "source")
    commit_args = _split_kv(args.commit, ids, "commit")
    repos = {}
    for sid, spec in manifest["sources"].items():
        repo = overrides.get(sid, spec.get("repo"))
        if repo is None:
            raise SyncError(f"source '{sid}' has no repo (manifest or --source)")
        rp = Path(repo)
        repos[sid] = str(rp if rp.is_absolute() else (mdir / rp).resolve())
    dest = Path(args.dest)
    lock_path = Path(args.lock) if args.lock else dest / DEFAULT_LOCK_NAME
    lock = load_lock(lock_path)
    return manifest, msha, repos, commit_args, dest, lock_path, lock


def _resolve_commits(manifest, repos, commit_args, lock, default_head):
    """--commit wins; else lock (check) or HEAD (pull/init; a source pending in the lock stays pending)."""
    commits, meta = {}, {}
    for sid in manifest["sources"]:
        if sid in commit_args:
            ref = commit_args[sid]
        elif lock and sid in lock.get("sources", {}) and (not default_head or lock["sources"][sid]["commit"] == PENDING):
            ref = lock["sources"][sid]["commit"]
        elif default_head:
            ref = "HEAD"
        else:
            raise SyncError(f"no commit for source '{sid}' (pass --commit or use a lock)")
        if ref == PENDING:
            commits[sid] = PENDING
            meta[sid] = {"repo_id": Path(repos[sid]).name, "commit": PENDING}
        else:
            commits[sid] = resolve_commit(repos[sid], ref)
            meta[sid] = commit_meta(repos[sid], commits[sid])
    return commits, meta


def _emit(report):
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")


# -- pull / init --

def cmd_pull(args, init=False):
    manifest, msha, repos, commit_args, dest, lock_path, lock = _setup(args)
    if init and lock is not None and not args.force:
        raise SyncError(f"init: lock {lock_path} already exists (use pull, or --force)")
    old_files = (lock or {}).get("files", {})
    commits, meta = _resolve_commits(manifest, repos, commit_args, lock if not init else None, True)
    writes = []
    used = {e["source"] for e in manifest.get("entries", []) if commits[e["source"]] != PENDING}
    _guard_dest(dest, repos, used)
    plan, skipped = build_plan(manifest, repos, commits, args.edition)

    files, conflicts, new_files = [], [], {}
    for rel in sorted(plan):
        it = plan[rel]
        target = dest / rel
        cur = _read(target)
        rec = {"path": rel, "class": it["class"]}
        lock_sha = old_files.get(rel, {}).get("sha256")
        if it["class"] == "managed":
            edited = cur is not None and cur != it["data"] and sha256(cur) != lock_sha
            if edited and not args.force:
                conflicts.append(rel)
                rec["action"] = "conflict-local-edit"
            elif cur == it["data"]:
                rec["action"] = "unchanged"
            else:
                rec["action"] = "forced" if edited else ("updated" if cur is not None else "written")
                writes.append((target, it["data"]))
        else:
            if cur is None:
                rec["action"] = "written"
                writes.append((target, it["data"]))
            elif cur == it["data"]:
                rec["action"] = "unchanged"
            else:
                rec["action"] = "kept-local-differs"
                rec["diff"] = _diff_summary(cur, it["data"])
        files.append(rec)
        new_files[rel] = {"sha256": it["sha256"], "class": it["class"], "source": it["source"]}

    report = {"command": "init" if init else "pull", "dry_run": bool(args.dry_run),
              "edition": args.edition, "files": files, "conflicts": conflicts,
              "skipped_pending": skipped, "ok": not conflicts}
    return report, (msha, meta, new_files, old_files, commits, lock_path, lock, writes)


def run_pull(args, init=False):
    report, ctx = cmd_pull(args, init)
    if report["conflicts"]:
        _emit(report)
        print("refused: local edits to managed files (use --force): " + ", ".join(report["conflicts"]), file=sys.stderr)
        return 1
    if not args.dry_run:
        msha, meta, new_files, old_files, commits, lock_path, lock, writes = ctx
        for target, data in writes:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        pend = {s for s, c in commits.items() if c == PENDING}
        carried = {p: v for p, v in old_files.items() if v.get("source") in pend}
        report["orphaned_left_on_disk"] = sorted(p for p in old_files if p not in new_files and p not in carried)
        sources = dict(meta)
        for sid, v in (lock or {}).get("sources", {}).items():
            sources.setdefault(sid, v)
        write_lock(lock_path, {"schema": LOCK_SCHEMA, "sources": sources, "manifest_sha256": msha,
                               "edition": args.edition, "files": {**carried, **new_files}})
    _emit(report)
    return 0


# -- check --

def cmd_check(args):
    dest = Path(args.dest)
    lock_path = Path(args.lock) if args.lock else dest / DEFAULT_LOCK_NAME
    lock = load_lock(lock_path)
    if lock is None:
        raise SyncError(f"check: no lock at {lock_path}")
    lfiles = lock.get("files", {})
    pend = {s for s, v in lock.get("sources", {}).items() if v.get("commit") == PENDING}
    report = {"command": "check", "lock": str(lock_path), "files": [], "notes": []}
    drift = False
    plan = None
    if args.manifest:
        args.dest = str(dest)
        manifest, msha, repos, commit_args, _, _, _ = _setup(args)
        edition = args.edition or lock.get("edition") or "engagement"
        commits, _m = _resolve_commits(manifest, repos, commit_args, lock, False)
        plan, skipped = build_plan(manifest, repos, commits, edition)
        pend |= set(skipped)
        if lock.get("manifest_sha256") != msha:
            report["notes"].append("manifest sha256 differs from lock (manifest changed since last pull)")
            drift = True
        report["mode"] = "full"
    else:
        report["mode"] = "lock-only"
        report["notes"].append("no --manifest: upstream comparison skipped")
    if pend:
        report["notes"].append("pending sources skipped: " + ", ".join(sorted(pend)))

    paths = set(lfiles) | set(plan or {})
    for rel in sorted(paths):
        le, it = lfiles.get(rel), (plan or {}).get(rel)
        src = (it or le or {}).get("source")
        if src in pend:
            continue
        cls = (it or le)["class"]
        cur = _read(dest / rel)
        st = []
        if cls == "managed":
            if cur is None:
                st.append("missing")
            elif le is not None and sha256(cur) != le["sha256"]:
                st.append("edited")
            if plan is not None:
                if it is None:
                    st.append("orphan")
                elif le is None:
                    st.append("unlocked")
                elif it["sha256"] != le["sha256"]:
                    st.append("upstream-differs")
            if st:
                drift = True
        else:
            ref = it["data"] if it else None
            if cur is None:
                st.append("missing")
            elif ref is not None and cur != ref:
                st.append("differs")
            elif ref is None and le is not None and sha256(cur) != le["sha256"]:
                st.append("differs")
        rec = {"path": rel, "class": cls, "status": st or ["clean"]}
        if "differs" in st and it is not None and cur is not None:
            rec["diff"] = _diff_summary(cur, it["data"])
        report["files"].append(rec)
    report["ok"] = not drift
    _emit(report)
    return 1 if drift else 0


# -- strip --

def cmd_strip(args):
    data = Path(args.path).read_bytes()
    out = apply_edition(data, args.edition, args.path)
    sys.stdout.buffer.write(out)
    sys.stdout.buffer.flush()
    return 0


# -- CLI --

def build_parser():
    ap = argparse.ArgumentParser(prog="template_sync", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="{pull,check,init,strip}")

    def common(p, dest_default="."):
        p.add_argument("--manifest", help="manifest file (template-sync-manifest/1)")
        p.add_argument("--dest", default=dest_default, help="destination directory (default .)")
        p.add_argument("--lock", help=f"lock file (default <dest>/{DEFAULT_LOCK_NAME})")
        p.add_argument("--source", action="append", help="[id=]repo path; overrides the manifest repo (repeatable)")
        p.add_argument("--commit", action="append", help="[id=]sha|ref to read (default: HEAD; check: the lock); 'pending' skips a source")
        p.add_argument("--edition", choices=EDITIONS, default=None, help="engagement (default) strips workspace spans; workspace keeps files unchanged")
        p.add_argument("--force", action="store_true", help="overwrite locally edited managed files")
        p.add_argument("--dry-run", action="store_true", help="report only; write nothing")

    for name, h in (("pull", "sync managed/seeded files from the pinned commit; write the lock"),
                    ("check", "drift report vs lock and pinned commit; exit 1 on managed drift"),
                    ("init", "instantiate into a new dest (refuses dest inside the source repo)")):
        p = sub.add_parser(name, help=h, description=h)
        common(p)
    s = sub.add_parser("strip", help="print the edition text of a local file to stdout",
                       description="print the edition text of a local file to stdout")
    s.add_argument("--edition", choices=EDITIONS, required=True)
    s.add_argument("path")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "strip":
            return cmd_strip(args)
        if args.cmd == "check":
            return cmd_check(args)
        if not args.manifest:
            raise SyncError(f"{args.cmd}: --manifest is required")
        args.edition = args.edition or "engagement"
        return run_pull(args, init=(args.cmd == "init"))
    except SyncError as e:
        print(f"template_sync: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
