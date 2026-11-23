# Changelog

All notable changes to this template host. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions: [SemVer](https://semver.org/spec/v2.0.0.html).

Every release entry has an `### Upgrading` subsection: what an existing engagement repo must do to adopt it.

## [Unreleased]

## [0.1.0] - 2026-11-23

### Changed

- Repository identity rewritten from a CLI utility to a client-free template host (`CLAUDE.md`, `README.md`).
- Placeholder `examples/reference-demo/` removed.

### Added

- `harness.manifest.json` (hop 1) and `engagement.manifest.json` (hop 2).
- `engagement/` seeded payload: onboarding `CLAUDE.md`, `README.md`, `.gitignore`, `.gitattributes`, control-plane indexes, locks, intake, friction ledger, `outputs/`, `scope/`, `client-docs/`, `client-data/`, `research/`, `config/` READMEs.
- `engagement/.claude/settings.json` (seeded), `engagement/.claude/rules/engagement.md` and `engagement/.claude/skills/scoping/` (managed), with their `engagement.manifest.json` entries.
- `engagement/.gitattributes`: `* -text`, so payload bytes are stored as written and lock hashes survive `core.autocrlf` (replaces the per-extension `eol=lf` rules).
- `fixtures/config-demo/`: demo engagement `config/` tree (environment, neutralised instance export, parts with `.source.md` sidecars) used by the tests and the P3 gate.
- `engagement/tools/fynapse/config_assemble.py`: parts → `config/build/<env>.bulk.json`; 28 DTO sections (+ `accounts` extension), per-section keys, duplicate-key and singleton checks, `version` from the instance export, deterministic output in dependency order.
- `engagement/tools/fynapse/config_validate.py`: documented-rule errors V1–V19 (each with its doc `file:line`), V20 export diff report, V21–V24 warnings, V25–V26 `unverified (vault)` warnings.
- `tests/test_config_assemble.py`, `tests/test_config_validate.py`.
- `engagement/.claude/skills/fynapse-config/` skill (managed), with its `engagement.manifest.json` entry.

### Upgrading

- First release. Instantiate with `tools/engagement_new.py --ref v0.1.0`. No engagement repos exist yet; nothing else to do.
