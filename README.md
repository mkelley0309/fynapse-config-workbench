# fynapse-config-workbench

A client-free **template host** for Fynapse configuration engagements.

- `engagement/` — the payload copied into every engagement repo: a pinned harness subset (hop 1, `harness.lock.json`) plus Fynapse configuration tooling (`engagement/tools/fynapse/`, upcoming).
- `tools/engagement_new.py` — instantiates an engagement repo from a tagged release (hop 2, `<engagement>/template.lock.json`).
- `CHANGELOG.md` — releases, each with upgrade notes.

Engagements never pull from the harness root. See [`CLAUDE.md`](./CLAUDE.md) for the contract: re-pull, release, instantiate, tests.

## Status

- Hop-1 source `knowledge` (scoped vault): pending — consumer contract not yet published.
- B9 plugin-disable probe: pending (run by the maintainer).
