#!/usr/bin/env python3
"""config_validate - check an assembled Fynapse bulk configuration against documented rules.

Usage (cwd = engagement root):

    python -B tools/fynapse/config_validate.py <env>

Reads   config/build/<env>.bulk.json        (missing -> exit 2: run config_assemble first)
        config/instance/<env>.export.json   (the instance export; diff baseline and fallback for references)

Every path resolves against the current working directory, never this file's location.

Severity
--------
| Rules | Severity | Effect |
|---|---|---|
| V1-V19 | error | exit 1 |
| V20 | report | export diff; never fails |
| V21-V24 | warning | exit 0, message printed (V21 is informational: a supported change) |
| V25-V26 | warning | vault claims with no doc support, labelled ``unverified (vault)`` |

Only documented rules are errors. Every rule carries its doc ``file:line`` (paths relative to the
Fynapse docs mirror) in a code comment and in its message. Undocumented limits are never errors.

References between sections resolve against the bulk file; when the bulk file omits a section
entirely, references into it resolve against the instance export (a SOFT_MERGE upload keeps
what the instance already holds).

Output: one line per finding, ``V<n> <error|warning|report>: <where>: <message> (<cite>)``,
then ``errors=N warnings=N``. Exit 0 ok, 1 on any error, 2 usage error.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling module import only; data paths use cwd
from config_assemble import LIST_KEYS, ENV_RE, sort_nested  # noqa: E402

CD = "configuration-data.md"
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class Findings:
    def __init__(self):
        self.items = []

    def add(self, rule, severity, where, message, cite):
        self.items.append((rule, severity, where, message, cite))

    def error(self, rule, where, message, cite):
        self.add(rule, "error", where, message, cite)

    def warning(self, rule, where, message, cite):
        self.add(rule, "warning", where, message, cite)

    def report(self, rule, where, message, cite):
        self.add(rule, "report", where, message, cite)

    def count(self, severity):
        return sum(1 for f in self.items if f[1] == severity)

    def lines(self):
        return [f"{r} {s}: {w}: {m} ({c})" for r, s, w, m, c in self.items]


def _list(cfg, section):
    v = cfg.get(section)
    return v if isinstance(v, list) else []


def _obj(cfg, section):
    v = cfg.get(section)
    return v if isinstance(v, dict) else None


class Ctx:
    def __init__(self, cfg, export_cfg):
        self.cfg = cfg
        self.export = export_cfg or {}

    def section(self, name):
        """Bulk section, else the export's when the bulk omits it."""
        if name in self.cfg:
            return self.cfg[name]
        return self.export.get(name)

    def names(self, section, key):
        v = self.section(section)
        return {x.get(key) for x in v if isinstance(x, dict)} if isinstance(v, list) else set()

    def jld_fields(self):
        jld = self.section("journalDefinition")
        return [f for f in (jld or {}).get("fields", []) if isinstance(f, dict)] if isinstance(jld, dict) else []

    def jld_node_fields(self):
        return {f.get("name") for f in self.jld_fields() if f.get("role") == "node"}


# ---------------------------------------------------------------- field rules (V1-V3)

def check_fields(fd, cfg):
    groups = []
    jld = _obj(cfg, "journalDefinition")
    if jld is not None:
        groups.append(("journalDefinition.fields", jld.get("fields") or []))
    bed = _obj(cfg, "businessEventDefinition")
    if bed is not None:
        groups.append(("businessEventDefinition.attributes", bed.get("attributes") or []))
    for where, fields in groups:
        seen_names, seen_labels = {}, {}
        for i, f in enumerate(fields):
            if not isinstance(f, dict):
                continue
            name, label = f.get("name"), f.get("label")
            # V1: field name unique (configuration-data.md:766-768, 897-899)
            if not name:
                fd.error("V1", f"{where}[{i}]", "field has no name", f"{CD}:766-768, 897-899")
            elif name in seen_names:
                fd.error("V1", f"{where}[{name}]", "duplicate field name", f"{CD}:766-768, 897-899")
            else:
                seen_names[name] = i
            # V2: field label unique (configuration-data.md:766-768, 897-899)
            if label is not None:
                if label in seen_labels:
                    fd.error("V2", f"{where}[{name}]", f"duplicate field label '{label}'", f"{CD}:766-768, 897-899")
                else:
                    seen_labels[label] = i
            # V3: field name/label maximum 128 characters
            # (business-event-definition.md:196; journal-line-definition.md:168; configuration-data.md:767-768, 898-899)
            for prop, val in (("name", name), ("label", label)):
                if isinstance(val, str) and len(val) > 128:
                    fd.error("V3", f"{where}[{name}]", f"field {prop} is {len(val)} characters; maximum 128",
                             f"business-event-definition.md:196; journal-line-definition.md:168; {CD}:767-768, 898-899")


# ---------------------------------------------------------------- entity rules (V4-V6)

def check_entities(fd, cfg):
    seen = set()
    for e in _list(cfg, "entities"):
        if not isinstance(e, dict):
            continue
        name = e.get("name") or ""
        where = f"entities[{name}]"
        # V4: entity name unique, letter then alphanumerics/underscore, max 128 (configuration-data.md:1777-1780)
        key = (e.get("namespace"), name)
        if key in seen:
            fd.error("V4", where, "duplicate entity name", f"{CD}:1777-1780")
        seen.add(key)
        if not NAME_RE.match(name):
            fd.error("V4", where, "entity name must start with a letter, then alphanumerics or underscore", f"{CD}:1777-1780")
        if len(name) > 128:
            fd.error("V4", where, f"entity name is {len(name)} characters; maximum 128", f"{CD}:1777-1780")
        attrs = [a for a in e.get("attributes") or [] if isinstance(a, dict)]
        anames = set()
        for a in attrs:
            an = a.get("name") or ""
            # V4: attribute name unique, syntax, max 128 (configuration-data.md:1802-1805)
            if an in anames:
                fd.error("V4", f"{where}.attributes[{an}]", "duplicate attribute name", f"{CD}:1802-1805")
            anames.add(an)
            if not NAME_RE.match(an):
                fd.error("V4", f"{where}.attributes[{an}]",
                         "attribute name must start with a letter, then alphanumerics or underscore", f"{CD}:1802-1805")
            if len(an) > 128:
                fd.error("V4", f"{where}.attributes[{an}]", f"attribute name is {len(an)} characters; maximum 128",
                         f"{CD}:1802-1805")
            # V5: attribute label max 128 (configuration-data.md:1806)
            label = a.get("label")
            if isinstance(label, str) and len(label) > 128:
                fd.error("V5", f"{where}.attributes[{an}]", f"attribute label is {len(label)} characters; maximum 128",
                         f"{CD}:1806")
        # V6: primary key 1-5 attributes, unique, primitive only (configuration-data.md:1788-1793)
        pk = e.get("primaryKeyAttributeNames") or []
        byname = {a.get("name"): a for a in attrs}
        if not 1 <= len(pk) <= 5:
            fd.error("V6", where, f"primary key has {len(pk)} attributes; must be 1 to 5", f"{CD}:1788-1793")
        if len(set(pk)) != len(pk):
            fd.error("V6", where, "primary key repeats an attribute", f"{CD}:1788-1793")
        for k in pk:
            a = byname.get(k)
            if a is None:
                fd.error("V6", where, f"primary key attribute '{k}' is not an attribute", f"{CD}:1788-1793")
            elif not (isinstance(a.get("type"), dict) and a["type"].get("typeName") == "PrimitiveType"):
                fd.error("V6", where, f"primary key attribute '{k}' is not primitive", f"{CD}:1788-1793")


# ---------------------------------------------------------------- dimension sets, accounts (V7, V8, V12)

def check_dimension_sets(fd, cfg, ctx):
    cite7 = f"{CD}:1201-1202; dimension-sets.md:41, 46"
    names, sets = set(), {}
    jld = {f.get("name") for f in ctx.jld_fields()}
    for ds in _list(cfg, "dimensionSets"):
        if not isinstance(ds, dict):
            continue
        name = ds.get("name") or ""
        where = f"dimensionSets[{name}]"
        # V7: name unique, max 255; unique set of dimensions
        if name in names:
            fd.error("V7", where, "duplicate dimension set name", cite7)
        names.add(name)
        if len(name) > 255:
            fd.error("V7", where, f"name is {len(name)} characters; maximum 255", cite7)
        attrs = frozenset(ds.get("attributes") or [])
        if attrs in sets:
            fd.error("V7", where, f"same set of dimensions as '{sets[attrs]}'", cite7)
        else:
            sets[attrs] = name
        # V12: dimension set attributes are JLD fields (configuration-data.md:1201-1202; dimension-sets.md:24)
        for a in sorted(attrs - jld):
            fd.error("V12", where, f"dimension '{a}' is not a Journal Line Definition field",
                     f"{CD}:1201-1202; dimension-sets.md:24")


def check_accounts(fd, cfg):
    if "accounts" not in cfg:
        return
    cite8 = f"{CD}:1574-1580; chart-of-accounts.md:98, 102"
    numbers, names = set(), set()
    for a in _list(cfg, "accounts"):
        if not isinstance(a, dict):
            continue
        num, name = str(a.get("number") or ""), str(a.get("name") or "")
        where = f"accounts[{num}]"
        # V8: account number unique, max 128; name unique, max 255
        if num in numbers:
            fd.error("V8", where, "duplicate account number", cite8)
        if name in names:
            fd.error("V8", where, f"duplicate account name '{name}'", cite8)
        numbers.add(num)
        names.add(name)
        if len(num) > 128:
            fd.error("V8", where, f"number is {len(num)} characters; maximum 128", cite8)
        if len(name) > 255:
            fd.error("V8", where, f"name is {len(name)} characters; maximum 255", cite8)
    # V16: accounts, if present, must include every account used in accountLookups (configuration-data.md:1585-1586)
    for lk in _list(cfg, "accountLookups"):
        for p in (lk or {}).get("accountLookupPatterns") or []:
            acc = (p or {}).get("account")
            if acc is not None and str(acc) not in numbers:
                fd.error("V16", f"accountLookups[{lk.get('postingCode')}]",
                         f"account '{acc}' missing from accounts; file would not be ingested", f"{CD}:1585-1586")


# ---------------------------------------------------------------- nodes, accounting bases (V9, V14, V15)

def _node_where(n):
    f = n.get("fields") if isinstance(n.get("fields"), dict) else {}
    return "nodes[" + ",".join(f"{k}={f[k]}" for k in sorted(f)) + "]"


def check_nodes(fd, cfg, ctx):
    bases = ctx.names("accountingConfigurations", "name")
    jld_nodes = ctx.jld_node_fields()
    values = {}
    nv = ctx.section("nodeValues")
    if isinstance(nv, list):
        values = {x.get("fieldName"): set(x.get("values") or []) for x in nv if isinstance(x, dict)}
    cite14 = f"{CD}:1144-1152"
    for n in _list(cfg, "nodes"):
        if not isinstance(n, dict):
            continue
        where = _node_where(n)
        fields = n.get("fields") if isinstance(n.get("fields"), dict) else {}
        # V14: node config needs nodes defined on the JLD, a time zone and an accounting base
        if not fields:
            fd.error("V14", where, "node has no fields", cite14)
        for k, v in fields.items():
            if k not in jld_nodes:
                fd.error("V14", where, f"field '{k}' is not a Subledger Node on the Journal Line Definition", cite14)
            elif k in values and v not in values[k]:
                fd.error("V14", where, f"value '{v}' not in nodeValues for '{k}'", f"{CD}:1130, 1144-1152")
        if not n.get("timeZone"):
            fd.error("V14", where, "no time zone", cite14)
        configs = n.get("nodeConfigs") or []
        if not configs:
            fd.error("V14", where, "no node configuration (accounting base) assigned", cite14)
        for c in configs:
            if not isinstance(c, dict):
                continue
            base = c.get("accountingConfigName")
            if not base:
                fd.error("V14", where, "node config has no accounting base", cite14)
            elif base not in bases:
                fd.error("V14", where, f"accounting base '{base}' not defined", cite14)
            # V9: grace days 0-31, hours 0-23 (configuration-data.md:1150-1152, 1183-1185)
            for prop, hi in (("graceDays", 31), ("graceHours", 23)):
                val = c.get(prop)
                if val is not None and (not isinstance(val, int) or isinstance(val, bool) or not 0 <= val <= hi):
                    fd.error("V9", f"{where}.nodeConfigs[{base}]", f"{prop} {val!r} outside 0-{hi}",
                             f"{CD}:1150-1152, 1183-1185")


def check_accounting_bases(fd, cfg, ctx):
    cite = f"accounting-bases.md:26-32; {CD}:1175-1185"
    refs = {
        "businessCalendarName": ctx.names("businessCalendars", "name"),
        "fiscalCalendarName": ctx.names("fiscalCalendars", "name"),
        "dimensionSetName": ctx.names("dimensionSets", "name"),
    }
    nodes = ctx.section("nodes")
    assigned = set()
    if isinstance(nodes, list):
        for n in nodes:
            for c in (n or {}).get("nodeConfigs") or []:
                assigned.add((c or {}).get("accountingConfigName"))
    for b in _list(cfg, "accountingConfigurations"):
        if not isinstance(b, dict):
            continue
        name = b.get("name")
        where = f"accountingConfigurations[{name}]"
        # V15: accounting base needs Business Calendar, Fiscal Calendar, Dimension Set; assigned to a node configuration
        for prop, known in refs.items():
            val = b.get(prop)
            if not val:
                fd.error("V15", where, f"no {prop}", cite)
            elif val not in known:
                fd.error("V15", where, f"{prop} '{val}' not defined", cite)
        if isinstance(nodes, list) and name not in assigned:
            fd.error("V15", where, "not assigned to any node configuration (inactive)", cite)


# ---------------------------------------------------------------- accounting engine (V10, V11, V18)

def check_posting_components(fd, cfg, ctx):
    jtypes = ctx.names("journalTypes", "code")
    bases = ctx.names("accountingConfigurations", "name")
    for pc in _list(cfg, "postingComponents"):
        if not isinstance(pc, dict):
            continue
        where = f"postingComponents[{pc.get('code')}]"
        pats = [p for p in pc.get("postingPatterns") or [] if isinstance(p, dict)]
        # V10: minimum 2 posting patterns, one DR and one CR (configuration-data.md:1485; put-posting-component.md:19)
        cite10 = f"{CD}:1485; put-posting-component.md:19"
        if len(pats) < 2:
            fd.error("V10", where, f"{len(pats)} posting pattern{'s' if len(pats) != 1 else ''}; minimum 2", cite10)
        sides = {p.get("debitCredit") for p in pats}
        if pats and not {"DR", "CR"} <= sides:
            fd.error("V10", where, "posting patterns need at least one DR and one CR", cite10)
        # V11: PC needs journal type + accounting base (configuration-data.md:1480-1485)
        cite11 = f"{CD}:1480-1485"
        jt, base = pc.get("journalType"), pc.get("accountingConfigName")
        if not jt:
            fd.error("V11", where, "no journal type", cite11)
        elif jt not in jtypes:
            fd.error("V11", where, f"journal type '{jt}' not defined", cite11)
        if not base:
            fd.error("V11", where, "no accounting base (accountingConfigName)", cite11)
        elif base not in bases:
            fd.error("V11", where, f"accounting base '{base}' not defined", cite11)


def check_identifications_and_journal_types(fd, cfg, ctx):
    bets = ctx.names("businessEventTypes", "name")
    pcs = ctx.names("postingComponents", "code")
    cite_id = f"{CD}:1492-1494"
    for ident in _list(cfg, "postingComponentIdentifications"):
        if not isinstance(ident, dict):
            continue
        bet = ident.get("businessEventTypeName")
        where = f"postingComponentIdentifications[{bet}]"
        # V18: identification references an existing BET and PC (configuration-data.md:1492-1494)
        if not bet:
            fd.error("V18", where, "no business event type", cite_id)
        elif bet not in bets:
            fd.error("V18", where, f"business event type '{bet}' not defined", cite_id)
        comps = ident.get("postingComponents") or []
        if not comps:
            fd.error("V18", where, "no posting component", cite_id)
        for c in comps:
            code = (c or {}).get("postingComponentCode")
            if code not in pcs:
                fd.error("V18", where, f"posting component '{code}' not defined", cite_id)
    cite_jt = f"{CD}:1685-1689, 1693-1706"
    for jt in _list(cfg, "journalTypes"):
        if not isinstance(jt, dict):
            continue
        where = f"journalTypes[{jt.get('code')}]"
        # V18: journal type needs code and behavior; reversing needs reversingDate (configuration-data.md:1685-1689, 1693-1706)
        if not jt.get("code"):
            fd.error("V18", where, "no journal code", cite_jt)
        if not jt.get("behavior"):
            fd.error("V18", where, "no behavior", cite_jt)
        elif jt.get("behavior") == "REVERSING" and not jt.get("reversingDate"):
            fd.error("V18", where, "REVERSING journal type has no reversingDate", cite_jt)


# ---------------------------------------------------------------- BED (V13, V17)

def check_bed(fd, cfg, ctx):
    bed = _obj(cfg, "businessEventDefinition")
    if bed is None:
        return
    # V13: JLD before BED; BED Subledger Nodes correspond 1:1 to JLD Subledger Nodes
    # (business-event-definition.md:28, 53). Creation order cannot be checked inside one bulk file; what is
    # checkable is that a JLD exists (bulk or instance) and that the node field sets match 1:1.
    cite13 = "business-event-definition.md:28, 53"
    if not ctx.jld_fields():
        fd.error("V13", "businessEventDefinition", "no Journal Line Definition in the bulk file or the instance export",
                 cite13)
    else:
        bed_nodes = {a.get("name") for a in bed.get("attributes") or [] if isinstance(a, dict) and a.get("role") == "node"}
        jld_nodes = ctx.jld_node_fields()
        for n in sorted(bed_nodes - jld_nodes):
            fd.error("V13", "businessEventDefinition", f"node field '{n}' has no JLD node field", cite13)
        for n in sorted(jld_nodes - bed_nodes):
            fd.error("V13", "businessEventDefinition", f"JLD node field '{n}' has no BED node field", cite13)
    # V17: linked references are validated in listed order; a reference used by another must be listed first
    # (configuration-data.md:1088)
    listed = set()
    for ref in bed.get("references") or []:
        if not isinstance(ref, dict):
            continue
        for d in ref.get("definition") or []:
            an = (d or {}).get("attributeName") or ""
            if "." in an:
                hook = an.split(".", 1)[0]
                if hook not in listed:
                    fd.error("V17", f"businessEventDefinition.references[{ref.get('name')}]",
                             f"uses reference '{hook}', which is not listed before it", f"{CD}:1088")
        listed.add(ref.get("name"))


# ---------------------------------------------------------------- fiscal calendars (V19)

def _date(s):
    from datetime import date
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def check_fiscal_calendars(fd, cfg):
    from datetime import timedelta
    cite = "fiscal-calendars.md:40, 46"
    for cal in _list(cfg, "fiscalCalendars"):
        if not isinstance(cal, dict) or cal.get("type") != "custom":
            continue  # gregorian periods are generated by the system
        where = f"fiscalCalendars[{cal.get('name')}]"
        periods = []
        for p in cal.get("periods") or []:
            s, e = _date((p or {}).get("startDate")), _date((p or {}).get("endDate"))
            if s and e:
                periods.append((s, e, p.get("year"), p.get("number")))
        periods.sort()
        # V19: fiscal periods neither overlap nor leave a gap (fiscal-calendars.md:40, 46)
        for (s1, e1, y1, n1), (s2, e2, y2, n2) in zip(periods, periods[1:]):
            if s2 <= e1:
                fd.error("V19", where, f"period {y2}/{n2} overlaps {y1}/{n1}", cite)
            elif s2 != e1 + timedelta(days=1):
                fd.error("V19", where, f"gap between period {y1}/{n1} and {y2}/{n2}", cite)


# ---------------------------------------------------------------- export diff (V20) and warnings (V21-V26)

def _canon(x):
    return json.dumps(sort_nested(x), sort_keys=True, ensure_ascii=False)


def _keyed(section, items):
    if section == "journalGrouping":
        return {str(x): x for x in items}
    keyfn = LIST_KEYS.get(section, (None, None))[1]
    out = {}
    for x in items:
        k = keyfn(x) if keyfn and isinstance(x, dict) else None
        out[k if k is not None else _canon(x)] = x
    return out


def diff_export(fd, cfg, export_cfg):
    cite = "export diff; D8 rule, not a doc limit"
    for section in sorted(set(cfg) | set(export_cfg)):
        if section not in export_cfg:
            fd.report("V20", section, "section added (not in instance export)", cite)
            continue
        if section not in cfg:
            fd.report("V20", section, "section absent from build (present in instance export)", cite)
            continue
        a, b = cfg[section], export_cfg[section]
        if isinstance(a, list) and isinstance(b, list):
            ka, kb = _keyed(section, a), _keyed(section, b)
            for k in sorted(set(ka) - set(kb)):
                fd.report("V20", f"{section}[{k}]", "added", cite)
            for k in sorted(set(kb) - set(ka)):
                fd.report("V20", f"{section}[{k}]", "removed", cite)
            for k in sorted(set(ka) & set(kb)):
                if _canon(ka[k]) != _canon(kb[k]):
                    fd.report("V20", f"{section}[{k}]", "changed", cite)
        elif _canon(a) != _canon(b):
            fd.report("V20", section, "changed", cite)


def check_entity_changes(fd, cfg, export_cfg):
    if "entities" not in cfg:
        return
    cite = f"{CD}:2705-2725"
    new = _keyed("entities", _list(cfg, "entities"))
    old = _keyed("entities", _list(export_cfg, "entities"))
    for k in sorted(set(new) & set(old)):
        n, o = new[k], old[k]
        where = f"entities[{k}]"
        na = {a.get("name"): a for a in n.get("attributes") or [] if isinstance(a, dict)}
        oa = {a.get("name"): a for a in o.get("attributes") or [] if isinstance(a, dict)}
        opk = set(o.get("primaryKeyAttributeNames") or [])
        # V22: unsupported entity changes lose that entity's transactional data (configuration-data.md:2705-2725)
        if n.get("temporalityType") != o.get("temporalityType"):
            fd.warning("V22", where, "temporality type changed; transactional data for this entity will be lost", cite)
        if list(n.get("primaryKeyAttributeNames") or []) != list(o.get("primaryKeyAttributeNames") or []):
            fd.warning("V22", where, "primary key changed; transactional data for this entity will be lost", cite)
        for an in sorted(set(na) & set(oa)):
            if _canon(na[an].get("type")) != _canon(oa[an].get("type")):
                fd.warning("V22", f"{where}.attributes[{an}]", "attribute type changed; data loss", cite)
            if bool(na[an].get("mandatory")) != bool(oa[an].get("mandatory")):
                fd.warning("V22", f"{where}.attributes[{an}]", "mandatory setting changed; data loss", cite)
        for an in sorted(set(na) - set(oa)):
            if na[an].get("mandatory"):
                fd.warning("V22", f"{where}.attributes[{an}]",
                           "mandatory attribute added (not a listed supported change); data loss", cite)
            else:
                # V21: supported change, informational (configuration-data.md:2705-2725)
                fd.warning("V21", f"{where}.attributes[{an}]", "non-mandatory attribute added (supported)", cite)
        for an in sorted(set(oa) - set(na)):
            if an not in opk:
                fd.warning("V21", f"{where}.attributes[{an}]", "attribute not in primary key dropped (supported)", cite)
        common_new = [a for a in na if a in oa]
        common_old = [a for a in oa if a in na]
        if common_new != common_old:
            fd.warning("V21", where, "attributes reordered (supported)", cite)
    # V23: upload lists conflicting/missing entities and deletes their data (configuration-data.md:2762-2764)
    for k in sorted(set(old) - set(new)):
        fd.warning("V23", f"entities[{k}]",
                   "in the instance but missing from the upload; the entity and its data will be deleted",
                   f"{CD}:2762-2764")


def check_node_permissions(fd, cfg, export_cfg):
    if "nodes" not in cfg:
        return
    a, b = _keyed("nodes", _list(cfg, "nodes")), _keyed("nodes", _list(export_cfg, "nodes"))
    changed = set(a) ^ set(b) | {k for k in set(a) & set(b) if _canon(a[k]) != _canon(b[k])}
    if changed:
        # V24: delete data permission rules on Subledger Nodes before uploading node changes (configuration-data.md:764)
        fd.warning("V24", "nodes", f"{len(changed)} node(s) differ from the instance; delete data permission rules "
                   "on affected Subledger Nodes before upload, else they are retained", f"{CD}:764")


def check_vault_claims(fd, cfg):
    ents = _list(cfg, "entities")
    # V25: vault claims a 100-entity cap; no mirror file states it
    if len(ents) > 100:
        fd.warning("V25", "entities", f"{len(ents)} entities; vault claims a cap of 100", "unverified (vault)")
    # V26: vault claims <= 3 lookup discriminators; not documented
    for lk in _list(cfg, "accountLookups"):
        defs = (lk or {}).get("accountLookupAttributeDefinition") or []
        if len(defs) > 3:
            fd.warning("V26", f"accountLookups[{lk.get('postingCode')}]",
                       f"{len(defs)} lookup discriminators; vault claims a maximum of 3", "unverified (vault)")


# ---------------------------------------------------------------- driver

def validate(bulk, export):
    fd = Findings()
    cfg = bulk.get("configuration") if isinstance(bulk, dict) else None
    cfg = cfg if isinstance(cfg, dict) else {}
    export_cfg = export.get("configuration") if isinstance(export, dict) else None
    export_cfg = export_cfg if isinstance(export_cfg, dict) else {}
    ctx = Ctx(cfg, export_cfg)
    check_fields(fd, cfg)
    check_entities(fd, cfg)
    check_dimension_sets(fd, cfg, ctx)
    check_accounts(fd, cfg)
    check_nodes(fd, cfg, ctx)
    check_accounting_bases(fd, cfg, ctx)
    check_posting_components(fd, cfg, ctx)
    check_identifications_and_journal_types(fd, cfg, ctx)
    check_bed(fd, cfg, ctx)
    check_fiscal_calendars(fd, cfg)
    diff_export(fd, cfg, export_cfg)
    check_entity_changes(fd, cfg, export_cfg)
    check_node_permissions(fd, cfg, export_cfg)
    check_vault_claims(fd, cfg)
    return fd


def main(argv):
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print("usage: config_validate.py <env>", file=sys.stderr)
        return 2
    env = argv[0]
    if not ENV_RE.match(env):
        print(f"error: <args>: invalid env name '{env}'", file=sys.stderr)
        return 2
    build = Path("config") / "build" / f"{env}.bulk.json"
    export = Path("config") / "instance" / f"{env}.export.json"
    if not build.is_file():
        print(f"error: {build.as_posix()}: missing; run config_assemble first", file=sys.stderr)
        return 2
    if not export.is_file():
        print(f"error: {export.as_posix()}: instance export missing", file=sys.stderr)
        return 2
    docs = []
    for p in (build, export):
        try:
            docs.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            print(f"error: {p.as_posix()}: invalid JSON: {e}", file=sys.stderr)
            return 1
    fd = validate(*docs)
    for line in fd.lines():
        print(line)
    errors, warnings = fd.count("error"), fd.count("warning")
    print(f"errors={errors} warnings={warnings}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
