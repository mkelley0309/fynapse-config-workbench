# Action: Complete an Assignment

## Steps

1. **Validate first — don't close on faith.** Run the gate or verify the work was actually done:

```bash
python -B tools/gate.py run
```

Or confirm via the project's test command / `/verify` skill. If the assignment has no automated checks, verify by observation and note what was checked.

2. **Record validated date:**

```bash
python -B tools/assignment.py validate <name>
```

3. **Capture handoff + lessons + friction** in `index.md`:
   - **Handoff** — one line for the next assignment or workstream picking up from here (omit if nothing to hand off).
   - **Lessons** — one line worth repeating or avoiding *about this work* (omit if nothing learned).
   - **Friction** — one line if the *harness* got in the way (omit if it didn't, which is the common case). Test: would this still be true on an unrelated assignment? If it names the subject matter it is a lesson, not friction.

4. **Carry unresolved friction out of the assignment.** For each Friction line still unresolved, append a row to `_harness/friction.md` under Open — `| date | assignment | {name} | {the rule} | 1 |`. Create the file from the `workstream` skill's `framework-templates.md` if absent. If an equivalent row already exists, increment its **Recurred** count rather than adding a duplicate — recurrence is the signal that it needs fixing. Skip anything already fixed during the assignment.


7. **Fill `## Residuals`, then complete.** The assignment `index.md` must carry a `## Residuals` section (one bullet per line; `complete` refuses if it is missing or empty). Forms:

   ```
   - none
   - intake:{slug}, {note}
   - milestone:{obj}#N, {note}
   - spawned:{unit id}
   - dropped: {text} (decision {obj} YYYY-MM-DD)
   - handover: {target} — {purpose}; inputs: {path}[, {path}]; backlog: {path}
   ```

   Prefer `handover:` for any artifact a later unit consumes. Residuals are unresolved work and handovers; lessons are not residuals. Then:

```bash
python -B tools/assignment.py complete <name>
```

   `complete` refuses on an unresolved ID or an open backlog row (fix through the CLIs and re-run). It then settles `intake_source` records (consumed and archived, or kept active), processes handovers, sets the unit's `milestone` to `done`, re-renders objective views, sets `status: complete`, moves the portfolio row, and prints the residual block. Do not move intake files or edit milestone records by hand.

8. **Write the log entry** in `control-plane/assignments/_log.md` (create it from the header in that file if absent), newest first, as a dated section:

   ```markdown
   ## YYYY-MM-DD · assignment-name

   **Was.** The assignment, in a sentence or two.
   **Produced.** What actually came out, and where anything durable now lives.
   **Carried forward.** The lesson worth repeating (lessons only). Say "nothing" rather than inventing one.
   **Residuals.** The block printed by `complete` (paste as-is; `none` if none).
   **Handoff.** Only if something picks up from here.
   ```

   **This is the durable record, not a summary layer** — the folder does not survive, so anything not carried here or rescued at step 6 is gone. Keep it proportional (an assignment is the lightest tier and never gets workstream-grade distillation) but not so thin the work becomes unreconstructable.

   This is the lessons analogue of `_harness/friction.md`, on the same argument: a lesson that lives only inside one assignment will not be noticed on the next one. **Check the log for a repeat while you are in it.** A lesson appearing twice belongs somewhere more permanent than a log — a skill, a tool, or a checklist — and saying so in the new entry is the most useful thing an assignment close can produce.

9. **Delete:**

```bash
python -B tools/assignment.py delete <name>
```

`delete` removes the folder permanently. **Verify the log entry exists before deleting** — read it back, the same discipline the workstream cleanup applies.

## Notes

- Assignments are lightweight, and the lightness is in the *record*, not the retention: one dated section in `_log.md` rather than a folder of artifacts. A workstream gets a whole `_log/` file because it has `research.md` and `_working/` bulk to compress. An assignment gets a paragraph.
- If the assignment grew into multi-session work, promote it instead: open a workstream and carry this assignment's assignment across as the originating capture. Promote before completing, not after — completing deletes the folder.
