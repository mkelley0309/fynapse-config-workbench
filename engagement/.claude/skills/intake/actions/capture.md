# Action: Capture

Land an idea, note or partial thought as an intake record. Load this file only.

## Steps

### 1. Pick a slug and title

Kebab-case slug, specific enough to find later. Title in one line. Source is free text: where it came from ("chat 2026-11-10", "meeting with X", a path).

### 2. Capture

```
python -B tools/intake.py capture {slug} --title "{title}" --source "{source}" [--objective {obj}] [--route {route}]
```

`--objective` and `--route` are optional at capture; supply them only if already known. Status is `captured`.

### 3. Add detail

The command writes the record. Put the substance in the record body (below the frontmatter) with the Edit tool; frontmatter stays CLI-managed.

### 4. Offer triage

Ask whether to triage now. If yes, load `actions/triage.md`. Commit per Commit Cadence in `.claude/rules/control-plane.md` (Intake capture).
