---
description: Operating contract for the control-plane subtree — orchestration layer for objectives, workstreams, and assignments.
paths: ["control-plane/**"]
---

# Control Plane

The orchestration layer. Coordinates objectives and workstreams; does not execute domain logic in place.

---

## Layout

```
control-plane/
  CLAUDE.md                 ← thin pointer (contract lives in .claude/rules/control-plane.md)
  intake/                   ← capture layer for unstructured input (pre-triage)
    index.md              ← intake conventions and lifecycle; generated `## Live Queue`
    {slug}.md             ← one record per captured idea, note or handover
    _archive/             ← consumed and dropped records (moved by the CLI, never deleted)
  gates/                    ← gate records: human, external, decision or artifact blockers
    {slug}.md
  locks.md                  ← lock registry: `| lock | probe | meaning |`
  objectives/               ← long-lived, checkpoint-cycle-measured initiatives
    index.md              ← portfolio index of active objectives
    {name}/
      index.md            ← objective anchor (goal, success, decisions log)
      milestones/
        NN-{slug}.md      ← one record per milestone; `## Milestones` in index.md is a generated view
      checkpoints/
        YYYY-MM-DD.md     ← one per cadence cycle; KR snapshot + health evidence
      {supporting files}    ← retained after completion; never deleted
    _archive/
      closed/{name}/        ← full objective folder, moved here on complete
      abandoned/{name}/     ← full objective folder, moved here on abandon
  workstreams/              ← multi-session discrete efforts (heavy lifecycle)
    index.md              ← portfolio index of active workstreams
    {name}/
      index.md            ← workstream status anchor (phase, health)
      request.md | research.md | design.md | blueprint.md | validate.md | worktree-{nn}.md
      friction-log.md       ← how the *harness* performed; never what the work found
      _working/             ← throwaway scratch
    _log/
      YYYY-MM-DD-{name}.md  ← durable summary after cleanup
  assignments/                    ← lightweight, often-repeatable units of work
    index.md              ← portfolio index of assignments
    _log.md               ← running log; durable record of every completed assignment
    {name}/                 ← deleted at completion, once logged
      index.md            ← assignment, checklist, handoff, lessons, friction
  cadences/                ← recurring work, scheduled or on demand
    index.md              ← portfolio index of active cadences
    _log.md               ← durable record of every retired/abandoned cadence
    {name}/                 ← deleted at close, once logged
      index.md            ← purpose, trigger, guardrails, run log, self-improvement diary
      _working/             ← scratch, for runs that need workstream-style handoffs
```

At the workspace root, alongside `control-plane/`:

```
_harness/                   ← the harness's own feedback loop; never deleted
  friction.md              ← cross-run ledger of unresolved framework friction
outputs/                    ← durable artifacts produced by workstreams (never deleted)
  index.md                 ← index of all outputs, organized by workstream
  {workstream-name}/       ← one folder per workstream that produced artifacts
    {artifact files}       ← slides, documents, configs, generated content, etc.
```

---

## Intake, Objectives, Workstreams, Assignments, and Cadences

**Intake** = unstructured capture. Ideas, notes, partial thoughts, handovers land here as records before routing. Lifecycle: `capture → triage → active → consumed | dropped`. `active` is set by the CLI when a unit that consumes the record opens (`create --intake-source`); `consumed` is set by the CLI when that unit closes (`complete`, `retire`, `abandon`), which also archives the file to `intake/_archive/`. Dropped records carry a reason and are archived too. Each record has exactly one `route`, plus `depends_on` edges to milestones, gates, other intake or units. Sequencing is read with `objective.py next`; change records only through `tools/intake.py`, `tools/objective.py` and the unit CLIs (see `tools/README.md`), never by hand.

**Milestones** are records, not checklist lines. **Gates** are records for blockers that need a human, an external party, a decision or an artifact. **Locks** (`control-plane/locks.md`) serialize exclusive resources; a lock is held by an active record, an open workstream or assignment that declares it, or a firing probe.

Below intake, work runs in **four tiers, with ceremony sized to the tier**:

**Objectives** = the long-lived *why*. Measured in formal checkpoint cycles, tracked with Key Results, milestones, linked workstreams, a checkpoint cadence, and a health signal. Retained after completion (the decisions log is the durable value). One folder per objective. Lifecycle: `active` → `complete` | `abandoned`; folders never deleted — moved to `_archive/{closed|abandoned}/` on close.

**Workstreams** = the heavy, formal lifecycle for complex multi-session, multi-handoff work. Follow Payload Relay / Short Relay. Open one when the work is too big for an assignment — too many sessions, too many handoffs, or too much structural risk to leave untracked. On cleanup, the folder is deleted after the log entry is written. Workstreams typically have `parent: "objectives/{name}"`.

**Assignments** = the lightweight unit. A small, often-repeatable job done under a workstream or standalone (add a source, refresh data, lint an area, one iteration against a workstream). Proportional admin only: assignment, checklist, handoff, lessons — never workstream-grade distillation. If an assignment grows into real multi-session research or design, promote it to a workstream.


The log also exists because a lesson left inside one assignment folder will not be noticed on the next assignment, which is the same reason harness friction goes to `../_harness/friction.md`. In both ledgers, an entry appearing twice has outgrown the log and belongs in a skill or a tool.

**Cadences** = work defined by its **recurrence**, not its size. Refresh docs into the knowledge base, drain the cleanup queue, report status across the portfolio, auto-lint. A cadence may be assignment-sized or workstream-sized — what makes it a cadence is that it runs again, whether on a schedule or on demand. It gets a folder for tracking, a `_working/` scratch area for runs that need workstream-style handoffs, and a **self-improvement diary**: after each run, one line on what would make the *next* run cheaper, safer or more accurate. A cadence that never improves is a subscription. Lifecycle: `active` → `paused` → `retired` (job done or automated away) or `abandoned` (stopped mattering); the folder is deleted once logged.

Pick the smallest tier that fits. Under-shaped work is expensive; over-ceremonied work is also expensive. Objective sits apart — it is chosen by durability (does this outlive any single session's work?), not by shape. The other three are chosen by shape, not size: **bounded and single-session** → assignment, **multi-session with handoffs** → workstream, **it runs again** → cadence.

**These relate in two different directions, so it is a graph rather than a strict tree.**

**Spawn — downward, during a life, many times.** A workstream spawns child assignments for parallel or repeatable sub-units. A cadence spawns whatever a given run deserves: nothing at all for a small inline run, an assignment for a bounded one, a workstream for one that needs real handoffs. A spawned child runs its own lifecycle and closes into its own log, so **the parent holds the coordination, not the work**. A quarterly refresh that turns into real research should spawn a workstream rather than growing a `research.md` inside the cadence. Recorded with `cadence.py run --spawned assignments/{name}`.

**Promotion — sideways or upward, at a boundary, once.** Work that turns out to be worth repeating becomes a cadence: `cadence.py create {name} --from assignments/{name}`. The originating assignment or workstream still closes normally into its own log, and the cadence is a *new* record that points back at what proved the case. Same class as an assignment that grows into multi-session work and is promoted to a workstream — which must happen **before** it completes, since completing deletes the folder.

The distinction matters because the mechanics differ: **spawn is delegation during a life, promotion is reshaping at a boundary.** A cadence that spawns an assignment every month is doing its job. An assignment that promotes to a cadence happens once and then never again.

**Every tier is a Payload Relay.** The tiers differ in how many legs the relay has, not in kind. A workstream is the full relay — most legs, most handoffs. An assignment is the same relay with fewer legs, because the body of work is smaller. A cadence is a relay that runs again; each run is its own sequence. An objective spawning a workstream or assignment is passing payload to another relay sequence. Read spawn and promotion above as payload movement between sequences, not as a separate mechanism.

### Autonomy mechanisms (`/goal`, `/loop`, `schedule`)

These are **mechanisms, not tiers** — they say *how* a unit of work keeps going, and any tier can use them. Pick by what ends the work:

| Mechanism | Repeats until | Use at |
|---|---|---|
| `/goal <condition>` | a stated condition holds, then self-clears | assignment · a workstream phase · one cadence run |
| `/loop [interval]` | you stop it | a cadence run that polls |
| `schedule` | its cron says otherwise | a cadence trigger |

**`/goal` applies wherever the work has a verifiable end state inside a session.** That is an assignment ("the checklist is complete and the gate reported GO"), a workstream *phase* ("every plan step is checked"), or a *single* cadence run ("the queue is drained"). It does **not** apply to an objective, which is measured in checkpoint cycles against Key Results and deliberately outlives any session, nor to a cadence itself, which by definition never completes.

Two constraints worth designing around. The evaluator judges the condition against **what has been surfaced in the conversation** — it does not run commands or read files — so a run must *print* its gate result for `"the gate passes"` to be a usable condition. And `/goal` needs an accepted trust dialog and is unavailable under `disableAllHooks` or `allowManagedHooksOnly`, so anything depending on it should say so in its guardrails.

```
objective
    ├── workstream ─── assignment   (child units)
    ├── assignment                  (standalone)
    └── cadence ──┬──  assignment   (spawned by a run)
                  └──  workstream   (spawned by a bigger run)
```

**Outputs** = durable artifacts produced during workstream implementation. Written to `outputs/{workstream-name}/` during the implement phase — never inside the workstream folder. This separation guarantees that cleanup (which deletes the workstream folder) cannot destroy produced artifacts. The `outputs/` tree is permanent; nothing is deleted from it.

---

## Harness Self-Improvement

Every tier records **how well the harness performed** during a run, separately from what the run produced:

| Tier | Where | Carried out at |
|---|---|---|
| Workstream | `friction-log.md` in the workstream folder | cleanup |
| Assignment | `## Friction` in the assignment's `index.md` | complete |
| Objective | `## Harness Friction` in each `checkpoints/YYYY-MM-DD.md` | checkpoint |

All three feed one permanent ledger: **`../_harness/friction.md`**.

**The inclusion test — would this note still be true and useful on a completely unrelated run?** If yes it is friction; if it names the subject matter it belongs in the work artifact (`research.md`, `design.md`, an assignment Lesson). Record the rule, not the incident.

Two things this is deliberately **not**:

- **Not a progress tracker.** `blueprint.md` checkboxes and `index.md` `current_step` are maintained together by `workstream.py check-step`. A second, hand-maintained status record rots and then misreports.
- **Not a general notepad.** The friction log is the only artifact that crosses every phase boundary, and that is affordable *only* while its scope stays narrow. Let it also carry findings and it becomes the cross-phase accumulator that progressive distillation exists to prevent.

Most runs produce no entries. An empty friction log is a clean run, not a gap to fill. Recurrence is the signal worth acting on: one annoyance is noise, the same annoyance three times is a defect.

---

## Commit Cadence (Workspace Root, Non-Project Work)



Message convention: `{workstream-or-assignment-name}: {what changed}`, matching existing practice
(e.g. `harness-consolidation: check-step 4a.1`).


---

## Session Entry

1. Read this file
2. Read `objectives/index.md`, `workstreams/index.md`, and `assignments/index.md`
3. If unstructured input needs triage, read `intake/index.md` first
4. If a specific item is in scope, read its `index.md`
5. Identify current phase (workstreams), checkpoint state (objectives), or assignment (assignments)
6. **State scope, phase/status, and intended next action before proceeding**

---

## Skill Routing (Claude Code)


---

## Workstream Framework

**Payload Relay** (default): Questions → Research → Design? → Blueprint → Implement → Validate → Cleanup
**Short Relay** (spec already clear): Research → Blueprint → Implement → Validate → Cleanup

Questions are cheap. Under-shaped work is expensive. Promote to Payload Relay the moment ambiguity, cross-system scope, or missing constraints surface.

**Research is mandatory** — there is no shortcut from Questions or Initiate to Design or Blueprint without a `research.md`. Even when source material is handed over directly, it goes to `_working/` and through the research protocol first.

**The gate is authored at Blueprint** (`outputs/{name}/gate.json` via `tools/gate.py`; `advance … implement` refuses a missing or placeholder gate), run at every implement batch close, and run as-is at **Validate** — the gate before close, plus adversarial QA for the soft concerns. Advance to `complete` only on GO.

Phase mechanics, artifact templates, and action-file routing live in the `workstream` skill.

> **Migrated 2026-07-30 from QRSPI/RPI.** The separate Outline step is folded into Design; Validate is new. Historical log entries under `_log/` still describe QRSPI and are left as written — they are the record of what was done at the time.
>
> **Migrated 2026-08-11: the Plan phase renamed to Blueprint** (`QRDPIV`/`RPIV` → `QRDBIV`/`RBIV`), including the `plan.md` artifact → `blueprint.md`. Existing workstreams opened before this date keep their `plan.md` filename and `qrdpiv`/`rpiv` frontmatter value as written; only new workstreams use the new name.
>
> **Migrated 2026-08-24: the framework renamed from `QRDBIV`/`RBIV` to Payload Relay / Short Relay**, and the handoff term from "primary artifact" to "payload". Workstreams opened before this date keep their `qrdbiv`/`rbiv` frontmatter value as written; only new workstreams use the new name.

---

## State Models

### Unit keys (workstream, assignment, cadence `index.md`)

Additive, CLI-written (`create --intake-source/--milestone/--locks`); never hand-add:

```yaml
intake_source: [intake:{slug}, ...]   # records this unit consumes
milestone: "{obj}#N"                  # milestone this unit delivers (workstream, assignment)
locks: [lock-name, ...]               # names from locks.md
inputs: [path, ...]                   # copied from intake_source records
backlog: [path, ...]                  # subset of inputs
claimed_by: "<git user.name>"         # workstream, assignment; written/cleared by claim|release
claimed: YYYY-MM-DD                   # with claimed_by
```

`workstream.py|assignment.py claim|release <name>` writes/clears `claimed_by` and `claimed`. `objective next` shows `CLAIMED(<user>)` and does not offer items claimed by someone else as READY.

Workstream and assignment bodies also carry `## Residuals` (one bullet per line: `none`, `intake:`, `milestone:`, `spawned:`, `dropped: ... (decision {obj} YYYY-MM-DD)`, `handover: {target} — {purpose}; inputs: ...; backlog: ...`). Cadences carry it at retire/abandon. `complete` / `retire` / `abandon` refuse without it, settle intake and the milestone, and print the residual block for the log entry (`### Residuals` in workstream logs, `**Residuals.**` in assignment and cadence logs; `**Carried forward.**` holds lessons only).

### Workstream `index.md` frontmatter

```yaml
workstream: kebab-case-name
framework: short-relay | payload-relay
workstream_phase: questions | research | design | blueprint | implement | validate | complete | cleanup
workstream_health: healthy | needs-questions | needs-design | under-shaped | blocked | stale
status: active | complete | paused | abandoned
started: YYYY-MM-DD
completed: YYYY-MM-DD
parent: null | "objectives/{name}"
# + unit keys above
```

### Objective `index.md` frontmatter

```yaml
objective: kebab-case-name
status: active | complete | abandoned
health: on-track | at-risk | blocked | stale
cadence: weekly | bi-weekly | monthly | quarterly | semi-annual | annual
created: YYYY-MM-DD
completed: YYYY-MM-DD          # set at close; folder retained
parent_objective: null | "objectives/{name}"   # nesting under another objective
promoted_from: "{origin}"                      # written by `create --from`: the work that proved the case (cadences carry it too)
tags: [objective, ...]
```

Canonical objective `index.md` section order:

```
## Objective              what and why
## Success Criteria       prose; the fuller narrative
## Key Results            measurable, with targets — CLI-managed
## Milestones             checklist — CLI-managed
## Workstreams            linked, advancing it — CLI-managed
[objective-specific sections — Content Scope, Sequencing, Stakeholders, …]
## Dependencies
## Key Decisions Log
## Definition of Done
## Related Notes          always last
```

The three CLI-managed sections sit **after** Success Criteria, matching what `objective.py create` generates. Objective-specific middle sections keep their own relative order; only the four fixed sections at the top and the four at the bottom are canonical.

The **Key Decisions Log** is an append-only table (`| Decision | Rationale | By | Date |`) — timestamped, never truncated, never reordered. `By` is `log-decision --by NAME`, default git `user.name`, else `operator`.

Not everything belongs in a Key Result. Where a Success Criterion states no count, threshold, or baseline, leave it as prose and log the gap in the Key Decisions Log — a KR with an invented target is worse than no KR.

### Objective checkpoints

`cadence` mandates recurring checkpoints; each checkpoint is written as its own dated file, never appended to `index.md`:

```
objectives/{name}/
  index.md              ← anchor
  checkpoints/
    YYYY-MM-DD.md       ← KR values at checkpoint, health call + evidence, decisions taken
  {supporting}.md       ← specs, artifacts retained with the objective
```

Scaffold with `python -B tools/objective.py checkpoint {name}` — it snapshots current KRs, milestones, workstreams, and health, and does **not** write to `index.md`. This is also what gives Key Results a history: `update-kr` overwrites `current` in place, so without a dated snapshot the trajectory is lost on every update. A `health` value asserted without evidence in a checkpoint entry is an assertion, not a signal.

`health`, `cadence`, Key Results, Milestones, and `checkpoints/` are **additive** — objectives created before 2026-07-30 simply have them empty until populated via `tools/objective.py`.

### Assignment frontmatter (`assignments/{name}/index.md`)

```yaml
assignment: kebab-case-name
status: active | complete | abandoned
parent: null | "workstreams/{name}" | "objectives/{name}"
started: YYYY-MM-DD
completed: YYYY-MM-DD
validated: YYYY-MM-DD
tags: [assignment/{name}]
# + unit keys above
```

Assignment body sections: **Assignment** (what the job is, in a sentence or two — this understanding is the assignment's real value) · checklist · handoff · lessons · `## Residuals`.

### Intake `intake/{slug}.md` frontmatter

```yaml
note_type: intake
kind: item | handover
status: captured | triaged | active | consumed | dropped
captured: YYYY-MM-DD
source: free text
objective: {obj} | none
route: milestone:{obj}#N | workstream:{name} | assignment:{name} | cadence:{name} | candidate:workstream | candidate:assignment | tools | none
depends_on: [id, ...]        # intake:{slug}, {obj}#N, gate:{slug}, workstream:{name}, assignment:{name}, cadence:{name}
related: [id, ...]           # never blocks
locks: [lock-name, ...]
inputs: [workspace-relative path, ...]
backlog: [path, ...]         # subset of inputs
consumed_by: [unit id, ...]
keep_until: id               # stays live until this id is satisfied
dropped_reason: text         # cites "{obj} YYYY-MM-DD"
consumed: YYYY-MM-DD         # written by the CLI when consumed or archived
dropped: YYYY-MM-DD          # written by the CLI when dropped or archived
```

ID `intake:{slug}` survives archiving. Satisfied when `consumed`. The `program-intake` view selects archived records by `consumed:`/`dropped:`, never by file mtime or clock.

### Milestone `objectives/{name}/milestones/NN-{slug}.md` frontmatter

```yaml
note_type: milestone
id: {obj}#N
title: text
status: open | active | done | dropped
order: int                   # defaults to N
conditional: true | false    # a dropped conditional milestone counts as satisfied
depends_on: [id, ...]
related: [id, ...]
locks: [lock-name, ...]
fed_by: [intake:{slug}, ...]
inputs: [path, ...]
backlog: [path, ...]
unit: workstream:{name} | assignment:{name} | cadence:{name}
ref: external ordinal
done: YYYY-MM-DD
legacy: "original checklist line, verbatim"
```

Sub-steps go in the body as a checklist. Satisfied when `done` (or `dropped` with `conditional: true`).

### Gate `gates/{slug}.md` frontmatter

```yaml
note_type: gate
title: text
gate_type: human | external | decision | artifact
who: operator | {name}
criteria: what resolves it
status: open | done | dropped
resolved: YYYY-MM-DD
evidence: sha | "{obj} YYYY-MM-DD" | path | cadence run row
objective: {obj} | none
```

ID `gate:{slug}`. Satisfied when `done`; `intake.py gate resolve` requires evidence.

Frontmatter allows only scalars, quoted strings and flow lists. Unknown keys are preserved and reported by `intake.py check` as warnings (errors under `--strict`). Generated views (`intake-queue`, `milestones`, `program-intake`, `carried-inputs`, `gates`) sit between `<!-- generated:{view} -->` markers; change them only with `intake.py render` / `objective.py render`. `intake.py render --resolve` / `objective.py render <name>|--all --resolve` drop both sides of a git conflict inside a generated region and re-render; conflict lines outside regions are left for a human and reported.

Root discovery: tools walk up from cwd to the nearest `control-plane/`. If `WORKSPACE_ROOT` is set and disagrees with that walk-up, the CLI refuses, naming both roots. Duplicate record ids (e.g. two milestone files minting the same `{obj}#N`) are an `intake.py check` error.

---

## Delegation Model

1. Interpret request into a structured objective
3. Decompose into discrete steps with owning targets
5. Collect outputs; reconcile against plan
6. Validate completeness against original intent

---

## Boundaries

- Do not bypass project boundaries to "just fix it quickly"
- Maintain separation: planning here, execution in projects
