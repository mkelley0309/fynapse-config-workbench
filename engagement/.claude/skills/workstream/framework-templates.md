# Workstream Templates

Fill-in templates for workstream artifacts. Load this file only when creating a new artifact — do not load during session entry, assess, or implement unless you are about to write a new file.

---

## `index.md` Template

```markdown
# {Workstream Title}

## Workstream Status

| Field | Value |
|---|---|
| Phase | {workstream_phase} |
| Health | {workstream_health} |
| Current Step | — |
| Blocker | — |
| Last Active | YYYY-MM-DD |

{One paragraph: what this workstream is and what it delivers.}

## Payload Relay Artifact Status   ← include for Payload Relay; omit for Short Relay

| Step | Artifact | Status |
|---|---|---|
| Questions | `request.md` | Not started |
| Research — Knowledge pass | `_working/research-knowledge-*.md` | Not started |
| Research — Web pass | `_working/research-web-*.md` | Not started |
| Research — Codebase pass | `_working/research-code-*.md` | Not started |
| Research — Distillation | `research.md` | Not started |
| Design | `design.md` | Not started |
| Blueprint | `blueprint.md` | Not started |
| Implement — Behavior Log | `behavior-log.md` | Not started |
| Implement — Handoff (current batch) | `_working/handoff.md` | Not started |
| Worktrees | `worktree-{nn}.md` | Not started |
| Validate | `validate.md` | Not started |

## Child Assignments

| Assignment | Linked |
|---|---|

## Residuals   ← required before `complete`; one bullet per line

- none   ← or: `intake:{slug}, {note}` · `milestone:{obj}#N, {note}` · `spawned:{unit id}` · `dropped: {text} (decision {obj} YYYY-MM-DD)` · `handover: {target} — {purpose}; inputs: {path}[, {path}]; backlog: {path}`

## Working Files   ← optional; add only once _working/ holds non-research-pass artifacts worth flagging

| File | Purpose | Read when |
|---|---|---|
| `_working/{name}.md` | {what it is — e.g. a design-phase scratch note, a blueprint draft} | {when a later phase escalating this far should bother opening it, vs. skip} |

## Cross-links

- **Parent Objective:** [objectives/{name}](../../objectives/{name}/index.md)   ← or omit if null
- {other relevant links}
```

---

## `request.md` Template

```markdown
# {Workstream Name} — Request

Refined specification produced at the Payload Relay Questions step. Replaces the original request as input to all downstream steps.

## Original Request

{Verbatim or paraphrased summary of what was asked}

## Clarifications

{Q&A from the Questions step — decisions made, scope confirmed}

## Refined Scope

**In:**
- {item}

**Out:**
- {item}

## Constraints and Assumptions

- {constraint or assumption}

## Success Definition

{How we'll know this workstream is done}
```

---

## `research.md` Template

```markdown
# {Workstream Name} — Research

Distilled from {n} knowledge pass(es), {n} web pass(es), {n} codebase pass(es). Self-contained — downstream steps do not read `_working/` files.

## Key Findings

### Knowledge

{Distilled vault/sources knowledge relevant to this workstream}

### Web

{Distilled external knowledge — standards, competitor info, technical refs}
← omit section if no web passes were run

### Codebase

{Distilled codebase knowledge — existing patterns, dependencies, constraints}
← omit section if no codebase passes were run

## Decisions Implied by Research

{Any decisions the research surfaces that need to be made in Design or Blueprint}

## Open Questions

{Anything research couldn't resolve — flags for Design or Questions follow-up}
```

---

## `design.md` Template

```markdown
# {Workstream Name} — Design

Architectural and structural decisions made before blueprinting. Produced from `research.md` (and `request.md` if Payload Relay).

## Decision: {Title}

**Context:** {why this decision was needed}
**Options considered:** {what was evaluated}
**Decision:** {what was chosen}
**Rationale:** {why}

## Decision: {Title}

...

## Constraints Carried into Blueprint

{What the blueprint must respect — architectural boundaries, interfaces, limits}
```

---

## `outline.md` Template

Written during Design when the deliverable's own structure needs agreement before blueprinting (document section order, vault layout, API shape, deck arc). Fold into `design.md` instead when the structure is small enough not to be referenced repeatedly.

```markdown
# {Workstream Name} — Outline

Structure of the deliverable, agreed before blueprinting. Authoritative over `research.md` where a `[D]` below supersedes it.

## Structure

1. **{Section}** — {what it must carry, and why it sits here}
2. **{Section}** — {…}

## Governing Decisions

- `[D] {Decision}` — {rationale; what it supersedes, if anything}
- `[D] {Decision}` — {…}

## Open Structural Questions

{Anything still unagreed — must close before implement}
```

---

## `blueprint.md` Template

```markdown
# {Workstream Name} — Blueprint

## Objective

{One sentence: what this workstream delivers}

## Scope

**In:** {item}, {item}
**Out:** {item}, {item}

## Steps

### Phase {N} — {Phase Name}   ← use phases for multi-phase work; skip for simple plans

- [ ] Step 1: {description} → *output: {what this step produces}*
- [ ] Step 2: {description} → *output: {what this step produces}*

### Phase {N+1} — {Phase Name}

- [ ] Step N: {description} → *output: {what this step produces}*

## Worktrees

{Describe parallel tracks if applicable, or omit section}

- `worktree-01.md` — {description of track 1}
- `worktree-02.md` — {description of track 2}

## Completion Criteria

- [ ] {verifiable criterion}
- [ ] {verifiable criterion}

## Gate

Config: `outputs/{name}/gate.json` (run from Workspace root: `python -B tools/gate.py run --config outputs/{name}/gate.json`). Baseline: {sha or capture}.

| Check | Completion Criterion |
|---|---|
| {check name} | {criterion it proves} |

QA-only (not mechanically checkable): {criteria left for adversarial QA, or "none"}

## Cross-links

- {related objective, project, or knowledge section}
```

---

## `behavior-log.md` Template

Created at the start of the first implement batch (not at initiate — it has no purpose before
implement). Appended by every batch. Records **conduct** — whether the batch followed its brief —
never findings or harness defects. See SKILL.md → *Behavior Log* for the inclusion test.

```markdown
---
note_type: workstream-artifact
workstream: {name}
tags: [workstream/{name}]
---

# Behavior Log — {name}

Self-reported conduct per implement batch: did it follow the blueprint steps and briefing as
given? Not a findings log (`research.md`/`design.md`) and not harness friction
(`friction-log.md`) — see SKILL.md → *Behavior Log*.

---

[implement] Batch {n} (steps {range}): {compliant, or the specific deviation/shortcut/skipped
check and why it happened}.
```

---

## `_working/handoff.md` Template

Written and overwritten by each implement batch subagent at its checkpoint — not appended, since
only the latest state matters for resuming. Purely functional: the next batch subagent's primary
resume context, cheaper to read than re-deriving state from `blueprint.md` diffs. Deleted with the
rest of `_working/` at cleanup; nothing here needs to survive past the workstream's life.

```markdown
---
note_type: workstream-artifact
workstream: {name}
tags: [workstream/{name}]
---

# Handoff — {name}

**As of:** batch {n}, step {last completed step}

## Done this batch

{steps completed, one line each}

## Next step

{the exact next unchecked step — number and one-line description}

## Watch for

{anything not obvious from blueprint.md's step text: a subtlety hit, a judgment call made and
why, a risk for the next batch to be aware of. Omit if genuinely nothing.}
```

---

## `friction-log.md` Template

Created at initiate, appended by **every** phase, reviewed at cleanup. Records how well
the *harness* performed — never what the work found. See SKILL.md → *Friction Log* for
the inclusion test.

```markdown
---
note_type: workstream-artifact
workstream: {name}
tags: [workstream/{name}]
---

# Friction Log — {name}

How well the harness supported this workstream. **Not** a record of the work itself:
findings go to `research.md`, decisions to `design.md`, progress to `blueprint.md`.

Inclusion test: *would this note still be true and useful on a completely unrelated
workstream?* If it names the subject matter, it belongs elsewhere. Record the rule,
not the incident. Prefix every entry with its phase.

Often empty — a run with no friction is a good run, not a gap to fill.

---

## Friction & Discrepancies

*(where the harness got in the way, was wrong, or contradicted itself)*

---

## Process Observations

*(what to repeat or avoid in how the framework is run)*

---

## Permission / Settings Suggestions

*(concrete harness changes worth making permanent)*
```

---

## Harness Friction Ledger (`_harness/friction.md`)

The cross-run aggregation point. Workstream cleanup, task complete, and objective review
each append unresolved, generalizable friction here. **Permanent** — the workstream folder
that produced an entry is deleted, so this is the only thing that survives to inform the
next run. Create it on first use.

```markdown
---
note_type: harness-ledger
tags: [harness, friction]
---

# Harness Friction Ledger

Unresolved friction in the harness itself, aggregated across runs. Appended by workstream
cleanup, task complete, and objective review. Entries are about the *framework*, never
about the work that surfaced them.

Resolve an entry by fixing the harness, then move its row to Resolved with the date and
what changed. Recurrence across several runs is the signal that something needs fixing —
one annoyance is noise, the same annoyance three times is a defect.

## Open

| Date | Tier | Source | Friction | Recurred |
|---|---|---|---|---|
| YYYY-MM-DD | workstream \| task \| objective | {name} | {the rule, one line} | 1 |

## Resolved

| Date | Friction | Resolution |
|---|---|---|
```

## Log Entry Template (`_log/YYYY-MM-DD-{name}.md`)

```markdown
# Workstream Summary — {Workstream Title}

## What and Why

{What the workstream was and why it was initiated — 2–4 sentences}

## What Was Delivered

{Bullet list of concrete deliverables}

## Key Decisions

{Decisions made and rationale — the stuff worth remembering}

## What Worked / Lessons Learned

{Honest assessment — what to repeat, what to avoid}

## Durable Artifacts

{Links to outputs, knowledge notes, project files, or systems that persist after the workstream closes}
- Produced artifacts → `outputs/{workstream-name}/` (slides, documents, configs, generated content)
← if none, write "None — {explanation}"

### Residuals

{Paste the residual block printed by `workstream.py complete`. Unresolved work and handovers only; lessons go under Lessons Learned.}

## Parent Objective

{Link to parent objective, or "None — standalone."}
```

---

## Portfolio Index Update Pattern

When adding to the Active table in `workstreams/index.md`:

```markdown
| [{name}]({name}/index.md) | {one-line description} | {Payload Relay\|Short Relay} | {phase} | {health} | [objectives/{parent}](../objectives/{parent}/index.md) |
```

When moving to Recently Completed:

```markdown
| [{date}-{name}](_log/{date}-{name}.md) | {one-line description} | {YYYY-MM-DD} |
```
