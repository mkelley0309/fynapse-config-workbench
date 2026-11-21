# Changelog

All notable changes to this template host. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions: [SemVer](https://semver.org/spec/v2.0.0.html).

Every release entry has an `### Upgrading` subsection: what an existing engagement repo must do to adopt it.

## [Unreleased]

### Changed

- Repository identity rewritten from a CLI utility to a client-free template host (`CLAUDE.md`, `README.md`).
- Placeholder `examples/reference-demo/` removed.

### Added

- `harness.manifest.json` (hop 1) and `engagement.manifest.json` (hop 2).
- `engagement/` seeded payload: onboarding `CLAUDE.md`, `README.md`, `.gitignore`, `.gitattributes`, control-plane indexes, locks, intake, friction ledger, `outputs/`, `scope/`, `client-docs/`, `client-data/`, `research/`, `config/` READMEs.
- Pending: seeded `engagement/.claude/settings.json`, `engagement/.claude/rules/engagement.md` and `engagement/.claude/skills/scoping/` (and their `engagement.manifest.json` entries).

### Upgrading

- No engagement repos exist yet; nothing to do.
