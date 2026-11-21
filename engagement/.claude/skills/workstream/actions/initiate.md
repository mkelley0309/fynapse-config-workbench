# Action: Initiate

## Decisions (LLM)

1. **Name** — propose `kebab-case-name`, confirm before creating anything.
2. **Framework** — Payload Relay unless spec is clear, well-scoped, single-domain → Short Relay.
3. **Parent** — check `control-plane/objectives/index.md`; standalone if no match. If strategic work warrants an objective that doesn't exist yet, suggest creating it first via the `/objective` skill.

## Scaffold (tool)

```bash
python -B tools/workstream.py create <name> [--framework short-relay] [--parent objectives/<name>] [--title "Title"] [--intake-source intake:<slug>]... [--milestone <obj>#N] [--locks <lock>]
```

A parent objective is recorded as `parent: "objectives/{name}"` in the created `index.md`. If the work was chosen with `objective.py next`, pass the record: `--milestone {obj}#N` (sets the milestone `active` and links its `unit`), `--intake-source intake:{slug}` per consumed record (repeatable; copies its `inputs`/`backlog` and sets it `active`), and `--locks` for any lock names the record declares (`control-plane/locks.md`). The CLI refuses unresolved IDs and held locks.

Fill in the one-paragraph description in the created `index.md`.

## Friction log

Create `friction-log.md` in the new workstream folder from the template in `framework-templates.md`. Every phase appends to it — but only about how the *harness* performed, never about the work itself (see SKILL.md → *Friction Log*). Expect it to stay empty on a clean run.

## Intake provenance

`--intake-source` writes `intake_source: [intake:{slug}, ...]` into the `index.md` frontmatter; never add it by hand. The intake file stays in `intake/` while the workstream runs; the CLI archives it at `complete`.

## Hand off

- Payload Relay → `actions/questions.md`
- Short Relay → `actions/research.md`
