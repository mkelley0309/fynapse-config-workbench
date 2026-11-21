# template-sync

Generic, stdlib-only template sync from a pinned git commit. Reads objects from the source repo (`git ls-tree` + `git cat-file --batch`), never the working tree. No dependency on `WORKSPACE_ROOT` or `control-plane/`.

## Hop model

| Hop | From → to | Edition | Pin |
|---|---|---|---|
| 1 | Workspace root → `wb/engagement/` (harness subset) | `engagement` (strips workspace-only spans) | lock in wb |
| 2 | wb → engagement repo (whole payload) | `engagement` (no `edition_strip` entries needed) | lock in engagement repo |

Engagements never pull from root.

## Commands

```
python -B tools/template-sync/template_sync.py pull  --manifest M --dest D [flags]
python -B tools/template-sync/template_sync.py check --dest D [--manifest M] [flags]
python -B tools/template-sync/template_sync.py init  --manifest M --dest NEW [flags]
python -B tools/template-sync/template_sync.py strip --edition engagement|workspace PATH
```

| Command | Behaviour |
|---|---|
| `pull` | Copy per manifest from `--commit` (default `HEAD`), write lock. Managed files with local edits refuse (exit 1, nothing written) unless `--force`. Seeded files written only if absent |
| `check` | Drift report. Without `--manifest`: lock-only (dest vs lock hashes; upstream comparison skipped). With `--manifest`: also compares post-strip content at the lock's commit (override with `--commit`) |
| `init` | `pull` into a new dest. Refuses dest == source repo or inside it; refuses an existing lock unless `--force` |
| `strip` | Print the edition text of a local file to stdout. `engagement` removes workspace spans; `workspace` prints the file unchanged (markers kept). Unbalanced markers: error |

Flags (pull/check/init):

| Flag | Meaning |
|---|---|
| `--manifest FILE` | Manifest (required for pull/init) |
| `--dest DIR` | Destination (default `.`) |
| `--lock FILE` | Lock path (default `<dest>/template-sync.lock.json`) |
| `--source [id=]PATH` | Override a source repo; bare form only for a single-source manifest. Repeatable |
| `--commit [id=]REF` | Commit/ref per source; bare form only for single-source. `pending` skips the source. Repeatable |
| `--edition engagement\|workspace` | Default `engagement` on pull/init; `check` defaults to the lock's edition |
| `--force` | Overwrite locally edited managed files |
| `--dry-run` | Report only; write nothing |

Output: JSON report on stdout (pull/init/check); messages on stderr.

## Manifest `template-sync-manifest/1`

```json
{"schema": "template-sync-manifest/1",
 "sources": {"root": {"repo": "../../.."}},
 "entries": [
   {"source": "root", "path": ".claude/skills/objective", "dest": "skills/objective",
    "class": "managed", "edition_strip": true, "exclude": ["__pycache__/**", "terms.local.json"]}]}
```

- `repo`: relative to the manifest's directory, or absolute.
- `path`: a file, a directory (recursive), or a glob (`*`, `?`, `**`). Dest is a prefix; structure relative to the directory (or the glob's literal base) is kept. A single-file `path` writes exactly `dest` (a trailing `/` appends the file name).
- `exclude`: globs matched against the relative path (also at any depth).
- `edition_strip`: apply marker stripping, only when the edition is `engagement`.
- An entry matching nothing, or two entries writing one dest, is an error.

## Lock `template-sync-lock/1`

```json
{"schema": "template-sync-lock/1", "edition": "engagement", "manifest_sha256": "…",
 "sources": {"root": {"repo_id": "Workspace", "commit": "<sha>", "commit_date": "<iso>", "tag": "optional"}},
 "files": {"skills/objective/SKILL.md": {"sha256": "…", "class": "managed", "source": "root"}}}
```

Sorted keys, indent 2, LF, trailing newline. `repo_id` is the source directory name. File `sha256` is of the bytes written (post-strip); for a seeded file kept local, the upstream hash. A source with commit `pending` is carried through unread: its entries are skipped and its lock files kept.

## Markers (engagement edition strips, marker lines inclusive)

```
<!-- EDITION:workspace:start -->  …  <!-- EDITION:workspace:end -->
# EDITION:workspace:start         …  # EDITION:workspace:end        (may be indented)
```

One kind only (`workspace`). Unbalanced, nested, or start/end of different syntax = error. Kept lines retain their EOL bytes (LF, CRLF, none at EOF).

## Classes

| Class | Sync |
|---|---|
| `managed` | Overwritten on pull. Dest hash differing from the lock (or no lock entry) = local edit: refuse unless `--force` |
| `seeded` | Written only if absent. Present and different: diff summary (lines added/removed) reported, never overwritten |

Lock files no longer produced by the manifest are reported as `orphaned_left_on_disk` and dropped from the lock; never deleted.

## `check` statuses and exit codes

Managed statuses: `missing`, `edited`, `upstream-differs`, `unlocked`, `orphan`. A manifest sha256 differing from the lock is also drift. Seeded `missing`/`differs` are reported only.

| Code | Meaning |
|---|---|
| 0 | OK / clean |
| 1 | Drift (check) or refused for local edits (pull/init) |
| 2 | Error: bad input, git failure, unbalanced markers, init into source |

## Tests

`python -B -m unittest tools.tests.test_template_sync` (from the Workspace root). Temp git repos; each CLI call spawns git several times, so the suite takes about a minute on Windows.
