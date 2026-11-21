# Action: Status

Report where an objective stands. Read-only. Load this file only.

## When to Run

- "What's the status of / in flight / blocked / waiting on me for {objective}?"
- No objective named -> portfolio roll-up (last section)

**Writes nothing.** No `update-kr`, `health`, `check-milestone`, `checkpoint` or `log-decision`. Updating KRs, milestones or health, or recording a checkpoint -> `actions/checkpoint.md`. Choosing and opening the next unit -> `actions/next.md`.

## Steps

### 1. Pull state

`python -B tools/objective.py status {name}` — health, cadence, KRs (current / target, last updated), milestone done/total, linked workstreams, last 3 decisions.

### 2. Pull the work queue

`python -B tools/objective.py next {name} --json` — read `active`, `ready` (ranked; first is top), `human` (gates: `who`, `criteria`), `lock` (`holder`), `blocked` (`root_blockers`). Exit 2 = dependency cycle; report it, do not fix it here. Field semantics and ranking: `actions/next.md` step 1. Do not re-rank.

### 3. Read recent decisions

`status` shows the last 3. If they don't explain the current state, read more rows of the Key Decisions Log in `control-plane/objectives/{name}/index.md`.

### 4. Report

```
Objective:   {name} — {health}, cadence {cadence}
Key Results: {result}: {current} / {target}   (one line each)
Milestones:  {done}/{total}
In flight:   {active ids + titles | none}
Top READY:   {ready[0] id + title | none} ({n} READY total)
Human gates: {gate id — who — criteria, one line each | none}
Locks:       {item -> lock held by holder | none}
Blocked:     {count; root blockers}
Decisions:   {last 1–3, one line each}
```

No recommendation. If the user wants one, or wants to open the top item, load `actions/next.md`.

### Portfolio (no objective named)

Run `python -B tools/objective.py list`, then `status` per active objective. One line each: name, health, KR summary, active count, open human gates.
