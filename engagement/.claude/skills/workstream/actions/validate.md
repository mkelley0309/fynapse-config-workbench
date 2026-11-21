# Action: Validate

Confirm the workstream's outputs are real before closing. A workstream does not advance to cleanup on faith.

## Steps

### 1. Run the deterministic gate

```bash
python -B tools/gate.py run --config outputs/<name>/gate.json
```

This runs the gate Blueprint wrote (`actions/blueprint.md` step 3) and returns a hard GO / NO-GO by exit code. Run it as-is; do not rebuild it at Validate. If a Completion Criterion changed during implement, update its check and record the change in `validate.md`. Also acceptable: the `/verify` or `/run` skill, or the project's test command from its `CLAUDE.md`. If the project genuinely has no automated checks, say so explicitly and verify behavior by an observable alternative — never skip silently.

Record the result (command run, exit code, what passed or failed) in `validate.md` — that is the work record. Only record it in `friction-log.md` if the *gate itself* misbehaved (no checks configured, the skill gave no usable instruction, the runner failed for reasons unrelated to the deliverables).

**If GO on a row-based deliverable** (inventory, tracker, table): still spot-check ≥10 rows by hand, sampled across the table, and record them in `validate.md`. Count and required-field gates miss content defects — self-referencing evidence, pointers to unrendered columns.

**If NO-GO:** stop. Document the failures in `validate.md` and surface them to the user. Return to `actions/implement.md` to remediate, then re-run the gate.

### 2. Adversarial QA

Hand the gate result and the workstream's completion criteria (from `blueprint.md`) to a Sonnet subagent with the prompt: "Red-team these deliverables against every completion criterion — find anything claimed done but not actually verified."

The subagent returns findings to main context (≤400 words). Record sign-off or objections in `validate.md`.

**If the session prohibits unrequested subagents** (a standing instruction, `disableAllHooks`, or similar): do not skip this step and do not silently violate the instruction. Surface the conflict to the user and ask before spawning. If the user declines or the tool is unavailable, run the red-team pass **in main context** instead — read `blueprint.md`'s Completion Criteria yourself, verify each independently, and actively try to falsify claims rather than confirm them. Record in `validate.md` that QA ran in main context rather than delegated, and why. A main-context pass is a documented deviation, not a missing step.

**If objections are raised:** resolve them before proceeding. Unresolved objections block advance to cleanup.

### 3. Advance phase

Only when the gate is GO **and** adversarial QA signs off:

Fill the `## Residuals` section of the workstream `index.md` first (forms in `actions/cleanup.md` step 4); `complete` refuses without it. Then:

```bash
python -B tools/workstream.py complete <name>
```

`complete` settles intake sources, handovers and the milestone, and prints the residual block for the log entry.

Load `actions/cleanup.md`.
