#!/usr/bin/env python3
"""eol-churn - detect whole-file rewrites (line-ending churn) in a git diff.

A file is flagged when its diff rewrites (nearly) every line:
  - more than 90% of lines changed while the content without CR is identical, or
  - numstat shows N/N (added == deleted == the file's line count, N >= 3).

Usage (run from the repo root):
    python -B tools/eol-churn.py --staged
    python -B tools/eol-churn.py --range <a>..<b> [--json]

Exit 1 if any file is flagged, else 0. Stdlib only.
"""

import argparse
import json
import subprocess
import sys

MIN_NN = 3


def git(args, cwd=None):
    r = subprocess.run(["git", *args], capture_output=True, cwd=cwd)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace"))
        sys.exit(2)
    return r.stdout


def _show(spec, cwd):
    r = subprocess.run(["git", "show", spec], capture_output=True, cwd=cwd)
    return r.stdout if r.returncode == 0 else None


def line_count(b):
    return b.count(b"\n") + (1 if b and not b.endswith(b"\n") else 0)


def classify(old, new, added, deleted):
    """-> (reason|None, fraction). old/new bytes; added/deleted from numstat."""
    if old is None or new is None:
        return None, 0.0  # added or deleted file: not a rewrite
    total = max(line_count(new), line_count(old), 1)
    frac = max(added, deleted) / total
    crless_same = old.replace(b"\r", b"") == new.replace(b"\r", b"")
    if crless_same and old != new and frac > 0.9:
        return "eol-only", frac
    if added == deleted == line_count(new) and added >= MIN_NN:
        return "N/N", frac
    return None, frac


def scan(staged=False, rng=None, cwd=None):
    if staged:
        diff_args, old_ref, new_ref = ["--cached"], "HEAD", None
    elif rng:
        a, _, b = rng.partition("..")
        if not b:
            sys.stderr.write("--range needs <a>..<b>\n")
            sys.exit(2)
        diff_args, old_ref, new_ref = [f"{a}..{b}"], a, b
    else:
        sys.stderr.write("need --staged or --range <a>..<b>\n")
        sys.exit(2)
    out = git(["diff", "--numstat", "--no-renames", "-z", *diff_args], cwd).decode("utf-8", "replace")
    flagged = []
    for rec in [r for r in out.split("\0") if r]:
        parts = rec.split("\t", 2)
        if len(parts) != 3 or parts[0] == "-":
            continue  # binary
        added, deleted, path = int(parts[0]), int(parts[1]), parts[2]
        old = _show(f"{old_ref}:{path}", cwd)
        new = _show(f":{path}" if new_ref is None else f"{new_ref}:{path}", cwd)
        reason, frac = classify(old, new, added, deleted)
        if reason:
            flagged.append({"path": path, "added": added, "deleted": deleted,
                            "reason": reason, "fraction": round(frac, 3)})
    return flagged


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--range", dest="rng")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cwd", help="git working directory (default: current)")
    a = ap.parse_args(argv)
    flagged = scan(a.staged, a.rng, a.cwd)
    if a.json:
        print(json.dumps({"whole_file_rewrites": len(flagged), "files": flagged}, indent=2))
    else:
        print(f"{len(flagged)} whole-file rewrites")
        for f in flagged:
            print(f"  {f['path']}  +{f['added']}/-{f['deleted']}  {f['reason']}")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
