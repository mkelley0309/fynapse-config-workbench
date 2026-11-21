---
name: workstream
description: >
  Manages the full lifecycle of a workstream in control-plane/workstreams/ —
  initiation, questions, research, design, blueprint, implement, validate, cleanup.
  A workstream is the heavy, formal lifecycle for complex multi-session, multi-handoff
  work: open one when the work is too big for a task (too many sessions, too many
  handoffs, or too much structural risk to leave untracked). Trigger whenever
  someone describes an undertaking with that level of complexity. Also trigger when
  asking about workstream status, continuing existing work, or signaling completion.
  When in doubt, trigger — the Questions step is cheap; under-shaped work is expensive.
---

# Workstream Skill

## Session Entry — Always Run First

1. Read `control-plane/CLAUDE.md`
2. Read `control-plane/workstreams/index.md`
3. If a specific workstream is in scope, read its `index.md`
4. Identify the current phase and health
5. Identify the current action from the table below
6. Load **only** that action file — nothing else
7. State phase, health, and intended action to the user before proceeding

**What NOT to load at session entry:** Do not read research files, design.md, blueprint.md, or any `_working/` files during session entry. These are loaded only when the action explicitly requires them (e.g., implement loads blueprint.md to check step status; a research step loads its source files). Assess and cleanup never need research files.

## Session Exit — Always Run Last

**Whenever a workstream session ends with work still remaining** — any phase, not just implement — close by producing a **Handover Prompt**: a short block of text, in the response itself, that the user can copy verbatim into a brand-new session to resume. This is a standing rule, not something to be asked for each time.

This is distinct from `_working/handoff.md` (the implement batch-to-batch relay one subagent writes for the next — see `actions/implement.md`). The Handover Prompt is for the *human* closing the whole session, not for subagent relay, though when `_working/handoff.md` exists the prompt should point at it rather than repeat its contents.

Format — keep it short, favor pointing at durable files over restating their content:

```
Continue workstream {name} (phase: {phase}{, step {n} if implement}).
{1-3 sentences: what just happened, what's next, and anything not already
captured in blueprint.md/design.md/index.md that the next session needs
before proceeding — a blocker, a deviation, a pending confirmation.}
{If implement and _working/handoff.md exists: "See _working/handoff.md for full batch state."}
```

Do not produce this when the workstream just closed at cleanup (nothing left to resume) or when the session is continuing uninterrupted in the same context.

## Action Routing

| Situation | Load |
|---|---|
| New workstream — nothing exists yet | `actions/initiate.md` |
| Existing workstream — need to understand state or advise | `actions/assess.md` |
| Payload Relay Questions step — refining an ambiguous request | `actions/questions.md` |
| Research step — running distillation passes | `actions/research.md` |
| Design step — architectural decisions | `actions/design.md` |
| Blueprint step — producing `blueprint.md` | `actions/blueprint.md` |
| Implement step — executing against `blueprint.md` or worktrees | `actions/implement.md` |
| Validate step — gate run + adversarial QA before closing | `actions/validate.md` |
| Workstream complete — writing log, deleting files | `actions/cleanup.md` |

## Framework at a Glance

**Payload Relay** (default): Questions → Research → Design? → Blueprint → Implement → Validate → Cleanup
**Short Relay** (clear-spec): Research → Blueprint → Implement → Validate → Cleanup

Default to Payload Relay. Questions are cheap; under-shaped blueprints are expensive.

**Research is mandatory.** There is no shortcut from Questions or Initiate to Design or Blueprint without a `research.md`. Even when the user provides source material directly, that material must be written to `_working/` and distilled through the research protocol before proceeding.

## Research Protocol (Non-Negotiable)

Every research phase follows these rules — no exceptions:

1. **Each pass writes to disk first.** Subagent pass findings go to `_working/research-{type}-{n}.md` before anything else. Raw pass output is never consumed by main context.
2. **Distillation runs in a fresh context.** A separate distillation subagent reads only `_working/` files and writes `research.md`. It has no access to the conversation or pass instructions.
3. **Main context reads only `research.md`.** Not `_working/` files, not pass summaries — only the distilled output.
4. **Passes run before distillation.** Run passes **sequentially, one at a time** — a stalled or half-written pass file leaves the workstream in an unrecoverable state, and certainty of completion outranks speed. All pass files must exist on disk before distillation begins, and distillation is itself a single sequential step.

These rules enforce progressive distillation, structured handoffs to clean context windows, limited token usage, and semantic density — the properties that make a workstream coherent across multiple sessions.

## Phase Handoff: Payload, Backward Escalation

Design, Blueprint, and Implement each behave like a separate Shape Up session (pitch / shape /
betting table) — a phase starts from **one payload**, the thing the previous phase
produced for it, not the conversation and not every upstream file. This is the actual context-
hygiene mechanism. It works even for a phase run entirely in main context with no subagent
involved, because a fresh session can enter a phase having read nothing but its payload.

**Payload per phase:**

| Phase | Payload | Handed off by |
|---|---|---|
| Design | `request.md` (inbound) + `research.md` (sounding board) — both are the payload, read together | Questions + Research |
| Blueprint | `design.md` — or `research.md` directly if Design was skipped | Design (or Research) |
| Implement | `blueprint.md` | Blueprint |

**Backward escalation — last resort, one step at a time, only on real ambiguity:**

A phase that cannot proceed from its payload alone may escalate **one artifact back**,
stopping the moment the ambiguity resolves:

1. Implement, stuck on a step → read `design.md` first.
2. Still stuck → read `research.md` and `request.md` — the two inputs Design itself worked from.
3. Still stuck → read the `_working/research-*.md` pass files. Deepest fallback, should be rare —
   those files were written for the distillation subagent, not for a downstream phase. Treat
   anything found there as raw material, not settled fact.

Blueprint escalates the same chain, one step shorter: `design.md` (payload) → `research.md` /
`request.md` → `_working/research-*.md`.

**Do not read ahead defensively.** Reading `research.md` "just in case" while writing Blueprint,
or `design.md` "just in case" while implementing a step that isn't actually stuck, defeats the
point — it's the same context pollution the handoff model exists to prevent, just self-inflicted
instead of carried from conversation. Escalate only when the payload is demonstrably
insufficient, and log what was missing as a `friction-log.md` entry (prefixed with the current
phase) so the upstream artifact gets fixed rather than re-escalated past on every future run.

**`_working/` artifacts beyond research passes** (a design-phase scratch file, a blueprint draft,
anything else that accumulates there) don't have self-evident purpose from the filename alone.
Note what each one is for and when it's worth reading in `index.md` under a short "Working Files"
list (template in `framework-templates.md`) — this is what lets a phase escalating that far decide
relevance without opening and reading everything speculatively.

## Friction Log — Every Phase

Each workstream keeps one `friction-log.md` in its folder. It records **how well the harness performed**, never what the work found.

- **Created at initiate** from the template in `framework-templates.md`.
- **Appended by every phase**, prefixed `[questions]` `[research]` `[design]` `[blueprint]` `[implement]` `[validate]` `[cleanup]`.
- **Reviewed at cleanup** — surfaced to the user, distilled into the log entry, and any unresolved generalizable entry appended to `_harness/friction.md`.

### The inclusion test

> **Would this note still be true and useful on a completely unrelated workstream?**

If yes, it belongs here. If it names the subject matter, it belongs in the work artifact instead.

| Belongs in `friction-log.md` | Belongs elsewhere |
|---|---|
| "Vault read scope was too narrow for the research pass" | A finding *from* that pass → `research.md` |
| "`actions/research.md` names an agent that has no Write tool" | A defect in the code under study → `research.md` |
| "`SKILL.md` and the action file contradict each other" | A design decision taken → `design.md` |
| "The CLI resolves the wrong root when run from a subfolder" | Step 1.4 is done → `blueprint.md` (via `check-step`) |

**Record the rule, not the incident.** "Diff before you copy — the plugin can be ahead" is the entry; the file you clobbered is a clause of evidence, not a paragraph.

### Why the scope is narrow

This is the only artifact that legitimately crosses every phase boundary. That privilege is affordable *only* because its scope is small and fixed. Let it also carry what the work found and it becomes the cross-phase accumulator that progressive distillation exists to prevent — every phase then reads every prior phase's findings, which is exactly the context pollution the handoff model is built to stop.

Progress tracking is **not** its job. `blueprint.md` checkboxes and `index.md` `current_step` are maintained together by `workstream.py check-step`; a third hand-maintained tracker rots and then lies.

## Behavior Log — Implement Only

`behavior-log.md` records **conduct** — whether the executing subagent actually followed its
brief, not what it built or how the harness performed. Created at the start of the first implement
batch (see `actions/implement.md`); appended by every batch.

The test: *did this batch do what it was told, the way it was told to?* A skipped verification, a
reinterpreted ambiguous instruction, a step marked done without actually checking the output, a
batch that pushed on past its own context-pressure warning instead of checkpointing — all belong
here. So does the negative case: "followed steps N–M as written, no deviations" is a valid,
expected entry, not a gap.

This is **not** `friction-log.md` (that's the harness/tooling misbehaving) and **not** a findings
record (that's `research.md`/`design.md`/the work itself). A tool that silently failed is friction;
a subagent that didn't notice the tool failed and reported success anyway is conduct.

Reviewed at cleanup alongside `friction-log.md`, folded into the closing log entry's lessons —
recurring conduct issues (not just one-offs) are worth carrying into `_harness/friction.md` the
same way recurring harness friction is, since "subagents given this kind of brief tend to skip
verification" is a rule about the harness's instructions, not about this workstream's subject.

## What Is a Workstream


## Child Tasks and Parent Objectives

Workstreams can link child tasks and have a parent at one tier:

- **Child Tasks** — the workstream's `index.md` maintains a roster of child task links.
- **Objective** (`parent: "objectives/{name}"`) — a checkpoint-cycle-measured strategic objective.

If the user describes work that should be tied to an objective and none exists, suggest creating it first via the `objective` skill.

## Framework Reference

Operational schemas and state transitions live in `framework.md`. Load it when creating or updating any workstream file.

Templates (index.md, request.md, research.md, design.md, blueprint.md, log entry) live in `framework-templates.md`. Load it **only** when you are about to fill in a new artifact — not during session entry, assess, or implement continuation.

## Subagent Delegation

Per workspace `CLAUDE.md`:
- **Sonnet subagents** for research passes, plan drafting, design analysis
- **Haiku subagents** for template filling, bounded lookups, file moves
- Never delegate synthesis, decisions, or cross-artifact reconciliation — those stay in main context

**Agent scoping (default).** Every subagent is **scoped to a single subtree** — it reads and writes within that subtree only. Cross-boundary work is the orchestrator's job: `control-plane` (main context) coordinates by deploying the **right agent per subtree** and passing distilled artifacts between them — never sending one agent across the boundary. (See `CLAUDE.md` → Subagent Delegation.)

- **Scope + absolute path.** Open each brief with `Work within <absolute-subtree-path>/ only`, using the absolute path of the agent's own subtree (agents don't resolve sibling top-level subtrees by glob).
- **Isolation by scope:** directory-scoped prompts for non-git subtrees (`control-plane/`); **worktree isolation** for code work inside a git-repo project. Never `isolation: "worktree"` from `control-plane/` (not a git repo).

## Guiding Principles

Orient → shape → execute → validate → distill → log → delete. At every transition, something becomes smaller and more useful.

**Progressive distillation:** Raw findings compress to pass files. Pass files compress to `research.md`. Research compresses to design decisions. Design compresses to blueprint steps. Blueprint compresses to a log entry. Nothing flows forward at full density.

**Structured handoffs:** Each phase transition hands off an artifact, not a conversation. The next phase reads the artifact, not what was said. Clean context windows are a feature — they enforce that the artifact carries all necessary information.
