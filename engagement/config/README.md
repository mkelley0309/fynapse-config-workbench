# Configuration

The cumulative Fynapse configuration for this engagement.

| Path | Content |
|---|---|
| `config/environments/<env>.json` | instance id, version string, export path; no credentials |
| `config/instance/<env>.export.json` | downloaded bulk export from the client environment (tracked) |
| `config/parts/<section>/<slug>.json` | one fragment per object or group, owned by a workstream |
| `config/parts/<section>/<slug>.source.md` | provenance sidecar (scoped-vault path or client doc); never inside the JSON |
| `config/build/<env>.bulk.json` | assembled output; regenerable; tracked for review |
