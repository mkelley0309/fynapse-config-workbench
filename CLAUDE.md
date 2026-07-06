# fynapse-config-workbench

A CLI utility that generates deployable **Fynapse configuration** from human-authored markdown *demo specs*. It is the precursor to LLM-prompt-based configuration of Fynapse.

> **Status:** scaffold (2026-07-06). Implementation not yet started. Design and resumption context live in a private planning workspace, not in this repository.

## Getting started (build kickoff)

When implementation begins, run the Claude Code `/init` skill in this repository to generate codebase documentation from the real code. Merge — don't discard — the guidance in this file.

## What it does

Reads markdown **demo-spec** files (entities, event models, data model, sample data, shared configuration) and emits a **Fynapse Bulk Configuration** payload ready to upload to a Fynapse instance.

## Output contract

The Fynapse Bulk Configuration JSON envelope:

```json
{ "version": "<instance-version>", "configuration": { /* ConfigurationExternalDTO */ } }
```

Uploaded via `PUT /api/v1/configuration/bulk` (`SOFT_MERGE` by default; `HARD_MERGE` optional). The `version` string is confirmed per target instance.

`ConfigurationExternalDTO` sections include: `businessCalendars`, `fiscalCalendars`, `businessEventDefinition` (one per instance), `businessEventTypes`, `accountingConfigurations`, `dimensionSets`, `nodes` (+`nodeConfigs`), `journalDefinition`, `journalTypes`, `journalMapping`, `postingComponents` (+`postingPatterns`), `postingComponentIdentifications`, `accountLookups`, `nodeValues`, functional/reporting currencies + FX, `featureFlags`, `flows`, `entities`, and extract/D365 configuration.

## Generation order (dependency)

`journalDefinition` → `businessEventDefinition` → `accountingConfigurations` → `nodes` → `postingComponents` → `accountLookups`.

## Key configuration facts

- **One BED per instance** = the union of the instance's mandatory accounting fields + reporting-useful fields. **There is no numeric cap on BED field count** — the only limit is the character length of field *names*.
- Sub-business variation is modeled with **multiple transactional entities**, each mapped to the single BED via **Flow** (transactional entity → BED). Multiple BEDs are not used.

## Language / stack

TBD by the implementing workstream (a Claude Code CLI utility). This scaffold is intentionally language-agnostic.

## Safety

Never commit real Fynapse instance configuration, credentials, or customer data. See `.gitignore`.
