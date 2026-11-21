# Action: Check

Inspect intake and verify record integrity. Load this file only.

## Steps

### 1. What is in intake

```
python -B tools/intake.py list --objective {obj} [--status {status}] [--kind {kind}] [--json]
```

### 2. Integrity

```
python -B tools/intake.py check [--strict] [--json]
```

Exit 1 means errors: schema, unresolved IDs, cycles, dropped non-conditional dependencies, unknown lock names, terminal records in the live folder, `dropped` without a reason, missing `inputs` paths, `backlog` not a subset of `inputs`. Warnings (unknown keys) become errors under `--strict`. Report findings; fix through the CLIs, never by hand-editing frontmatter.

### 3. Backlog progress

```
python -B tools/intake.py backlog {path} [--json]
python -B tools/intake.py backlog {path} --done {id}
python -B tools/intake.py backlog {path} --drop {id} --reason "{why}"
python -B tools/intake.py backlog {path} --move {id} --to {target}
```

### 4. Outputs liveness

```
python -B tools/intake.py check --inputs [--json]
```

Lists which `outputs/` folders are live (named in a record's or unit's `inputs`, referenced from live surfaces, or kept in `outputs/index.md`) and reports defects (`stale-prefix`, `archived-live`, `absent`, `missing-row`, `extra-row`). Exit 1 on any defect.

### 5. Generated queue

```
python -B tools/intake.py render --check
python -B tools/intake.py render
```

`--check` exits 1 if the `## Live Queue` region is stale. A hand-edited region is refused unless `--force`.
