# config-demo fixture

A small engagement root holding only `config/`, used to test the Fynapse configuration tools
(`engagement/tools/fynapse/config_assemble.py`, `config_validate.py`).

| Path | Content |
|---|---|
| `config/environments/demo.json` | instance id, version, export path; no credentials |
| `config/instance/demo.export.json` | a demo bulk export (version `v20260515`), `downloadedBy`/`downloadTime` removed, names neutralised |
| `config/parts/<section>/<slug>.json` | fragments split from the export's `configuration` |
| `config/parts/<section>/<slug>.source.md` | provenance sidecar per fragment |

`config/build/` is regenerable and gitignored.

## Split

| Section | Files |
|---|---|
| `businessCalendars`, `fiscalCalendars`, `journalTypes`, `journalDefinition`, `nodeValues`, `dimensionSets`, `accountingConfigurations`, `businessEventDefinition`, `journalMapping` | one file each |
| `nodes` | one file per `legalEntity` |
| `postingComponents`, `postingComponentIdentifications`, `businessEventTypes`, `accountLookups` | one file per accounting base; posting codes used by more than one base go to `shared.json` |

The parts are a subset of the export: `entities`, `accounts`, `featureFlags`,
`unpostedJournalsFeatureFlag`, `d365Configurations` and `extractConfigurations` are left out,
and the validator reports them as V20 export-diff lines.

## How the gate uses it

From a temporary copy of this folder (cwd = the copy):

1. `config_assemble.py demo` and `config_validate.py demo` must both exit 0.
2. `config/build/demo.bulk.json` has exactly `{version, configuration}`; `version` equals the export's.
3. A second assemble is byte-identical.
4. Truncating the first posting component in the first sorted `config/parts/postingComponents/*.json`
   to one posting pattern makes `config_validate.py demo` exit non-zero (V10).

The wb test suite (`tests/test_config_assemble.py`, `tests/test_config_validate.py`) runs the same checks.
