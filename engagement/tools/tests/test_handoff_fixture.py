#!/usr/bin/env python3
"""Gate item 5a: the producer -> handover -> receiver fixture (blueprint step 3.3).

Temp workspace with objective `obj` (record mode), producer workstream `prod` and receiver
assignment `recv`. Every command is a real CLI call (subprocess, WORKSPACE_ROOT).
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wsfix import WSBase  # noqa: E402
import harnesslib as H  # noqa: E402

WS, AS, IN = "workstream.py", "assignment.py", "intake.py"
GAPS = "outputs/prod/gaps.md"
HANDOVER = ("- handover: assignment:recv — work the gaps; "
            f"inputs: {GAPS}; backlog: {GAPS}")


class TestHandoffFixture(WSBase):
    def setUp(self):
        super().setUp()
        self.backlog_file(GAPS)                                   # step 1: 3-row backlog
        self.ok(WS, "create", "prod", "--parent", "objectives/obj")

    def rows(self):
        return {r["id"]: r for r in H.backlog_parse(self.root / GAPS)["rows"]}

    # -- (i) receiver not yet open
    def test_receiver_not_open_generates_handover_intake(self):
        self.residuals(WS, "prod", HANDOVER)
        self.ok(WS, "complete", "prod")                           # step 2
        fm = self.ifm("prod-handover-1")
        self.assertEqual(fm["kind"], "handover")
        self.assertEqual(fm["status"], "triaged")
        self.assertEqual(fm["route"], "assignment:recv")
        self.assertEqual(fm["inputs"], [GAPS])
        self.assertEqual(fm["backlog"], [GAPS])
        self.ok(AS, "create", "recv", "--intake-source", "intake:prod-handover-1")
        recv = self.ufm(AS, "recv")
        self.assertEqual(recv["inputs"], [GAPS])
        self.assertEqual(recv["backlog"], [GAPS])
        self.assertEqual(self.ifm("prod-handover-1")["status"], "active")

    # -- (ii) receiver already open
    def test_receiver_already_open_appends_and_creates_no_intake(self):
        self.ok(AS, "create", "recv")
        self.residuals(WS, "prod", HANDOVER)
        self.ok(WS, "complete", "prod")
        recv = self.ufm(AS, "recv")
        self.assertEqual(recv["inputs"], [GAPS])
        self.assertEqual(recv["backlog"], [GAPS])
        self.assertEqual(list((self.cp / "intake").glob("*handover*")), [], "no intake file may be created")

    # -- step 3: the handover record carries the outputs path (visible through `list`)
    def test_handover_record_lists_the_outputs_path(self):
        self.residuals(WS, "prod", HANDOVER)
        self.ok(WS, "complete", "prod")
        env = json.loads(self.ok(IN, "list", "--json", "--kind", "intake"))
        rec = next(r for r in env["records"] if r["id"] == "intake:prod-handover-1")
        self.assertIn(GAPS, rec["inputs"])
        self.assertIn(GAPS, rec["backlog"])
        code, out, err = self.run_(IN, "check")
        self.assertEqual(code, 0, out + err)

    def test_check_inputs_lists_outputs_prod_live_with_record_id(self):
        self.residuals(WS, "prod", HANDOVER)
        self.ok(WS, "complete", "prod")
        env = json.loads(self.ok(IN, "check", "--inputs", "--json"))
        live = {x["folder"]: x["reasons"] for x in env["live"]}
        self.assertIn("intake:prod-handover-1", live["outputs/prod"])

    # -- steps 4-6: the receiver cannot close until the backlog is resolved
    def test_receiver_close_gated_by_backlog_then_moves_and_archives(self):
        self.residuals(WS, "prod", HANDOVER)
        self.ok(WS, "complete", "prod")
        self.ok(AS, "create", "recv", "--intake-source", "intake:prod-handover-1")
        self.residuals(AS, "recv", "- none")

        self.refused(AS, "complete", "recv", text="open backlog row")            # 3 open
        self.ok(IN, "backlog", GAPS, "--done", "r1")
        self.refused(AS, "complete", "recv", text="open backlog row")            # r2, r3 open
        self.ok(IN, "backlog", GAPS, "--drop", "r2", "--reason", "x")
        self.refused(AS, "complete", "recv", text="open backlog row r3")         # r3 open

        # step 5: move r3 out; recv may now close
        self.ok(IN, "backlog", GAPS, "--move", "r3", "--to", "candidate:workstream")
        rows = self.rows()
        self.assertEqual(rows["r3"]["status"], "moved")
        self.assertEqual(rows["r3"]["route"], "candidate:workstream")
        moved = self.ifm("prod-handover-2")
        self.assertEqual(moved["route"], "candidate:workstream")
        self.assertEqual(moved["inputs"], [GAPS])
        self.assertEqual(moved["backlog"], [])

        self.ok(AS, "complete", "recv")
        self.assertEqual(self.rows()["r3"]["route"], "candidate:workstream")

        # step 6: the handover intake is consumed and archived
        self.assertFalse((self.cp / "intake" / "prod-handover-1.md").exists())
        done = self.ifm("prod-handover-1", archived=True)
        self.assertEqual(done["status"], "consumed")
        self.assertEqual(done["consumed_by"], ["assignment:recv"])
        # the moved-row handover is still live and untouched
        self.assertEqual(self.ifm("prod-handover-2")["status"], "triaged")


if __name__ == "__main__":
    unittest.main(verbosity=2)
