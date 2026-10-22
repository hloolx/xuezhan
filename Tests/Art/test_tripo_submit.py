"""Offline paid-submission boundary tests. Never invoke Tripo, Node or a network."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("tripo_submit_under_test", ROOT / "Tools/submit_tripo_geometry.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class TripoSubmissionBoundaryTests(unittest.TestCase):
    ASSET = "OfflineTestProp"
    VERSION = "geometry_v01"
    PRESET = "h_prop_geometry"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.art = self.root / "RawAssets/Art/Tripo_v01"
        self.folder = self.art / "prepared_tripo_canonical" / self.ASSET
        self.folder.mkdir(parents=True)
        self.output = self.art / "tripo_raw" / self.ASSET / self.VERSION
        self.original_hashes = {}
        for view, color in (("front", "red"), ("left", "green"), ("back", "blue")):
            path = self.folder / (view + ".png")
            Image.new("RGB", (1024, 1024), color).save(path)
            self.original_hashes[view] = digest(path)
        self.metadata = {"files": {view: {"canonical_sha256": value}
                                  for view, value in self.original_hashes.items()}}
        self.approval = {"approved_for_geometry_pilot": True,
                         "sha256": dict(self.original_hashes), "allowed_presets": [self.PRESET]}
        write_json(self.folder / "upload_manifest.json", {
            "view_convention": "tripo_api_canonical_probe_e175fe52",
            "files": {v: v + ".png" for v in self.original_hashes},
            "project_required_views": ["front", "left", "back"]})
        write_json(self.folder / "canonical_metadata.json", self.metadata)
        write_json(self.art / "reviews/geometry_pilot_approvals.json", {"assets": {self.ASSET: self.approval}})
        write_json(self.art / "generation_presets.json", {"presets": {self.PRESET: {"parameters": {
            "model": "v3.1-20260211", "texture": False, "pbr": False}}}})
        for target, value in (("ROOT", self.root), ("ART", self.art)):
            patcher = patch.object(runner, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(runner.subprocess, "run", side_effect=AssertionError("Unexpected external CLI call"))
        self.run_cli = patcher.start()
        self.addCleanup(patcher.stop)
        # Defense in depth: a future implementation must not make HTTP calls
        # behind these mocked CLI calls, including during the dry-plan path.
        for target in ("socket.create_connection", "socket.socket"):
            patcher = patch(target, side_effect=AssertionError("Network forbidden in offline tests"))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.commands = []

    def plan(self, version=None):
        return runner.plan(self.ASSET, version or self.VERSION, self.PRESET)

    def fake_cli(self, *, balance=1000, on_balance=None, on_generate=None):
        def run(command, **kwargs):
            self.commands.append(command)
            if "balance" in command:
                if on_balance:
                    on_balance()
                return subprocess.CompletedProcess(command, 0, json.dumps({"balance": balance, "frozen": 0}), "")
            if "generate" in command:
                if on_generate:
                    on_generate(command)
                return subprocess.CompletedProcess(command, 0, json.dumps({"task_id": "offline-fake-task", "status": "queued"}), "")
            raise AssertionError("Unexpected command: " + repr(command))
        self.run_cli.side_effect = run

    def generated_commands(self):
        return [command for command in self.commands if "generate" in command]

    def single_front_review(self, **overrides):
        review = {"asset_id": self.ASSET, "version": self.VERSION, "preset": self.PRESET,
                  "approved_for_single_front_geometry": True, "reason": "Reviewed contradictory rear leaf placement",
                  "sha256": {"front": self.original_hashes["front"]}, "maximum_credits": 20}
        review.update(overrides)
        path = self.art / "reviews/single_front.json"
        write_json(path, review)
        return str(path)

    def test_single_front_requires_exact_variant_identity_and_hash(self):
        for overrides in ({"version": "different"}, {"sha256": {"front": "wrong"}},
                          {"approved_for_single_front_geometry": False}, {"reason": ""}, {"maximum_credits": 100}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    runner.plan(self.ASSET, self.VERSION, self.PRESET, self.single_front_review(**overrides))
        self.run_cli.assert_not_called()

    def test_single_front_submission_freezes_only_approved_front(self):
        planned = runner.plan(self.ASSET, self.VERSION, self.PRESET, self.single_front_review())
        self.assertEqual("image-to-model", planned["generation_type"])
        self.assertEqual({"front": self.original_hashes["front"]}, planned["sha256"])
        self.fake_cli()
        with contextlib.redirect_stdout(io.StringIO()):
            runner.submit(planned)
        command = self.generated_commands()[0]
        self.assertIn("image-to-model", command)
        self.assertNotIn("multiview-to-model", command)
        self.assertEqual(["front.png"], sorted(path.name for path in (self.output / "inputs").iterdir()))
        self.assertEqual(self.original_hashes["front"], digest(self.output / "inputs/front.png"))
        with self.assertRaises(ValueError):
            runner.plan(self.ASSET, self.VERSION, self.PRESET, self.single_front_review())

    def test_single_front_revoked_during_balance_check_never_generates(self):
        review = self.single_front_review()
        planned = runner.plan(self.ASSET, self.VERSION, self.PRESET, review)
        self.fake_cli(on_balance=lambda: self.single_front_review(approved_for_single_front_geometry=False))
        with self.assertRaises(ValueError):
            runner.submit(planned)
        self.assertEqual([], self.generated_commands())
        self.assertFalse(self.output.exists())

    def test_single_front_reason_mutation_during_balance_check_never_generates(self):
        review = self.single_front_review()
        planned = runner.plan(self.ASSET, self.VERSION, self.PRESET, review)
        self.fake_cli(on_balance=lambda: self.single_front_review(reason="Changed input rationale"))
        with self.assertRaises(ValueError):
            runner.submit(planned)
        self.assertEqual([], self.generated_commands())

    def test_downloaded_task_without_submission_receipt_blocks_generation(self):
        write_json(self.output / "task.json", {"task_id": "already-generated", "status": "success"})
        with self.assertRaisesRegex(ValueError, "reconcile"):
            self.plan()
        self.run_cli.assert_not_called()

    def test_dry_plan_is_local_and_has_no_submission_side_effects(self):
        with patch("sys.argv", ["submit_tripo_geometry.py", self.ASSET, "--version", self.VERSION, "--preset", self.PRESET]):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                runner.main()
        planned = json.loads(stdout.getvalue())
        self.assertEqual(self.original_hashes, planned["sha256"])
        self.assertEqual(["front", "left", "back"], list(planned["input_files"]))
        self.run_cli.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_changed_canonical_pixels_are_rejected_before_any_external_call(self):
        Image.new("RGB", (1024, 1024), "yellow").save(self.folder / "left.png")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.plan()
        self.run_cli.assert_not_called()

    def test_updated_metadata_cannot_reuse_approval_for_old_image_hashes(self):
        Image.new("RGB", (1024, 1024), "yellow").save(self.folder / "left.png")
        self.metadata["files"]["left"]["canonical_sha256"] = digest(self.folder / "left.png")
        write_json(self.folder / "canonical_metadata.json", self.metadata)
        with self.assertRaisesRegex(ValueError, "approval"):
            self.plan()
        self.run_cli.assert_not_called()

    def test_existing_intent_or_receipt_prevents_a_duplicate_plan(self):
        for index, filename in enumerate(("submission.intent.json", "submission.json")):
            with self.subTest(filename=filename):
                version = f"already_submitted_{index}"
                marker = self.art / "tripo_raw" / self.ASSET / version / filename
                write_json(marker, {"existing": True})
                with self.assertRaisesRegex(ValueError, "reconcile"):
                    self.plan(version)
        self.run_cli.assert_not_called()

    def test_concurrent_intent_after_planning_blocks_generate(self):
        planned = self.plan()
        marker = self.output / "submission.intent.json"
        original = {"task_started_by": "another_process"}
        self.fake_cli(on_balance=lambda: write_json(marker, original))
        with self.assertRaises((ValueError, FileExistsError)):
            runner.submit(planned)
        self.assertEqual([], self.generated_commands())
        self.assertEqual(original, json.loads(marker.read_text(encoding="utf-8")))

    def test_receipt_appearing_after_plan_is_not_overwritten_or_resubmitted(self):
        planned = self.plan()
        marker = self.output / "submission.json"
        original = {"task_id": "already-charged-task"}
        self.fake_cli(on_balance=lambda: write_json(marker, original))
        with self.assertRaises((ValueError, FileExistsError)):
            runner.submit(planned)
        self.assertEqual([], self.generated_commands())
        self.assertEqual(original, json.loads(marker.read_text(encoding="utf-8")))

    def test_receipt_appearing_when_intent_is_locked_still_blocks_generate(self):
        planned = self.plan()
        marker = self.output / "submission.json"
        original = {"task_id": "already-charged-during-lock"}
        self.fake_cli()
        real_write = runner.write
        def write_and_publish_receipt(path, data, exclusive=False):
            real_write(path, data, exclusive=exclusive)
            if path.name == "submission.intent.json":
                write_json(marker, original)
        with patch.object(runner, "write", side_effect=write_and_publish_receipt):
            with self.assertRaises(ValueError):
                runner.submit(planned)
        self.assertEqual([], self.generated_commands())
        self.assertEqual(original, json.loads(marker.read_text(encoding="utf-8")))

    def test_insufficient_balance_never_invokes_generate(self):
        planned = self.plan()
        self.fake_cli(balance=planned["expected_geometry_credits"] - 1)
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            runner.submit(planned)
        self.assertEqual([], self.generated_commands())
        self.assertFalse((self.output / "submission.intent.json").exists())

    def test_timeout_keeps_intent_and_prevents_automatic_or_manual_duplicate(self):
        planned = self.plan()
        def timeout(command):
            raise subprocess.TimeoutExpired(command, 240)
        self.fake_cli(on_generate=timeout)
        with self.assertRaises(subprocess.TimeoutExpired):
            runner.submit(planned)
        self.assertTrue((self.output / "submission.intent.json").exists())
        uncertain = json.loads((self.output / "submission.uncertain.json").read_text(encoding="utf-8"))
        self.assertIs(False, uncertain["automatic_retry"])
        self.assertFalse((self.output / "submission.json").exists())
        with self.assertRaises(ValueError):
            self.plan()
        with self.assertRaises((ValueError, FileExistsError)):
            runner.submit(planned)
        self.assertEqual(1, len(self.generated_commands()))

    def test_input_mutation_during_balance_check_cannot_use_old_approval(self):
        planned = self.plan()
        def mutate_input():
            Image.new("RGB", (1024, 1024), "yellow").save(self.folder / "left.png")
        self.fake_cli(on_balance=mutate_input)
        with self.assertRaises(ValueError):
            runner.submit(planned)
        self.assertEqual([], self.generated_commands())

    def test_approval_revocation_during_balance_check_blocks_generate(self):
        planned = self.plan()
        def revoke_approval():
            self.approval["approved_for_geometry_pilot"] = False
            write_json(self.art / "reviews/geometry_pilot_approvals.json", {"assets": {self.ASSET: self.approval}})
        self.fake_cli(on_balance=revoke_approval)
        with self.assertRaises(ValueError):
            runner.submit(planned)
        self.assertEqual([], self.generated_commands())

    def test_paid_command_reads_approved_snapshot_even_if_source_changes_at_launch(self):
        planned = self.plan()
        def check_paid_inputs(command):
            # Models are charged for the bytes read by the CLI, not for bytes
            # hashed earlier. Mutating the editable source must not change them.
            Image.new("RGB", (1024, 1024), "yellow").save(self.folder / "left.png")
            paths = command[command.index("multiview-to-model") + 1:command.index("--model")]
            actual = {Path(path).stem: digest(Path(path)) for path in paths}
            self.assertEqual(self.original_hashes, actual)
        self.fake_cli(on_generate=check_paid_inputs)
        with contextlib.redirect_stdout(io.StringIO()):
            runner.submit(planned)
        self.assertEqual(1, len(self.generated_commands()))
        receipt = json.loads((self.output / "submission.json").read_text(encoding="utf-8"))
        self.assertEqual("offline-fake-task", receipt["task_id"])
        self.assertTrue((self.output / "submission.intent.json").exists())
        with self.assertRaises(ValueError):
            self.plan()


if __name__ == "__main__":
    unittest.main()
