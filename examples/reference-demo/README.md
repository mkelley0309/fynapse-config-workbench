# Reference Demo — Config Build Methodology

A worked, end-to-end example of building a Fynapse configuration **in component parts**, then assembling, deploying, and testing it. This is the workbench's reference implementation and integration test.

> ⚠️ **PLACEHOLDER.** The component decomposition and dependency order below are **provisional**. The real dependency graph must be worked through carefully during config-workbench implementation (against a live Fynapse instance). Treat every file here as a stub to be replaced.

## The loop
1. **Requirements** (`requirements.md`) — a minimal fictional company's accounting/reporting requirements.
2. **Build parts** (`parts/`) — construct each config component from the requirements, in dependency order. Building piece-by-piece is how the approach is learned and encoded.
3. **Assemble** — merge the parts into one Bulk Configuration payload: `{ "version": "<instance>", "configuration": { /* ConfigurationExternalDTO */ } }`.
4. **Push** — upload via `PUT /api/v1/configuration/bulk` (SOFT_MERGE).
5. **Test** (`tests/`) — post sample business events via API and assert the resulting postings, balances, and drill-through.

## Component parts (dependency order — PROVISIONAL)
1. `journal-definition`
2. `business-event-definition` (the single BED — no field-count cap; only field-name length)
3. `accounting-configurations`
4. `nodes` (+ node configs)
5. `posting-components` (+ posting patterns)
6. `account-lookups`

Additional sections — business/fiscal calendars, dimension sets, journal types/mapping, flows, entities, currencies/FX, feature flags — are layered in as the decomposition is worked out.

## Example configs
Known-good assembled Bulk Configuration payloads live in `expected/` as fixtures for tests and as teaching references. (To be added.)
