#!/usr/bin/env python3
"""intake.py - intake, gate and backlog records for the control plane (harness-records/1).

Commands:
  capture <slug> --title T --source S [--objective O --route R]
  triage <slug> --objective O --route R [--depends-on --related --locks --inputs --backlog --keep-until]
  consume <slug> --by <unit>      drop <slug> --reason T      archive <slug>
  split <slug> --into a,b,..
  set <slug> [--kind --captured --source --objective --route --depends-on --related --locks --inputs
              --backlog --consumed-by --keep-until --dropped-reason]     (status is command-only)
  backlog <path> [--json] [--done ID | --drop ID --reason T | --move ID --to TARGET]
  gate add <slug> --title --type --who --criteria [--objective] | gate resolve <slug> --evidence E
       | gate drop <slug> --reason T | gate set <slug> [--title --type --who --criteria --objective --evidence]
  list [--objective --status --kind] [--json]
  check [--inputs] [--strict] [--json]
  render [--check] [--force] [--adopt] [--resolve]

Repeatable list flags accept `--x a --x b` or `--x a,b`. Stdlib only.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesslib as H  # noqa: E402

INTAKE_STATUS = ("captured", "triaged", "active", "consumed", "dropped")
MS_STATUS = ("open", "active", "done", "dropped")
GATE_STATUS = ("open", "done", "dropped")
GATE_TYPES = ("human", "external", "decision", "artifact")
TERMINAL = {"intake": ("consumed", "dropped"), "milestone": ("done", "dropped"), "gate": ("done", "dropped")}
STATUS = {"intake": INTAKE_STATUS, "milestone": MS_STATUS, "gate": GATE_STATUS}
KEYS = {
    "intake": {"note_type", "kind", "status", "captured", "source", "objective", "route", "depends_on",
               "related", "locks", "inputs", "backlog", "consumed_by", "keep_until", "dropped_reason",
               "consumed", "dropped"},
    "milestone": {"note_type", "id", "title", "status", "order", "conditional", "depends_on", "related",
                  "locks", "fed_by", "inputs", "backlog", "unit", "ref", "done", "legacy"},
    "gate": {"note_type", "title", "gate_type", "who", "criteria", "status", "resolved", "evidence",
             "objective"},
}
REQUIRED = {"intake": ("kind", "status", "captured", "source", "objective", "route"),
            "milestone": ("id", "title", "status"),
            "gate": ("title", "gate_type", "who", "criteria", "status")}
ROUTE_RE = re.compile(r"^(milestone:[a-z0-9-]+#\d+|(workstream|assignment|cadence):[a-z0-9-]+"
                      r"|candidate:(workstream|assignment)|tools|none)$")
ID_RE = re.compile(r"^(intake:[a-z0-9-]+|gate:[a-z0-9-]+|[a-z0-9-]+#\d+|(workstream|assignment|cadence):[a-z0-9-]+)$")
UNIT_RE = re.compile(r"^(workstream|assignment|cadence):[a-z0-9-]+$")


def die(msg):
    H.die(msg)


listflag = H.listflag     # one parsing helper for every list flag (repeated or comma-separated)


def root():
    return H.find_root()


def cp(r):
    return r / "control-plane"


def intake_path(r, slug, archived=False):
    return cp(r) / "intake" / ("_archive" if archived else "") / f"{slug}.md"


def need_slug(slug):
    if not H.kebab_ok(slug):
        die(f"bad slug (kebab-case required): {slug}")


def check_enum(val, allowed, what):
    if val not in allowed:
        die(f"bad {what} '{val}' (allowed: {', '.join(allowed)})")


def check_route(route, recs):
    if not ROUTE_RE.match(route or ""):
        die(f"bad route '{route}'")
    if route.startswith("milestone:") and route[len("milestone:"):] not in recs:
        die(f"unresolved route target: {route}")


def check_ids(ids, recs, what, root_=None):
    for i in ids:
        if not ID_RE.match(i):
            die(f"bad id in {what}: {i}")
        if not UNIT_RE.match(i) and i not in recs:
            die(f"unresolved id in {what}: {i}")


def check_locks(names, r):
    reg = H.load_locks(r)
    for n in names:
        if n not in reg:
            die(f"unknown lock '{n}' (registry: control-plane/locks.md)")


def check_no_cycle(recs, rid, deps):
    g = H.build_graph(recs)
    g[rid] = list(deps)
    cyc = H.find_cycle(g)
    if cyc:
        die("dependency cycle: " + " -> ".join(cyc))


def check_paths(paths, r, what):
    for p in paths:
        if not (r / p).exists():
            die(f"{what} path does not exist: {p}")


def get_live(r, slug):
    p = intake_path(r, slug)
    if not p.exists():
        die(f"no live intake record: {slug}")
    return p


def doc(fm_pairs, body):
    return "\n".join(["---"] + [f"{k}: {H.render_value(v)}" if H.render_value(v) != "" else f"{k}:"
                                for k, v in fm_pairs] + ["---", "", body, ""])


# --------------------------------------------------------------------------- intake commands

def new_intake(r, slug, title, source, objective, route, status="captured", captured=None,
               extra=(), kind="item", depends_on=(), related=(), locks=(), inputs=(), backlog=()):
    p = intake_path(r, slug)
    if p.exists() or intake_path(r, slug, True).exists():
        die(f"intake already exists: {slug}")
    pairs = [("note_type", "intake"), ("kind", kind), ("status", status),
             ("captured", captured or H.today()), ("source", source), ("objective", objective),
             ("route", route), ("depends_on", list(depends_on)), ("related", list(related)),
             ("locks", list(locks)), ("inputs", list(inputs)), ("backlog", list(backlog))] + list(extra)
    H.write_text(p, doc(pairs, f"# {title}"))
    return p


def cmd_capture(a):
    r = root()
    need_slug(a.slug)
    recs = H.load_records(r)
    check_route(a.route, recs)
    new_intake(r, a.slug, a.title, a.source, a.objective, a.route)
    print(f"captured intake:{a.slug}")


def cmd_triage(a):
    r = root()
    p = get_live(r, a.slug)
    recs = H.load_records(r)
    rid = f"intake:{a.slug}"
    fm = recs[rid]["fm"]
    if fm.get("status") not in ("captured", "triaged"):
        die(f"cannot triage a {fm.get('status')} record")
    check_route(a.route, recs)
    dep, rel, locks = listflag(a.depends_on), listflag(a.related), listflag(a.locks)
    inputs, backlog = listflag(a.inputs), listflag(a.backlog)
    check_ids(dep, recs, "depends_on")
    check_ids(rel, recs, "related")
    check_locks(locks, r)
    check_paths(inputs, r, "inputs")
    if not set(backlog) <= set(inputs):
        die("backlog must be a subset of inputs")
    if a.keep_until:
        check_ids([a.keep_until], recs, "keep_until")
    check_no_cycle(recs, rid, dep)
    upd = {"status": "triaged", "objective": a.objective, "route": a.route}
    for k, v in (("depends_on", dep), ("related", rel), ("locks", locks), ("inputs", inputs),
                 ("backlog", backlog)):
        if v:
            upd[k] = v
    if a.keep_until:
        upd["keep_until"] = a.keep_until
    H.fm_write(p, upd)
    print(f"triaged {rid}")


def cmd_consume(a):
    r = root()
    p = get_live(r, a.slug)
    if not UNIT_RE.match(a.by):
        die(f"--by must be a unit id (workstream:|assignment:|cadence:), got {a.by}")
    fm = H.fm_read(p)[0]
    if fm.get("status") in ("consumed", "dropped"):
        die(f"already {fm.get('status')}")
    H.fm_write(p, {"status": "consumed", "consumed_by": H._union(fm.get("consumed_by"), [a.by]),
                     "consumed": H.today()})
    print(f"consumed intake:{a.slug} by {a.by}")


def cmd_drop(a):
    r = root()
    p = get_live(r, a.slug)
    if not a.reason.strip():
        die("--reason required")
    fm = H.fm_read(p)[0]
    if fm.get("status") in ("consumed", "dropped"):
        die(f"already {fm.get('status')}")
    H.fm_write(p, {"status": "dropped", "dropped_reason": a.reason, "dropped": H.today()})
    print(f"dropped intake:{a.slug}")


def open_backlog_rows(r, paths):
    out = []
    for p in paths or []:
        f = r / p
        if f.exists():
            try:
                for row in H.backlog_parse(f)["rows"]:
                    if row["status"] == "open":
                        out.append((p, row["id"]))
            except H.HarnessError:
                pass
    return out


def archive_blockers(r, slug, recs, closing=None):
    rec = recs.get(f"intake:{slug}")
    fm = rec["fm"]
    why = []
    if fm.get("status") not in TERMINAL["intake"]:
        why.append(f"status is {fm.get('status')}, not consumed/dropped")
    for u in fm.get("consumed_by") or []:
        if UNIT_RE.match(u) and u != closing and H.unit_state(u, r) == "open":
            why.append(f"consumer still open: {u}")
    ku = fm.get("keep_until")
    if ku and not H.satisfied(ku, recs, r):
        why.append(f"keep_until unmet: {ku}")
    for p, i in open_backlog_rows(r, fm.get("backlog")):
        why.append(f"open backlog row {i} in {p}")
    return why


def _move_archive(r, slug):
    try:
        H.move_archive(r, slug)
    except H.HarnessError as e:
        die(str(e))


def do_archive(r, slug, closing=None):
    recs = H.load_records(r)
    if f"intake:{slug}" not in recs or recs[f"intake:{slug}"]["archived"]:
        die(f"no live intake record: {slug}")
    why = archive_blockers(r, slug, recs, closing)
    if why:
        die(f"cannot archive {slug}: " + "; ".join(why))
    _move_archive(r, slug)


def cmd_archive(a):
    do_archive(root(), a.slug)
    print(f"archived intake:{a.slug}")


def cmd_split(a):
    r = root()
    p = get_live(r, a.slug)
    recs = H.load_records(r)
    parent = recs[f"intake:{a.slug}"]["fm"]
    if parent.get("status") in ("consumed", "dropped"):
        die("cannot split a terminal record")
    names = listflag(a.into)
    if len(names) < 2:
        die("--into needs at least two slices")
    routes = dict(x.split("=", 1) for x in listflag(a.route))
    objs = dict(x.split("=", 1) for x in listflag(a.objective))
    for n in names:
        need_slug(n)
        if intake_path(r, f"{a.slug}-{n}").exists() or intake_path(r, f"{a.slug}-{n}", True).exists():
            die(f"child exists: {a.slug}-{n}")
    for n, rt in routes.items():
        if n not in names:
            die(f"--route names unknown slice {n}")
        check_route(rt, recs)
    status = "triaged" if parent.get("status") in ("triaged", "active") else "captured"
    kids = []
    for n in names:
        cid = f"{a.slug}-{n}"
        new_intake(r, cid, f"{cid} (split from {a.slug})",
                   f"split from intake:{a.slug} ({n})",
                   objs.get(n, parent.get("objective", "none")), routes.get(n, parent.get("route", "none")),
                   status=status, captured=str(parent.get("captured") or H.today()))
        kids.append(f"intake:{cid}")
    H.fm_write(p, {"status": "consumed", "consumed_by": H._union(parent.get("consumed_by"), kids)})
    _move_archive(r, a.slug)
    print("split into " + ", ".join(kids))


SET_SCALARS = ("kind", "captured", "source", "objective", "route", "keep_until", "dropped_reason")
SET_LISTS = ("depends_on", "related", "locks", "inputs", "backlog", "consumed_by")
KINDS = ("item", "handover")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _real_date(val, what):
    import datetime
    try:
        if not DATE_RE.match(val or ""):
            raise ValueError
        datetime.date.fromisoformat(val)
    except ValueError:
        die(f"{what} must be a real date YYYY-MM-DD, got '{val}'")


def cmd_set(a):
    """Set any non-status intake key on a live record. Everything is validated before the write."""
    r = root()
    p = get_live(r, a.slug)
    recs = H.load_records(r)
    rid = f"intake:{a.slug}"
    fm = recs[rid]["fm"]
    upd = {}
    for k in SET_SCALARS:
        v = getattr(a, k, None)
        if v is not None:
            upd[k] = v
    for k in SET_LISTS:
        v = getattr(a, k, None)
        if v is not None:
            upd[k] = listflag(v)
    if not upd:
        die("nothing to set")
    if "kind" in upd:
        check_enum(upd["kind"], KINDS, "kind")
    if "captured" in upd:
        _real_date(upd["captured"], "--captured")
    for k in ("source", "objective"):
        if k in upd and not upd[k].strip():
            die(f"--{k} cannot be empty")
    if "route" in upd:
        check_route(upd["route"], recs)
    if "depends_on" in upd:
        check_ids(upd["depends_on"], recs, "depends_on")
        check_no_cycle(recs, rid, upd["depends_on"])
    if "related" in upd:
        check_ids(upd["related"], recs, "related")
    if "locks" in upd:
        check_locks(upd["locks"], r)
    if "consumed_by" in upd:
        for u in upd["consumed_by"]:
            if not UNIT_RE.match(u):
                die(f"consumed_by must hold unit ids (workstream:|assignment:|cadence:), got {u}")
    if upd.get("keep_until"):
        check_ids([upd["keep_until"]], recs, "keep_until")
    if "inputs" in upd:
        check_paths(upd["inputs"], r, "inputs")
    if "backlog" in upd:
        check_paths(upd["backlog"], r, "backlog")
    if "inputs" in upd or "backlog" in upd:
        ins = upd.get("inputs", fm.get("inputs") or [])
        bl = upd.get("backlog", fm.get("backlog") or [])
        if not set(bl) <= set(ins):
            die("backlog must be a subset of inputs")
    H.fm_write(p, upd)
    print(f"set {rid}: {', '.join(upd)}")


# --------------------------------------------------------------------------- gates

def gate_path(r, slug):
    return cp(r) / "gates" / f"{slug}.md"


def cmd_gate(a):
    r = root()
    need_slug(a.slug)
    p = gate_path(r, a.slug)
    if a.gcmd == "set":
        if not p.exists():
            die(f"no gate: {a.slug}")
        upd = {}
        for k, flag in (("title", "title"), ("gate_type", "type"), ("who", "who"), ("criteria", "criteria"),
                        ("objective", "objective"), ("evidence", "evidence")):
            v = getattr(a, flag, None)
            if v is not None:
                upd[k] = v
        if not upd:
            die("nothing to set")
        if "gate_type" in upd:
            check_enum(upd["gate_type"], GATE_TYPES, "gate type")
        for k in ("title", "gate_type", "who", "criteria", "objective"):
            if k in upd and not upd[k].strip():
                die(f"--{'type' if k == 'gate_type' else k} cannot be empty")
        H.fm_write(p, upd)
        print(f"set gate:{a.slug}: {', '.join(upd)}")
        return
    if a.gcmd == "add":
        if p.exists():
            die(f"gate exists: {a.slug}")
        check_enum(a.type, GATE_TYPES, "gate type")
        pairs = [("note_type", "gate"), ("title", a.title), ("gate_type", a.type), ("who", a.who),
                 ("criteria", a.criteria), ("status", "open"), ("objective", a.objective or "none")]
        H.write_text(p, doc(pairs, f"# {a.title}"))
        print(f"gate:{a.slug} added")
        return
    if not p.exists():
        die(f"no gate: {a.slug}")
    fm = H.fm_read(p)[0]
    if fm.get("status") != "open":
        die(f"gate is {fm.get('status')}, not open")
    if a.gcmd == "resolve":
        if not a.evidence.strip():
            die("--evidence required")
        H.fm_write(p, {"status": "done", "resolved": H.today(), "evidence": a.evidence})
    else:
        if not a.reason.strip():
            die("--reason required")
        H.fm_write(p, {"status": "dropped", "resolved": H.today(), "evidence": a.reason})
    print(f"gate:{a.slug} {a.gcmd}d" if a.gcmd == "resolve" else f"gate:{a.slug} dropped")


# --------------------------------------------------------------------------- backlog

def cmd_backlog(a):
    r = root()
    path = Path(a.path)
    if not path.is_absolute():
        path = r / path
    if not path.exists():
        die(f"no such file: {a.path}")
    try:
        if a.done:
            H.backlog_tick(path, a.done, "done")
        elif a.drop:
            if not (a.reason or "").strip():
                die("--drop requires --reason")
            H.backlog_tick(path, a.drop, "dropped", note=a.reason)
        elif a.move:
            if not a.to:
                die("--move requires --to")
            tgt = a.to
            if not (ROUTE_RE.match(tgt) and tgt != "none") and not UNIT_RE.match(tgt):
                die(f"bad --to target: {tgt}")
            recs = H.load_records(r)
            if tgt.startswith("milestone:") and tgt[10:] not in recs:
                die(f"unresolved target {tgt}")
            rel = path.resolve().relative_to(r.resolve()).as_posix()
            parts = rel.split("/")
            producer = parts[1] if len(parts) > 2 and parts[0] == "outputs" else path.parent.name
            H.backlog_tick(path, a.move, "moved", route=tgt)
            row = next(x for x in H.backlog_parse(path)["rows"] if x["id"] == a.move)
            H.write_handover(r, producer, tgt, f"moved backlog row {a.move}: {row['item']}",
                             inputs=[rel], backlog=[], objective="none")
    except H.HarnessError as e:
        die(str(e))
    bl = H.backlog_parse(path)
    counts = H.backlog_counts(bl["rows"])
    if a.json:
        rel = path.resolve().relative_to(r.resolve()).as_posix() if path.resolve().is_relative_to(r.resolve()) \
            else str(path)
        rows = [{k: x[k] for k in ("id", "item", "status", "route")} for x in bl["rows"]]
        print(json.dumps(H.envelope("backlog", path=rel, counts=counts, rows=rows), indent=2))
    else:
        print(" ".join(f"{k}={v}" for k, v in counts.items()))


# --------------------------------------------------------------------------- list / check

def rec_row(rec, r):
    fm = rec["fm"]
    return {"id": rec["id"], "kind": rec["kind"], "status": fm.get("status"), "title": H.record_title(rec),
            "objective": fm.get("objective") or (rec["id"].split("#")[0] if rec["kind"] == "milestone" else "none"),
            "route": fm.get("route", ""), "depends_on": fm.get("depends_on") or [],
            "related": fm.get("related") or [], "locks": fm.get("locks") or [],
            "inputs": fm.get("inputs") or [], "backlog": fm.get("backlog") or [],
            "path": rec["path"].resolve().relative_to(r.resolve()).as_posix()}


def cmd_list(a):
    r = root()
    rows = []
    for rec in H.load_records(r).values():
        row = rec_row(rec, r)
        if a.objective and row["objective"] != a.objective:
            continue
        if a.status and row["status"] != a.status:
            continue
        if a.kind and row["kind"] != a.kind:
            continue
        rows.append(row)
    rows.sort(key=lambda x: x["id"])
    if a.json:
        print(json.dumps(H.envelope("list", records=rows), indent=2))
    else:
        for x in rows:
            print(f"{x['id']} · {x['status']} · {x['route'] or x['title']}")


def rel_path(r, p):
    try:
        return Path(p).resolve().relative_to(r.resolve()).as_posix()
    except ValueError:
        return str(p)


def run_check(r):
    errors, warnings = [], []

    def err(code, rec, msg):
        errors.append({"code": code, "id": rec["id"], "path": rec_row(rec, r)["path"], "message": msg})

    def warn(code, rec, msg):
        warnings.append({"code": code, "id": rec["id"], "path": rec_row(rec, r)["path"], "message": msg})

    dups = []
    recs = H.load_records(r, dups)
    for rid, kept, lost in dups:
        errors.append({"code": "duplicate-id", "id": rid, "path": rel_path(r, lost),
                       "message": f"duplicate record id {rid}: {rel_path(r, kept)} and {rel_path(r, lost)}"})
    reg = H.load_locks(r)
    for n, l in reg.items():
        if l["probe"].split(":")[0] != "git-dirty":
            errors.append({"code": "unknown-probe", "id": f"lock:{n}", "path": "control-plane/locks.md",
                           "message": f"unknown probe kind '{l['probe']}'"})
    for rid, rec in sorted(recs.items()):
        fm, kind = rec["fm"], rec["kind"]
        st = fm.get("status")
        for k in REQUIRED[kind]:
            if k not in fm:
                err("missing-key", rec, f"missing key {k}")
        if st not in STATUS[kind]:
            err("bad-status", rec, f"bad status '{st}'")
        if kind == "gate" and fm.get("gate_type") not in GATE_TYPES:
            err("bad-gate-type", rec, f"bad gate_type '{fm.get('gate_type')}'")
        for k in fm:
            if k not in KEYS[kind]:
                warn("unknown-key", rec, f"unknown key {k}")
        if kind == "intake":
            route = fm.get("route", "")
            if not ROUTE_RE.match(str(route)):
                err("bad-route", rec, f"bad route '{route}'")
            elif str(route).startswith("milestone:") and route[10:] not in recs:
                err("unresolved-id", rec, f"route target missing: {route}")
        for k in ("depends_on", "related", "fed_by", "consumed_by"):
            for i in fm.get(k) or []:
                if not ID_RE.match(str(i)) or (not UNIT_RE.match(str(i)) and i not in recs):
                    err("unresolved-id", rec, f"{k}: {i}")
        for i in fm.get("depends_on") or []:
            t = recs.get(i)
            if t and t["fm"].get("status") == "dropped" and str(t["fm"].get("conditional")).lower() != "true":
                err("dropped-dependency", rec, f"depends on dropped non-conditional {i}")
        for n in fm.get("locks") or []:
            if n not in reg:
                err("unknown-lock", rec, f"lock not in registry: {n}")
        ins = fm.get("inputs") or []
        for p in ins:
            if not rec["archived"] and not (r / p).exists():  # archived inputs are history; the unit may have deleted them
                err("missing-input", rec, f"inputs path missing: {p}")
        for p in fm.get("backlog") or []:
            if p not in ins:
                err("backlog-not-in-inputs", rec, f"backlog {p} not in inputs")
        if st in ("consumed", "done"):
            for p, i in open_backlog_rows(r, fm.get("backlog")):
                err("open-backlog", rec, f"{st} but row {i} open in {p}")
        if kind == "intake":
            term = st in TERMINAL["intake"]
            if not rec["archived"] and term:
                warn("live-terminal", rec, f"{st} but still live (archive pending)")
            if rec["archived"] and not term:
                err("archived-nonterminal", rec, f"archived with status {st}")
        if st == "dropped" and kind == "intake" and not fm.get("dropped_reason"):
            err("dropped-no-reason", rec, "dropped without dropped_reason")
    cyc = H.find_cycle(H.build_graph(recs))
    if cyc:
        errors.append({"code": "cycle", "id": cyc[0], "path": "", "message": " -> ".join(cyc)})
    return errors, warnings


def cmd_check(a):
    if a.inputs:
        return cmd_check_inputs(a)
    r = root()
    errors, warnings = run_check(r)
    if a.strict:
        errors, warnings = errors + [dict(w, code=w["code"]) for w in warnings], []
    if a.json:
        print(json.dumps(H.envelope("check", errors=errors, warnings=warnings), indent=2))
    else:
        for e in errors:
            print(f"ERROR {e['code']} {e['id']}: {e['message']}")
        for w in warnings:
            print(f"warn  {w['code']} {w['id']}: {w['message']}")
        if not errors and not warnings:
            print("ok")
    sys.exit(1 if errors else 0)


# --------------------------------------------------------------------------- render (R10 intake-queue)

QUEUE_HEADING = "## Live Queue"


def queue_text(r):
    recs = H.load_records(r)
    groups = {}
    for rid, rec in recs.items():
        if rec["kind"] != "intake" or rec["archived"]:
            continue
        fm = rec["fm"]
        groups.setdefault(str(fm.get("objective") or "none"), {}).setdefault(str(fm.get("route") or "none"), []).append(rec)
    if not groups:
        return "*(none)*\n"
    out = []
    for obj in sorted(groups):
        out += [f"### {obj}", ""]
        for route in sorted(groups[obj]):
            out += [f"#### {route}", ""]
            for rec in sorted(groups[obj][route], key=lambda x: x["id"]):
                fm = rec["fm"]
                wait = [d for d in fm.get("depends_on") or [] if not H.satisfied(d, recs, r)]
                nxt = ("waits on " + ", ".join(wait)) if wait else "ready"
                out.append(f"- {rec['id']} · {fm.get('status')} · {route} · next: {nxt}")
            out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def cmd_render(a):
    r = root()
    path = cp(r) / "intake" / "index.md"
    if not path.exists():
        die("control-plane/intake/index.md not found")
    if a.resolve:
        views, outside = H.resolve_conflicted_regions(path)
        for v in views:
            print(f"{v}: conflict dropped, re-rendering")
        if outside:
            print("warning: conflict markers outside generated regions left alone (lines "
                  + ", ".join(map(str, outside)) + ")", file=sys.stderr)
    try:
        st = H.render_view(path, "intake-queue", queue_text(r), QUEUE_HEADING, force=a.force,
                           adopt=a.adopt, check=a.check)
    except H.RegionEdited as e:
        die(f"{e}")
    print(f"intake-queue: {st}")
    if a.check and st == "stale":
        sys.exit(1)


# --------------------------------------------------------------------------- inputs liveness (R12)

REF_RE = re.compile(r"(?:^|[^A-Za-z0-9_-])(?:control-plane[/\\])?outputs[/\\][^\s\"'`)\]>|,;]*")
FOLDER_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".obsidian"}
TERMINAL_ST = ("consumed", "dropped", "done")
UNIT_DIRS = ("workstreams", "assignments", "cadences")


def _skip_path(rel):
    """Referrer paths that are history, scratch or fixtures: never a liveness signal."""
    if rel.startswith("tools/tests/") or rel.startswith("outputs/"):
        return True
    if rel.startswith("control-plane/intake/") or "/milestones/" in rel and rel.startswith("control-plane/"):
        return True        # record inputs are read by the (a) pass, which honours terminal status
    if rel.startswith(("control-plane/intake/_archive/", "control-plane/objectives/_archive/",
                       "control-plane/workstreams/_log/")):
        return True
    if rel in ("control-plane/assignments/_log.md", "control-plane/cadences/_log.md"):
        return True
    parts = rel.split("/")
    if len(parts) >= 4 and parts[0] == "control-plane" and parts[1] in UNIT_DIRS and not parts[2].startswith("_"):
        # Inside a unit folder only index.md is a referrer: its inputs/intake_source frontmatter is the
        # unit's real relation. Planning prose (request, research, design, blueprint, logs) quotes paths
        # without consuming them.
        return not (len(parts) == 4 and parts[3] == "index.md")
    return "/_working/" in rel or "/_archive/" in rel and rel.startswith("control-plane/")


def _walk_refs(root_, subs):
    for sub in subs:
        base = root_ / sub
        if not base.exists():
            continue
        for dp, dns, fns in __import__("os").walk(base):
            dns[:] = [d for d in dns if d not in SKIP_DIRS]
            for fn in fns:
                f = Path(dp) / fn
                try:
                    txt = f.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                rel = f.relative_to(root_).as_posix()
                for m in REF_RE.finditer(txt):
                    yield rel, m.group(0)


def _rg_refs(root_, subs):
    import shutil
    exe = shutil.which("rg")
    if not exe:
        return None
    subs = [s for s in subs if (root_ / s).exists()]
    if not subs:
        return []
    cmd = [exe, "--no-heading", "-n", "--no-ignore", "--hidden", "--color", "never", "-o", "-e", REF_RE.pattern,
           "-g", "!.git", "-g", "!__pycache__", "-g", "!node_modules", "-g", "!.obsidian", "--"] + subs
    try:
        res = subprocess.run(cmd, cwd=root_, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if res.returncode not in (0, 1):
        return None
    out = []
    for ln in res.stdout.splitlines():
        parts = ln.split(":", 2)
        if len(parts) == 3:
            out.append((parts[0].replace("\\", "/"), parts[2]))
    return out


def scan_refs(root_, use_rg=None):
    """[(referrer_rel_path, matched text)] over control-plane/, tools/, .claude/, knowledge/vault/.
    ripgrep when on PATH (and not disabled), else os.walk."""
    import os
    subs = ["control-plane", "tools", ".claude", "knowledge/vault"]
    if use_rg is None:
        use_rg = not os.environ.get("HARNESS_NO_RG")
    hits = _rg_refs(root_, subs) if use_rg else None
    if hits is None:
        hits = list(_walk_refs(root_, subs))
    return [(p, t) for p, t in hits if not _skip_path(p)]


def _index_rows(root_):
    """-> (rows {folder: keep}, has_index). Rows are data rows of any table in outputs/index.md;
    the folder is the first cell, Keep is the cell under a `Keep` header (blank when absent)."""
    p = root_ / "outputs" / "index.md"
    if not p.exists():
        return None
    lines = p.read_text(encoding="utf-8").splitlines()
    rows, hdr = {}, None
    for i, ln in enumerate(lines):
        cells = H._cells(ln)
        if not cells:
            hdr = None
            continue
        nxt = H._cells(lines[i + 1]) if i + 1 < len(lines) else []
        if nxt and all(re.fullmatch(r":?-{1,}:?", c) for c in nxt if c):
            hdr = [c.lower() for c in cells]
            continue
        if all(re.fullmatch(r":?-{1,}:?", c) for c in cells if c) or hdr is None:
            continue
        first = re.sub(r"^\[([^\]]*)\]\([^)]*\)$", r"\1", cells[0]).strip("`* ").replace("\\", "/")
        first = re.sub(r"^(?:control-plane/)?outputs/", "", first).strip("/")
        first = re.sub(r"^_archive/", "", first).strip("/")
        if not FOLDER_OK.match(first):
            continue
        keep = cells[hdr.index("keep")].strip("`* ").lower() if "keep" in hdr and hdr.index("keep") < len(cells) else ""
        rows[first] = keep
    return rows


def inputs_check(r, use_rg=None):
    """R12: -> {"live": [{folder, reasons}], "defects": [...]}."""
    out_dir = r / "outputs"
    top = {d.name for d in out_dir.iterdir() if d.is_dir() and d.name != "_archive"} if out_dir.is_dir() else set()
    arch_dir = out_dir / "_archive"
    arch = {d.name for d in arch_dir.iterdir() if d.is_dir()} if arch_dir.is_dir() else set()
    live, defects, seen = {}, [], set()

    def classify(ref, who, kind):
        folder, archived, defect = H.norm_outputs_ref(ref)
        if defect and (who, defect, ref) not in seen:
            seen.add((who, defect, ref))
            defects.append({"code": defect, "folder": folder or "", "ref": who,
                            "message": f"{ref.strip()} (use workspace-root outputs/, not control-plane/outputs/)"})
        if not folder or not FOLDER_OK.match(folder):
            return
        if folder in top and not archived:
            reason = who
            live.setdefault(folder, [])
            if reason not in live[folder]:
                live[folder].append(reason)
        elif folder in arch and archived:
            return          # explicit outputs/_archive/<f> link: a valid pointer to history, not a live input
        elif folder in arch:
            key = (who, "archived-live", folder)   # pre-move live path that now resolves only under _archive/
            if key not in seen:
                seen.add(key)
                defects.append({"code": "archived-live", "folder": folder, "ref": who,
                                "message": f"live surface references outputs/_archive/{folder}"})
        else:
            key = (who, "absent", folder)
            if key not in seen:
                seen.add(key)
                defects.append({"code": "absent", "folder": folder, "ref": who,
                                "message": f"outputs/{folder} does not exist"})

    # (a) inputs on non-terminal records and open units
    for rid, rec in sorted(H.load_records(r).items()):
        if rec["archived"] or rec["fm"].get("status") in TERMINAL_ST or rec["kind"] == "gate":
            continue
        for p in rec["fm"].get("inputs") or []:
            classify(str(p), rid, "inputs")
    for d in UNIT_DIRS:
        base = cp(r) / d
        if not base.is_dir():
            continue
        for idx in sorted(base.glob("*/index.md")):
            if idx.parent.name.startswith("_"):
                continue
            fm = H.fm_read(idx)[0]
            if fm.get("status", "active") not in ("active", "paused"):
                continue
            uid = f"{d[:-1]}:{idx.parent.name}"
            for p in fm.get("inputs") or []:
                classify(str(p), uid, "inputs")
    # (b) references from tools/, .claude/, knowledge/vault/ and live control-plane surfaces
    for rel, text in scan_refs(r, use_rg):
        classify(text, f"ref:{rel}", "ref")
    # (c) Keep column, and row <-> disk diff
    rows = _index_rows(r)
    if rows is not None:
        for folder, keep in rows.items():
            if keep in ("tool", "permanent") and folder in top:
                live.setdefault(folder, []).append(f"keep:{keep}")
        disk = top | arch
        for f in sorted(disk - set(rows)):
            defects.append({"code": "missing-row", "folder": f, "ref": "outputs/index.md",
                            "message": f"outputs/{f} has no row in outputs/index.md"})
        for f in sorted(set(rows) - disk):
            defects.append({"code": "extra-row", "folder": f, "ref": "outputs/index.md",
                            "message": f"outputs/index.md row for {f}, but no such folder"})
    order = lambda x: (0 if not x.startswith(("ref:", "keep:")) else 1 if x.startswith("ref:") else 2, x)
    return {"live": [{"folder": f"outputs/{f}", "reasons": sorted(rs, key=order)} for f, rs in sorted(live.items())],
            "defects": defects}


def cmd_check_inputs(a):
    res = inputs_check(root())
    if a.json:
        print(json.dumps(H.envelope("inputs", **res), indent=2))
    else:
        for x in res["live"]:
            print(f"live  {x['folder']}: {', '.join(x['reasons'])}")
        for d in res["defects"]:
            print(f"DEFECT {d['code']} {d['folder']} ({d['ref']}): {d['message']}")
        if not res["live"] and not res["defects"]:
            print("ok")
    sys.exit(1 if res["defects"] else 0)


# --------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(prog="intake.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *args, **flags):
        p = sub.add_parser(name)
        for x in args:
            p.add_argument(x)
        for f, kw in flags.items():
            p.add_argument("--" + f.replace("_", "-"), **kw)
        p.set_defaults(fn=fn)
        return p

    rep = {"action": "append"}
    add("capture", cmd_capture, "slug", title={"required": True}, source={"required": True},
        objective={"default": "none"}, route={"default": "none"})
    add("triage", cmd_triage, "slug", objective={"required": True}, route={"required": True},
        depends_on=rep, related=rep, locks=rep, inputs=rep, backlog=rep, keep_until={})
    add("consume", cmd_consume, "slug", by={"required": True})
    add("drop", cmd_drop, "slug", reason={"required": True})
    add("archive", cmd_archive, "slug")
    add("split", cmd_split, "slug", into={"required": True, "action": "append"}, route=rep, objective=rep)
    add("set", cmd_set, "slug", kind={}, captured={}, source={}, objective={}, route={}, keep_until={},
        dropped_reason={}, depends_on=rep, related=rep, locks=rep, inputs=rep, backlog=rep, consumed_by=rep)
    add("backlog", cmd_backlog, "path", json={"action": "store_true"}, done={}, drop={}, move={},
        reason={}, to={})
    g = sub.add_parser("gate")
    gs = g.add_subparsers(dest="gcmd", required=True)
    for n in ("add", "resolve", "drop", "set"):
        p = gs.add_parser(n)
        p.add_argument("slug")
        if n == "add":
            for f in ("title", "type", "who", "criteria"):
                p.add_argument("--" + f, required=True)
            p.add_argument("--objective")
        elif n == "set":
            for f in ("title", "type", "who", "criteria", "objective", "evidence"):
                p.add_argument("--" + f)
        elif n == "resolve":
            p.add_argument("--evidence", required=True)
        else:
            p.add_argument("--reason", required=True)
        p.set_defaults(fn=cmd_gate)
    add("list", cmd_list, objective={}, status={}, kind={}, json={"action": "store_true"})
    add("check", cmd_check, strict={"action": "store_true"}, json={"action": "store_true"},
        inputs={"action": "store_true"})
    add("render", cmd_render, check={"action": "store_true"}, force={"action": "store_true"},
        adopt={"action": "store_true"},
        resolve={"action": "store_true",
                 "help": "drop both sides of a git conflict inside a generated region, then re-render it"})
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
