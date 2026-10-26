"""Observation metadata must not silently certify compatibility or freshness."""
import importlib.util
import json
from datetime import date
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "currency", Path(__file__).resolve().parents[2] / "scripts/currency.py")
currency = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(currency)


class ObservationTests(unittest.TestCase):
    def report(self, **extra):
        pin = {"identity": "draft", "pinned_version": "retained-contract",
               "checked_at": "2026-06-12", "staleness_window_days": 7,
               **extra}
        return currency.build_report({"pins": [pin]}, date(2026, 10, 26))[0]

    def test_recent_observation_does_not_refresh_contract(self):
        observation = {"observed_at": "2026-10-26T19:46:51Z",
                       "value": "new-draft", "outcome": "observed",
                       "evidence": "docs/evidence.json#draft"}
        disposition = {"status": "pending", "reason": "compatibility not established"}
        row = self.report(pin_kind="compatibility-reference",
                          latest_observation=observation,
                          review_disposition=disposition)
        self.assertEqual(row["latest_observation"], observation)
        self.assertEqual(row["review_disposition"], disposition)
        self.assertEqual(row["pin_kind"], "compatibility-reference")
        self.assertEqual(row["pinned_version"], "retained-contract")
        self.assertEqual(row["checked_at"], "2026-06-12")
        self.assertEqual(row["status"], "stale")

    def test_indeterminate_evidence_remains_visible_and_stale(self):
        row = self.report(latest_observation={"observed_at": "2026-10-26", "outcome": "indeterminate",
                                             "value": "extractor unavailable", "evidence": "docs/evidence.json"},
                          review_disposition={"status": "indeterminate", "reason": "missing sentinel"})
        self.assertEqual(row["latest_observation"]["outcome"], "indeterminate")
        self.assertEqual(row["review_disposition"]["status"], "indeterminate")
        self.assertEqual(row["status"], "stale")

    def test_legacy_rows_do_not_invent_an_observation(self):
        row = self.report()
        for key in ("latest_observation", "review_disposition", "pin_kind"):
            self.assertNotIn(key, row)
        self.assertEqual(row["status"], "stale")

    def test_cli_exposes_pending_observation_without_mutating_input(self):
        datum = {"pins": [{"identity": "example", "pinned_version": "old",
                           "checked_at": "2020-01-01",
                           "latest_observation": {"observed_at": "2026-10-26",
                                                  "outcome": "observed", "value": "new",
                                                  "evidence": "docs/evidence.json"},
                           "review_disposition": {"status": "pending", "reason": "needs comparison"}}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pins.json"
            original = json.dumps(datum).encode()
            path.write_bytes(original)
            args = [sys.executable, currency.__file__, "--pins", str(path), "--today", "2026-10-26"]
            text = subprocess.run(args, capture_output=True, text=True, check=True)
            self.assertIn("observed 2026-10-26: observed — new", text.stdout)
            self.assertIn("disposition pending: needs comparison", text.stdout)
            self.assertIn("PAST SLA", text.stdout)
            report = json.loads(subprocess.check_output(args + ["--json"]))
            self.assertEqual(report["stale_count"], 1)
            self.assertTrue(report["advisory"])
            self.assertEqual(report["pins"][0]["pinned_version"], "old")
            self.assertEqual(path.read_bytes(), original)

    def test_malformed_metadata_is_input_error_in_both_modes_before_any_output(self):
        good = {"observed_at": "2026-10-26", "outcome": "observed", "value": "new",
                "evidence": "docs/evidence.json"}
        cases = [{"latest_observation": v} for v in ("pending", ["pending"], None, False, {})]
        cases += [{"review_disposition": v} for v in ("pending", [], None, {}, {"status": "pending"})]
        cases += [{"pin_kind": v} for v in ("invented", [], None)]
        cases += [{"review_disposition": {"status": "approved", "reason": "x"}}]
        cases += [{"latest_observation": {k: v for k, v in good.items() if k != field}}
                  for field in good]
        cases += [{"latest_observation": {**good, key: value}} for key, value in (
            ("outcome", "compatible"), ("observed_at", "not-a-date"), ("evidence", "../elsewhere"),
            ("evidence", "/absolute"), ("evidence", "https://example.com/record"),
            ("evidence_identity", []))]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pins.json"
            for metadata in cases:
                path.write_text(json.dumps({"pins": [self.report(), {"identity": "bad", **metadata}]}))
                for mode in ([], ["--json"]):
                    with self.subTest(metadata=metadata, mode=mode):
                        result = subprocess.run([sys.executable, currency.__file__, "--pins", str(path),
                                                 "--today", "2026-10-26", *mode], capture_output=True, text=True)
                        self.assertEqual(result.returncode, 2)
                        self.assertEqual(result.stdout, "")
                        self.assertIn("currency: invalid pin metadata:", result.stderr)
                        self.assertNotIn("Traceback", result.stderr)

    def test_shipped_evidence_identity_mapping_and_retained_values(self):
        root = Path(__file__).resolve().parents[2]
        pins = json.loads((root / "schemas/currency/pins.v1.json").read_text())
        evidence = json.loads((root / "docs/currency/reverification-2026-10-26.json").read_text())
        records = {r["identity"]: r for r in evidence["identities"]}
        observed = [p for p in pins["pins"] if "latest_observation" in p]
        self.assertEqual(len(records), 18)
        self.assertEqual(len(observed), 18)
        self.assertEqual(sum(len(r["sources"]) for r in records.values()), 20)
        for pin in observed:
            record = records[pin["identity"]]
            sources = record["sources"]
            observation = pin["latest_observation"]
            self.assertEqual(observation["observed_at"], sources[0]["observed"])
            self.assertEqual(observation["value"], " | ".join(s["extracted_value"] for s in sources))
            self.assertEqual(observation["outcome"], "indeterminate" if
                             record["disposition"]["status"] == "indeterminate" else "observed")
            self.assertEqual(pin["latest_observation"]["evidence_identity"], pin["identity"])
            self.assertEqual(pin["pinned_version"], record["retained_pinned_version"])
            self.assertEqual(pin["checked_at"], record["retained_checked_at"])
            self.assertEqual(pin["review_disposition"], record["disposition"])
            self.assertEqual((root / pin["latest_observation"]["evidence"]).resolve(),
                             (root / "docs/currency/reverification-2026-10-26.json").resolve())
            for source in record["sources"]:
                self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
                self.assertGreater(source["bytes"], 0)
                self.assertEqual(source["status"], 200)
                self.assertTrue(source["url"].startswith("https://"))
                self.assertTrue(source["finalUrl"].startswith("https://"))
        self.assertEqual(sum(p["status"] == "stale" for p in currency.build_report(
            pins, date(2026, 10, 26))), 18)


if __name__ == "__main__":
    unittest.main()
