# Action: Implement

Execute the blueprint, one subagent **batch** at a time.

## Artifact destination

**Any file a workstream produces for use beyond the workstream itself** (slides, documents, configs, reports, generated content) must be written to `outputs/{workstream-name}/`, not inside the workstream folder. This is non-negotiable — the workstream folder is deleted at cleanup, so anything written there is at risk.

Working files (`_working/`), process artifacts (`blueprint.md`, `research.md`, `design.md`), and the `index.md` anchor belong in the workstream folder. Everything the workstream *produces* belongs in `outputs/`.

After writing output files: update `outputs/index.md` to add a row for this workstream if one doesn't already exist.

## Session start

Read `index.md` and `blueprint.md` — Implement's payload (see SKILL.md → Phase Handoff). Confirm `workstream_health: healthy`. If not, load `actions/assess.md`.

If `_working/handoff.md` exists, read it too — it's the previous batch's handover and is the fastest way to resume without re-deriving state from `blueprint.md` checkboxes alone. Treat `blueprint.md` as the source of truth for exact step text if the two ever disagree.

If a step can't be executed from `blueprint.md` alone, escalate backward one artifact at a time — `design.md` first, then `research.md`/`request.md`, then `_working/research-*.md` as a last resort — stopping as soon as it resolves. Log the escalation in `friction-log.md` (`[implement]`): a step that needed backward escalation is a blueprint gap, not a one-off to silently work around. Reading a `research.md` section named in `design.md`'s Data Inputs is planned input, not escalation.

`friction-log.md` already exists (created at initiate; see SKILL.md → *Friction Log*). If it doesn't, create it from the template in `framework-templates.md`. `behavior-log.md` is created at the start of the **first** implement batch if it doesn't already exist — see SKILL.md → *Behavior Log*.

Do **not** build a step-status table anywhere. `blueprint.md` checkboxes and `index.md` `current_step` are the progress record, and `check-step` maintains both together.

## Execution loop — batch model

**One subagent per batch, not per step.** A batch subagent owns a *run* of consecutive steps — as many as it can execute reliably — not a single step and not necessarily the whole blueprint. This trades the old strict one-step-per-subagent isolation for fewer relay round-trips, on the premise that a subagent's own judgment about its remaining context headroom is a better checkpoint boundary than a fixed step count. Main context still never executes step logic directly — it only deploys batches and reads their reports.

For each batch:

1. **Brief the subagent** with:
   - The workstream's absolute path and `blueprint.md` (or the remaining unchecked steps if the blueprint is long).
   - `_working/handoff.md` if one exists from a prior batch — point at it explicitly as the primary resume context.
   - The instruction below, included verbatim:

     > "Execute consecutive blueprint steps starting from the current unchecked step, ticking each one via `python -B tools/workstream.py check-step <name> "<step>"` as you complete it — this is the only progress write, do not build a separate status table. Keep going step by step for as long as you can reason reliably about the full picture. Stop and checkpoint **before** you'd need to re-read earlier steps to recall what you already did, or before roughly 15-20 tool calls, whichever comes first — do not push through degraded context to finish faster. Stop immediately and checkpoint if you hit a blocker.
     >
     > At checkpoint, in this order: (1) confirm every step you completed is ticked; (2) append a `[implement]`-prefixed entry to `friction-log.md` only if the harness itself got in the way (a misbehaving tool, a wrong instruction, too-narrow access) — most batches produce no entry; (3) append an entry to `behavior-log.md` — a self-report of your own conduct this batch: did you follow the blueprint steps as written, or did you cut a corner, skip a verification, reinterpret an ambiguous instruction, or stop before checking your own work because of context pressure? Say so plainly even if it's a compliant batch with nothing to flag — "followed steps N-M as written, no deviations" is a valid entry; (4) overwrite `_working/handoff.md` with a fresh handover for whoever runs the next batch — current state, immediate next step, open concerns, anything the next implementer needs that the checkboxes don't show; (5) if blocked, run `workstream.py block <name> "<reason>"` instead of (3)/(4) and stop.
     >
     > Return a short report only: steps completed this batch, whether blocked, and confirmation that friction-log/behavior-log/handoff were updated per the rules above. Do not return full file contents or a restatement of what's in blueprint.md."

2. **Read only the batch report.** Never pull `behavior-log.md`, `friction-log.md`, or `handoff.md` content into main context — their audience is the next subagent and the eventual cleanup review, not this session.
   **Then run the gate** Blueprint wrote: `python -B tools/gate.py run --config outputs/<name>/gate.json`. Run it in the background when its checks exceed 120s, and capture its exit code. A check that is meant to stay red until a later batch is fine, but name it in the next brief. An unexpected NO-GO blocks the next batch, as in step 4.
3. **Decide whether to continue:** if `blueprint.md` still has unchecked steps or completion criteria, deploy the next batch subagent per step 1 above (its brief now finds the fresh `_working/handoff.md` waiting for it). If everything is `[x]`, proceed to Phase transition.
4. **If a batch reports blocked:** stop the loop immediately, surface the blocker to the user. Do not deploy a follow-up batch until it's resolved.

**Parallelizable steps are the exception to the batch model.** Steps the blueprint marks `[parallelizable]` still run as their own concurrent subagents (up to `max_concurrent_agents`, default 2) rather than being folded into a sequential batch — a batch subagent should treat a `[parallelizable]` step it reaches as a signal to fan out, not to execute inline.

## Delegation (Claude Code)

- `→ delegate: Sonnet subagent` — the batch subagent itself, and any multi-step investigation or drafting work within a step.
- `→ delegate: Haiku subagent` — template filling, bounded file ops, status checks a batch subagent spins off for a sub-task.

**If the session prohibits unrequested subagents:** do not skip execution and do not silently violate the instruction. Surface the conflict once, up front, and ask before spawning the first batch. If the user declines, run the batch loop **in main context** instead — same checkpoint discipline (tick steps, update `friction-log.md`/`behavior-log.md`/`handoff.md`), just without the subagent boundary. Note in `behavior-log.md` that batches ran in main context and why.



## Phase transition

When all steps and completion criteria are `[x]`:

```bash
python -B tools/workstream.py advance <name> validate
```

Load `actions/validate.md`. Verification and adversarial QA happen there — do not advance to complete from implement.
