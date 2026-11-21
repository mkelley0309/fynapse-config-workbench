# Action: Triage

Give captured items an objective, one route, and dependency edges. Load this file only.

## Steps

### 1. List the queue

```
python -B tools/intake.py list --status captured
python -B tools/intake.py list --objective {obj}
```

Add `--json` for the `harness-records/1` payload.

### 2. Decide per item

| Question | Field |
|---|---|
| Which objective does it serve? | `--objective` (or `none`) |
| Where does the work go? Exactly one target | `--route` |
| What must be done first? | `--depends-on` (intake record, milestone `{obj}#N`, `gate:{slug}`, or a `workstream:`/`assignment:`/`cadence:` unit ID) |
| What does it only relate to? (never blocks) | `--related` |
| Which exclusive resource does it need? | `--locks` (names in `control-plane/locks.md`) |
| Which artifacts does it carry? | `--inputs`; `--backlog` for the subset that is a backlog table |
| Must it stay live past its consumer until something else lands? | `--keep-until {id}` |

Route values: `milestone:{obj}#N`, `workstream:{name}`, `assignment:{name}`, `cadence:{name}`, `candidate:workstream`, `candidate:assignment`, `tools`, `none`.

Sequencing decisions are `depends_on` edges, not prose. A human or external blocker is a gate (`intake.py gate add ...`), not a note. List flags take `--x a --x b` or `--x a,b`.

### 3. Triage

```
python -B tools/intake.py triage {slug} --objective {obj} --route {route} [--depends-on ...] [--related ...] [--locks ...] [--inputs ...] [--backlog ...] [--keep-until ...]
```

The CLI rejects unknown enum values, unresolved IDs and dependency cycles. Status becomes `triaged`.

### 4. Split when one item holds more than one route

Every record has exactly one route. If an item mixes work for different units or objectives, split it. Only open slices become children; the parent is archived as `consumed` with `consumed_by` pointing at the children and its body unchanged.

```
python -B tools/intake.py split {slug} --into {a},{b} [--route {route}] [--objective {obj}]
```

Children are `{slug}-{a}`, `{slug}-{b}`; each inherits `captured` and records `source: split from intake:{slug}`. Triage each child afterwards. A whole backlog keeps one route; rows move elsewhere only with `intake.py backlog {path} --move {id} --to {target}`.

### 5. Verify

```
python -B tools/intake.py check
```

Fix every error before moving on. Commit (Intake capture).
