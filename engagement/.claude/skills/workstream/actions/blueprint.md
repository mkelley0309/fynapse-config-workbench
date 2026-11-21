# Action: Blueprint

Produce the executable blueprint. Output: `blueprint.md`. The blueprint must be self-contained — an implementer must not need to read any prior artifact to execute it.

## Steps

1. Read `design.md` — Blueprint's payload (see SKILL.md → Phase Handoff). If Design was skipped, read `research.md` directly instead — that's the fallback payload, not an addition to `design.md`. Exception: `research.md` sections listed in `design.md`'s Data Inputs are planned payload — read those. Do not otherwise read `research.md`/`request.md` alongside an existing `design.md`; escalate to them only if `design.md` is demonstrably insufficient to write a concrete step, and log the gap in `friction-log.md` (`[blueprint]`) so `design.md` gets fixed rather than re-escalated past next time.
2. Write `blueprint.md` using the template in `framework-templates.md`. Frontmatter: `note_type: workstream-blueprint`. Write it as Implement's self-contained payload — an implementer should not need `design.md` to execute a step unless that step is genuinely ambiguous.
3. **Write the gate:** `outputs/{name}/gate.json`, with one check for each Completion Criterion that can be checked mechanically. Scaffold it with `python -B tools/gate.py init --config outputs/{name}/gate.json`, then replace the placeholder checks.
   - Put helper scripts in `outputs/{name}/scripts/` and run every command from the Workspace root.
   - Pin a baseline the checks compare against (e.g. a commit sha in `outputs/{name}/baseline.txt`, or a lint capture).
   - Self-test each script: it must PASS on the current tree and FAIL on a deliberate negative case. A gate's first NO-GO can be its own bug.
   - A criterion that cannot be checked mechanically stays for adversarial QA; name it in the blueprint's `## Gate` section.
   - A prior workstream's `outputs/*/scripts/` often fits with only a path change (lint-vs-baseline, `^id` diff, EOL churn).
   - Implement batches run the same gate at their close, so it is a batch check, not only the final one.
   - `workstream.py advance <name> implement` refuses while the gate is missing, invalid or still holds the `init` placeholder.
4. If the blueprint defines worktrees, write each `worktree-{nn}.md` in the same session. Each must be fully self-contained.
5. Present the blueprint and gate to the user. Do not advance to implement until they confirm.
6. On confirmation:

```bash
python -B tools/workstream.py advance <name> implement
```

## Quality checks before writing

- Every step has a concrete output, not just an action.
- Scope "Out" excludes things someone might assume are in.
- Completion criteria are verifiable — not "done" but "file X exists and passes Y".
- Worktrees are truly independent of each other.
- Every design decision a step cites ("per D-B") is inlined in the blueprint's Reference Tables. A bare citation forces implement to read `design.md` — an off-payload read.
- Every count or row total a step states ("143 rows from K-D") is checked against its source table before presenting. Count the table's rows; footnote or prose-only items are not rows. A wrong count forces implement to invent or drop rows.

**Claude Code:** delegate blueprint drafting to a Sonnet subagent when the blueprint has >3 phases or >10 steps.
