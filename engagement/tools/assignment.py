#!/usr/bin/env python3
"""Assignment (light unit) state management — lightweight, no phase machine, no LLM."""

import argparse
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesslib  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

WORKSPACE = harnesslib.find_root()
ASSIGNMENTS_DIR = WORKSPACE / "control-plane" / "assignments"
PORTFOLIO_INDEX = ASSIGNMENTS_DIR / "index.md"

# ── helpers ───────────────────────────────────────────────────────────────────

def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)

def today():
    return date.today().strftime("%Y-%m-%d")

def kebab_ok(name):
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name))

def assignment_dir(name):
    if not kebab_ok(name):
        die(f"invalid assignment name '{name}' — must be kebab-case (a-z, 0-9, hyphens); no path separators")
    p = ASSIGNMENTS_DIR / name
    if not p.exists():
        die(f"assignment '{name}' not found at {p}")
    return p

def read_index(name):
    p = assignment_dir(name) / "index.md"
    if not p.exists():
        die(f"index.md not found for '{name}'")
    return p, p.read_text(encoding="utf-8")

def fm_get(text, field):
    m = re.search(rf"^{re.escape(field)}:[^\S\n]*([^\r\n]+)", text, re.MULTILINE)
    return m.group(1).strip().strip('"') if m else None

def fm_set(text, field, value):
    # `\s*` would cross the newline, so setting an EMPTY field ("completed:") captured
    # the following line into the match and overwrote it. Horizontal whitespace only.
    return re.sub(
        rf"^({re.escape(field)}:)[^\S\n]*[^\r\n]*$",
        f"\\g<1> {value}",
        text, flags=re.MULTILINE, count=1
    )

def _root():
    """Workspace root implied by ASSIGNMENTS_DIR (control-plane/assignments)."""
    return ASSIGNMENTS_DIR.parent.parent

def ensure_portfolio_index():
    if not PORTFOLIO_INDEX.exists():
        ASSIGNMENTS_DIR.mkdir(parents=True, exist_ok=True)
        harnesslib.write_text(PORTFOLIO_INDEX, "# Assignments\n\n"
            "## Active\n\n"
            "| Assignment | Description | Parent | Started |\n"
            "|---|---|---|---|\n\n"
            "## Complete\n\n"
            "| Assignment | Description | Completed |\n"
            "|---|---|---|\n")

# ── commands ──────────────────────────────────────────────────────────────────

SEPARATOR_RE = re.compile(r"^\|[\s\-|]+\|$")

def parse_index_rows(text):
    """Return the data rows of the Active table, across all ### subgroups.

    The Active table may be split under ### subgroup headings, each with its own
    header + separator row. Without resetting per subgroup, every subgroup header
    after the first is mistaken for a data row.
    """
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
            after_sep = False
            continue
        if SEPARATOR_RE.match(line):
            after_sep = True
            continue
        if after_sep and line.startswith("|") and "*(none yet)*" not in line:
            rows.append(line)
    return rows

def cmd_list(_args):
    if not PORTFOLIO_INDEX.exists():      # no index yet = no assignments (a fresh workspace lists nothing)
        return
    for line in parse_index_rows(PORTFOLIO_INDEX.read_text(encoding="utf-8")):
        print(line)


def cmd_set_unit(args):
    read_index(args.name)
    try:
        harnesslib.run_set_unit(_root(), f"assignment:{args.name}", args)
    except harnesslib.HarnessError as e:
        die(str(e))


def cmd_claim(args):
    read_index(args.name)
    harnesslib.run_claim(_root(), f"assignment:{args.name}")


def cmd_release(args):
    read_index(args.name)
    harnesslib.run_claim(_root(), f"assignment:{args.name}", release=True)


def cmd_create(args):
    name   = args.name
    if not kebab_ok(name):
        die(f"invalid assignment name '{name}' — must be kebab-case (a-z, 0-9, hyphens); no path separators")
    dest   = ASSIGNMENTS_DIR / name
    if dest.exists():
        die(f"'{name}' already exists")

    # R7 create-side flags: validate everything before the first write.
    sources = harnesslib.listflag(getattr(args, "intake_source", None))
    milestone = getattr(args, "milestone", None) or ""
    locks = harnesslib.listflag(getattr(args, "locks", None))
    try:
        cplan = harnesslib.create_plan(_root(), sources, milestone, locks, f"assignment:{args.name}")
    except harnesslib.HarnessError as e:
        die(str(e))

    parent  = args.parent or "null"
    title   = args.title or name.replace("-", " ").title()
    today_s = today()
    parent_q = f'"{parent}"' if parent != "null" else "null"
    if parent != "null":
        _rel = parent if "/" in parent else f"workstreams/{parent}"
        parent_link = f"[{_rel}](../../{_rel}/index.md)"
    else:
        parent_link = "—"

    index_md = f"""---
assignment: {name}
status: active
parent: {parent_q}
started: {today_s}
completed:
validated:
tags: [assignment/{name}]
intake_source: {harnesslib.render_value(sources)}
milestone: {milestone}
locks: {harnesslib.render_value(locks)}
inputs: {harnesslib.render_value(cplan["inputs"])}
backlog: {harnesslib.render_value(cplan["backlog"])}
---

# {title}

## Assignment

*What this assignment is — what you understand the job to be, in a sentence or two. This understanding is the assignment's real value.*

## Checklist

- [ ] *step placeholder*

## Handoff

*One line for the next assignment, if anyone picks up from here.*

## Lessons

*One line worth repeating or avoiding about this work, if you learned something.*

## Friction

*One line only if the harness got in the way — a tool that misbehaved, an instruction that
was wrong, an access scope too narrow. Would it still be true on an unrelated assignment? If it
names the subject matter it is a Lesson, not Friction. Usually empty.*

## Residuals

{harnesslib.RESIDUALS_COMMENT}

## Cross-links

- **Parent:** {parent_link}
"""

    dest.mkdir(parents=True)
    harnesslib.write_text((dest / "index.md"), index_md)
    print(f"created: {dest / 'index.md'}")
    harnesslib.create_apply(_root(), f"assignment:{name}", cplan)
    for sid in sources:
        print(f"active: {sid}")
    if milestone:
        print(f"active: {milestone} (unit assignment:{name})")

    ensure_portfolio_index()
    portfolio = PORTFOLIO_INDEX.read_text(encoding="utf-8")
    if parent != "null":
        rel = parent if "/" in parent else f"workstreams/{parent}"
        parent_col = f"[{rel}](../{rel}/index.md)"
    else:
        parent_col = "—"
    new_row = f"| [{name}]({name}/index.md) | *add description* | {parent_col} | {today_s} |"
    out, in_active, inserted = [], False, False
    for line in portfolio.splitlines():
        if line.startswith("## Active"):
            in_active = True
        elif line.startswith("## "):
            in_active = False
        if in_active and "*(none yet)*" in line:
            continue
        out.append(line)
        if in_active and not inserted and re.match(r"^\|[\s\-|]+\|$", line):
            out.append(new_row)
            inserted = True
    portfolio = "\n".join(out) + "\n"
    harnesslib.write_text(PORTFOLIO_INDEX, portfolio)
    print(f"updated: {PORTFOLIO_INDEX}")


def cmd_status(args):
    _, text = read_index(args.name)
    for field, key in [
        ("assignment",       "assignment"),
        ("status",     "status"),
        ("parent",     "parent"),
        ("started",    "started"),
        ("completed",  "completed"),
        ("validated",  "validated"),
    ]:
        val = fm_get(text, key) or "—"
        print(f"{field:<12} {val}")


def cmd_validate(args):
    idx_path, idx_text = read_index(args.name)
    today_s = today()
    # Test for the field's PRESENCE, not a non-empty value. The template ships
    # "validated:" empty, so a value-test failed and the else-branch inserted a
    # second key, leaving duplicate frontmatter fields.
    if re.search(r"^validated:", idx_text, re.MULTILINE):
        idx_text = fm_set(idx_text, "validated", today_s)
    else:
        # Insert validated field after completed field
        idx_text = re.sub(
            r"^(completed:.*)$",
            f"\\g<1>\nvalidated: {today_s}",
            idx_text, flags=re.MULTILINE, count=1
        )
    harnesslib.write_text(idx_path, idx_text)
    print(f"validated: {args.name}  date: {today_s}")


def cmd_complete(args):
    idx_path, idx_text = read_index(args.name)
    today_s = today()
    # R7 steps 1-2 + target resolution: refuse before the first write.
    try:
        plan = harnesslib.close_plan(_root(), f"assignment:{args.name}", idx_path)
    except harnesslib.HarnessError as e:
        die(str(e))
    actions = harnesslib.close_apply(_root(), plan)          # steps 3-5
    idx_text = fm_set(idx_text, "status", "complete")
    # Presence, not value — see the note on validated above.
    if re.search(r"^completed:", idx_text, re.MULTILINE):
        idx_text = fm_set(idx_text, "completed", today_s)
    else:
        idx_text = re.sub(
            r"^(status:.*)$",
            f"\\g<1>\ncompleted: {today_s}",
            idx_text, flags=re.MULTILINE, count=1
        )
    harnesslib.write_text(idx_path, idx_text)

    # Move from Active to Complete in portfolio
    portfolio = PORTFOLIO_INDEX.read_text(encoding="utf-8")
    row_match = re.search(rf"(\|\s*\[{re.escape(args.name)}\][^\n]+\n)", portfolio)
    if row_match:
        row = row_match.group(1)
        # Active is (assignment, description, parent, started); Complete is (assignment,
        # description, completed). Rebuild rather than patch the trailing cell,
        # otherwise the parent column rides along and the row has one cell too many.
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]
        # The assignment folder is deleted once its log entry is written, so a completed
        # row must not keep pointing at it. Repoint to the running log.
        name_cell = re.sub(
            rf"\[{re.escape(args.name)}\]\([^)]*\)",
            f"[{args.name}](_log.md)",
            cells[0], count=1
        )
        desc_cell = cells[1] if len(cells) > 1 else ""
        completed_row = f"| {name_cell} | {desc_cell} | {today_s} |"
        moved, n = re.subn(
            r"(## Complete\n\n\|[^\n]+\n\|[-|]+\n)",
            f"\\g<1>{completed_row}\n",
            portfolio, count=1
        )
        # Only drop the Active row once the Complete row is actually placed.
        # Removing first meant a missing "## Complete" section silently lost the assignment.
        if n:
            portfolio = moved.replace(row, "", 1)
        else:
            print("warning: no '## Complete' section in the portfolio index; "
                  "left the row under Active rather than dropping it")
    harnesslib.write_text(PORTFOLIO_INDEX, portfolio)
    print(f"completed: {args.name}")
    actions += harnesslib.render_views(_root(), plan["objectives"])   # step 6
    print("\n".join(harnesslib.close_report(plan, actions)))          # step 7


def cmd_delete(args):
    path = assignment_dir(args.name)
    shutil.rmtree(path)
    print(f"deleted: {path}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Assignment state management — lightweight")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List active assignments")

    s = sub.add_parser("create", help="Create a new assignment")
    s.add_argument("name", help="Assignment name (kebab-case)")
    s.add_argument("--parent", metavar="workstreams/<name>|objectives/<name>",
                   help="Parent path, e.g. workstreams/my-workstream")
    s.add_argument("--title", help="Human-readable title (defaults to title-cased name)")
    s.add_argument("--intake-source", action="append", metavar="intake:<slug>",
                   help="intake record this assignment consumes (repeatable); copies its inputs/backlog")
    s.add_argument("--milestone", metavar="<obj>#N", help="milestone this assignment delivers")
    s.add_argument("--locks", action="append", metavar="LOCK", help="lock names (repeatable or comma-separated)")

    harnesslib.add_set_unit_args(sub.add_parser("set-unit", help="Bind intake_source/milestone/locks/inputs/backlog to an open assignment"))

    for name_cmd in ("status", "validate", "complete", "delete"):
        s = sub.add_parser(name_cmd)
        s.add_argument("name")

    for name_cmd, hlp in (("claim", "Claim an open assignment for the git user (claimed_by/claimed)"),
                          ("release", "Release a claim (removes claimed_by/claimed)")):
        sub.add_parser(name_cmd, help=hlp).add_argument("name")

    args = p.parse_args()
    {
        "list":     cmd_list,
        "create":   cmd_create,
        "set-unit": cmd_set_unit,
        "claim":    cmd_claim,
        "release":  cmd_release,
        "status":   cmd_status,
        "validate": cmd_validate,
        "complete": cmd_complete,
        "delete":   cmd_delete,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
