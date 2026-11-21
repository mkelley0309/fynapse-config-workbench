---
name: intake
description: >
  Manages the intake queue in control-plane/intake/ -- capture, triage, check and drop of
  unstructured input as dependency-linked records. Trigger on "capture this", "triage intake",
  "what's in intake for X", "drop this idea", or when an idea, note or handover needs a home
  before it becomes an objective milestone, workstream, assignment or cadence. All writes go
  through tools/intake.py.
---

# Intake Skill

Intake is the capture layer: unstructured input lands here before it is routed. Each item is a **record** (`control-plane/intake/{slug}.md`) with an ID `intake:{slug}`, a lifecycle status, one `route`, and optional `depends_on` edges, locks, inputs and backlog.

Contract: `.claude/rules/control-plane.md` (State Models hold the frontmatter). CLI reference: `tools/README.md`.

## Lifecycle

```
captured -> triaged -> active -> consumed | dropped
```

| Status | Meaning | Set by |
|---|---|---|
| `captured` | landed, not yet routed | `intake.py capture` |
| `triaged` | objective, route and edges set | `intake.py triage` |
| `active` | a unit that consumes it is open | the CLI, when `create --intake-source` opens the unit |
| `consumed` | the consuming unit closed; file archived to `intake/_archive/` | the CLI, at the unit's `complete` / `retire` / `abandon` |
| `dropped` | discarded with a reason; archived | `intake.py drop` |

To change any other field on an existing record, use `python -B tools/intake.py set <slug> --<field> <value>` (intake) or `python -B tools/intake.py gate set <slug> --<field> <value>` (gate). Status is never a `set` field. To bind records to a unit that is already open, use `python -B tools/{workstream,assignment,cadence}.py set-unit <name> --intake-source intake:<slug> [--milestone <obj>#N] [--locks ...]`. List flags accept both repeated flags and comma-separated values. Run `--help` on any command for exact flags.

Never set `active` or `consumed` by hand. Never hand-edit record frontmatter, backlog rows or generated regions (the `## Live Queue` in `intake/index.md` is generated: `python -B tools/intake.py render`).

## Action Routing

| Situation | Load |
|---|---|
| Something new to capture | `actions/capture.md` |
| Captured items need objective, route, edges | `actions/triage.md` |
| "What's in intake for X", health of the queue, outputs liveness | `actions/check.md` |
| Discard an item | `actions/drop.md` |

## Session Entry

1. Read `.claude/rules/control-plane.md`
2. Read `control-plane/intake/index.md`
3. Load only the action file for the situation

## Routing a triaged item onward

An item routes to one target (`route`): `milestone:{obj}#N`, `workstream:{name}`, `assignment:{name}`, `cadence:{name}`, `candidate:workstream`, `candidate:assignment`, `tools`, or `none`. To act on it, create the unit with `--intake-source intake:{slug}` (workstream and assignment skills); the CLI marks the record `active`. For "what should I open next", use `objective.py next {obj}` (objective skill, `actions/next.md`).
