# disclosure-scan

Deterministic pre-push disclosure scanner. Flags internal hostnames, emails, identities, customer names, client-document references, local paths and private paths before content leaves the workspace. Stdlib only, Python 3.12. No network, no LLM.

Rerun it yourself — never trust a reported zero.

## Categories

| Category | Source (terms file) | Matches |
|---|---|---|
| `hostname` | `internal_domains`, `host_patterns` | Host ending in a configured domain (dot variants `.` `[dot]` `(dot)` ` dot `); raw `host_patterns` regexes |
| `email` | `email_domains`, `identities.local_parts` | Any address at a configured domain, except local-parts in that entry's optional `allow_local_parts`; any identity local-part at any domain. `@` variants `@` `[at]` `(at)` ` at ` `%40`, with optional spaces or tabs around `@` `[at]` `(at)` `%40` |
| `identity` | `identities.names`, `identities.local_parts` | Bare name or local-part on word boundaries, no `@` context |
| `customer` | `customers` with `public_citation: null` | Name and variants. Cited customers do not match. Spans overlapping a partner match are suppressed |
| `client-path` | `client_paths` | (a) Presence: one finding per root holding files, with file count; contents not scanned. (b) Reference: any `reference_terms` occurrence in text or path, `/` or `\` |
| `local-path` | `identities.usernames` | `X:\Users\<u>`, `X:/Users/<u>`, `/Users/<u>`, `/home/<u>`, `\\`-escaped forms; case-insensitive |
| `private-path` | `private_terms` | `literal`: `/` and `\` interchangeable, leading boundary; `regex`: as written |

- Term matching tolerates separators, case and camelCase: `Phase 0` matches `Phase-0`, `phase_0`, `Phase0`, `PHASE.0`; not `Phase 01`, `xPhase0`.
- One text span reports once. Priority: `local-path` > `email` > `client-path` > `hostname` > `customer` > `identity` > `private-path`.
- Every text line is scanned (frontmatter included). Each file's workspace-relative POSIX path is scanned as line 0.
- Files with a NUL in the first 8 KB, or over `max_bytes`, land in `skipped` (listed, never silent).
- The active terms file is always excluded.

## CLI

```
python -B tools/disclosure-scan/disclosure_scan.py tree [PATH ...]            # default: knowledge/
python -B tools/disclosure-scan/disclosure_scan.py tree --git-set DIR
python -B tools/disclosure-scan/disclosure_scan.py diff (--staged | --range A..B) [--cwd DIR]
common: --terms FILE (default tools/disclosure-scan/terms.local.json)
        --waivers FILE (default tools/disclosure-scan/waivers.json)
        --json  --out FILE  --show-values  --strict
```

- `tree`: sorted walk, `exclude_globs` applied; works on directories that are not git repos.
- `tree --git-set DIR`: scans exactly what `git -C DIR ls-files -co --exclude-standard` lists (tracked + untracked, gitignored excluded). A nested repo it lists as a directory goes to `skipped` (`nested-repo`). Takes no PATHs.
- Reported paths are workspace-relative in every mode (`diff` in a nested repo prefixes that repo's path, e.g. `knowledge/...`), so `waivers.json` and `client_paths` use one path form.
- `diff`: scans only added lines, reports new-file line numbers; removed lines are never flagged. Added files also get a path scan. Binary diffs go to `skipped`. Covers git repos only: workspace root by default, nested repos via `--cwd`.
- A `client_paths` root with files in the diff yields one presence finding (with count) and its contents are not scanned.
- `--json` prints the report to stdout; `--out FILE` writes it to a file.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | No unwaived findings |
| 1 | Unwaived findings, or stale waivers under `--strict` |
| 2 | Usage, config or git error (terms file missing, zero terms, duplicate id, bad regex, partner equals customer, bad waiver, bad range) |

## Output and redaction guarantee

- Report is `harness-records/1`, `kind: disclosure-scan`: `generated, mode, targets, terms_digest, counts, findings, skipped, stale_waivers`.
- Finding fields: `category, term_id, path, line, col, waived, waiver_reason` (plus `count` on client-path presence findings). **No matched values**; reports cite term ids.
- Console default: `path:line:col category term_id`. `--show-values` appends matched text to the console only, never to `--json` or `--out`.
- A term in a file name appears in `path`; that is inherent to citing locations.
- Findings sort by `(path, line, col, category, term_id)`; reruns match except `generated`.

## First-time setup

1. Copy `terms.example.json` to `terms.local.json` (gitignored, operator-owned).
2. Replace every fake value. Keep ids unique across the whole file.
3. Run `tree` on a known-dirty fixture to confirm each category fires.

## Curating customers

- Add every customer with `"public_citation": null`.
- Set a citation only after checking the actual source. The scanner never decides publicness.
- Optional top-level `citation_domains`: when set, every `public_citation` must be an `https://` URL on one of those domains (subdomains allowed), or the terms file fails to load (exit 2).
- Keep partners in `partners`, separate. A name or variant in both lists is a config error (exit 2).

## Waivers

`waivers.json`: `{"path": "<fnmatch glob>", "category": "...", "term_id": "...", "reason": "..."}`.

Glob semantics are plain `fnmatch`: `*` crosses `/` (so `a/*.md` also matches `a/b/c.md`), and `**/x.md` does not match a top-level `x.md`. Keep waiver globs as narrow as the finding needs.

A customer with a `public_citation` requires a non-empty `citation_domains` (exit 2 otherwise): a cited customer is never scanned, so every citation must be checkable.

- `reason` is required and must hold no sensitive values.
- Waived findings stay in the report with `waived: true`.
- A waiver that matches no finding, but whose path glob covers at least one path this run scanned, is listed in `stale_waivers` (warning; exit 1 under `--strict`). Waivers for paths outside a scoped `tree` are not stale. `diff` never reports stale waivers: it sees only added lines, so an unused waiver there proves nothing. Check staleness with a full `tree` run. Review and prune stale waivers.

## Pre-push command

```
python -B tools/disclosure-scan/disclosure_scan.py diff --range <remote>/main..HEAD --strict
```

Run inside the repo being pushed (`--cwd` for nested repos).
