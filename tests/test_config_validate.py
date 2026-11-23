"""Tests for engagement/tools/fynapse/config_validate.py.

Run from the wb root with WORKSPACE_ROOT unset:
    python -B -m unittest discover -s tests -t .

Negative cases start from a minimal, fictional, valid bulk dict built in code and break one thing.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WB = Path(__file__).resolve().parent.parent
TOOLS = WB / "engagement" / "tools" / "fynapse"
ASSEMBLE = TOOLS / "config_assemble.py"
VALIDATE = TOOLS / "config_validate.py"
FIXTURE = WB / "fixtures" / "config-demo"


def env():
    return {k: v for k, v in os.environ.items() if k != "WORKSPACE_ROOT"}


def run(tool, cwd, name="acme"):
    return subprocess.run([sys.executable, "-B", str(tool), name], cwd=str(cwd), env=env(),
                          capture_output=True, text=True)


def text_attr(name, label=None, mandatory=False):
    return {"name": name, "label": label or name, "mandatory": mandatory,
            "type": {"typeName": "PrimitiveType", "primitive": "TEXT"}}


def base_config():
    return {
        "businessCalendars": [{"name": "Acme Business Calendar"}],
        "fiscalCalendars": [{"name": "Acme Fiscal Calendar", "type": "custom", "periods": [
            {"year": 2099, "number": 1, "startDate": "2099-01-01", "endDate": "2099-01-31"},
            {"year": 2099, "number": 2, "startDate": "2099-02-01", "endDate": "2099-02-28"},
        ]}],
        "journalTypes": [{"code": "Perm", "behavior": "PERMANENT"}],
        "journalDefinition": {"active": True, "fields": [
            {"name": "account", "label": "Account", "role": "account", "type": "text"},
            {"name": "entity", "label": "Entity", "role": "node", "type": "text"},
            {"name": "amount", "label": "Amount", "role": "transactionAmount", "type": "amount"},
        ]},
        "nodeValues": [{"fieldName": "entity", "values": ["Acme One"]}],
        "dimensionSets": [{"name": "Acme Dimensions", "attributes": ["account", "entity"]}],
        "accountingConfigurations": [{"name": "Acme Basis", "businessCalendarName": "Acme Business Calendar",
                                      "fiscalCalendarName": "Acme Fiscal Calendar",
                                      "dimensionSetName": "Acme Dimensions"}],
        "nodes": [{"fields": {"entity": "Acme One"}, "timeZone": "UTC",
                   "nodeConfigs": [{"accountingConfigName": "Acme Basis", "graceDays": 0, "graceHours": 0}]}],
        "businessEventDefinition": {"active": True, "attributes": [
            {"name": "eventCode", "label": "Event Type", "role": "event_type", "type": "text"},
            {"name": "entity", "label": "Entity", "role": "node", "type": "text"},
        ], "references": []},
        "entities": [{"namespace": "fynapse", "name": "Widget", "temporalityType": "Reference",
                      "primaryKeyAttributeNames": ["widgetId"], "attributes": [text_attr("widgetId", mandatory=True)]}],
        "businessEventTypes": [{"name": "EVT_SALE"}],
        "accounts": [{"number": "100", "name": "Cash"}, {"number": "200", "name": "Revenue"}],
        "accountLookups": [{"postingCode": "Cash", "accountLookupPatterns": [{"account": "100"}]},
                           {"postingCode": "Revenue", "accountLookupPatterns": [{"account": "200"}]}],
        "postingComponents": [{"code": "PC_SALE", "journalType": "Perm", "accountingConfigName": "Acme Basis",
                               "postingPatterns": [{"postingCode": "Cash", "debitCredit": "DR"},
                                                   {"postingCode": "Revenue", "debitCredit": "CR"}]}],
        "postingComponentIdentifications": [{"businessEventTypeName": "EVT_SALE",
                                             "postingComponents": [{"postingComponentCode": "PC_SALE"}]}],
    }


class Validate(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def check(self, cfg, export_cfg=None):
        export_cfg = base_config() if export_cfg is None else export_cfg
        for rel, cfgx in (("config/build/acme.bulk.json", cfg), ("config/instance/acme.export.json", export_cfg)):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(json.dumps({"version": "v20990101", "configuration": cfgx}).encode("utf-8"))
        return run(VALIDATE, self.root)

    def expect(self, rule, mutate, severity="error"):
        cfg = base_config()
        mutate(cfg)
        r = self.check(cfg)
        self.assertEqual(r.returncode, 1 if severity == "error" else 0, r.stdout + r.stderr)
        self.assertIn(f"{rule} {severity}:", r.stdout)
        return r

    # ---- baseline

    def test_valid_minimal(self):
        r = self.check(base_config())
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(r.stdout.strip().endswith("errors=0 warnings=0"), r.stdout)

    def test_missing_build_exit_2(self):
        r = run(VALIDATE, self.root)
        self.assertEqual(r.returncode, 2)
        self.assertIn("run config_assemble first", r.stderr)

    # ---- errors V1-V19

    def test_v1_duplicate_field_name(self):
        self.expect("V1", lambda c: c["journalDefinition"]["fields"].append(
            {"name": "account", "label": "Account 2", "role": "attribute", "type": "text"}))

    def test_v2_duplicate_field_label(self):
        self.expect("V2", lambda c: c["businessEventDefinition"]["attributes"].append(
            {"name": "other", "label": "Event Type", "role": "attribute", "type": "text"}))

    def test_v3_field_name_too_long(self):
        self.expect("V3", lambda c: c["businessEventDefinition"]["attributes"].append(
            {"name": "x" * 129, "label": "Long", "role": "attribute", "type": "text"}))

    def test_v4_entity_name_syntax(self):
        self.expect("V4", lambda c: c["entities"][0].update(name="1widget"))

    def test_v5_attribute_label_too_long(self):
        self.expect("V5", lambda c: c["entities"][0]["attributes"].append(text_attr("note", label="L" * 129)))

    def test_v6_primary_key_empty(self):
        self.expect("V6", lambda c: c["entities"][0].update(primaryKeyAttributeNames=[]))

    def test_v7_duplicate_dimension_set(self):
        self.expect("V7", lambda c: c["dimensionSets"].append(
            {"name": "Acme Dimensions Copy", "attributes": ["entity", "account"]}))

    def test_v8_account_name_too_long(self):
        self.expect("V8", lambda c: c["accounts"][0].update(name="N" * 256))

    def test_v9_grace_days_out_of_range(self):
        self.expect("V9", lambda c: c["nodes"][0]["nodeConfigs"][0].update(graceDays=32))

    def test_v10_single_posting_pattern(self):
        r = self.expect("V10", lambda c: c["postingComponents"][0].update(
            postingPatterns=c["postingComponents"][0]["postingPatterns"][:1]))
        self.assertIn("postingComponents[PC_SALE]: 1 posting pattern; minimum 2", r.stdout)
        self.assertIn("configuration-data.md:1485; put-posting-component.md:19", r.stdout)

    def test_v11_unknown_journal_type(self):
        self.expect("V11", lambda c: c["postingComponents"][0].update(journalType="Nope"))

    def test_v12_dimension_not_on_jld(self):
        self.expect("V12", lambda c: c["dimensionSets"][0]["attributes"].append("notAField"))

    def test_v13_bed_node_not_on_jld(self):
        self.expect("V13", lambda c: c["businessEventDefinition"]["attributes"].append(
            {"name": "region", "label": "Region", "role": "node", "type": "text"}))

    def test_v14_node_without_time_zone(self):
        self.expect("V14", lambda c: c["nodes"][0].pop("timeZone"))

    def test_v15_accounting_base_missing_dimension_set(self):
        self.expect("V15", lambda c: c["accountingConfigurations"][0].update(dimensionSetName="Missing"))

    def test_v16_lookup_account_not_in_accounts(self):
        self.expect("V16", lambda c: c["accountLookups"][0]["accountLookupPatterns"].append({"account": "999"}))

    def test_v17_reference_order(self):
        self.expect("V17", lambda c: c["businessEventDefinition"].update(references=[
            {"name": "second", "definition": [{"typeName": "Attribute", "attributeName": "first.code"}]},
            {"name": "first", "definition": []},
        ]))

    def test_v18_identification_unknown_bet(self):
        self.expect("V18", lambda c: c["postingComponentIdentifications"][0].update(businessEventTypeName="NOPE"))

    def test_v18_reversing_without_date(self):
        self.expect("V18", lambda c: c["journalTypes"].append({"code": "Rev", "behavior": "REVERSING"}))

    def test_v19_fiscal_period_overlap(self):
        self.expect("V19", lambda c: c["fiscalCalendars"][0]["periods"][1].update(startDate="2099-01-15"))

    def test_v19_fiscal_period_gap(self):
        self.expect("V19", lambda c: c["fiscalCalendars"][0]["periods"][1].update(startDate="2099-02-05"))

    # ---- report V20

    def test_v20_object_added(self):
        cfg = base_config()
        cfg["businessEventTypes"].append({"name": "EVT_REFUND"})
        cfg["postingComponentIdentifications"].append(
            {"businessEventTypeName": "EVT_REFUND", "postingComponents": [{"postingComponentCode": "PC_SALE"}]})
        r = self.check(cfg)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("V20 report: businessEventTypes[EVT_REFUND]: added", r.stdout)

    # ---- warnings V21-V26

    def test_v21_supported_entity_change(self):
        r = self.expect("V21", lambda c: c["entities"][0]["attributes"].append(text_attr("colour")), "warning")
        self.assertIn("non-mandatory attribute added (supported)", r.stdout)

    def test_v22_unsupported_entity_change(self):
        self.expect("V22", lambda c: c["entities"][0].update(temporalityType="Transaction"), "warning")

    def test_v23_entity_missing_from_upload(self):
        cfg = base_config()
        export = base_config()
        export["entities"].append({"namespace": "fynapse", "name": "Gadget", "temporalityType": "Reference",
                                   "primaryKeyAttributeNames": ["gadgetId"], "attributes": [text_attr("gadgetId")]})
        r = self.check(cfg, export)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("V23 warning: entities[fynapse/Gadget]", r.stdout)

    def test_v24_node_change(self):
        self.expect("V24", lambda c: c["nodes"][0].update(timeZone="Europe/Paris"), "warning")

    def test_v25_vault_entity_cap(self):
        def many(c):
            for i in range(101):
                c["entities"].append({"namespace": "fynapse", "name": f"Thing{i}", "temporalityType": "Reference",
                                      "primaryKeyAttributeNames": ["k"], "attributes": [text_attr("k")]})
        r = self.expect("V25", many, "warning")
        self.assertIn("unverified (vault)", r.stdout)

    def test_v26_vault_lookup_discriminators(self):
        r = self.expect("V26", lambda c: c["accountLookups"][0].update(accountLookupAttributeDefinition=[
            {"fieldName": f"f{i}", "matchingOrder": i} for i in range(4)]), "warning")
        self.assertIn("unverified (vault)", r.stdout)


class Fixture(unittest.TestCase):
    def test_fixture_validates_and_single_pattern_fails(self):
        with tempfile.TemporaryDirectory() as td:
            eng = Path(td) / "eng"
            shutil.copytree(FIXTURE, eng, ignore=shutil.ignore_patterns("build"))
            self.assertEqual(run(ASSEMBLE, eng, "demo").returncode, 0)
            r = run(VALIDATE, eng, "demo")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("errors=0", r.stdout)
            # gate step: first PC in the first sorted fragment cut to one posting pattern
            first = sorted((eng / "config/parts/postingComponents").glob("*.json"))[0]
            frag = json.loads(first.read_text(encoding="utf-8"))
            items = frag if isinstance(frag, list) else [frag]
            items[0]["postingPatterns"] = items[0]["postingPatterns"][:1]
            first.write_text(json.dumps(frag), encoding="utf-8")
            self.assertEqual(run(ASSEMBLE, eng, "demo").returncode, 0)
            r = run(VALIDATE, eng, "demo")
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn(f"V10 error: postingComponents[{items[0]['code']}]", r.stdout)


if __name__ == "__main__":
    unittest.main()
