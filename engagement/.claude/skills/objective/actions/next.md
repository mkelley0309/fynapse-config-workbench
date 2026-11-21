# Action: Next

Decide what to open next for an objective. Load this file only.

## When to Run

- "What should I work on next for {objective}?"
- A checkpoint (`actions/checkpoint.md`) or session start needs a recommendation
- A unit just closed and the next one must be chosen

## Steps

### 1. Compute

```
python -B tools/objective.py next {name} --json
```

Output is `harness-records/1`, kind `next`: `ready` (ranked), `blocked` (with root blockers), `human` (open gates with `who` and `criteria`), `lock` (ready but a lock is held, naming the holder), `active` (already in flight, not ranked) and `notes`. Exit 2 means a dependency cycle; the output names it. Fix it through the CLI (`objective.py set-milestone ... --depends-on`) before continuing.

Items claimed by someone else (`claimed_by` on the unit) are not READY: they show as `CLAIMED(<user>)` in the `CLAIMED` list. Claim with `python -B tools/workstream.py|assignment.py claim <name>`, release with `release <name>`.

An objective without a `milestones/` folder is not migrated; the command says so.

### 2. Read recent decisions

Read the last few rows of the objective's Key Decisions Log in `control-plane/objectives/{name}/index.md`. A decision may reorder or close off a READY item; if it does, the right fix is a `depends_on` edge or a dropped record (CLI), not a prose override.

### 3. Recommend

State one item and why:

- **READY exists** -> name the top-ranked item (most downstream unblocked, then `order`). Give its `unblocks` count and any backlog progress. If the notes say several READY items share a free lock, only one can open; say which and why.
- **Nothing READY, HUMAN exists** -> name each open gate the operator can clear (`who`, `criteria`) and what it unblocks. Clearing is `python -B tools/intake.py gate resolve {slug} --evidence "{sha | decision row | path}"`; evidence is required.
- **Nothing READY, only BLOCKED or LOCK** -> name the root blockers or the lock holder. A lock held by `uncommitted changes` means commit the vault edits first.
- **ACTIVE items** -> list them first; opening more work while units are in flight is the operator's call.

### 4. Open it

When the operator agrees, open the unit with the matching skill, passing the record: `workstream.py create ... --milestone {obj}#N` or `--intake-source intake:{slug}` (and `--locks` if the record declares locks). The CLI marks the record `active`.

Do not summarize the whole objective; the recommendation is the output.
