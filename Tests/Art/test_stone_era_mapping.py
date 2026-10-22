"""Keep preview activation tied to a different process and real motion results."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Tools"))
from prepare_stone_era_mapping import validate_single_result


class MappingReadbackTest(unittest.TestCase):
    def setUp(self):
        self.initial = {"status": "imported_preview_requires_fresh_reopen", "execution_process_id": 11,
                        "destination": "/Game/ArtPilot/Test", "manifest": "new_body.json"}
        clips = [{"clip": name, "path": name, "duration_seconds": duration, "same_skeleton": True,
                  "enable_root_motion": False, "root_translation_delta_cm": 0,
                  "absolute_motion_validation": {"status": "passed"}}
                 for name, duration in (("Idle", 2), ("Move", .6), ("Attack", .9), ("Hit", .5), ("Death", 1.2))]
        self.fresh = dict(self.initial, status="fresh_reopen_verified_preview", execution_process_id=22,
                          result={"structural_checks_passed": True,
                                  "reference_pose": {"bone_names_match_source": True,
                                                     "maximum_reference_bone_basis_error_cm": .0001},
                                  "clips": clips, "disk_dependency_validation":
                                  {"status": "passed", "validated_in_fresh_process": True}})

    def verify(self):
        return validate_single_result("Champion_Stone", self.initial, self.fresh)

    def test_independent_readback_preserves_actual_paths(self):
        _, clips = self.verify()
        self.assertEqual(clips["Attack"], "Attack")

    def test_same_process_is_not_fresh(self):
        self.fresh["execution_process_id"] = 11
        with self.assertRaisesRegex(ValueError, "reused"):
            self.verify()

    def test_other_source_cannot_borrow_approval(self):
        self.fresh["manifest"] = "old_body.json"
        with self.assertRaisesRegex(ValueError, "lineage"):
            self.verify()

    def test_duration_drift_blocks_mapping(self):
        self.fresh["result"]["clips"][2]["duration_seconds"] = 1.4
        with self.assertRaisesRegex(ValueError, "clip contract"):
            self.verify()

    def test_failed_motion_blocks_mapping(self):
        self.fresh["result"]["clips"][1]["absolute_motion_validation"]["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "clip contract"):
            self.verify()

    def test_files_only_are_not_full_humanoid_readback(self):
        self.fresh["result"]["disk_dependency_validation"]["validated_in_fresh_process"] = False
        with self.assertRaisesRegex(ValueError, "independently"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
