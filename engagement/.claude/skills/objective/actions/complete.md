# Action: Close Objective (Complete or Abandon)

Close out an objective, either because it succeeded (**complete**) or because it stopped mattering (**abandon** — includes merges into another objective). Load this file only.

## Key Difference From Workstream Cleanup

**Objective folders are never deleted.** Closing an objective is a status change, a Key Decisions Log entry, and a move — never a deletion. The folder, its `index.md`, and its full decisions log persist indefinitely at a new location:

- Complete → `control-plane/objectives/_archive/closed/{name}/`
- Abandoned → `control-plane/objectives/_archive/abandoned/{name}/`

Nothing is summarized or dropped in the move — the objective's own `index.md` is the record for future reference, in full.

## When to Run

**Complete:**
- All Success Criteria met (verify each explicitly)
- All Definition of Done conditions satisfied
- User confirms they are ready to close

**Abandon:**
- The objective stopped being a priority — user confirms this explicitly. Staleness (no recent checkpoint activity, no linked workstream progress) is a prompt to *ask*, never grounds to abandon unilaterally — content alone cannot establish that an objective no longer matters.
- Also covers a **merge**: two or more objectives consolidating into one. The predecessor(s) are abandoned with a reason naming the successor (e.g. `--reason "merged into gtm-enablement" --disposition "merged into gtm-enablement"`); the successor objective is created or updated separately (not by this action).

If any child workstream is still active, do not close the objective either way — complete or explicitly abandon those first (via the `workstream` skill).

## Steps

### 1. Verify readiness

**Complete:** Read `control-plane/objectives/{name}/index.md`. For each item in Success Criteria, confirm it's actually met. If any are not: stop, report the gap, do not close.

**Abandon:** Confirm the disposition and reason with the user if not already explicit — the CLI requires `--reason` and will not proceed without one.

### 2. Check child workstreams

Read `control-plane/workstreams/index.md` — any active workstream with `parent: "objectives/{name}"` must be resolved first (completed via `workstream` skill's cleanup, or explicitly paused/abandoned).

### 3. Write a closing summary section

Use the Edit tool to append a new top-level section to the objective's `index.md`, immediately before the `## Related Notes` section (or at the end if no Related Notes):

**Complete:**
```markdown
## Completion Summary

**Completed:** {YYYY-MM-DD}

### Outcome

{2–4 sentences on what was achieved vs. the Objective statement. Honest — if scope changed, say so.}

### Key Results Resolution

{For each KR, note the final value achieved vs. the target.}

### What Lives On After Close

{Where the work continues — systems, ongoing workflows, spawned objectives, etc.}

### Lessons Learned

{What to carry into future objectives. Honest.}
```

**Abandon:**
```markdown
## Closing Summary

**Abandoned:** {YYYY-MM-DD}

### Why

{The reason this stopped mattering — the same substance as the CLI's `--reason`, in fuller prose if useful.}

### State at Close

{Where things actually stood — KRs/milestones as of closure, honestly, not retroactively improved.}

### What Carries Forward

{A successor objective this merged into, a lesson worth remembering, or "nothing — the work itself stopped mattering," if that's the honest answer.}
```

This section is optional for a quick, low-stakes abandon (e.g. an objective that never left discovery stage) — the CLI's Key Decisions Log entry (step 4) is the non-negotiable minimum record either way. Write the fuller section when there's real history worth narrating.

### 4. Run the CLI — writes the Key Decisions Log entry and moves the folder

**Complete:**
```
python -B tools/objective.py complete <name> [--reason "<reason>"]
```

**Abandon:**
```
python -B tools/objective.py abandon <name> --reason "<reason>" [--disposition "<disposition>"]
```

`--disposition` defaults to `"abandoned"` — pass a more specific value (e.g. `"merged into gtm-enablement"`) when the closure reason has a name worth surfacing directly in the Key Decisions Log entry and the portfolio index's Abandoned-table Reason column.

Both commands: append a Key Decisions Log row to the objective's own `index.md` (do NOT hand-write this yourself — the CLI does it, matching the exact table format `cmd_log_decision` already uses), update the portfolio index (`objectives/index.md`) Active table → Complete/Abandoned table with a link to the new archive path, then physically move the folder to `_archive/closed/{name}/` or `_archive/abandoned/{name}/`.

Do NOT remove other frontmatter fields. Do NOT truncate the decisions log. Do NOT move the folder by hand — the CLI's move and its portfolio-index link update happen together; doing one without the other leaves a dangling link.

### 5. Report

Tell the user:
- Objective closed, folder moved to `control-plane/objectives/_archive/{closed|abandoned}/{name}/`
- Decisions log preserved in full, plus the new closure entry
- Closing summary written (if step 3 produced one)
- Any workstream logs that reference this objective remain valid (they still name the objective by its original name; only its filesystem location changed)

Remind them: the folder is not deleted, only relocated. It remains the full record for future reference.
