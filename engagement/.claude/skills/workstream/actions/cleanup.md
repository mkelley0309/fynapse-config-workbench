# Action: Cleanup

Write the log entry, delete all working files, remove the folder.

## Steps

1. **Review `friction-log.md`** — read it if it exists. It records how the *harness* performed across all phases. Surface to the user:
   - Friction and process observations worth remembering — these feed the log entry's "What Worked / Lessons Learned" section
   - Any suggestions recorded in the Permission / Settings Suggestions section

   **Always ask before acting on suggestions.** Present each suggestion and wait for explicit confirmation before changing settings, permissions, or skill files. Do not implement suggestions silently as part of cleanup.

   **Then close the loop.** The workstream folder is about to be deleted, so any friction not carried out of it dies here — and the next workstream hits the same wall. Append every entry that is **generalizable and still unresolved** to `_harness/friction.md` (create it from the template in `framework-templates.md` if absent), one row per entry. Skip anything already fixed during this workstream, and anything specific to this subject matter — that was never friction to begin with.

   If `friction-log.md` is empty, say so and move on. An empty log is a clean run, not a missing artifact.

2. **Review `behavior-log.md`** — read it if it exists (implement-only artifact; absent if the workstream never reached implement). It records self-reported conduct — whether batches followed their briefs. Fold any real finding into the log entry's lessons. A recurring conduct issue (not a one-off) belongs in `_harness/friction.md` too, since "subagents given this brief tend to skip X" is a rule about the harness's instructions. An all-compliant log is a clean run, not a missing artifact.

3. **Verify outputs are safe** before deleting anything:
   - Produced artifacts (slides, documents, configs, generated content) should already be in `outputs/{name}/` — confirm they are there before proceeding. If they are still in the workstream folder, move them now.
   - Decisions relevant to parent objective → append via `python -B tools/objective.py log-decision <parent> "..." "..."`

4. **Fill `## Residuals`, then close** — the workstream `index.md` must carry a `## Residuals` section (one bullet per line; refusal if missing or empty). If `workstream.py complete` has already run (validate step 3), confirm its residual block was printed and keep it for step 9; otherwise fill the section and run `python -B tools/workstream.py complete {name}` now. Forms:

   ```
   - none
   - intake:{slug}, {note}
   - milestone:{obj}#N, {note}
   - spawned:{unit id}
   - dropped: {text} (decision {obj} YYYY-MM-DD)
   - handover: {target} — {purpose}; inputs: {path}[, {path}]; backlog: {path}
   ```

   Prefer `handover:` for any artifact a later unit consumes (it carries `inputs`/`backlog` to an existing target, or writes a new intake record for a missing one). `complete` refuses when an ID fails to resolve, a `backlog` has open rows, or a `dropped:` cites a decision row that does not exist; fix through the CLIs, then re-run. The CLI also settles the unit's `intake_source` records and its `milestone` (step 7). Paste the printed residual block into the log entry's `### Residuals`.


7. **Intake provenance and milestone — the CLI does it at `complete`.** Each `intake_source` record becomes `consumed` and is archived to `intake/_archive/` (or stays `active` if its `keep_until` is unmet or another open unit shares it); the unit's `milestone` becomes `done`; affected objective views re-render. Do not move, edit or delete intake files or milestone records by hand. Verify with `python -B tools/intake.py check`.


9. **Write log entry** `control-plane/workstreams/_log/YYYY-MM-DD-{name}.md` using the template in `framework-templates.md`, including the `### Residuals` block printed by `complete`. Verify the file exists (Read tool) before deleting anything.

10. **Archive and delete**:

```bash
python -B tools/workstream.py archive <name> --log-date YYYY-MM-DD --description "<one-line>"
python -B tools/workstream.py delete <name>
```

Log entries are never deleted. The folder is permanently removed.
