---
description: Operating contract for the tools subtree — generic capability primitives.
paths: ["tools/**"]
---

# Tools

Capability primitives — scripts, CLIs, helpers that are not domain-specific. Invoked by control-plane, projects, or skills.

```
tools/
  CLAUDE.md    ← thin pointer (contract lives in .claude/rules/tools.md)
  {tool-name}/ or {tool-name}.{ext}
```

---

## What Belongs Here

- Generic utilities usable across multiple projects
- Shared scripts (file conversion, format validation, cross-system glue)
- Small CLIs wrapping external APIs or services

## What Does Not

- One-off scratch → workstream `_working/`

---

## Conventions

- Each non-trivial tool gets a folder with a `README.md` (purpose, usage, dependencies)
- Prefer idempotent, composable scripts over monolithic pipelines
- Structured output (JSON, JSONL) over free-form
- Document invocation examples so callers don't read source

---

## Boundaries

- Do not orchestrate — coordination belongs in control-plane
