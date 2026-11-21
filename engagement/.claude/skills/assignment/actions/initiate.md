# Action: Initiate an Assignment

## Steps

1. **Name** — propose `kebab-case-name`, confirm before creating.
2. **Parent** — check `control-plane/workstreams/index.md` and `control-plane/objectives/index.md`; standalone if no match.
3. **Create**:

```bash
python -B tools/assignment.py create <name> [--parent workstreams/<name>|objectives/<name>] [--title "Title"] [--intake-source intake:<slug>]... [--milestone <obj>#N] [--locks <lock>]
```

Claim it before working: `python -B tools/assignment.py claim <name>` (`release <name>` to hand off; writes `claimed_by` / `claimed`).

If the work consumes intake records or delivers a milestone, pass them: `--intake-source` (repeatable; copies the record's `inputs`/`backlog` and sets it `active`), `--milestone {obj}#N` (sets the milestone `active`), `--locks` (names from `control-plane/locks.md`). Never hand-add `intake_source` or other record keys.

4. **Write the assignment** in `index.md` — one or two sentences: what the assignment is, what you understand the job to be. This is the assignment's durable value.
5. **Populate the checklist** with concrete steps.
6. **Link to parent** (if applicable):

```bash
python -B tools/workstream.py link <workstream-name> <assignment-name>
```

## Hand off

Proceed directly to doing the work — no phase advance needed. Assignments are lightweight and execute without a phase machine.
