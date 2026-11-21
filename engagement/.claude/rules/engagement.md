# Engagement Boundaries

Applies to every session in this repo. Fills the gaps left by the engagement edition of the vendored skills and rules.

## Sources of truth

Precedence for Fynapse behaviour:

1. Current Fynapse docs, via the scoped vault (`scoped-vault/`)
2. The instance export (`config/instance/<env>.export.json`)
3. Vault interpretation

Client documents (`client-docs/`) and client data (`client-data/`) are authoritative for client facts.

## Cite rule

Every claim in `research/`, design artifacts and `config/parts/*.source.md` cites a path under `client-docs/`, `client-data/`, `research/`, `scoped-vault/`, `config/` or `scope/`.

## Client data policy

- This repo is private and client-specific; it may commit client documents and data.
- `.gitignore` excludes only secrets, credentials, instance connection files and build junk.
- LFS is deferred until a data pack outgrows normal git. Raise a gate if it does.

## One-way vault flow

- `scoped-vault/` is generated and read-only. Never hand-edit it.
- Findings go back to the harness owner as intake records, never written into the vault from here.

## Engagement edition notes

### workstream skill

- **What a workstream is:** heavy, formal, multi-session work with a defined completion state and a cleanup step that deletes the folder. Not: long-lived objectives, single-session assignments, or generic utilities.
- **Subagent delegation:** where the skill cites the root contract's Subagent Delegation, read this file instead. Scope each subagent to one subtree of this repo and give it absolute paths in its brief.
- **Actions:** questions, research, design, blueprint, implement, validate, cleanup. Research passes are web, codebase and provided.
- **Research pass types:** web; codebase; provided (client docs, scoped vault).
- **Blueprint:** annotate steps meant to delegate with `→ delegate: Sonnet subagent | Haiku subagent`.
- **Artifact destinations:**

  | Artifact | Destination |
  |---|---|
  | Scratch | `_working/` in the workstream folder |
  | Process artifacts | the workstream folder |
  | Harness friction | `_harness/friction.md` |
  | New work found | intake |
  | Durable outputs | `outputs/{name}/` |
  | Close summary | `control-plane/workstreams/_log/` |

- **Log template, Durable Artifacts:** code → repo paths.
- **Cleanup:** durable outputs go to this repo or `outputs/{name}/`. The cleanup order is unchanged and has no queue gate.

### assignment skill

- **Close:** rescue durable items to `outputs/`, fill `## Residuals`, run `assignment.py complete`, write the `_log.md` entry, then run `assignment.py delete`.
- **Complete action:** resolve every checkbox (Done, Dropped or Carried). Rescue durable items to `outputs/` and sources to `intake/_archive/`.

### control-plane rule

- **Assignment close:** rescue durable artifacts to `outputs/` and sources to `intake/_archive/`, resolve every checkbox, write a dated entry in `assignments/_log.md`, then complete and delete.
- **Commit cadence:** this repo covers everything here. Commit on phase advance, unit close, decision logged and session end. Commit and push go through a PR per the onboarding in `CLAUDE.md`.
- **Skill routing:**

  | Situation | Skill |
  |---|---|
  | Unstructured input needing capture or triage | `intake` |
  | Multi-session work with handoffs | `workstream` |
  | The engagement objective, KRs, decisions | `objective` |
  | Small, bounded, single-session unit | `assignment` |
  | Fynapse configuration parts, assemble, validate | `fynapse-config` |
  | Scoped-vault procedure | `scoping` |

- **Delegation and boundaries:** execution happens in this repo's `config/`, `research/` and `outputs/`. The control plane plans and tracks; it does not hold configuration.

### tools rule

- Domain-specific logic goes in `tools/fynapse/` or the engagement's own folders, never in the vendored harness CLIs.
