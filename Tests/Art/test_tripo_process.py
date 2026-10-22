"""Offline checks for paid processing; no real API or credentials are used."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("tripo_process", ROOT / "Tools/submit_tripo_process.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class ProcessingBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.art = self.root / "RawAssets/Art/Tripo_v01"
        self.art.mkdir(parents=True)
        self.source = self.art / "source.glb"
        self.source.write_bytes(b"reviewed mesh")
        self.review = self.art / "review.json"
        self.review.write_text("{}")
        self.spec_path = self.art / "spec.json"
        self.spec = {"asset_id": "Unit_Test", "version": "rig_v1", "operation": "rig",
                     "approved_for_processing": True, "expected_credits": 25,
                     "source_file": self.source.relative_to(self.root).as_posix(),
                     "source_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
                     "review_file": self.review.relative_to(self.root).as_posix(),
                     "arguments": ["--spec", "unreal"]}
        self.spec_path.write_text(json.dumps(self.spec))
        self.output = self.art / "tripo_raw/Unit_Test/rig_v1"
        for target, value in (("ROOT", self.root), ("ART", self.art)):
            patcher = patch.object(runner, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(runner.subprocess, "run")
        self.run_cli = patcher.start()
        self.addCleanup(patcher.stop)

    def balance(self, amount=100):
        return subprocess.CompletedProcess([], 0, json.dumps({"balance": amount, "frozen": 0}), "")

    def test_dry_plan_has_no_external_call(self):
        runner.plan(self.spec_path)
        self.run_cli.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_changed_mesh_rejects_before_spend(self):
        self.source.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            runner.plan(self.spec_path)
        self.run_cli.assert_not_called()

    def test_low_balance_does_not_write_intent(self):
        item = runner.plan(self.spec_path)
        self.run_cli.return_value = self.balance(24)
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            runner.submit(item)
        self.assertEqual(1, self.run_cli.call_count)
        self.assertFalse(self.output.exists())

    def test_concurrent_receipt_blocks_paid_call(self):
        item = runner.plan(self.spec_path)
        def arrive(*args, **kwargs):
            self.output.mkdir(parents=True)
            (self.output / "submission.json").write_text('{"task_id":"existing"}')
            return self.balance()
        self.run_cli.side_effect = arrive
        with self.assertRaisesRegex(ValueError, "reconcile"):
            runner.submit(item)
        self.assertEqual(1, self.run_cli.call_count)

    def test_timeout_keeps_lock_and_prevents_resubmission(self):
        item = runner.plan(self.spec_path)
        self.run_cli.side_effect = [self.balance(), subprocess.TimeoutExpired("cli", 240)]
        with self.assertRaises(subprocess.TimeoutExpired):
            runner.submit(item)
        self.assertTrue((self.output / "submission.uncertain.json").exists())
        self.assertEqual(b"reviewed mesh", (self.output / "inputs/input.glb").read_bytes())
        self.assertEqual([], list(self.output.glob("*.glb")))
        with self.assertRaisesRegex(ValueError, "reconcile"):
            runner.plan(self.spec_path)


if __name__ == "__main__":
    unittest.main()
