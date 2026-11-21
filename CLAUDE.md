# fynapse-config-workbench — template host contract

## What `wb` is

A **client-free template host**. It:

| Does | Where |
|---|---|
| Vendors a pinned subset of a private harness (hop 1) | `engagement/` (lock: `harness.lock.json`) |
| Adds Fynapse configuration tooling | `engagement/tools/fynapse/` (P3) |
| Instantiates engagement repos from a tagged release (hop 2) | `tools/engagement_new.py` → `<engagement>/template.lock.json` |

`wb` has a public remote. Never name a client, customer, engagement or person in files, commit messages, test data or comments. Use fictional names (`acme-demo`, `example-engagement`).

## Layering

| Hop | From → to | Manifest | Lock |
|---|---|---|---|
| 1 | harness root → `wb/engagement/` | `harness.manifest.json` | `harness.lock.json` |
| 2 | `wb` → engagement repo | `engagement.manifest.json` | `<engagement>/template.lock.json` |

Engagements never pull from the harness root.

## Rules

- `engagement/` is **payload**, not `wb`'s own `.claude/`. `wb` has **no** `.claude/` directory.
- Never hand-edit vendored files (managed by hop 1). Fix upstream in the harness root, then re-pull.
- Run every CLI and test with `WORKSPACE_ROOT` unset.
- New files use LF.

## Re-pull hop 1

From the `wb` root, with `<WS>` = the harness root:

```
python -B <WS>/tools/template-sync/template_sync.py pull --manifest harness.manifest.json --dest engagement \
  --lock harness.lock.json --commit workspace=<sha> --commit knowledge=pending --edition engagement
python -B <WS>/tools/template-sync/template_sync.py check --manifest harness.manifest.json --dest engagement --lock harness.lock.json
```

`check` must exit 0. Commit `harness.lock.json` with the pulled files: `wb: pull harness @<sha8>`.

## Release

1. Update `CHANGELOG.md` (move `[Unreleased]` to the new version; fill `### Upgrading`).
2. `git tag vX.Y.Z`.
3. Push after review.

## Instantiate an engagement

```
python -B tools/engagement_new.py <target> --name <slug> --success-criteria <file> [--title T] [--adopt] [--ref <tag|sha>]
```

Creates the engagement objective, seeds one KR per success-criteria line, adds the standard gates, renders views.

## Tests

```
python -B -m unittest discover -s tests -t .
```

From the `wb` root, `WORKSPACE_ROOT` unset. Needs `git` and the harness root at `../..` (for `template_sync`).

## Configuration knowledge

Moves into the `fynapse-config` skill in P3.

- **Output envelope:** `{ "version": "<instance-version>", "configuration": { /* ConfigurationExternalDTO */ } }`, uploaded with `PUT /api/v1/configuration/bulk` (`SOFT_MERGE` default, `HARD_MERGE` optional). `version` comes from the target instance's export; never hard-code it.
- **Build loop:** requirements → parts → assemble → validate → review → (manual upload).
- **BED:** one business event definition per instance. No documented cap on BED field count; only field-name length (128 characters) is limited. Sub-business variation = multiple transactional entities mapped to the single BED via Flow.
- **`ConfigurationExternalDTO` sections include:** `businessCalendars`, `fiscalCalendars`, `businessEventDefinition` (one per instance), `businessEventTypes`, `accountingConfigurations`, `dimensionSets`, `nodes` (+`nodeConfigs`), `journalDefinition`, `journalTypes`, `journalMapping`, `postingComponents` (+`postingPatterns`), `postingComponentIdentifications`, `accountLookups`, `nodeValues`, functional/reporting currencies + FX, `featureFlags`, `flows`, `entities`, and extract/D365 configuration.
- **Generation order (placeholder; superseded by the assemble order in P3):** `journalDefinition` → `businessEventDefinition` → `accountingConfigurations` → `nodes` → `postingComponents` → `accountLookups`.

## Safety

Never commit real Fynapse instance configuration, credentials, or customer data. See `.gitignore`.
