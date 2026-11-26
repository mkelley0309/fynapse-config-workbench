# fynapse-config-workbench

> **Retired 2026-11;** superseded by the fynapse-workbench plugin (Fynapse-Labs/fynapse-workbench-plugin) and payload-relay.

A client-free **template host** for Fynapse configuration engagements.

- `engagement/` — the payload copied into every engagement repo: a pinned harness subset (hop 1, `harness.lock.json`) plus Fynapse configuration tooling (`engagement/tools/fynapse/`: `config_assemble.py`, `config_validate.py`).
- `fixtures/config-demo/` — a demo engagement `config/` tree the tools are tested against.
- `tools/engagement_new.py` — instantiates an engagement repo from a tagged release (hop 2, `<engagement>/template.lock.json`).
- `CHANGELOG.md` — releases, each with upgrade notes.

Engagements never pull from the harness root. See [`CLAUDE.md`](./CLAUDE.md) for the contract: re-pull, release, instantiate, tests.

## Status

- Hop-1 source `knowledge` (scoped vault): pending — consumer contract not yet published.
- Plugin-disable probe (2026-11-21): `"enabledPlugins": {"harness-core@friendly-neighborhood": false}` in the engagement's `.claude/settings.json` keeps the plugin's skills from loading; the vendored skills are listed.

`engagement/.gitattributes` sets `* -text`: payload bytes are stored exactly as written (`wb` uses `core.autocrlf=true`; an `eol` rule would rewrite vendored CRLF files and break the lock hashes).
