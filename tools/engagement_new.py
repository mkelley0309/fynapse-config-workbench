#!/usr/bin/env python3
"""Instantiate an engagement repo from the workbench (hop 2).

Usage:
  python -B tools/engagement_new.py <target> --name <slug> --success-criteria <file>
                                    [--title T] [--adopt] [--ref <tag|sha>]

Steps: template_sync init (wb read by commit) -> objective create -> one KR per
success-criteria line -> standard gates -> render views -> print next steps.

Exit codes: 0 ok; 1 already instantiated or a step failed; 2 bad input or target inside wb.
Stdlib only.
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

WB = Path(__file__).resolve().parent.parent
MANIFEST = WB / "engagement.manifest.json"
LOCK_NAME = "template.lock.json"
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)")

GATES = [
    ("sandbox-probe", "Sandbox probe", "artifact", "engagement lead",
     "first sandbox upload records SOFT_MERGE vs HARD_MERGE, accounts acceptance, error shape, PERM vs PERMANENT"),
    ("client-data-pack", "Client data pack", "external", "client",
     "client data pack received into client-data/"),
    ("remote-permitted", "Remote permitted", "decision", "operator",
     "a permitted company remote exists for this repo"),
]


class Fail(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def clean_env():
    return {k: v for k, v in os.environ.items() if k != "WORKSPACE_ROOT"}


def run(cmd, cwd, check=True):
    r = subprocess.run(cmd, cwd=str(cwd), env=clean_env(), capture_output=True)
    if check and r.returncode != 0:
        raise Fail(f"command failed ({r.returncode}): {' '.join(map(str, cmd))}\n"
                   f"{r.stdout.decode('utf-8', 'replace')}{r.stderr.decode('utf-8', 'replace')}")
    return r


def is_within(child, parent):
    c = os.path.normcase(os.path.realpath(child))
    p = os.path.normcase(os.path.realpath(parent))
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def criteria_lines(path):
    out = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = LIST_MARKER_RE.sub("", line).strip()
        if line:
            out.append(line)
    return out


def source_path(manifest, rel):
    """Map a dest-relative path back to its path in the wb repo via the manifest entries."""
    for e in manifest["entries"]:
        d = e["dest"].rstrip("/")
        if rel == d:
            return e["path"]
        if rel.startswith(d + "/"):
            return e["path"].rstrip("/") + rel[len(d):]
    return None


def adopt(target, report, commit):
    """Overwrite seeded files that differ locally with the template version; print a unified diff each."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    adopted = []
    for rec in report.get("files", []):
        if rec.get("action") != "kept-local-differs":
            continue
        rel = rec["path"]
        src = source_path(manifest, rel)
        if src is None:
            raise Fail(f"--adopt: cannot map {rel} to a template path")
        new = run(["git", "show", f"{commit}:{src}"], WB).stdout
        dest = Path(target) / rel
        old = dest.read_bytes()
        diff = difflib.unified_diff(old.decode("utf-8", "replace").splitlines(keepends=True),
                                    new.decode("utf-8", "replace").splitlines(keepends=True),
                                    fromfile=f"a/{rel}", tofile=f"b/{rel}")
        sys.stdout.write("".join(diff))
        dest.write_bytes(new)
        adopted.append(rel)
    return adopted


def main(argv=None):
    ap = argparse.ArgumentParser(description="Instantiate an engagement repo from the workbench.")
    ap.add_argument("target")
    ap.add_argument("--name", required=True, help="engagement objective slug (kebab-case)")
    ap.add_argument("--success-criteria", required=True, help="file: one criterion per line")
    ap.add_argument("--title")
    ap.add_argument("--adopt", action="store_true", help="overwrite existing seeded files (prints diffs)")
    ap.add_argument("--ref", default="HEAD", help="workbench tag or sha (default HEAD)")
    a = ap.parse_args(argv)

    try:
        target = Path(a.target).resolve()
        if is_within(target, WB):
            raise Fail(f"target {target} is the workbench or inside it ({WB})", 2)
        if not SLUG_RE.fullmatch(a.name):
            raise Fail(f"--name '{a.name}' must be kebab-case", 2)
        if not Path(a.success_criteria).is_file():
            raise Fail(f"--success-criteria {a.success_criteria}: not a file", 2)
        lines = criteria_lines(a.success_criteria)
        lock = target / LOCK_NAME
        if lock.exists():
            raise Fail("already instantiated; use template_sync pull", 1)
        target.mkdir(parents=True, exist_ok=True)

        commit = run(["git", "rev-parse", "--verify", f"{a.ref}^{{commit}}"], WB).stdout.decode().strip()
        sync = WB / "engagement" / "tools" / "template-sync" / "template_sync.py"
        if not sync.is_file():
            raise Fail(f"{sync} missing: pull hop 1 into engagement/ first", 2)
        if not (WB / "engagement" / "tools" / "objective.py").is_file():
            raise Fail("engagement/tools/objective.py missing: pull hop 1 into engagement/ first", 2)
        r = run([sys.executable, "-B", str(sync), "init", "--source", f"wb={WB}", "--commit", f"wb={commit}",
                 "--manifest", str(MANIFEST), "--dest", str(target), "--lock", str(lock),
                 "--edition", "engagement"], target, check=False)
        if r.returncode != 0:
            raise Fail("template_sync init failed:\n" + r.stdout.decode("utf-8", "replace")
                       + r.stderr.decode("utf-8", "replace"), 1 if r.returncode == 1 else 2)
        report = json.loads(r.stdout.decode("utf-8"))
        kept = [f["path"] for f in report["files"] if f.get("action") == "kept-local-differs"]
        if a.adopt:
            for p in adopt(target, report, commit):
                print(f"adopted: {p}")
        else:
            for p in kept:
                print(f"seeded file exists, left alone: {p} (use --adopt to overwrite)")

        py = [sys.executable, "-B"]
        run(py + ["tools/objective.py", "create", a.name, "--title", a.title or a.name], target)
        for line in lines:
            run(py + ["tools/objective.py", "add-kr", a.name, line, "met"], target)
        for slug, title, gtype, who, criteria in GATES:
            run(py + ["tools/intake.py", "gate", "add", slug, "--title", title, "--type", gtype,
                      "--who", who, "--criteria", criteria, "--objective", a.name], target)
        run(py + ["tools/intake.py", "render"], target)
        run(py + ["tools/objective.py", "render", "--all"], target)
    except Fail as e:
        print(f"engagement_new: {e}", file=sys.stderr)
        return e.code

    print(f"instantiated {target} from workbench @{commit[:8]} ({len(lines)} KRs, {len(GATES)} gates)")
    print("next steps:")
    print("  1. commit: git add -A && git commit -m \"engagement: instantiate from workbench\"")
    print(f"  2. onboarding step 2: python -B tools/objective.py next {a.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
