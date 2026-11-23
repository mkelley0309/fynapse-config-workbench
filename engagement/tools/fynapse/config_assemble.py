#!/usr/bin/env python3
"""config_assemble - assemble Fynapse bulk configuration parts into one upload file.

Usage (cwd = engagement root):

    python -B tools/fynapse/config_assemble.py <env>

Reads   config/parts/<section>/*.json        fragments (anything else, e.g. *.source.md, is ignored)
        config/instance/<env>.export.json    the instance's bulk export; source of ``version``
Writes  config/build/<env>.bulk.json         {"version": ..., "configuration": {...}}

Every path resolves against the current working directory, never this file's location.

Sections
--------
``SECTIONS`` is the ``definitions-ConfigurationExternalDTO`` key list, 28 keys, in the order of
``S/api-reference/api-reference/platform-settings/bulk-configuration/put-bulk.md:49-78``
(the same 28 properties appear in the OpenAPI block of the older mirror page
``S/api-reference/api-reference/bulk-configuration/put-bulk.md:1842-1938``; lines 49-78 of that
older page are the request parameters, not the DTO). ``accounts`` is not a DTO key. It is
accepted as an extension section (``EXTENSION_SECTIONS``) because the UI doc documents it
(``configuration-data.md:1570-1605``) and instance exports carry it; the sandbox-probe gate
records whether the API accepts it.

Fragment shapes and keys
------------------------
A fragment for a list section holds one object or a list of objects. A fragment for a singleton
section holds the object itself; two fragments for one singleton section is an error. List items
are keyed as below; a duplicate key across fragments is an error naming both files.

| Section | Shape | Key |
|---|---|---|
| accountLookups | list | postingCode |
| accountingConfigurations | list | name |
| accounts (extension) | list | number |
| balanceProcessing | singleton | - |
| businessCalendars | list | name |
| businessDateSettings | singleton | - |
| businessEventDefinition | singleton (one BED per instance) | - |
| businessEventTypes | list | name |
| d365Configurations | list | name |
| deferralCalculatorConfig | singleton | - |
| dimensionSets | list | name |
| entities | list | namespace + "/" + name |
| extractConfigurations | list | extractConfigurationName |
| featureFlags | singleton (map string -> boolean) | - |
| fiscalCalendars | list | name |
| flows | list | name |
| foreignExchangeSettings | singleton | - |
| functionalCurrencies | singleton | - |
| journalDefinition | singleton | - |
| journalGrouping | list of strings | the string |
| journalMapping | singleton | - |
| journalTypes | list | code |
| nodeValues | list | fieldName |
| nodes | list | the node's ``fields`` map as "k=v" pairs sorted by k, joined by "," |
| postingComponentIdentifications | list | businessEventTypeName + " " + canonical JSON of matchDefinitions (one BET may carry several identifications that differ only by match definitions; instance exports do this) |
| postingComponents | list | code |
| rateSets | list | name |
| reportingCurrencies | singleton | - |
| unpostedJournalsFeatureFlag | singleton | - |

Output order and determinism
----------------------------
The envelope is written as ``version`` then ``configuration``. Sections inside ``configuration``
are emitted in ``EMIT_ORDER``, the RT-7 inferred dependency order (not vendor-documented; a bulk
upload is applied as a whole): feature flags and currency settings, calendars, journal types,
JLD (+ grouping, node values), dimension sets, accounting bases, nodes (node configs are nested
in ``nodes`` and reference accounting bases, so nodes follow them), BED + entities, business
event types, accounts, account lookups, posting components, identifications, journal mapping,
flows, then the remaining optional sections. The top level is NOT key-sorted, so the emitted
order is ``EMIT_ORDER``. Every object below a section has its keys sorted; list sections are
sorted by their key; lists nested inside objects keep their authored order (reference order is
significant: configuration-data.md:1088). Output: ``json.dumps(indent=2)``, LF, trailing newline.

Exit codes: 0 ok, 1 content error, 2 usage error. Errors go to stderr as
``error: <file>: <message>``.
"""
import json
import re
import sys
from pathlib import Path

# definitions-ConfigurationExternalDTO, put-bulk.md:49-78 (platform-settings/bulk-configuration).
SECTIONS = (
    "accountLookups",
    "accountingConfigurations",
    "balanceProcessing",
    "businessCalendars",
    "businessDateSettings",
    "businessEventDefinition",
    "businessEventTypes",
    "d365Configurations",
    "deferralCalculatorConfig",
    "dimensionSets",
    "entities",
    "extractConfigurations",
    "featureFlags",
    "fiscalCalendars",
    "flows",
    "foreignExchangeSettings",
    "functionalCurrencies",
    "journalDefinition",
    "journalGrouping",
    "journalMapping",
    "journalTypes",
    "nodeValues",
    "nodes",
    "postingComponentIdentifications",
    "postingComponents",
    "rateSets",
    "reportingCurrencies",
    "unpostedJournalsFeatureFlag",
)

# Not in the DTO; documented in the UI doc (configuration-data.md:1570-1605) and present in exports.
EXTENSION_SECTIONS = ("accounts",)

SINGLETONS = frozenset({
    "balanceProcessing",
    "businessDateSettings",
    "businessEventDefinition",
    "deferralCalculatorConfig",
    "featureFlags",
    "foreignExchangeSettings",
    "functionalCurrencies",
    "journalDefinition",
    "journalMapping",
    "reportingCurrencies",
    "unpostedJournalsFeatureFlag",
})


def _node_key(item):
    fields = item.get("fields")
    if not isinstance(fields, dict) or not fields:
        return None
    return ",".join(f"{k}={fields[k]}" for k in sorted(fields))


def _entity_key(item):
    if not item.get("name"):
        return None
    return f"{item.get('namespace', '')}/{item['name']}"


def _identification_key(item):
    bet = item.get("businessEventTypeName")
    if not isinstance(bet, str) or not bet:
        return None
    match = json.dumps(item.get("matchDefinitions") or [], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{bet} {match}"


def _field(name):
    return lambda item: item.get(name) if isinstance(item.get(name), str) and item.get(name) else None


LIST_KEYS = {
    "accountLookups": ("postingCode", _field("postingCode")),
    "accountingConfigurations": ("name", _field("name")),
    "accounts": ("number", _field("number")),
    "businessCalendars": ("name", _field("name")),
    "businessEventTypes": ("name", _field("name")),
    "d365Configurations": ("name", _field("name")),
    "dimensionSets": ("name", _field("name")),
    "entities": ("namespace/name", _entity_key),
    "extractConfigurations": ("extractConfigurationName", _field("extractConfigurationName")),
    "fiscalCalendars": ("name", _field("name")),
    "flows": ("name", _field("name")),
    "journalTypes": ("code", _field("code")),
    "nodeValues": ("fieldName", _field("fieldName")),
    "nodes": ("fields", _node_key),
    "postingComponentIdentifications": ("businessEventTypeName", _identification_key),
    "postingComponents": ("code", _field("code")),
    "rateSets": ("name", _field("name")),
}
# journalGrouping: list of strings, keyed by the string itself (handled inline).

# RT-7 inferred dependency order; covers every SECTIONS key plus the extension sections.
EMIT_ORDER = (
    "featureFlags",
    "unpostedJournalsFeatureFlag",
    "businessDateSettings",
    "foreignExchangeSettings",
    "functionalCurrencies",
    "reportingCurrencies",
    "rateSets",
    "businessCalendars",
    "fiscalCalendars",
    "journalTypes",
    "journalDefinition",
    "journalGrouping",
    "nodeValues",
    "dimensionSets",
    "accountingConfigurations",
    "nodes",
    "businessEventDefinition",
    "entities",
    "businessEventTypes",
    "accounts",
    "accountLookups",
    "postingComponents",
    "postingComponentIdentifications",
    "journalMapping",
    "flows",
    "deferralCalculatorConfig",
    "balanceProcessing",
    "d365Configurations",
    "extractConfigurations",
)

assert set(EMIT_ORDER) == set(SECTIONS) | set(EXTENSION_SECTIONS), "EMIT_ORDER must cover every section"
assert set(LIST_KEYS) | SINGLETONS | {"journalGrouping"} == set(EMIT_ORDER)

ENV_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ContentError(Exception):
    def __init__(self, path, message):
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


def rel(p):
    try:
        return Path(p).resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return Path(p).as_posix()


def sort_nested(value):
    """Sort object keys at every depth; keep list order."""
    if isinstance(value, dict):
        return {k: sort_nested(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [sort_nested(v) for v in value]
    return value


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ContentError(rel(path), f"invalid JSON: {e}")


def read_version(env):
    export = Path("config") / "instance" / f"{env}.export.json"
    if not export.is_file():
        raise ContentError(rel(export), "instance export missing (download it from the target instance)")
    data = read_json(export)
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or not version:
        raise ContentError(rel(export), "export has no 'version' string")
    return version


def collect(parts_dir):
    """Return {section: value} from the fragments under parts_dir."""
    parts_dir = Path(parts_dir)
    if not parts_dir.is_dir():
        raise ContentError(rel(parts_dir), "parts directory missing")
    known = set(EMIT_ORDER)
    lists = {}        # section -> {key: (item, file)}
    singles = {}      # section -> (value, file)
    for path in sorted(parts_dir.rglob("*.json"), key=lambda p: p.relative_to(parts_dir).as_posix()):
        if not path.is_file():
            continue
        relparts = path.relative_to(parts_dir).parts
        f = rel(path)
        if len(relparts) < 2:
            raise ContentError(f, "fragment must sit in config/parts/<section>/")
        section = relparts[0]
        if section not in known:
            raise ContentError(f, f"unknown section '{section}'")
        data = read_json(path)
        if section in SINGLETONS:
            if not isinstance(data, dict):
                raise ContentError(f, f"section '{section}' is a singleton; fragment must be one object")
            if section in singles:
                raise ContentError(f, f"second fragment for singleton section '{section}' (first: {singles[section][1]})")
            singles[section] = (data, f)
            continue
        items = data if isinstance(data, list) else [data]
        bucket = lists.setdefault(section, {})
        for i, item in enumerate(items):
            if section == "journalGrouping":
                if not isinstance(item, str) or not item:
                    raise ContentError(f, f"journalGrouping item {i} must be a non-empty string")
                key = item
            else:
                if not isinstance(item, dict):
                    raise ContentError(f, f"{section} item {i} must be an object")
                keyname, keyfn = LIST_KEYS[section]
                key = keyfn(item)
                if key is None:
                    raise ContentError(f, f"{section} item {i} has no key '{keyname}'")
            if key in bucket:
                raise ContentError(f, f"duplicate {section} key '{key}' (also in {bucket[key][1]})")
            bucket[key] = (item, f)
    out = {}
    for section in EMIT_ORDER:
        if section in singles:
            out[section] = sort_nested(singles[section][0])
        elif section in lists:
            out[section] = [sort_nested(lists[section][k][0]) for k in sorted(lists[section])]
    return out


def render(version, configuration):
    text = json.dumps({"version": version, "configuration": configuration}, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def assemble(env):
    version = read_version(env)
    configuration = collect(Path("config") / "parts")
    out = Path("config") / "build" / f"{env}.bulk.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(render(version, configuration))
    return out, configuration


def main(argv):
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print("usage: config_assemble.py <env>", file=sys.stderr)
        return 2
    env = argv[0]
    if not ENV_RE.match(env):
        print(f"error: <args>: invalid env name '{env}'", file=sys.stderr)
        return 2
    try:
        out, configuration = assemble(env)
    except ContentError as e:
        print(f"error: {e.path}: {e.message}", file=sys.stderr)
        return 1
    counts = ", ".join(f"{k}={len(v) if isinstance(v, list) else 1}" for k, v in configuration.items())
    print(f"wrote {rel(out)} ({counts})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
