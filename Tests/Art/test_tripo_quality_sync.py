import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("quality_sync", ROOT / "Tools/sync_tripo_quality_reviews.py")
quality_sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality_sync)


class IsolatedImportSyncTests(unittest.TestCase):
    def test_current_partial_checkpoint_retains_historical_evidence(self):
        ledger = {"assets": {"Env_Pine": {"quality_review": {"status": "old_geometry", "isolated_ue_import": {"triangles": 3794}}}},
                  "acceptance_checkpoints": {"environment_six_partial_game_review": {"production_approved": False, "full_environment_complete": False,
                      "reviewed_actual_game_images": 16, "camera_sides": [0, 1]}}}
        quality_sync.merge_current_checkpoints(ledger)
        review = ledger["assets"]["Env_Pine"]["quality_review"]
        self.assertEqual("six_asset_partial_game_reviewed_not_full_environment", review["status"])
        self.assertEqual("old_geometry", review["historical_stage_status"])
        self.assertEqual(3794, review["isolated_ue_import"]["triangles"])
        self.assertFalse(review["production_approved"])

    def test_checkpoint_presence_alone_does_not_grant_visual_approval(self):
        bindings = [("stoneaxe_actual_assembly_pilot", "Unit_StoneAxe"),
                    ("environment_six_partial_game_review", "Env_Pine"),
                    ("base_stone_pbr_pilot", "Base_Stone")]
        for checkpoint_name, asset_id in bindings:
            ledger = {"assets": {asset_id: {}}, "acceptance_checkpoints": {checkpoint_name: {"production_approved": False}}}
            quality_sync.merge_current_checkpoints(ledger)
            self.assertEqual("stage_specific_review_pending", ledger["assets"][asset_id]["quality_review"]["status"])

    def test_repeated_sync_keeps_original_historical_stage(self):
        ledger = {"assets": {"Unit_StoneSlinger": {"quality_review": {"status": "old_stage"}}},
                  "acceptance_checkpoints": {"stone_slinger_geometry_pilot": {"status": "geometry_only", "production_approved": False}}}
        quality_sync.merge_current_checkpoints(ledger)
        quality_sync.merge_current_checkpoints(ledger)
        self.assertEqual("old_stage", ledger["assets"]["Unit_StoneSlinger"]["quality_review"]["historical_stage_status"])

    def test_geometry_checkpoint_does_not_imply_rig_or_game_acceptance(self):
        ledger = {"assets": {"Unit_StoneSlinger": {}}, "acceptance_checkpoints": {
            "stone_slinger_geometry_pilot": {"status": "geometry_only", "rig_approved": False, "production_approved": False}}}
        quality_sync.merge_current_checkpoints(ledger)
        review = ledger["assets"]["Unit_StoneSlinger"]["quality_review"]
        self.assertEqual("geometry_only", review["status"])
        self.assertFalse(review["current_checkpoint_evidence"]["rig_approved"])
        self.assertFalse(review["production_approved"])

    def test_full_approval_is_not_inferred_by_partial_checkpoint_merger(self):
        ledger = {"assets": {"Env_Pine": {}}, "acceptance_checkpoints": {
            "environment_six_partial_game_review": {"production_approved": True}}}
        quality_sync.merge_current_checkpoints(ledger)
        self.assertEqual({}, ledger["assets"]["Env_Pine"])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "model.glb"
        self.source.write_bytes(b"reviewed model")
        self.ledger = {"assets": {"Env_Pine": {}}}
        self.report = {"dry_run": False, "failed": 0, "results": [{
            "id": "Env_Pine", "status": "imported", "warnings": [], "source": "model.glb",
            "source_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
            "destination": "/Game/ArtPilot/test", "material_audit": {"status": "structural_checks_passed"},
            "runtime_material_overrides": {"Metallic": 0},
            "assets": [{"type": "static_mesh", "path": "/Game/ArtPilot/test/mesh.mesh",
                        "triangles_lod0": 3794, "dimensions_cm": [406, 561, 650]}]}]}

    def test_real_import_does_not_grant_game_approval(self):
        quality_sync.merge_isolated_import(self.ledger, self.report, "proof.json", self.root)
        review = self.ledger["assets"]["Env_Pine"]["quality_review"]["isolated_ue_import"]
        self.assertFalse(review["production_approved"])
        self.assertEqual(3794, review["triangles_lod0"])

    def test_changed_source_rejected_without_partial_update(self):
        before = copy.deepcopy(self.ledger)
        self.source.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "source changed"):
            quality_sync.merge_isolated_import(self.ledger, self.report, "proof.json", self.root)
        self.assertEqual(before, self.ledger)

    def test_dry_run_and_warnings_do_not_pass(self):
        for field, value in (("dry_run", True), ("failed", 1)):
            report = copy.deepcopy(self.report)
            report[field] = value
            with self.assertRaises(ValueError):
                quality_sync.merge_isolated_import(self.ledger, report, "proof.json", self.root)
        self.report["results"][0]["warnings"] = ["material_audit_requires_review"]
        with self.assertRaises(ValueError):
            quality_sync.merge_isolated_import(self.ledger, self.report, "proof.json", self.root)


if __name__ == "__main__":
    unittest.main()
