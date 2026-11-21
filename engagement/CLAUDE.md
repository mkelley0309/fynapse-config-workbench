# Engagement repo — session contract

A private, client-specific repo for one Fynapse configuration engagement. It was instantiated from the Fynapse configuration workbench at the tag recorded in `template.lock.json`.

## Session entry

1. Read this file.
2. Read `.claude/rules/engagement.md`.
3. Read `control-plane/` per the vendored `.claude/rules/control-plane.md` rule.
4. State scope and next action before proceeding.

## Onboarding

**Step 0.** If the `harness-core` plugin is installed, it is disabled for this repo in `.claude/settings.json`. The vendored skills under `.claude/skills/` are the authority.

1. `git pull`.
2. `python -B tools/objective.py next <engagement>`.
3. Take the top READY item that nobody has claimed, and claim it: `python -B tools/workstream.py claim <name>` (or `python -B tools/assignment.py claim <name>`).
4. Work it through its skill.
5. Open a PR. After any merge, run `python -B tools/intake.py render --resolve` and `python -B tools/objective.py render --all --resolve`, then the `--check` forms.
6. Log decisions with `python -B tools/objective.py log-decision <obj> "<decision>" "<rationale>"`. By comes from git `user.name`; `--by NAME` overrides it.
7. Before pushing, run `python -B tools/disclosure-scan/disclosure_scan.py diff --staged` with the engagement's own terms file. It guards against leaking *other* clients' material, not this client's.

Decisions-log and portfolio-table append conflicts are manual keep-both merges.

## Layout

| Path | Holds |
|---|---|
| `control-plane/` | objectives, workstreams, assignments, intake, gates, locks |
| `config/` | the cumulative Fynapse configuration (see `config/README.md`) |
| `client-docs/`, `client-data/` | client documents and data (tracked) |
| `research/` | distilled engagement research, citing sources |
| `scope/` | scope manifest and scoping worksheet |
| `scoped-vault/` | generated, read-only scoped knowledge (never hand-edited) |
| `outputs/` | durable workstream artifacts and `gate.json` per workstream |
| `_harness/friction.md` | engagement-local harness friction |
| `tools/` | vendored harness CLIs (managed; do not edit) |

## Updates

Managed files come from the workbench. Never hand-edit them; pull a newer workbench release with `python -B tools/template-sync/template_sync.py pull`. Seeded files are yours to edit.

## Scoped vault consumer contract

Pending: the consumer contract is published by the scope-manifest workstream and vendored at the next workbench release.
