# Action: Drop

Discard an intake item. Load this file only.

## Steps

### 1. Confirm

State what is being dropped and why. If the reason is a decision made on an objective, log it first (`objective.py log-decision`, objective skill) so the reason can cite it as `"{obj} YYYY-MM-DD"`.

### 2. Drop

```
python -B tools/intake.py drop {slug} --reason "{reason citing the decision, e.g. gtm-enablement 2026-11-10}"
```

The record is set `dropped` and archived to `control-plane/intake/_archive/`. A dropped non-conditional dependency does not satisfy dependents; `intake.py check` flags it.

### 3. Verify

```
python -B tools/intake.py check
```

Commit (Intake capture covers archive-out).
