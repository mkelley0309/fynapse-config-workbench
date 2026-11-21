# Workstream Framework Reference

Operational reference for workstream state, routing, and artifact rules. Load this file when creating or updating any workstream file.

Templates (index.md, request.md, research.md, design.md, blueprint.md, log entry) live in `framework-templates.md` — load that file only when filling in a new artifact.

---

## Frontmatter Schemas

### `index.md` — primary status anchor

```yaml
workstream: kebab-case-name
framework: short-relay | payload-relay
workstream_phase: questions | research | design | blueprint | implement | validate | complete | cleanup
workstream_health: healthy | needs-questions | needs-design | under-shaped | blocked | stale
current_step: "Phase N — Step X: description"   # only during blueprint/implement; omit otherwise
status: active | complete | paused | abandoned
started: YYYY-MM-DD
completed: YYYY-MM-DD                            # set when cleanup log entry is filed
parent: null | "objectives/{name}"
intake_source: [intake:{slug}, ...]             # CLI-written (create --intake-source); settled at complete
milestone: "{obj}#N"                             # CLI-written (create --milestone); set done at complete
locks: [lock-name, ...]                          # CLI-written (create --locks); names from control-plane/locks.md
inputs: [outputs/..., ...]                       # copied from intake_source records
backlog: [outputs/..., ...]                      # subset of inputs
tags: [workstream/{name}]
```

The `index.md` body also carries `## Residuals` (one bullet per line: `none`, `intake:`, `milestone:`, `spawned:`, `dropped:`, `handover:` forms), required before `complete`. Unknown frontmatter keys are preserved and reported by `intake.py check`.

### Supporting files (`research.md`, `blueprint.md`, `design.md`, etc.)

```yaml
note_type: workstream-blueprint | workstream-research | workstream-artifact
workstream: kebab-case-name
tags: [workstream/{name}]
```

### Log entries (`_log/YYYY-MM-DD-{name}.md`)

```yaml
note_type: workstream-log
workstream: kebab-case-name
framework: short-relay | payload-relay
completed: YYYY-MM-DD
parent: null | "objectives/{name}"
tags: [workstream/{name}]
```

---

## Artifact Destination Rule


**Produced outputs** = anything the workstream creates for use beyond the workstream: slides, documents, configs, reports, generated content. Write these to `outputs/{name}/` during implement, then add a row to `outputs/index.md`.

---

## `workstream_phase` Transition Map

```
questions  →  research      (after request.md written)
research   →  design        (after research.md written; if design needed)
research   →  blueprint     (after research.md written; if no design needed)
design     →  blueprint     (after design.md written)
blueprint  →  implement     (when execution begins)
implement  →  validate      (when all blueprint.md checkboxes checked)
validate   →  complete      (when gate is GO and adversarial QA signs off)
complete   →  cleanup       (when log entry is being written)
cleanup    →  (done)        (after log filed, outputs verified in outputs/, folder deleted)
```

---

## Research Pass Selection

| Workstream type | Knowledge | Web | Codebase |
|---|---|---|---|
| Knowledge maintenance / reorg | ✓ | — | — |
| Content generation (GTM, narrative) | ✓ | ✓ | — |
| Build project (greenfield) | ✓ | ✓ | — |
| Build project (extending existing) | ✓ | ✓ | ✓ |
| Competitive / external research | ✓ | ✓ | — |
| Initial system setup | ✓ | — | — |
| Research with deliverable | ✓ | ✓ | — |

---

## Subagent Delegation Within Actions

- **Research passes** → Sonnet subagent per pass (knowledge, web, codebase), run **sequentially one at a time**. Each returns only the distilled findings (≤200 words).
- **Blueprint drafting** → Sonnet subagent when the blueprint has >3 phases or >10 steps. (≤400 words back to main context.)
- **Template filling, file renames, status checks** → Haiku subagent. (≤200 words back to main context.)
- **Cleanup file deletions** → confirm with user first; do not delegate destructive ops.

**Concurrency budget: up to your configured limit in flight** (`max_concurrent_agents`, default 2; set during `init-workspace`). Default behavior is sequential.
