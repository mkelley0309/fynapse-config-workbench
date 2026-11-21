# tools

Workspace capability primitives. Run every script from the Workspace root as `python -B tools/<script>`. Stdlib only, Python 3.12. Every tool finds the root by walking up from the current directory to the first `control-plane/` (R1), so they run from any subdirectory. `WORKSPACE_ROOT` is optional; when set it must name that same root. If it names a different root, the tool dies naming both roots and writes nothing (R2). With no `control-plane/` above the current directory the env root is used. Tests run in temp workspaces with cwd set to the temp root.

| Tool | Purpose |
|---|---|
| `harnesslib.py` | Shared library: root discovery, frontmatter read/write, EOL-preserving `splice_write`, record graph (intake, milestones, gates), generated regions, outputs-path normalisation, R7 close checks. Imported by the other tools; not run directly. |
| `intake.py` | Intake, gate and backlog records: capture/triage/consume/drop/archive/split, `backlog`, `gate`, `list`, `check`, `check --inputs`, `render`. |
| `eol-churn.py` | Flags whole-file line-ending rewrites in a git diff. Run before every commit. |
| `disclosure-scan/` | Deterministic pre-push disclosure scanner (`disclosure_scan.py tree\|diff`). Reports term ids, never values. See `disclosure-scan/README.md`. |
| `nested-repo-run/` | Launch a headless child session in a nested repo from a brief, then verify commits, denials, EOL churn and disclosure (`nested_repo_run.py run\|verify`). See `nested-repo-run/README.md`. |
| `objective.py` | Objective bookkeeping. `objective.py next <obj>` computes READY / BLOCKED / HUMAN / LOCK work from milestone and intake records. `render` regenerates the index views. |

Other tools (`workstream.py`, `assignment.py`, `cadence.py`, `gate.py`, ...) keep their own `--help`. Vault tooling (`vault-lint.py`, `build_bridges.py`, `vault-replicate/`, `vault-viewer/`) lives in `knowledge/tools/`.

## Invocation

```
python -B tools/intake.py capture my-idea --title "..." --source "chat" [--objective obj --route tools]
python -B tools/intake.py triage my-idea --objective obj --route workstream:foo --inputs outputs/<producer>/gaps.md --backlog outputs/<producer>/gaps.md
python -B tools/intake.py list --objective obj --json
python -B tools/intake.py backlog outputs/<producer>/gaps.md --done r1
python -B tools/intake.py check --strict --json
python -B tools/intake.py check --inputs --json        # which outputs/ folders are live (R12)
python -B tools/intake.py render [--check] [--force] [--adopt] [--resolve]
python -B tools/intake.py set my-idea --route workstream:foo --depends-on intake:a,gate:g   # any non-status field
python -B tools/intake.py gate set my-gate --title "..." --type decision --who operator --criteria "..." --evidence E
python -B tools/intake.py split big --into a,b            # or --into a --into b
python -B tools/objective.py add-milestone obj --title T --id 0 --unit workstream:w --inputs p --backlog p --legacy "- [x] line" --substep s1 --substep s2
python -B tools/objective.py set-milestone obj 3 --legacy "- [x] line" --done 2026-10-01
python -B tools/objective.py check-milestone obj 3 --date 2026-10-01     # date defaults to today
python -B tools/workstream.py set-unit w --intake-source intake:a --milestone obj#1 --locks vault-edit --inputs p --backlog p
python -B tools/assignment.py set-unit a ...              # same flags; cadence.py set-unit c ... too
python -B tools/objective.py next obj --json
python -B tools/objective.py render obj|--all [--check] [--force] [--adopt] [--resolve]
python -B tools/objective.py log-decision obj "decision" "rationale" [--by NAME]   # By defaults to git user.name, else operator
python -B tools/workstream.py claim|release w            # assignment.py claim|release a: claimed_by / claimed in the index frontmatter
python -B tools/eol-churn.py --staged
python -B tools/disclosure-scan/disclosure_scan.py tree [PATH ...]      # default: knowledge/
python -B tools/disclosure-scan/disclosure_scan.py tree --git-set knowledge   # exactly what the nested repo lists (tracked + untracked, ignored excluded)
python -B tools/disclosure-scan/disclosure_scan.py diff --range <remote>/main..HEAD --strict [--cwd DIR]
```

Repeatable list flags take `--x a --x b` or `--x a,b`.

## Record field coverage

Every record key except lifecycle status has a CLI setter. Lifecycle (`status`, gate `resolved`) changes only through `consume`, `drop`, `archive`, `check-milestone`, `drop-milestone` and gate `resolve`/`drop`.

| Record | Command | Flags |
|---|---|---|
| intake | `intake.py set <slug>` | `--kind --captured --source --objective --route --depends-on --related --locks --inputs --backlog --consumed-by --keep-until --dropped-reason` |
| gate | `intake.py gate set <slug>` | `--title --type --who --criteria --objective --evidence` |
| milestone (create) | `objective.py add-milestone` | `--title --id N --order --conditional --depends-on --related --locks --fed-by --ref --unit --inputs --backlog --legacy --substep` (`--substep` repeats; commas kept) |
| milestone (edit) | `objective.py set-milestone` | `--title --order --conditional --ref --unit --depends-on --related --locks --fed-by --inputs --backlog --legacy --done` |
| milestone (complete) | `objective.py check-milestone` | `--date YYYY-MM-DD` |
| unit keys | `workstream.py` / `assignment.py` / `cadence.py` `set-unit <name>` | `--intake-source --milestone --locks --inputs --backlog` |

- `set` validates enums, ids, routes, locks, paths and dependency cycles as `triage` does, before the write. An empty value clears a field (`--keep-until ""`, `--related ""`).
- `set-unit` is additive on an open unit. Binding `--intake-source` copies the record's inputs/backlog and sets it `active`; binding `--milestone` sets the milestone `active` and fills its `unit`. A refusal writes nothing.
- List flags go through one helper (`harnesslib.listflag`): repeated flags and comma-separated values both work.

## Generated views

Regions sit between `<!-- generated:<view> -->` and `<!-- /generated:<view> sha=<8 hex> -->`. The sha is the first 8 hex digits of sha256 over the region text with LF newlines.

| Command | Views | File and section |
|---|---|---|
| `intake.py render` | `intake-queue` | `control-plane/intake/index.md`, `## Live Queue` |
| `objective.py render` | `milestones`, `program-intake`, `carried-inputs`, `gates` | objective `index.md`: `## Milestones`, `## Program Intake`, `## Carried Inputs`, `## Open Gates` |

- Rendering replaces only the region and keeps the file's EOL.
- A sha mismatch means a hand edit: rendering refuses unless `--force`.
- `--check` exits 1 if any region is stale; it never writes.
- A section with no region is skipped. `--adopt` replaces that section's hand-kept body with a marked region (the heading stays; `## Open Gates` is inserted after `## Milestones` if absent).
- `add-milestone`, `check-milestone`, `set-milestone` and `drop-milestone` edit records and then re-render `milestones` (a missing region is skipped; a hand-edited one is left alone with a warning).
- `intake-queue` line: `id · status · route · next: ready | waits on <ids>`.
- `program-intake` lists the objective's live intake plus archived intake whose `consumed:` date is within 30 days of the latest `consumed:`/`dropped:` date among archived records. No file mtime and no clock, so the view is reproducible. Archived records with no date are left out (`migrate_r4_archive_dates.py` dates the legacy ones).
- `--resolve` (`intake.py render`, `objective.py render <name>|--all`) repairs a merge: inside a generated region holding git conflict markers it drops both sides (including a footer duplicated across the conflict) and re-renders the region. Conflict markers outside regions are left alone and reported on stderr. `render --check` is clean afterwards.

## Keys and decision log

- Intake archive dates: `consumed: YYYY-MM-DD` / `dropped: YYYY-MM-DD`, written by `consume`, `drop`, unit close and, when missing, by the archive move. An existing date is never overwritten.
- Unit claims: `claimed_by: "<git user.name>"` and `claimed: YYYY-MM-DD` in a workstream or assignment `index.md`. `claim` refuses a unit held by someone else and a closed unit; `release` removes both keys. `objective.py next` shows `CLAIMED(<user>)` on claimed items and moves items claimed by someone else out of READY into a `CLAIMED` list (JSON: `claimed`, per-item `claimed_by`).
- Key Decisions Log header: `| Decision | Rationale | By | Date |`. `log-decision`, `complete`, `abandon` and `drop-milestone` write the By cell (`--by`, else git `user.name`, else `operator`).
- `intake.py check` errors `duplicate-id` (naming the id and both paths) when two records share an id, e.g. two `01-*.md` milestone files.
- Writes never change a file's EOL: `harnesslib.splice_write` raises when a write would give an all-CRLF file LF-only lines.

## harness-records/1

Every `--json` output is one object:

```json
{"schema": "harness-records/1", "kind": "list|backlog|next|check|inputs", "generated": "YYYY-MM-DD", ...}
```

| kind | Payload |
|---|---|
| list | `records: [{id, kind, status, title, objective, route, depends_on, related, locks, inputs, backlog, path}]` |
| backlog | `path, counts: {open, done, dropped, moved}, rows: [{id, item, status, route}]` |
| next | `objective, ready: [{id, title, unblocks, order, backlog}], blocked: [{id, root_blockers}], human: [{id, gates: [{id, who, criteria}]}], lock: [{id, lock, holder}], active: [...], notes: [...]` |
| check | `errors: [{code, id, path, message}], warnings: [...]` |
| inputs | `live: [{folder, reasons: [record id \| "ref:<path>" \| "keep:tool\|permanent"]}], defects: [{code, folder, ref, message}]` |

- Every record and row carries its stable `id`.
- `inputs` defect codes: `stale-prefix`, `archived-live`, `absent`, `missing-row`, `extra-row`.
- `check --inputs` exits 1 when any defect exists. Live reasons: (a) the folder is in `inputs` of a non-terminal record or open unit; (b) it is referenced from `control-plane/` live surfaces, `tools/`, `.claude/` or `knowledge/vault/` (`rg` if on PATH, else `os.walk`; set `HARNESS_NO_RG=1` to force the walk); (c) its `outputs/index.md` row has `Keep` = `tool` or `permanent`. A missing `Keep` column means no keeps.

### External-writer rule

External writers (skills, agents, scripts) change records only through the CLIs above. Never hand-edit record frontmatter, backlog rows, or generated regions; the CLIs preserve line endings, ids and the append-only logs.
