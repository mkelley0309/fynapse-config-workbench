---
name: fynapse-config
description: Build or change a Fynapse bulk configuration in this engagement. Use when authoring or editing configuration parts under config/parts/ (journal line definition, business event definition, nodes, dimension sets, calendars, accounting bases, journal types, business event types, posting components, identifications, account lookups, journal mapping), when assembling them into config/build/<env>.bulk.json with tools/fynapse/config_assemble.py, when validating with tools/fynapse/config_validate.py, when reading validator findings, or when preparing a bulk file for manual upload to an instance.
---

# fynapse-config

Turns scoped knowledge and client sources into Fynapse configuration **parts**, assembles them
into one bulk upload file, and validates it against documented rules. Upload stays manual.

## Procedure

Iterate; never one-shot. Each pass:

1. **Sources.** Read the scoped vault (`scoped-vault/`) and client docs (`client-docs/`, `client-data/`).
   - Posting side: the scoped vault's `posting-block`s, the posting-code registry and the basis matrix.
   - Foundation side (BED, nodes, dimension sets, calendars, chart of accounts): client docs and the engagement design (`research/`, workstream `design.md`).
2. **Parts.** Write fragments to `config/parts/<section>/<slug>.json`; each gets a sidecar `<slug>.source.md` citing its sources (vault path or client doc). Provenance never goes inside the JSON.
3. **Assemble.** `python -B tools/fynapse/config_assemble.py <env>` (cwd = engagement root).
4. **Validate.** `python -B tools/fynapse/config_validate.py <env>`. Fix every error in the parts, never in the build file.
5. **Review.** Read the V20 diff against the instance export and every warning. Log decisions in the engagement control plane (`python -B tools/objective.py log-decision ...`).
6. Repeat until the validator reports `errors=0` and review signs off. Then upload manually.

Each rollout workstream (foundation first, then by basis, offering or event model) owns its own fragment files.

## Layout

| Path | Content |
|---|---|
| `config/environments/<env>.json` | instance id, version string, export path; no credentials |
| `config/instance/<env>.export.json` | downloaded bulk export of the target instance (fixes `version`) |
| `config/parts/<section>/<slug>.json` | one fragment per object or group |
| `config/parts/<section>/<slug>.source.md` | provenance sidecar |
| `config/build/<env>.bulk.json` | assembled output; regenerable |

## Bulk `configuration` keys

Authoritative list: `definitions-ConfigurationExternalDTO`, 28 keys, all optional —
`api-reference/api-reference/platform-settings/bulk-configuration/put-bulk.md:49-78` (docs mirror).
The older page `api-reference/api-reference/bulk-configuration/put-bulk.md` carries the same 28
properties in its OpenAPI block (lines 1842-1938); its lines 49-78 are request parameters.

`accountLookups`, `accountingConfigurations`, `balanceProcessing`, `businessCalendars`,
`businessDateSettings`, `businessEventDefinition`, `businessEventTypes`, `d365Configurations`,
`deferralCalculatorConfig`, `dimensionSets`, `entities`, `extractConfigurations`, `featureFlags`,
`fiscalCalendars`, `flows`, `foreignExchangeSettings`, `functionalCurrencies`, `journalDefinition`,
`journalGrouping`, `journalMapping`, `journalTypes`, `nodeValues`, `nodes`,
`postingComponentIdentifications`, `postingComponents`, `rateSets`, `reportingCurrencies`,
`unpostedJournalsFeatureFlag`.

`accounts` is **not** a DTO key. The UI doc documents it (`configuration-data.md:1570-1605`) and
exports carry it, so the assembler accepts it as an extension section. Whether the API accepts it
is a sandbox-probe record.

## Section keys (assembler)

List-section fragments hold one object or a list; singleton fragments hold the object. A duplicate
key across fragments, or two fragments for one singleton, is an assemble error.

| Section | Key |
|---|---|
| `accountLookups` | `postingCode` |
| `accountingConfigurations`, `businessCalendars`, `businessEventTypes`, `d365Configurations`, `dimensionSets`, `fiscalCalendars`, `flows`, `rateSets` | `name` |
| `accounts` (extension) | `number` |
| `entities` | `namespace/name` |
| `extractConfigurations` | `extractConfigurationName` |
| `journalGrouping` | the string |
| `journalTypes` | `code` |
| `nodeValues` | `fieldName` |
| `nodes` | the `fields` map (`k=v` pairs sorted by `k`) |
| `postingComponentIdentifications` | `businessEventTypeName` + `matchDefinitions` (one event type may carry several identifications that differ by match definitions) |
| `postingComponents` | `code` |

Singletons: `balanceProcessing`, `businessDateSettings`, `businessEventDefinition` (one per
instance), `deferralCalculatorConfig`, `featureFlags` (map string → boolean),
`foreignExchangeSettings`, `functionalCurrencies`, `journalDefinition`, `journalMapping`,
`reportingCurrencies`, `unpostedJournalsFeatureFlag`.

Emit order (inferred dependency order, not vendor-documented; a bulk upload applies as a whole):
feature flags and currency settings → calendars → journal types → JLD (+ grouping, node values) →
dimension sets → accounting bases → nodes (node configs nested) → BED + entities → business event
types → accounts → account lookups → posting components → identifications → journal mapping →
flows → remaining sections.

## Facts

- **Envelope:** `{"version": "<instance-version>", "configuration": {...}}`, uploaded with `PUT /api/v1/configuration/bulk`; `uploadMode` `SOFT_MERGE` (default) or `HARD_MERGE`. `version` comes from the target instance's export; never hard-code it.
- **Build loop:** requirements → parts → assemble → validate → review → manual upload.
- **BED:** one business event definition per instance. No documented cap on BED field count; only field name/label length (128 characters) is limited. Sub-business variation = multiple transactional entities mapped to the single BED via Flow.

## Precedence

1. Current docs mirror (via the scoped vault)
2. The instance export
3. The vault

## Overrides (vault vs docs; docs win)

| Topic | Vault says | Use (docs) |
|---|---|---|
| BED attribute `type` | text, decimal, date, uuid | date, text, integer, decimal (`business-event-definition.md:34-39`); uuid and amount are JLD types (`journal-line-definition.md:30-37`) |
| Journal type behaviour | `PERM` | `PERMANENT` (`configuration-data.md:1698`); `REVERSING` + `reversingDate: NEXT_DAY` (`:1703-1704`) |
| Entity cap | 100 | not documented → warning only |
| Lookup discriminators | ≤ 3 | not documented → warning only |
| BED roles | `event_type`, `effective_date`, `node`, `attribute` | matches the bulk example (`bulk-operations-via-api.md:84-118`); full list undocumented |

Schema vs UI-doc differences:

| Topic | Detail |
|---|---|
| `accounts` | in the UI doc (`configuration-data.md:1570-1605`), not in the API DTO; granular alternative `api-reference/api-reference/accounting-rules/accounts/*` |
| `databaseConfiguration` | in the UI doc (`configuration-data.md:1829-1838`), absent from the entity DTO |
| Type spelling | JLD/BED field `type` lowercase; entity attribute `type` is `{typeName: "PrimitiveType", primitive: "TEXT"\|"DATE"\|"DECIMAL"…}` |
| PC accounting base key | bulk `accountingConfigName`; granular PC endpoint `accountingConfig` (`put-posting-component.md:57`) |

**Override statement:** generate `PERMANENT`, not `PERM`; BED additional-field types date/text/integer/decimal; `accountingConfigName` in bulk.

## Validator rules

Errors (exit 1) — documented rules only; each finding prints its cite.

| # | Rule | Cite |
|---|---|---|
| V1 | BED/JLD field name unique | `configuration-data.md:766-768, 897-899` |
| V2 | BED/JLD field label unique | same |
| V3 | BED/JLD field name/label ≤ 128 | `business-event-definition.md:196`; `journal-line-definition.md:168` |
| V4 | entity / attribute name unique, letter then alphanumerics/underscore, ≤ 128 | `configuration-data.md:1777-1780, 1802-1805` |
| V5 | attribute label ≤ 128 | `configuration-data.md:1806` |
| V6 | entity primary key 1–5 primitive attributes | `configuration-data.md:1788-1793` |
| V7 | dimension set name unique, ≤ 255; unique set of dimensions | `configuration-data.md:1201-1202`; `dimension-sets.md:41, 46` |
| V8 | account number unique ≤ 128, name unique ≤ 255 | `configuration-data.md:1574-1580`; `chart-of-accounts.md:98, 102` |
| V9 | grace days 0–31, hours 0–23 | `configuration-data.md:1150-1152, 1183-1185` |
| V10 | ≥ 2 posting patterns, one DR and one CR | `configuration-data.md:1485`; `put-posting-component.md:19` |
| V11 | PC has a defined journal type and accounting base | `configuration-data.md:1480-1485` |
| V12 | dimension set attributes are JLD fields | `configuration-data.md:1201-1202`; `dimension-sets.md:24` |
| V13 | JLD exists; BED node fields map 1:1 to JLD node fields (creation order itself is not checkable in one file) | `business-event-definition.md:28, 53` |
| V14 | node fields are JLD nodes (values in `nodeValues`), time zone, defined accounting base | `configuration-data.md:1130, 1144-1152` |
| V15 | accounting base has defined business calendar, fiscal calendar, dimension set; assigned to a node config | `accounting-bases.md:26-32`; `configuration-data.md:1175-1185` |
| V16 | `accounts`, if present, holds every lookup account | `configuration-data.md:1585-1586` |
| V17 | BED linked references listed before use | `configuration-data.md:1088` |
| V18 | identifications reference defined event types and PCs; journal type has code + behaviour, reversing has `reversingDate` | `configuration-data.md:1492-1494, 1685-1689, 1693-1706` |
| V19 | custom fiscal periods neither overlap nor gap | `fiscal-calendars.md:40, 46` |

Report: **V20** diff against the instance export (sections and objects added/removed/changed, by key); never fails.

Warnings (exit 0): **V21** supported entity change (informational), **V22** unsupported entity change → data loss (`configuration-data.md:2705-2725`), **V23** entities missing from an upload that carries `entities` are deleted with their data (`:2762-2764`), **V24** delete data-permission rules on changed Subledger Nodes before upload (`:764`), **V25–V26** `unverified (vault)`: > 100 entities, > 3 lookup discriminators.

References into a section the bulk file omits resolve against the instance export.

## Undocumented limits are warnings

Never make an undocumented limit an error. The docs mirror is silent on:

- BED field/attribute count (no "50 fields" limit);
- entities per instance;
- payload size, request rate, node counts, PC counts, lookups, dimensions per set;
- enumerations: `conversionMode`, `overridePostingDate`, `mappingType`, `nwdType`, `frequency`, `journalGrouping`, full `FieldDefinition.role` list, `Entity.type` beyond two values, `reversingDate` beyond `NEXT_DAY`;
- `amountSignage` beyond POS/NEG/AUTO and `matchDefinitions.type` beyond ANY/IN/NOT IN/EMPTY (`mapping.md:45-49`).

## Sandbox-probe gate

Seeded in every engagement. The first foundation workstream downloads the export (fixes the
version), uploads a minimal assembled config, and records:

| Record |
|---|
| SOFT_MERGE vs HARD_MERGE behaviour |
| `accounts` acceptance |
| error shape |
| `PERM` vs `PERMANENT` |

Findings go to `research/` and, through an operator intake, back to the harness owner. **Until the
gate resolves, generate for a clean instance** (HARD_MERGE semantics irrelevant).

## Upload

Manual, through the UI (Configuration Data screen) or the API, outside this tooling. The Fynapse
`subledger-configuration` skill or MCP server is a possible future apply path; it is not vendored.
